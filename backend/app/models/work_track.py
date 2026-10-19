"""Task tracks and ordered work sequences."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkTrack(Base):
    """User-owned sequence of DPMS and personal tasks."""

    __tablename__ = "work_tracks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    color: Mapped[str] = mapped_column(String(30), nullable=False, default="slate")
    methodology_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_methodologies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    product_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    route_key: Mapped[str | None] = mapped_column(String(100), nullable=True)
    methodology_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    route_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class WorkTrackItem(Base):
    """One ordered item in a work track."""

    __tablename__ = "work_track_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    track_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_tracks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    item_type: Mapped[str] = mapped_column(String(30), nullable=False, default="manual", index=True)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    personal_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("personal_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    methodology_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_methodologies.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    methodology_node_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    methodology_node_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    methodology_stage_id: Mapped[str | None] = mapped_column(String(120), nullable=True, index=True)
    methodology_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    checklist_snapshot: Mapped[list | dict | None] = mapped_column(JSONB, nullable=True)
    proposed_executor_email: Mapped[str | None] = mapped_column(String(320), nullable=True, index=True)
    proposed_executor_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    reservation_status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft", index=True)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active", index=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class WorkMethodology(Base):
    """Versioned methodology payload imported into DPMS."""

    __tablename__ = "work_methodologies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    methodology_version: Mapped[str | None] = mapped_column(String(80), nullable=True, index=True)
    display_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    release_kind: Mapped[str | None] = mapped_column(String(80), nullable=True)
    source_kind: Mapped[str] = mapped_column(String(60), nullable=False, default="json")
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    stages_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cubes_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    routes_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    products_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )
