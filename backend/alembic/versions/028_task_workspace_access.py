"""Add task workspace access flag

Revision ID: 028_task_workspace_access
Revises: 027_competency_answer_updated_at
"""

from alembic import op
import sqlalchemy as sa


revision = "028_task_workspace_access"
down_revision = "027_competency_answer_updated_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("task_workspace_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("users", "task_workspace_enabled", server_default=sa.false())


def downgrade() -> None:
    op.drop_column("users", "task_workspace_enabled")
