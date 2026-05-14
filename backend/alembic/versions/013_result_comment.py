"""Add result_comment to tasks"""

from alembic import op
import sqlalchemy as sa


revision = "013_result_comment"
down_revision = "012_rejection_count"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("result_comment", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "result_comment")
