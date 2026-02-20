"""Теги задач (идентификаторы проектов/инцидентов).

Revision ID: 008_task_tags
Revises: 007_deadlines_quality
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, TEXT


revision: str = "008_task_tags"
down_revision: Union[str, None] = "007_deadlines_quality"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("tags", ARRAY(TEXT()), nullable=True))
    op.execute("UPDATE tasks SET tags = '{}' WHERE tags IS NULL")
    op.alter_column("tasks", "tags", nullable=False)


def downgrade() -> None:
    op.drop_column("tasks", "tags")
