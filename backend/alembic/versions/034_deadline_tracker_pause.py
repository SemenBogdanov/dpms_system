"""Add pause support to deadline trackers

Revision ID: 034_deadline_tracker_pause
Revises: 033_deadline_trackers
"""

from alembic import op
import sqlalchemy as sa

revision = "034_deadline_tracker_pause"
down_revision = "033_deadline_trackers"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("deadline_trackers", sa.Column("pause_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("deadline_trackers", sa.Column("paused_seconds", sa.Integer(), nullable=False, server_default="0"))
    op.drop_constraint("ck_deadline_trackers_status", "deadline_trackers", type_="check")
    op.create_check_constraint(
        "ck_deadline_trackers_status",
        "deadline_trackers",
        "status IN ('active', 'paused', 'done', 'archived')",
    )


def downgrade() -> None:
    op.execute("UPDATE deadline_trackers SET status = 'active' WHERE status = 'paused'")
    op.drop_constraint("ck_deadline_trackers_status", "deadline_trackers", type_="check")
    op.create_check_constraint(
        "ck_deadline_trackers_status",
        "deadline_trackers",
        "status IN ('active', 'done', 'archived')",
    )
    op.drop_column("deadline_trackers", "paused_seconds")
    op.drop_column("deadline_trackers", "pause_started_at")
