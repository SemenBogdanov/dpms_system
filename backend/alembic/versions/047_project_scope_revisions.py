"""Mark work introduced after the project baseline.

Revision ID: 047_project_scope_revisions
Revises: 046_project_cockpit
"""
from alembic import op
import sqlalchemy as sa


revision = "047_project_scope_revisions"
down_revision = "046_project_cockpit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    for table_name in ("work_entity_tasks", "work_entity_milestones"):
        op.add_column(
            table_name,
            sa.Column(
                "introduced_after_baseline",
                sa.Boolean(),
                nullable=False,
                server_default=sa.false(),
            ),
        )
        op.add_column(
            table_name,
            sa.Column("introduced_at_revision", sa.Integer(), nullable=True),
        )
    op.execute(
        """
        UPDATE knowledge_articles
        SET body = replace(
                body,
                '## Изменение срока',
                '## Изменение scope после запуска

Новая работа или контрольная точка, добавленная после запуска, помечается как
изменение scope и связывается с ревизией графика. Она не маскируется под элемент
первоначального базового плана.

## Изменение срока'
            ),
            updated_at = now()
        WHERE slug = 'rabochee-prostranstvo-proekta'
          AND body NOT LIKE '%## Изменение scope после запуска%'
        """
    )


def downgrade() -> None:
    for table_name in ("work_entity_milestones", "work_entity_tasks"):
        op.drop_column(table_name, "introduced_at_revision")
        op.drop_column(table_name, "introduced_after_baseline")
