"""Phase 3: shop_items, purchases, period_snapshots.

Revision ID: 003
Revises: 002
Create Date: 2026-02-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "shop_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("cost_q", sa.Numeric(5, 1), nullable=False),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column("icon", sa.String(50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=True),
        sa.Column("max_per_month", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "purchases",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("shop_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cost_q", sa.Numeric(5, 1), nullable=False),
        sa.Column("status", sa.String(20), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("approved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["shop_item_id"], ["shop_items.id"]),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"]),
    )
    op.create_table(
        "period_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("mpw", sa.Integer(), nullable=False),
        sa.Column("earned_main", sa.Numeric(10, 1), nullable=False),
        sa.Column("earned_karma", sa.Numeric(10, 1), nullable=False),
        sa.Column("tasks_completed", sa.Integer(), nullable=True),
        sa.Column("league", sa.String(1), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
    )


def downgrade() -> None:
    op.drop_table("period_snapshots")
    op.drop_table("purchases")
    op.drop_table("shop_items")
