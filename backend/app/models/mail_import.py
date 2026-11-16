"""Private, one-way Outlook Inbox storage; no messaging side effects."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, LargeBinary, String, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class MailImportDevice(Base):
    __tablename__ = "mail_import_devices"
    __table_args__ = (
        CheckConstraint("source_state IS NULL OR source_state IN ('cached', 'online', 'offline')", name="ck_mail_import_devices_source_state"),
        CheckConstraint("last_skipped_items BETWEEN 0 AND 5000", name="ck_mail_import_devices_skipped_items"),
        Index("ix_mail_import_devices_owner_created", "owner_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    include_body: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    include_attachments: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    owner_auth_version: Mapped[int] = mapped_column(Integer, nullable=False)
    pairing_code_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    pairing_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    device_secret_hash: Mapped[str | None] = mapped_column(String(64), unique=True)
    paired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mailbox_id: Mapped[str | None] = mapped_column(String(64))
    mailbox_label: Mapped[str | None] = mapped_column(String(200))
    source_state: Mapped[str | None] = mapped_column(String(10))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_scan_complete: Mapped[bool | None] = mapped_column(Boolean)
    last_skipped_items: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class MailImportItem(Base):
    __tablename__ = "mail_import_items"
    __table_args__ = (
        UniqueConstraint("owner_id", "mailbox_id", "source_id", name="uq_mail_import_items_source"),
        CheckConstraint("kind IN ('mail', 'meeting')", name="ck_mail_import_items_kind"),
        CheckConstraint("meeting_status IS NULL OR meeting_status IN ('invited', 'updated', 'cancelled', 'response')", name="ck_mail_import_items_meeting_status"),
        CheckConstraint("(starts_at IS NULL AND ends_at IS NULL) OR (starts_at IS NOT NULL AND ends_at IS NOT NULL AND ends_at >= starts_at)", name="ck_mail_import_items_schedule"),
        CheckConstraint("body_text IS NULL OR char_length(body_text) <= 2000000", name="ck_mail_import_items_body_length"),
        CheckConstraint("body_html IS NULL OR char_length(body_html) <= 2000000", name="ck_mail_import_items_html_length"),
        CheckConstraint("content_byte_length >= 0", name="ck_mail_import_items_content_bytes"),
        Index("ix_mail_import_items_owner_received", "owner_id", "received_at", "id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    mailbox_id: Mapped[str] = mapped_column(String(64), nullable=False)
    mailbox_label: Mapped[str] = mapped_column(String(200), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    source_modified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    subject: Mapped[str] = mapped_column(String(1000), nullable=False)
    sender_name: Mapped[str] = mapped_column(String(300), nullable=False)
    sender_address: Mapped[str] = mapped_column(String(320), nullable=False)
    body_text: Mapped[str | None] = mapped_column(Text)
    body_html: Mapped[str | None] = mapped_column(Text)
    to_recipients: Mapped[str] = mapped_column(String(20000), nullable=False, default="", server_default="")
    cc_recipients: Mapped[str] = mapped_column(String(20000), nullable=False, default="", server_default="")
    source_is_read: Mapped[bool] = mapped_column(Boolean, nullable=False)
    meeting_status: Mapped[str | None] = mapped_column(String(12))
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    all_day: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    location: Mapped[str] = mapped_column(String(1000), nullable=False, default="", server_default="")
    meeting_key: Mapped[str | None] = mapped_column(String(64))
    is_recurring: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    semantic_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    content_byte_length: Mapped[int] = mapped_column(BigInteger, nullable=False)
    body_captured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    attachments_captured: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_read: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now, server_default=func.now())


class MailImportAttachment(Base):
    __tablename__ = "mail_import_attachments"
    __table_args__ = (
        UniqueConstraint("item_id", "ordinal", name="uq_mail_import_attachments_ordinal"),
        CheckConstraint("ordinal >= 0 AND ordinal < 100", name="ck_mail_import_attachments_ordinal"),
        CheckConstraint("size BETWEEN 0 AND 10485760 AND octet_length(data) = size", name="ck_mail_import_attachments_size"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    item_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mail_import_items.id", ondelete="CASCADE"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(String(200), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size: Mapped[int] = mapped_column(Integer, nullable=False)
    is_inline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    content_id: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
