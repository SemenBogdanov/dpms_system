"""Add task review event history

Revision ID: 041_task_review_events
Revises: 040_personal_task_start_at
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "041_task_review_events"
down_revision = "040_personal_task_start_at"
branch_labels = None
depends_on = None


event_type = postgresql.ENUM(
    "submitted",
    "returned",
    "accepted",
    name="taskrevieweventtype",
    create_type=False,
)


def upgrade() -> None:
    event_type.create(op.get_bind(), checkfirst=True)
    op.create_table(
        "task_review_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", event_type, nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("result_url", sa.String(length=1000), nullable=True),
        sa.Column("result_comment", sa.Text(), nullable=True),
        sa.Column("brief_rating", sa.Integer(), nullable=True),
        sa.Column("brief_feedback", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_task_review_events_actor_id"), "task_review_events", ["actor_id"])
    op.create_index(op.f("ix_task_review_events_event_type"), "task_review_events", ["event_type"])
    op.create_index(op.f("ix_task_review_events_task_id"), "task_review_events", ["task_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_task_review_events_task_id"), table_name="task_review_events")
    op.drop_index(op.f("ix_task_review_events_event_type"), table_name="task_review_events")
    op.drop_index(op.f("ix_task_review_events_actor_id"), table_name="task_review_events")
    op.drop_table("task_review_events")
    event_type.drop(op.get_bind(), checkfirst=True)
