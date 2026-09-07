"""Durable source staging, deliberately independent of the working audit registry."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, JSON, LargeBinary, String
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class AuditLegacyImport(Base):
    __tablename__ = "audit_legacy_imports"
    __table_args__ = (
        CheckConstraint("status IN ('uploaded', 'checked')", name="ck_audit_legacy_status"),
        CheckConstraint("revision >= 1", name="ck_audit_legacy_revision"),
        CheckConstraint("size_bytes > 0 AND size_bytes <= 10485760", name="ck_audit_legacy_size"),
        CheckConstraint(
            "(status = 'uploaded' AND mapping IS NULL AND report IS NULL) OR "
            "(status = 'checked' AND mapping IS NOT NULL AND report IS NOT NULL)",
            name="ck_audit_legacy_check_state",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="uploaded", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    source_bytes: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False, deferred=True, deferred_raiseload=True,
    )
    inspection: Mapped[dict] = mapped_column(
        JSONB(none_as_null=True).with_variant(JSON(none_as_null=True), "sqlite"), nullable=False,
    )
    mapping: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True).with_variant(JSON(none_as_null=True), "sqlite"), nullable=True,
    )
    report: Mapped[dict | None] = mapped_column(
        JSONB(none_as_null=True).with_variant(JSON(none_as_null=True), "sqlite"), nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now, nullable=False,
    )
