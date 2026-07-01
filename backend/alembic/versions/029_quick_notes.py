"""Add personal quick notes

Revision ID: 029_quick_notes
Revises: 028_task_workspace_access
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "029_quick_notes"
down_revision = "028_task_workspace_access"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quick_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=160), nullable=False, server_default=""),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("context", sa.String(length=160), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="draft"),
        sa.Column(
            "tags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::text[]"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('draft', 'processed', 'archived')",
            name="ck_quick_notes_status",
        ),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quick_notes_owner_id"), "quick_notes", ["owner_id"])
    op.create_index(op.f("ix_quick_notes_status"), "quick_notes", ["status"])
    op.create_index("ix_quick_notes_owner_updated", "quick_notes", ["owner_id", "updated_at"])


def downgrade() -> None:
    op.drop_index("ix_quick_notes_owner_updated", table_name="quick_notes")
    op.drop_index(op.f("ix_quick_notes_status"), table_name="quick_notes")
    op.drop_index(op.f("ix_quick_notes_owner_id"), table_name="quick_notes")
    op.drop_table("quick_notes")
