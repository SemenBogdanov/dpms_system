"""Universal private deadline trackers."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, event, func, inspect, text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.orm.attributes import flag_modified

from app.models import Base


class DeadlineTracker(Base):
    """Private timeline item with a start date and a target date."""

    __tablename__ = "deadline_trackers"
    __table_args__ = (
        UniqueConstraint("owner_id", "personal_task_id", name="uq_tracker_owner_personal_task"),
        UniqueConstraint("owner_id", "linked_task_id", name="uq_tracker_owner_task"),
        CheckConstraint("personal_task_id IS NULL OR linked_task_id IS NULL", name="ck_tracker_single_source"),
        CheckConstraint("recurrence IS NULL OR (personal_task_id IS NULL AND linked_task_id IS NULL)", name="ck_tracker_linked_one_time"),
        Index("ix_tracker_expansion", "schedule_check_at", postgresql_where=text("schedule_check_at IS NOT NULL")),
        Index("ix_tracker_source_check", "source_check_at", postgresql_where=text("source_check_at IS NOT NULL")),
    )

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
    tracker_type: Mapped[str] = mapped_column(String(30), nullable=False, default="other", index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="active", index=True)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    pause_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    paused_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_action: Mapped[str | None] = mapped_column(String(500), nullable=True)
    responsible: Mapped[str | None] = mapped_column(String(200), nullable=True)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    group_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("deadline_tracker_groups.id", ondelete="SET NULL"), index=True)
    category_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("deadline_tracker_categories.id", ondelete="SET NULL"), index=True)
    url: Mapped[str | None] = mapped_column(String(2000))
    recurrence: Mapped[dict | None] = mapped_column(JSONB(none_as_null=True))
    schedule_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    next_sequence: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")
    next_occurrence_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    schedule_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_check_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    alerts_suppressed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    personal_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("personal_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    linked_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


_SCHEDULE_TELEMETRY_FIELDS = frozenset({
    "source_check_at", "schedule_check_at", "next_occurrence_at", "next_sequence",
    "alerts_suppressed_until",
})


@event.listens_for(DeadlineTracker, "before_update")
def _preserve_content_timestamp_for_telemetry(mapper, connection, tracker):
    """Scheduler bookkeeping is not a new editor version of the tracker."""
    state = inspect(tracker)
    changed = set()
    for attribute in state.mapper.column_attrs:
        history = state.attrs[attribute.key].history
        if not history.has_changes():
            continue
        if history.added and history.deleted:
            before, after = history.deleted[0], history.added[0]
            if isinstance(before, datetime) and isinstance(after, datetime):
                before = before.replace(tzinfo=timezone.utc) if before.tzinfo is None else before
                after = after.replace(tzinfo=timezone.utc) if after.tzinfo is None else after
                if before == after:
                    continue
        changed.add(attribute.key)
    if changed and changed <= _SCHEDULE_TELEMETRY_FIELDS and tracker.updated_at is not None:
        # Explicitly bind the existing value; assigning it alone is a no-op and
        # SQLAlchemy would still invoke the column's onupdate default.
        flag_modified(tracker, "updated_at")


class DeadlineTrackerGroup(Base):
    __tablename__ = "deadline_tracker_groups"
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str | None] = mapped_column(String(7))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_collapsed: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")


class DeadlineTrackerCategory(Base):
    __tablename__ = "deadline_tracker_categories"
    __table_args__ = (UniqueConstraint("owner_id", "legacy_type", name="uq_tracker_category_legacy"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(100))
    color: Mapped[str | None] = mapped_column(String(7))
    sort_order: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    legacy_type: Mapped[str | None] = mapped_column(String(30))


class DeadlineTrackerOccurrence(Base):
    __tablename__ = "deadline_tracker_occurrences"
    __table_args__ = (
        UniqueConstraint("tracker_id", "schedule_version", "sequence", name="uq_tracker_occurrence_sequence"),
        Index("ix_tracker_occurrence_current", "tracker_id", "status", "due_at"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tracker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("deadline_trackers.id", ondelete="CASCADE"))
    schedule_version: Mapped[int] = mapped_column(Integer, default=1)
    sequence: Mapped[int] = mapped_column(Integer)
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeadlineTrackerReminder(Base):
    __tablename__ = "deadline_tracker_reminders"
    __table_args__ = (UniqueConstraint("tracker_id", "offset_seconds", name="uq_tracker_reminder_offset"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tracker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("deadline_trackers.id", ondelete="CASCADE"))
    value: Mapped[int] = mapped_column(Integer)
    unit: Mapped[str] = mapped_column(String(10))
    offset_seconds: Mapped[int] = mapped_column(Integer)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeadlineTrackerDelivery(Base):
    __tablename__ = "deadline_tracker_deliveries"
    __table_args__ = (
        UniqueConstraint("tracker_id", "occurrence_id", "reminder_id", name="uq_tracker_delivery"),
        Index("ix_tracker_delivery_due", "status", "scheduled_for"),
        Index("ix_tracker_delivery_history", "tracker_id", "scheduled_for"),
    )
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tracker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("deadline_trackers.id", ondelete="CASCADE"))
    occurrence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("deadline_tracker_occurrences.id", ondelete="CASCADE"))
    reminder_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("deadline_tracker_reminders.id", ondelete="CASCADE"))
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="pending", server_default="pending")
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    notification_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey("notifications.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class DeadlineTrackerEvent(Base):
    __tablename__ = "deadline_tracker_events"
    __table_args__ = (Index("ix_tracker_event_history", "tracker_id", "created_at"),)
    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tracker_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("deadline_trackers.id", ondelete="CASCADE"))
    event_type: Mapped[str] = mapped_column(String(40))
    details: Mapped[dict] = mapped_column(JSONB, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
