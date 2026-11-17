"""Private queue for the direct-PostgreSQL mail transport."""
from __future__ import annotations

from datetime import datetime
from uuid import UUID as PyUUID

from sqlalchemy import BigInteger, Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, false, text, true
from sqlalchemy.dialects.postgresql import JSONB, OID, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class MailImportDBLogin(Base):
    """DBA-only authorization; an existing DB login never implies a DPMS owner."""
    __tablename__ = "mail_import_db_logins"

    role_oid: Mapped[int] = mapped_column(OID, primary_key=True)
    role_name: Mapped[str] = mapped_column(String(63), nullable=False, unique=True)
    owner_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    include_body: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    include_attachments: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())


class MailImportDBDevice(Base):
    __tablename__ = "mail_import_db_devices"

    device_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), ForeignKey("mail_import_devices.id", ondelete="CASCADE"), primary_key=True)
    # Keep the identity snapshot if a DBA removes the login mapping. A missing
    # mapping must deny access, not turn this into an unbound legacy device.
    role_oid: Mapped[int] = mapped_column(OID, nullable=False)
    role_name: Mapped[str] = mapped_column(String(63), nullable=False)


class MailImportQueue(Base):
    __tablename__ = "mail_import_queue"
    __table_args__ = (
        CheckConstraint("payload_bytes BETWEEN 1 AND 33554432", name="ck_mail_import_queue_bytes"),
        CheckConstraint("(login_role_oid IS NULL) = (login_role_name IS NULL)", name="ck_mail_import_queue_login"),
        CheckConstraint(
            "(state = 'pending' AND payload IS NOT NULL AND result IS NULL AND error_code IS NULL "
            "AND error_status IS NULL AND finished_at IS NULL) OR "
            "(state = 'done' AND payload IS NULL AND result IS NOT NULL AND error_code IS NULL "
            "AND error_status IS NULL AND finished_at IS NOT NULL) OR "
            "(state = 'error' AND payload IS NULL AND result IS NULL AND error_code IS NOT NULL "
            "AND error_status IS NOT NULL AND error_status BETWEEN 400 AND 599 AND finished_at IS NOT NULL)",
            name="ck_mail_import_queue_state",
        ),
        Index("uq_mail_import_queue_pending_device", "device_id", unique=True, postgresql_where=text("state = 'pending'")),
        Index("ix_mail_import_queue_owner_state", "owner_id", "state"),
        Index("ix_mail_import_queue_pending", "created_at", postgresql_where=text("state = 'pending'")),
        Index("ix_mail_import_queue_finished", "finished_at"),
    )

    # Auth snapshots, deliberately not FKs: enqueue must not acquire device/user
    # row locks through FK checks. The worker revalidates both before any import.
    device_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    request_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    owner_id: Mapped[PyUUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    device_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    login_role_oid: Mapped[int | None] = mapped_column(OID)
    login_role_name: Mapped[str | None] = mapped_column(String(63))
    payload: Mapped[str | None] = mapped_column(Text)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    payload_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(String(8), nullable=False, default="pending", server_default="pending")
    result: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    error_code: Mapped[str | None] = mapped_column(String(80))
    error_status: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
