"""Add rejection_count to tasks"""

from alembic import op
import sqlalchemy as sa


revision = "012_rejection_count"
down_revision = "011_focus"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("rejection_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("tasks", "rejection_count")

