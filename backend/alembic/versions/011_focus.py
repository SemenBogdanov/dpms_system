"""Add focus tracking fields to tasks"""

from alembic import op
import sqlalchemy as sa


revision = "011_focus"
down_revision = "010_assigned_by"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("focus_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("active_seconds", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("tasks", "active_seconds")
    op.drop_column("tasks", "focus_started_at")

