"""Add user absences for capacity planning

Revision ID: 020_user_absences
Revises: 019_activity_events
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "020_user_absences"
down_revision = "019_activity_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "user_absences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("type", sa.String(length=32), nullable=False),
        sa.Column("affects_plan", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("end_date >= start_date", name="ck_user_absences_date_order"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_user_absences_user_id", "user_absences", ["user_id"])
    op.create_index(
        "ix_user_absences_user_dates",
        "user_absences",
        ["user_id", "start_date", "end_date"],
    )
    op.create_index(
        "ix_user_absences_dates_affects_plan",
        "user_absences",
        ["start_date", "end_date", "affects_plan"],
    )


def downgrade() -> None:
    op.drop_index("ix_user_absences_dates_affects_plan", table_name="user_absences")
    op.drop_index("ix_user_absences_user_dates", table_name="user_absences")
    op.drop_index("ix_user_absences_user_id", table_name="user_absences")
    op.drop_table("user_absences")
