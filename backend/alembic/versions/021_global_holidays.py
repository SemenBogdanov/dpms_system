"""Add global holidays for capacity planning

Revision ID: 021_global_holidays
Revises: 020_user_absences
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "021_global_holidays"
down_revision = "020_user_absences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "global_holidays",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("affects_plan", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("holiday_date", name="uq_global_holidays_holiday_date"),
    )
    op.create_index("ix_global_holidays_holiday_date", "global_holidays", ["holiday_date"])


def downgrade() -> None:
    op.drop_index("ix_global_holidays_holiday_date", table_name="global_holidays")
    op.drop_table("global_holidays")
