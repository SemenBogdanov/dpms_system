"""Improvements: requires_approval, is_proactive, index.

Revision ID: 006
Revises: 005
Create Date: 2026-02-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shop_items",
        sa.Column("requires_approval", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "tasks",
        sa.Column("is_proactive", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index(
        "ix_tasks_assignee_status_completed",
        "tasks",
        ["assignee_id", "status", "completed_at"],
        postgresql_where=sa.text("completed_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_assignee_status_completed", table_name="tasks")
    op.drop_column("tasks", "is_proactive")
    op.drop_column("shop_items", "requires_approval")
