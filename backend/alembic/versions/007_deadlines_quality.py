"""Дедлайны, Quality Score, баг-фиксы.

Revision ID: 007_deadlines_quality
Revises: 006_improvements
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "007_deadlines_quality"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Новое значение enum для типа задачи
    op.execute("ALTER TYPE tasktype ADD VALUE IF NOT EXISTS 'bugfix'")

    # Task: дедлайны и баг-фиксы
    op.add_column("tasks", sa.Column("due_date", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tasks", sa.Column("sla_hours", sa.Integer(), nullable=True))
    op.add_column(
        "tasks",
        sa.Column("is_overdue", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column("tasks", sa.Column("parent_task_id", UUID(as_uuid=True), nullable=True))

    # FK для parent_task_id (self-referential)
    op.create_foreign_key("fk_tasks_parent", "tasks", "tasks", ["parent_task_id"], ["id"])

    # User: quality score
    op.add_column(
        "users",
        sa.Column("quality_score", sa.Float(), server_default="100.0", nullable=False),
    )

    # Индекс для поиска просроченных
    op.create_index(
        "ix_tasks_overdue",
        "tasks",
        ["is_overdue", "status"],
        postgresql_where=sa.text("is_overdue = true"),
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_overdue", table_name="tasks")
    op.drop_column("users", "quality_score")
    op.drop_constraint("fk_tasks_parent", "tasks", type_="foreignkey")
    op.drop_column("tasks", "parent_task_id")
    op.drop_column("tasks", "is_overdue")
    op.drop_column("tasks", "sla_hours")
    op.drop_column("tasks", "due_date")

