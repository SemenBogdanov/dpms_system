"""Add bounded revisions for criterion acceptance decisions.

Revision ID: 051_acceptance_revisions
Revises: 050_task_acceptance_criteria
"""
from alembic import op
import sqlalchemy as sa


revision = "051_acceptance_revisions"
down_revision = "050_task_acceptance_criteria"
branch_labels = None
depends_on = None


ARTICLE_SECTION = """

## Если решение принято ошибочно

Ответственный за приемку может изменить решение по отдельному критерию: принятый
критерий вернуть исполнителю или ранее возвращенный критерий принять. Для каждого
изменения обязательна причина. Система сохраняет автора, время, предыдущее и новое
решение в истории критерия.

Одно решение можно изменить не более двух раз. После финальной приемки задачи и
начисления Q изменения блокируются. Если критерий возвращен в момент, когда задача
уже была на финальной приемке, задача автоматически возвращается в работу.
"""


def upgrade() -> None:
    op.add_column(
        "task_acceptance_criteria",
        sa.Column(
            "decision_change_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.create_check_constraint(
        "ck_task_acceptance_criteria_decision_change_count",
        "task_acceptance_criteria",
        "decision_change_count BETWEEN 0 AND 2",
    )

    op.drop_constraint(
        "ck_task_acceptance_criterion_events_type",
        "task_acceptance_criterion_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_task_acceptance_criterion_events_type",
        "task_acceptance_criterion_events",
        "event_type IN ('submitted', 'accepted', 'returned', 'not_applicable', 'decision_changed')",
    )

    op.execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET body = CASE
                    WHEN position('## Если решение принято ошибочно' in body) = 0
                    THEN replace(body, 'Обновлено: 2026-08-03', 'Обновлено: 2026-08-04') || :section
                    ELSE body
                END,
                updated_at = now(),
                published_at = now()
            WHERE id = '5072e1f7-ec75-4ac9-9c0d-f7e743684a76'
              AND slug = 'priemka-zadach-po-kriteriyam'
            """
        ).bindparams(section=ARTICLE_SECTION)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET body = replace(
                    replace(body, :section, ''),
                    'Обновлено: 2026-08-04',
                    'Обновлено: 2026-08-03'
                ),
                updated_at = now(),
                published_at = now()
            WHERE id = '5072e1f7-ec75-4ac9-9c0d-f7e743684a76'
              AND slug = 'priemka-zadach-po-kriteriyam'
            """
        ).bindparams(section=ARTICLE_SECTION)
    )

    op.execute(
        """
        UPDATE task_acceptance_criterion_events
        SET event_type = CASE
            WHEN to_status = 'accepted' THEN 'accepted'
            ELSE 'returned'
        END
        WHERE event_type = 'decision_changed'
        """
    )

    op.drop_constraint(
        "ck_task_acceptance_criterion_events_type",
        "task_acceptance_criterion_events",
        type_="check",
    )
    op.create_check_constraint(
        "ck_task_acceptance_criterion_events_type",
        "task_acceptance_criterion_events",
        "event_type IN ('submitted', 'accepted', 'returned', 'not_applicable')",
    )
    op.drop_constraint(
        "ck_task_acceptance_criteria_decision_change_count",
        "task_acceptance_criteria",
        type_="check",
    )
    op.drop_column("task_acceptance_criteria", "decision_change_count")
