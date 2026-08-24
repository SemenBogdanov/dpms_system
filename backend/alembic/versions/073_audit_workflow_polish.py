"""Unify the audit workflow control and repair assigned draft cases.

Revision ID: 073_audit_workflow_polish
Revises: 072_audit_multi_model
"""

from alembic import op
import sqlalchemy as sa


revision = "073_audit_workflow_polish"
down_revision = "072_audit_multi_model"
branch_labels = None
depends_on = None


DEFAULT_AUDIT_CONTEXT = (
    "Выполняется аудит каждого элемента сформированного и отработанного технического задания."
)

OLD_ASSIGNMENT_PARAGRAPH = (
    "Этап аудита отделен от технического состояния карточки. Поэтому дальнейшее уточнение "
    "бизнес-процесса не меняет правила черновика, архива и доступа к данным."
)
NEW_ASSIGNMENT_PARAGRAPH = (
    "Пользователь управляет единым этапом аудита. После назначения договор автоматически "
    "переходит в этап «Атомизация», а архив выбирается в том же списке этапов. Техническое "
    "состояние карточки сохраняется внутри системы для защиты архива и удаления, но отдельного "
    "поля в форме больше нет."
)

WORKSPACE_APPENDIX = """

## Этап, назначение и архив
В карточке используется одно поле `Этап аудита`. Новый договор имеет этап `Договор не назначен`. Первое назначение сотруднику автоматически переводит его в `Атомизацию`; вручную дублировать этот переход не нужно. `Архив` находится в том же списке и переводит карточку в режим только для чтения.

Контекст нового договора по умолчанию: «Выполняется аудит каждого элемента сформированного и отработанного технического задания». Его можно уточнить при редактировании карточки.

Номер договора остается справочным конфиденциальным реквизитом. Он отображается и доступен для изменения только сотрудникам, включенным в команду аудита. Остальные пользователи с административным доступом к разделу не получают этот реквизит через API.
"""


def upgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            UPDATE audit_cases
            SET notes = :context,
                updated_at = now()
            WHERE notes IS NULL OR btrim(notes) = ''
            """
        ),
        {"context": DEFAULT_AUDIT_CONTEXT},
    )
    op.alter_column(
        "audit_cases",
        "notes",
        existing_type=sa.Text(),
        server_default=sa.text("'" + DEFAULT_AUDIT_CONTEXT.replace("'", "''") + "'"),
    )

    bind.execute(
        sa.text(
            """
            UPDATE audit_cases AS audit_case
            SET workflow_stage = CASE
                    WHEN audit_case.status = 'ready' THEN 'ready'
                    ELSE 'atomization'
                END,
                status = CASE
                    WHEN audit_case.status = 'draft' THEN 'atomization'
                    ELSE audit_case.status
                END,
                updated_at = now()
            WHERE audit_case.status <> 'archived'
              AND audit_case.workflow_stage = 'unassigned'
              AND EXISTS (
                  SELECT 1
                  FROM audit_assignments AS assignment
                  WHERE assignment.case_id = audit_case.id
              )
            """
        )
    )

    bind.execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET body = replace(body, :old_paragraph, :new_paragraph),
                updated_at = now()
            WHERE slug = 'audit-assigned-contracts'
            """
        ),
        {
            "old_paragraph": OLD_ASSIGNMENT_PARAGRAPH,
            "new_paragraph": NEW_ASSIGNMENT_PARAGRAPH,
        },
    )
    bind.execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET body = body || :appendix,
                summary = 'Как работать с реестром, единым этапом аудита, назначениями и конфиденциальными реквизитами.',
                updated_at = now()
            WHERE slug = 'audit-workspace-registry-team-documents'
              AND body NOT LIKE '%Этап, назначение и архив%'
            """
        ),
        {"appendix": WORKSPACE_APPENDIX},
    )

def downgrade() -> None:
    bind = op.get_bind()
    op.alter_column(
        "audit_cases",
        "notes",
        existing_type=sa.Text(),
        server_default=None,
    )
    bind.execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET body = replace(body, :new_paragraph, :old_paragraph),
                updated_at = now()
            WHERE slug = 'audit-assigned-contracts'
            """
        ),
        {
            "new_paragraph": NEW_ASSIGNMENT_PARAGRAPH,
            "old_paragraph": OLD_ASSIGNMENT_PARAGRAPH,
        },
    )
    bind.execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET body = replace(body, :appendix, ''),
                updated_at = now()
            WHERE slug = 'audit-workspace-registry-team-documents'
            """
        ),
        {"appendix": WORKSPACE_APPENDIX},
    )
