"""Add feedback access flag

Revision ID: 024_feedback_access_flag
Revises: 023_feedback_request_artifacts
"""

from alembic import op
import sqlalchemy as sa


revision = "024_feedback_access_flag"
down_revision = "023_feedback_request_artifacts"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("feedback_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute("UPDATE users SET feedback_enabled = true WHERE role = 'admin'")


def downgrade() -> None:
    op.drop_column("users", "feedback_enabled")
