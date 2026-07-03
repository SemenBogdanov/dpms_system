"""Add period closures

Revision ID: 036_period_closures
Revises: 035_user_sidebar_menu_order
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "036_period_closures"
down_revision = "035_user_sidebar_menu_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "period_closures",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period", sa.String(length=7), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="closed"),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="manual"),
        sa.Column("closed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cancelled_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("users_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_main_reset", sa.Numeric(10, 1), nullable=False, server_default="0"),
        sa.Column("total_karma_burned", sa.Numeric(10, 1), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["cancelled_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["closed_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("period"),
    )
    op.create_index(op.f("ix_period_closures_period"), "period_closures", ["period"], unique=False)
    op.execute(
        """
        INSERT INTO period_closures (
            id, period, status, mode, closed_at, users_processed, total_main_reset, total_karma_burned, created_at, updated_at
        )
        SELECT
            md5(period)::uuid,
            period,
            'closed',
            'legacy',
            MIN(created_at),
            COUNT(id),
            COALESCE(SUM(earned_main), 0),
            0,
            MIN(created_at),
            MIN(created_at)
        FROM period_snapshots
        GROUP BY period
        ON CONFLICT (period) DO NOTHING
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_period_closures_period"), table_name="period_closures")
    op.drop_table("period_closures")
