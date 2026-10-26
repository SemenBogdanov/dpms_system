"""Immutable host boot events and a durable per-source import heartbeat."""
from __future__ import annotations

from datetime import datetime
import uuid

from sqlalchemy import CheckConstraint, DateTime, Float, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class ServerBootEvent(Base):
    __tablename__ = "server_boot_events"
    __table_args__ = (
        UniqueConstraint("source_id", "event_id", name="uq_server_boot_events_source_event"),
        CheckConstraint("uptime_seconds >= 0", name="ck_server_boot_events_uptime"),
        Index("ix_server_boot_events_boot_time", "boot_time", "event_id", "source_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    event_id: Mapped[str] = mapped_column(String(32), nullable=False)
    boot_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    uptime_seconds: Mapped[float] = mapped_column(Float, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class ServerBootImportStatus(Base):
    __tablename__ = "server_boot_import_status"
    __table_args__ = (
        CheckConstraint("invalid_files >= 0", name="ck_server_boot_import_invalid"),
        CheckConstraint("conflicting_files >= 0", name="ck_server_boot_import_conflicting"),
        CheckConstraint("checked_files >= 0", name="ck_server_boot_import_checked"),
        CheckConstraint(
            "error_code IS NULL OR error_code IN "
            "('directory_missing', 'directory_unreadable', 'scan_failed', "
            "'invalid_files', 'conflicting_files', 'too_many_files')",
            name="ck_server_boot_import_error_code",
        ),
    )

    source_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    last_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_success_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    invalid_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    conflicting_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    checked_files: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    error_code: Mapped[str | None] = mapped_column(String(32))
