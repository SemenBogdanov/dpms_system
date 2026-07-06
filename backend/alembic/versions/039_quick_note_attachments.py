"""Add quick note attachments

Revision ID: 039_quick_note_attachments
Revises: 038_quick_note_comments
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "039_quick_note_attachments"
down_revision = "038_quick_note_comments"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "quick_note_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_by_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("stored_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["note_id"], ["quick_notes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quick_note_attachments_note_id"), "quick_note_attachments", ["note_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_quick_note_attachments_note_id"), table_name="quick_note_attachments")
    op.drop_table("quick_note_attachments")
