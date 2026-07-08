"""Add personal task start date

Revision ID: 040_personal_task_start_at
Revises: 039_quick_note_attachments
"""

from alembic import op
import sqlalchemy as sa


revision = "040_personal_task_start_at"
down_revision = "039_quick_note_attachments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "personal_tasks",
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute("UPDATE personal_tasks SET start_at = COALESCE(created_at, now()) WHERE start_at IS NULL")
    op.alter_column("personal_tasks", "start_at", nullable=False)


def downgrade() -> None:
    op.drop_column("personal_tasks", "start_at")
