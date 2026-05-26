"""Add activity events audit log

Revision ID: 019_activity_events
Revises: 018_dashboard_perf
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "019_activity_events"
down_revision = "018_dashboard_perf"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "activity_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("event_type", sa.String(length=80), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tasks.id"), nullable=True),
        sa.Column("metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_activity_events_actor_id", "activity_events", ["actor_id"])
    op.create_index("ix_activity_events_task_id", "activity_events", ["task_id"])
    op.create_index("ix_activity_events_event_type", "activity_events", ["event_type"])
    op.create_index("ix_activity_events_occurred_at", "activity_events", ["occurred_at"])
    op.create_index(
        "ix_activity_events_actor_occurred",
        "activity_events",
        ["actor_id", "occurred_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_activity_events_actor_occurred", table_name="activity_events")
    op.drop_index("ix_activity_events_occurred_at", table_name="activity_events")
    op.drop_index("ix_activity_events_event_type", table_name="activity_events")
    op.drop_index("ix_activity_events_task_id", table_name="activity_events")
    op.drop_index("ix_activity_events_actor_id", table_name="activity_events")
    op.drop_table("activity_events")
