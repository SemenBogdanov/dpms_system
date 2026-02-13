"""Phase 2: result_url, rejection_comment в tasks.

Revision ID: 002
Revises: 001
Create Date: 2026-02-12

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("result_url", sa.String(1000), nullable=True))
    op.add_column("tasks", sa.Column("rejection_comment", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "rejection_comment")
    op.drop_column("tasks", "result_url")
