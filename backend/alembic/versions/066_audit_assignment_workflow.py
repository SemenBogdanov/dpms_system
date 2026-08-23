"""Make audit assignments exclusive and add workflow stages.

Revision ID: 066_audit_assignment_workflow
Revises: 065_audit_assignments
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid


revision = "066_audit_assignment_workflow"
down_revision = "065_audit_assignments"
branch_labels = None
depends_on = None


ARTICLE_BODY = """Обновлено: 2026-08-23

## Для чего нужен экран
`Назначения` показывает загрузку сотрудников аудита в календарной матрице. Строка соответствует дате, столбец — сотруднику, а ячейка — договорам, назначенным этому сотруднику на выбранный день.

## Как выбрать период
Укажите даты `С` и `По`. За один раз можно открыть период до 92 дней. Кнопки со стрелками сдвигают весь выбранный период назад или вперед.

## Как назначить договор
1. Откройте `Аудит -> Назначения`.
2. Выберите период.
3. Нажмите ячейку на пересечении сотрудника и даты.
4. Отметьте один или несколько договоров и сохраните.

Один договор может иметь только одно активное календарное назначение. Если он уже назначен, система показывает текущего сотрудника и дату. Подтвержденный выбор в другой ячейке передает договор новому сотруднику: второй экземпляр назначения не создается.

Редактировать назначения может администратор, teamlead или руководитель аудита. Остальные участники команды видят общую матрицу без возможности изменения.

## Как читать ячейку
В правом верхнем углу показано общее число назначенных договоров. Каждая строка содержит цветную точку этапа, название цифрового продукта и количество атомов. Внизу сохраняются системные номера `AUD-*`.

Фон ячейки соответствует самому раннему незавершенному этапу среди находящихся в ней договоров. Цветная точка у каждой строки показывает точный этап конкретного договора.

## Этапы аудита
- красный — договор не назначен;
- желтый — выполняется атомизация;
- голубой — выполняется альфа-проверка;
- фиолетовый — ожидается комиссия;
- оранжевый — комиссия пройдена, ожидаются исправления;
- синий — выполняются исправления;
- индиго — ожидается повторная комиссия;
- зеленый — договор готов.

Этап аудита отделен от технического состояния карточки. Поэтому дальнейшее уточнение бизнес-процесса не меняет правила черновика, архива и доступа к данным.

## Передача и история
При первом назначении выбранный сотрудник становится ответственным в реестре. При передаче существующая запись назначения переносится в новую ячейку атомарно, а история фиксирует прежнего и нового сотрудника, прежнюю и новую дату. Снятие договора из ячейки снимает текущего ответственного, если им был тот же сотрудник.
"""


def _consolidate_duplicate_assignments() -> None:
    bind = op.get_bind()
    rows = bind.execute(
        sa.text(
            """
            SELECT assignment.id,
                   assignment.case_id,
                   assignment.assignee_id,
                   assignment.scheduled_date,
                   assignment.assigned_by_id,
                   assignment.created_at,
                   assignment.updated_at,
                   audit_case.responsible_user_id
            FROM audit_assignments AS assignment
            JOIN audit_cases AS audit_case ON audit_case.id = assignment.case_id
            WHERE assignment.case_id IN (
                SELECT case_id
                FROM audit_assignments
                GROUP BY case_id
                HAVING count(*) > 1
            )
            ORDER BY assignment.case_id,
                     (assignment.assignee_id = audit_case.responsible_user_id) DESC NULLS LAST,
                     assignment.updated_at DESC,
                     assignment.created_at DESC,
                     assignment.id DESC
            """
        )
    ).mappings().all()
    by_case: dict[object, list[dict]] = {}
    for row in rows:
        by_case.setdefault(row["case_id"], []).append(dict(row))

    insert_event = sa.text(
        """
        INSERT INTO audit_events (
            id, case_id, actor_id, event_type, message, payload_json, created_at
        ) VALUES (
            :id, :case_id, :actor_id, 'assignment_consolidated', :message, :payload, now()
        )
        """
    ).bindparams(sa.bindparam("payload", type_=postgresql.JSONB))
    for case_id, assignments in by_case.items():
        retained = assignments[0]
        for discarded in assignments[1:]:
            bind.execute(
                insert_event,
                {
                    "id": uuid.uuid4(),
                    "case_id": case_id,
                    "actor_id": discarded["assigned_by_id"],
                    "message": "Параллельное назначение сохранено в истории при переходе к одному исполнителю",
                    "payload": {
                        "previous_assignment_id": str(discarded["id"]),
                        "previous_assignee_id": str(discarded["assignee_id"]),
                        "previous_scheduled_date": discarded["scheduled_date"].isoformat(),
                        "retained_assignment_id": str(retained["id"]),
                    },
                },
            )
            bind.execute(
                sa.text("DELETE FROM audit_assignments WHERE id = :id"),
                {"id": discarded["id"]},
            )
        bind.execute(
            sa.text(
                """
                UPDATE audit_cases
                SET responsible_user_id = :assignee_id,
                    updated_at = now()
                WHERE id = :case_id
                """
            ),
            {"assignee_id": retained["assignee_id"], "case_id": case_id},
        )


def upgrade() -> None:
    op.add_column(
        "audit_cases",
        sa.Column(
            "workflow_stage",
            sa.String(length=40),
            nullable=False,
            server_default=sa.text("'unassigned'"),
        ),
    )
    op.execute(
        """
        UPDATE audit_cases
        SET workflow_stage = CASE
            WHEN status = 'ready' THEN 'ready'
            WHEN status = 'atomization' OR responsible_user_id IS NOT NULL THEN 'atomization'
            ELSE 'unassigned'
        END
        """
    )
    op.create_index("ix_audit_cases_workflow_stage", "audit_cases", ["workflow_stage"])

    _consolidate_duplicate_assignments()
    op.drop_constraint(
        "uq_audit_assignments_case_assignee_date",
        "audit_assignments",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_audit_assignments_case_id",
        "audit_assignments",
        ["case_id"],
    )

    op.get_bind().execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET title = 'Аудит: назначения',
                summary = 'Как распределять договоры по сотрудникам и датам без двойного назначения.',
                body = :body,
                status = 'published',
                updated_at = now(),
                published_at = COALESCE(published_at, now())
            WHERE slug = 'audit-assigned-contracts'
            """
        ),
        {"body": ARTICLE_BODY},
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_audit_assignments_case_id",
        "audit_assignments",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_audit_assignments_case_assignee_date",
        "audit_assignments",
        ["case_id", "assignee_id", "scheduled_date"],
    )
    op.drop_index("ix_audit_cases_workflow_stage", table_name="audit_cases")
    op.drop_column("audit_cases", "workflow_stage")
