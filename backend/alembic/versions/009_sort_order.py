"""Добавить sort_order в catalog_items.

Revision ID: 009_sort_order
Revises: 008_task_tags
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "009_sort_order"
down_revision: Union[str, None] = "008_task_tags"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "catalog_items",
        sa.Column(
            "sort_order",
            sa.Integer(),
            nullable=False,
            server_default="100",
        ),
    )


def downgrade() -> None:
    op.drop_column("catalog_items", "sort_order")

