"""Add assigned_by_id to tasks."""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "010_assigned_by"
down_revision: Union[str, None] = "009_sort_order"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("assigned_by_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_tasks_assigned_by_id",
        "tasks",
        "users",
        ["assigned_by_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_tasks_assigned_by_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "assigned_by_id")
