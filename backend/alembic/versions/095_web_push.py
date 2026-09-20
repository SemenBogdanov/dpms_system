"""Add per-device Web Push subscriptions and delivery outbox.

Revision ID: 095_web_push
Revises: 094_audit_lane_checkpoints
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "095_web_push"
down_revision = "094_audit_lane_checkpoints"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "web_push_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("endpoint_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("endpoint", sa.Text(), nullable=False),
        sa.Column("p256dh", sa.String(128), nullable=False),
        sa.Column("auth_value", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_web_push_subscriptions_user_id", "web_push_subscriptions", ["user_id"])
    op.create_table(
        "web_push_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("web_push_subscriptions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_key", sa.String(100), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("path", sa.String(512), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("subscription_id", "event_key", name="uq_web_push_delivery_event"),
        sa.CheckConstraint("kind IN ('direct', 'important')", name="ck_web_push_delivery_kind"),
        sa.CheckConstraint("status IN ('pending', 'leased', 'sent', 'failed')", name="ck_web_push_delivery_status"),
    )
    op.create_index("ix_web_push_delivery_due", "web_push_deliveries", ["status", "due_at"])


def downgrade() -> None:
    op.drop_table("web_push_deliveries")
    op.drop_table("web_push_subscriptions")
