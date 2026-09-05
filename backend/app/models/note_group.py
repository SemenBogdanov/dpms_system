"""Private organization and explicit, replay-safe sharing of quick notes."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class NoteGroup(Base):
    __tablename__ = "note_groups"
    __table_args__ = (
        CheckConstraint("position >= 0", name="ck_note_groups_position"),
        CheckConstraint("revision >= 1", name="ck_note_groups_revision"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(160))
    position: Mapped[int] = mapped_column(Integer, default=0)
    collapsed: Mapped[bool] = mapped_column(Boolean, default=False)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    revision: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, onupdate=utc_now)


class NoteContextLink(Base):
    """Context is not an ACL and is never copied into project-visible artifacts."""
    __tablename__ = "note_context_links"
    __table_args__ = (
        CheckConstraint("(group_id IS NULL) <> (note_id IS NULL)", name="ck_note_context_source"),
        CheckConstraint("(entity_id IS NULL) <> (personal_task_id IS NULL)", name="ck_note_context_target"),
        UniqueConstraint("group_id", "entity_id", name="uq_note_context_group_entity"),
        UniqueConstraint("group_id", "personal_task_id", name="uq_note_context_group_task"),
        UniqueConstraint("note_id", "entity_id", name="uq_note_context_note_entity"),
        UniqueConstraint("note_id", "personal_task_id", name="uq_note_context_note_task"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("note_groups.id", ondelete="CASCADE"), index=True)
    note_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("quick_notes.id", ondelete="CASCADE"), index=True)
    entity_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("work_entities.id", ondelete="CASCADE"), index=True)
    personal_task_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("personal_tasks.id", ondelete="CASCADE"), index=True)


class NoteShareBatch(Base):
    """Owner-only preview plus durable audit of exactly what was applied."""
    __tablename__ = "note_share_batches"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    snapshot: Mapped[dict] = mapped_column(JSONB)
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
