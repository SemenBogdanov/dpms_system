"""Add sidebar menu order to users

Revision ID: 035_user_sidebar_menu_order
Revises: 034_deadline_tracker_pause
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "035_user_sidebar_menu_order"
down_revision = "034_deadline_tracker_pause"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("sidebar_menu_order", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "sidebar_menu_order")
