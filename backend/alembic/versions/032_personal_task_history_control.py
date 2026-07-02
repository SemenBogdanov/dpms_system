"""Add personal task history and control checkpoints

Revision ID: 032_personal_task_history
Revises: 031_personal_tasks_tracker
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "032_personal_task_history"
down_revision = "031_personal_tasks_tracker"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("personal_tasks", sa.Column("responsible", sa.String(length=200), nullable=True))

    op.create_table(
        "personal_task_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=40), nullable=False, server_default="note"),
        sa.Column("title", sa.String(length=200), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("from_status", sa.String(length=30), nullable=True),
        sa.Column("to_status", sa.String(length=30), nullable=True),
        sa.Column("next_step", sa.String(length=500), nullable=True),
        sa.Column("waiting_for", sa.String(length=200), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "event_type IN ('task_created', 'task_updated', 'status_changed', 'meeting', 'follow_up', 'note', 'checkpoint_created', 'checkpoint_updated', 'checkpoint_done', 'promoted')",
            name="ck_personal_task_events_type",
        ),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["task_id"], ["personal_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_task_events_task_id", "personal_task_events", ["task_id"])
    op.create_index("ix_personal_task_events_actor_id", "personal_task_events", ["actor_id"])
    op.create_index("ix_personal_task_events_event_type", "personal_task_events", ["event_type"])
    op.create_index("ix_personal_task_events_created_at", "personal_task_events", ["created_at"])

    op.create_table(
        "personal_task_checkpoints",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="planned"),
        sa.Column("next_step", sa.String(length=500), nullable=True),
        sa.Column("waiting_for", sa.String(length=200), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('planned', 'in_progress', 'waiting', 'blocked', 'done')",
            name="ck_personal_task_checkpoints_status",
        ),
        sa.ForeignKeyConstraint(["task_id"], ["personal_tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_personal_task_checkpoints_task_id", "personal_task_checkpoints", ["task_id"])
    op.create_index("ix_personal_task_checkpoints_status", "personal_task_checkpoints", ["status"])
    op.create_index("ix_personal_task_checkpoints_due_at", "personal_task_checkpoints", ["due_at"])


def downgrade() -> None:
    op.drop_index("ix_personal_task_checkpoints_due_at", table_name="personal_task_checkpoints")
    op.drop_index("ix_personal_task_checkpoints_status", table_name="personal_task_checkpoints")
    op.drop_index("ix_personal_task_checkpoints_task_id", table_name="personal_task_checkpoints")
    op.drop_table("personal_task_checkpoints")
    op.drop_index("ix_personal_task_events_created_at", table_name="personal_task_events")
    op.drop_index("ix_personal_task_events_event_type", table_name="personal_task_events")
    op.drop_index("ix_personal_task_events_actor_id", table_name="personal_task_events")
    op.drop_index("ix_personal_task_events_task_id", table_name="personal_task_events")
    op.drop_table("personal_task_events")
    op.drop_column("personal_tasks", "responsible")
