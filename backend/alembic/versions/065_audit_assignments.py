"""Add calendar assignments for audit contracts.

Revision ID: 065_audit_assignments
Revises: 064_audit_ai_drafts
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "065_audit_assignments"
down_revision = "064_audit_ai_drafts"
branch_labels = None
depends_on = None


ARTICLE = {
    "id": "4fd8b282-207c-4ed9-91bb-3192afd912d0",
    "slug": "audit-assigned-contracts",
    "title": "Аудит: назначения",
    "summary": "Как распределять договоры по сотрудникам и датам в календарной матрице.",
    "section": "audit",
    "body": """Обновлено: 2026-08-23

## Для чего нужен экран
`Назначения` показывает загрузку сотрудников аудита в одной календарной матрице. Строка соответствует дате, столбец — сотруднику, а ячейка — договорам, назначенным этому сотруднику на выбранный день.

## Как назначить договор
1. Откройте `Аудит -> Назначения`.
2. Выберите период или перейдите к нужной неделе.
3. Нажмите ячейку на пересечении сотрудника и даты.
4. Отметьте один или несколько договоров и сохраните.

Редактировать назначения может администратор, teamlead или руководитель аудита. Остальные участники команды видят общую матрицу без возможности изменения.

## Как читать цвет
- красный — договор в черновике;
- желтый — идет атомизация;
- зеленый — договор готов;
- серый — договор находится в архиве.

Если в одной ячейке есть договоры на разных этапах, внутри отображаются отдельные цветовые сегменты и количество по каждому этапу. Цвет вычисляется из текущего статуса договора, поэтому после изменения статуса матрица обновляется без ручного перекрашивания.

## Связь с ответственным
При добавлении договора в ячейку выбранный сотрудник становится текущим ответственным в реестре. История договора отдельно фиксирует календарное назначение и смену ответственного. Снятие календарного назначения не очищает ответственного автоматически: при необходимости его нужно переназначить явно. Один договор можно планировать на несколько дат, но ответственным считается сотрудник из последнего нового назначения.
""",
}


def upgrade() -> None:
    op.create_table(
        "audit_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assignee_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("scheduled_date", sa.Date(), nullable=False),
        sa.Column("assigned_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.ForeignKeyConstraint(["case_id"], ["audit_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assignee_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["assigned_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "case_id",
            "assignee_id",
            "scheduled_date",
            name="uq_audit_assignments_case_assignee_date",
        ),
    )
    op.create_index("ix_audit_assignments_case_id", "audit_assignments", ["case_id"])
    op.create_index("ix_audit_assignments_assignee_id", "audit_assignments", ["assignee_id"])
    op.create_index("ix_audit_assignments_scheduled_date", "audit_assignments", ["scheduled_date"])
    op.create_index("ix_audit_assignments_assigned_by_id", "audit_assignments", ["assigned_by_id"])
    op.create_index("ix_audit_assignments_date_assignee", "audit_assignments", ["scheduled_date", "assignee_id"])
    op.create_index("ix_audit_assignments_case_date", "audit_assignments", ["case_id", "scheduled_date"])

    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO knowledge_articles (
                id, slug, title, summary, section, body, status, sort_order,
                created_at, updated_at, published_at
            ) VALUES (
                :id, :slug, :title, :summary, :section, :body, 'published', 215,
                now(), now(), now()
            )
            ON CONFLICT (slug) DO UPDATE SET
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                section = EXCLUDED.section,
                body = EXCLUDED.body,
                status = 'published',
                updated_at = now(),
                published_at = COALESCE(knowledge_articles.published_at, now())
            """
        ),
        ARTICLE,
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text("DELETE FROM knowledge_articles WHERE id = :id"),
        {"id": ARTICLE["id"]},
    )
    op.drop_index("ix_audit_assignments_case_date", table_name="audit_assignments")
    op.drop_index("ix_audit_assignments_date_assignee", table_name="audit_assignments")
    op.drop_index("ix_audit_assignments_assigned_by_id", table_name="audit_assignments")
    op.drop_index("ix_audit_assignments_scheduled_date", table_name="audit_assignments")
    op.drop_index("ix_audit_assignments_assignee_id", table_name="audit_assignments")
    op.drop_index("ix_audit_assignments_case_id", table_name="audit_assignments")
    op.drop_table("audit_assignments")
