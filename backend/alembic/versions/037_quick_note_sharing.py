"""Add quick note sharing

Revision ID: 037_quick_note_sharing
Revises: 036_period_closures
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "037_quick_note_sharing"
down_revision = "036_period_closures"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requester_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "requester_id <> recipient_id",
            name="ck_contacts_no_self",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'rejected')",
            name="ck_contacts_status",
        ),
        sa.ForeignKeyConstraint(["requester_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("requester_id", "recipient_id", name="uq_contacts_pair"),
    )
    op.create_index(op.f("ix_contacts_requester_id"), "contacts", ["requester_id"])
    op.create_index(op.f("ix_contacts_recipient_id"), "contacts", ["recipient_id"])
    op.create_index(op.f("ix_contacts_status"), "contacts", ["status"])

    op.create_table(
        "quick_note_shares",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "owner_id <> recipient_id",
            name="ck_quick_note_shares_no_self",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'revoked')",
            name="ck_quick_note_shares_status",
        ),
        sa.ForeignKeyConstraint(["note_id"], ["quick_notes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recipient_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("note_id", "recipient_id", name="uq_quick_note_shares_note_recipient"),
    )
    op.create_index(op.f("ix_quick_note_shares_note_id"), "quick_note_shares", ["note_id"])
    op.create_index(op.f("ix_quick_note_shares_owner_id"), "quick_note_shares", ["owner_id"])
    op.create_index(op.f("ix_quick_note_shares_recipient_id"), "quick_note_shares", ["recipient_id"])
    op.create_index(op.f("ix_quick_note_shares_status"), "quick_note_shares", ["status"])

    op.create_table(
        "quick_note_comments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("author_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["note_id"], ["quick_notes.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["author_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["quick_note_comments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_quick_note_comments_note_id"), "quick_note_comments", ["note_id"])
    op.create_index(op.f("ix_quick_note_comments_author_id"), "quick_note_comments", ["author_id"])
    op.create_index(op.f("ix_quick_note_comments_parent_id"), "quick_note_comments", ["parent_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_quick_note_comments_parent_id"), table_name="quick_note_comments")
    op.drop_index(op.f("ix_quick_note_comments_author_id"), table_name="quick_note_comments")
    op.drop_index(op.f("ix_quick_note_comments_note_id"), table_name="quick_note_comments")
    op.drop_table("quick_note_comments")

    op.drop_index(op.f("ix_quick_note_shares_status"), table_name="quick_note_shares")
    op.drop_index(op.f("ix_quick_note_shares_recipient_id"), table_name="quick_note_shares")
    op.drop_index(op.f("ix_quick_note_shares_owner_id"), table_name="quick_note_shares")
    op.drop_index(op.f("ix_quick_note_shares_note_id"), table_name="quick_note_shares")
    op.drop_table("quick_note_shares")

    op.drop_index(op.f("ix_contacts_status"), table_name="contacts")
    op.drop_index(op.f("ix_contacts_recipient_id"), table_name="contacts")
    op.drop_index(op.f("ix_contacts_requester_id"), table_name="contacts")
    op.drop_table("contacts")
