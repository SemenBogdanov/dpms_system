"""Add private Inbox devices and items. Never discard imported data on downgrade.

Revision ID: 100_mail_import
Revises: 099_graphs_hierarchy_knowledge
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "100_mail_import"
down_revision = "099_graphs_hierarchy_knowledge"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mail_import_devices",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("include_body", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("include_attachments", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("owner_auth_version", sa.Integer(), nullable=False),
        sa.Column("pairing_code_hash", sa.String(64), unique=True),
        sa.Column("pairing_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("device_secret_hash", sa.String(64), unique=True),
        sa.Column("paired_at", sa.DateTime(timezone=True)),
        sa.Column("expires_at", sa.DateTime(timezone=True)),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
        sa.Column("mailbox_id", sa.String(64)),
        sa.Column("mailbox_label", sa.String(200)),
        sa.Column("source_state", sa.String(10)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("last_sync_at", sa.DateTime(timezone=True)),
        sa.Column("last_scan_complete", sa.Boolean()),
        sa.Column("last_skipped_items", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint("source_state IS NULL OR source_state IN ('cached', 'online', 'offline')", name="ck_mail_import_devices_source_state"),
        sa.CheckConstraint("last_skipped_items BETWEEN 0 AND 5000", name="ck_mail_import_devices_skipped_items"),
    )
    op.create_index("ix_mail_import_devices_owner_created", "mail_import_devices", ["owner_id", "created_at"])
    op.create_table(
        "mail_import_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("mailbox_id", sa.String(64), nullable=False),
        sa.Column("mailbox_label", sa.String(200), nullable=False),
        sa.Column("source_id", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(10), nullable=False),
        sa.Column("source_modified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("subject", sa.String(1000), nullable=False),
        sa.Column("sender_name", sa.String(300), nullable=False),
        sa.Column("sender_address", sa.String(320), nullable=False),
        sa.Column("body_text", sa.Text()),
        sa.Column("body_html", sa.Text()),
        sa.Column("to_recipients", sa.String(20000), nullable=False, server_default=""),
        sa.Column("cc_recipients", sa.String(20000), nullable=False, server_default=""),
        sa.Column("source_is_read", sa.Boolean(), nullable=False),
        sa.Column("meeting_status", sa.String(12)),
        sa.Column("starts_at", sa.DateTime(timezone=True)),
        sa.Column("ends_at", sa.DateTime(timezone=True)),
        sa.Column("all_day", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("location", sa.String(1000), nullable=False, server_default=""),
        sa.Column("meeting_key", sa.String(64)),
        sa.Column("is_recurring", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("semantic_hash", sa.String(64), nullable=False),
        sa.Column("content_byte_length", sa.BigInteger(), nullable=False),
        sa.Column("body_captured", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("attachments_captured", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_read", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("owner_id", "mailbox_id", "source_id", name="uq_mail_import_items_source"),
        sa.CheckConstraint("kind IN ('mail', 'meeting')", name="ck_mail_import_items_kind"),
        sa.CheckConstraint("meeting_status IS NULL OR meeting_status IN ('invited', 'updated', 'cancelled', 'response')", name="ck_mail_import_items_meeting_status"),
        sa.CheckConstraint("(starts_at IS NULL AND ends_at IS NULL) OR (starts_at IS NOT NULL AND ends_at IS NOT NULL AND ends_at >= starts_at)", name="ck_mail_import_items_schedule"),
        sa.CheckConstraint("body_text IS NULL OR char_length(body_text) <= 2000000", name="ck_mail_import_items_body_length"),
        sa.CheckConstraint("body_html IS NULL OR char_length(body_html) <= 2000000", name="ck_mail_import_items_html_length"),
        sa.CheckConstraint("content_byte_length >= 0", name="ck_mail_import_items_content_bytes"),
    )
    op.create_index("ix_mail_import_items_owner_received", "mail_import_items", ["owner_id", "received_at", "id"])
    op.create_table(
        "mail_import_attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("mail_import_items.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("content_type", sa.String(200), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("is_inline", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("content_id", sa.String(500), nullable=False, server_default=""),
        sa.Column("data", postgresql.BYTEA(), nullable=False),
        sa.UniqueConstraint("item_id", "ordinal", name="uq_mail_import_attachments_ordinal"),
        sa.CheckConstraint("ordinal >= 0 AND ordinal < 100", name="ck_mail_import_attachments_ordinal"),
        sa.CheckConstraint("size BETWEEN 0 AND 10485760 AND octet_length(data) = size", name="ck_mail_import_attachments_size"),
    )


def downgrade() -> None:
    # The check and DDL share a transaction and block concurrent inserts.
    op.execute("LOCK TABLE mail_import_devices, mail_import_items, mail_import_attachments IN ACCESS EXCLUSIVE MODE")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM mail_import_devices)
               OR EXISTS (SELECT 1 FROM mail_import_items)
               OR EXISTS (SELECT 1 FROM mail_import_attachments) THEN
                RAISE EXCEPTION 'mail_import downgrade blocked: stored data exists';
            END IF;
        END $$;
    """)
    op.drop_table("mail_import_attachments")
    op.drop_table("mail_import_items")
    op.drop_table("mail_import_devices")
