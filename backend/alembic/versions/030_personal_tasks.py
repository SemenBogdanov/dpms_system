"""Add personal tasks

Revision ID: 030_personal_tasks
Revises: 029_quick_notes
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "030_personal_tasks"
down_revision = "029_quick_notes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "personal_tasks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="planned"),
        sa.Column("priority", sa.String(length=30), nullable=False, server_default="medium"),
        sa.Column("next_step", sa.String(length=500), nullable=True),
        sa.Column("next_step_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("linked_task_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_quick_note_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('planned', 'in_progress', 'done', 'archived')",
            name="ck_personal_tasks_status",
        ),
        sa.CheckConstraint(
            "priority IN ('low', 'medium', 'high')",
            name="ck_personal_tasks_priority",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["linked_task_id"], ["tasks.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_quick_note_id"], ["quick_notes.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_personal_tasks_owner_id"), "personal_tasks", ["owner_id"])
    op.create_index(op.f("ix_personal_tasks_status"), "personal_tasks", ["status"])
    op.create_index(op.f("ix_personal_tasks_priority"), "personal_tasks", ["priority"])
    op.create_index(op.f("ix_personal_tasks_linked_task_id"), "personal_tasks", ["linked_task_id"])
    op.create_index(op.f("ix_personal_tasks_source_quick_note_id"), "personal_tasks", ["source_quick_note_id"])
    op.create_index("ix_personal_tasks_owner_status_due", "personal_tasks", ["owner_id", "status", "due_at"])
    op.create_index("ix_personal_tasks_owner_next_step", "personal_tasks", ["owner_id", "next_step_at"])


def downgrade() -> None:
    op.drop_index("ix_personal_tasks_owner_next_step", table_name="personal_tasks")
    op.drop_index("ix_personal_tasks_owner_status_due", table_name="personal_tasks")
    op.drop_index(op.f("ix_personal_tasks_source_quick_note_id"), table_name="personal_tasks")
    op.drop_index(op.f("ix_personal_tasks_linked_task_id"), table_name="personal_tasks")
    op.drop_index(op.f("ix_personal_tasks_priority"), table_name="personal_tasks")
    op.drop_index(op.f("ix_personal_tasks_status"), table_name="personal_tasks")
    op.drop_index(op.f("ix_personal_tasks_owner_id"), table_name="personal_tasks")
    op.drop_table("personal_tasks")
