"""Durable tracker schedule. Callers commit; tracker row locks serialize mutations."""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import select, update

from app.models.deadline_tracker import (
    DeadlineTracker, DeadlineTrackerDelivery, DeadlineTrackerEvent,
    DeadlineTrackerOccurrence, DeadlineTrackerReminder,
)
from app.services.deadline_tracker_calendar import effective_due, first_occurrence_after, occurrence_due, utc
from app.schemas.deadline_tracker import TrackerRecurrence

EXPANSION_LIMIT = 512
SOURCE_CHECK_DISABLED_AT = datetime(9999, 1, 1, tzinfo=timezone.utc)


def tracker_source_deleted(tracker):
    # SET NULL removes the FK, but not this durable marker of a former source.
    return not (tracker.personal_task_id or tracker.linked_task_id) and tracker.source_check_at is not None


def record_event(db, tracker, event_type, **details):
    db.add(DeadlineTrackerEvent(tracker_id=tracker.id, event_type=event_type, details=details))


async def set_reminders(db, tracker, inputs, *, now=None):
    now = now or datetime.now(timezone.utc)
    rows = list((await db.execute(select(DeadlineTrackerReminder).where(
        DeadlineTrackerReminder.tracker_id == tracker.id,
    ))).scalars())
    by_offset = {r.offset_seconds: r for r in rows}
    offsets = {r.offset_seconds for r in inputs}
    for row in rows:
        row.is_active = row.offset_seconds in offsets
    for item in inputs:
        row = by_offset.get(item.offset_seconds)
        if row is None:
            row = DeadlineTrackerReminder(tracker_id=tracker.id, offset_seconds=item.offset_seconds, created_at=now)
            db.add(row)
        row.value, row.unit, row.is_active = item.value, item.unit, True
    await db.flush()
    inactive = [r.id for r in rows if not r.is_active]
    if inactive:
        await db.execute(update(DeadlineTrackerDelivery).where(
            DeadlineTrackerDelivery.tracker_id == tracker.id,
            DeadlineTrackerDelivery.reminder_id.in_(inactive),
            DeadlineTrackerDelivery.status == "pending",
        ).values(status="cancelled"))


async def _schedule_occurrences(db, tracker, occurrences, reminders, *, now):
    if not occurrences or not reminders:
        return
    deliveries = list((await db.execute(select(DeadlineTrackerDelivery).where(
        DeadlineTrackerDelivery.tracker_id == tracker.id,
        DeadlineTrackerDelivery.occurrence_id.in_([o.id for o in occurrences]),
    ))).scalars())
    by_pair = {(d.occurrence_id, d.reminder_id): d for d in deliveries}
    for occurrence in occurrences:
        for reminder in reminders:
            when = utc(occurrence.due_at) - timedelta(seconds=reminder.offset_seconds)
            delivery = by_pair.get((occurrence.id, reminder.id))
            if delivery is None:
                eligible = when >= utc(reminder.created_at) and (
                    tracker.alerts_suppressed_until is None or when > utc(tracker.alerts_suppressed_until)
                )
                db.add(DeadlineTrackerDelivery(
                    id=uuid4(), tracker_id=tracker.id, occurrence_id=occurrence.id, reminder_id=reminder.id,
                    scheduled_for=when, status="pending" if eligible else "suppressed",
                ))
            elif delivery.status == "pending" and utc(delivery.scheduled_for) > now:
                # Sent or already-due points stay immutable when deadlines move.
                delivery.scheduled_for = when
                if when < now:
                    delivery.status = "suppressed"
            elif delivery.status == "cancelled" and when > now:
                delivery.scheduled_for = when
                delivery.status = "pending"


async def expand_tracker(db, tracker, *, now=None):
    now = now or datetime.now(timezone.utc)
    reminders = list((await db.execute(select(DeadlineTrackerReminder).where(
        DeadlineTrackerReminder.tracker_id == tracker.id, DeadlineTrackerReminder.is_active.is_(True),
    ))).scalars())
    horizon = now + timedelta(days=31, seconds=max((r.offset_seconds for r in reminders), default=0))
    rule = TrackerRecurrence.model_validate(tracker.recurrence) if tracker.recurrence else None
    needs_frontier = await db.scalar(select(DeadlineTrackerOccurrence.id).where(
        DeadlineTrackerOccurrence.tracker_id == tracker.id,
        DeadlineTrackerOccurrence.schedule_version == tracker.schedule_version,
        DeadlineTrackerOccurrence.status == "pending",
    ).limit(1)) is None
    dates = []
    for _ in range(EXPANSION_LIMIT):
        due = tracker.next_occurrence_at
        if due is None or (utc(due) > horizon and not needs_frontier):
            break
        dates.append((tracker.next_sequence, due))
        # Keep one visible next occurrence even for yearly/long-interval series.
        # Once one is planned, the usual horizon bounds all further expansion.
        needs_frontier = False
        tracker.next_sequence += 1
        tracker.next_occurrence_at = occurrence_due(effective_due(tracker), rule, tracker.next_sequence)
    if dates:
        existing = {o.sequence: o for o in (await db.execute(select(DeadlineTrackerOccurrence).where(
            DeadlineTrackerOccurrence.tracker_id == tracker.id,
            DeadlineTrackerOccurrence.schedule_version == tracker.schedule_version,
            DeadlineTrackerOccurrence.sequence.in_([sequence for sequence, _ in dates]),
        ))).scalars()}
        materialized = []
        for sequence, due in dates:
            occurrence = existing.get(sequence)
            if occurrence is None:
                occurrence = DeadlineTrackerOccurrence(
                    id=uuid4(), tracker_id=tracker.id, schedule_version=tracker.schedule_version,
                    sequence=sequence, due_at=due, status="pending",
                )
                db.add(occurrence)
                record_event(db, tracker, "occurrence_created", occurrence_id=str(occurrence.id), due_at=utc(due).isoformat())
            if occurrence.status == "pending":
                materialized.append(occurrence)
        # One batched flush, never a round trip per occurrence.
        await db.flush()
        await _schedule_occurrences(db, tracker, materialized, reminders, now=now)
    tracker.schedule_check_at = (
        utc(tracker.next_occurrence_at) - (horizon - now)
        if tracker.next_occurrence_at else None
    )
    await db.flush()


async def sync_tracker_schedule(db, tracker, *, now=None):
    """Hook for personal-task/Q-task updates, before commit. Preserves delivery history.

    The tracker lock must precede delivery locks everywhere (including the worker).
    Flushing before the SELECT also locks existing tracker rows changed by callers.
    """
    now = now or datetime.now(timezone.utc)
    await db.flush()
    await db.execute(select(DeadlineTracker.id).where(DeadlineTracker.id == tracker.id).with_for_update())
    source_deleted = tracker_source_deleted(tracker)
    if source_deleted:
        recorded = await db.scalar(select(DeadlineTrackerEvent.id).where(
            DeadlineTrackerEvent.tracker_id == tracker.id,
            DeadlineTrackerEvent.event_type == "source_deleted",
        ).limit(1))
        if recorded is None:
            record_event(db, tracker, "source_deleted")
        if recorded is None or tracker.status != "archived" or tracker.pause_started_at is not None:
            tracker.updated_at = now
        tracker.status = "archived"
        tracker.pause_started_at = None
        tracker.next_occurrence_at = None
    if tracker.schedule_version is None:
        tracker.schedule_version = 1
    if tracker.next_sequence is None:
        tracker.next_sequence = 1
    if tracker.next_sequence == 1 and tracker.next_occurrence_at is None:
        tracker.next_occurrence_at = effective_due(tracker)
    if tracker.status in {"done", "archived"}:
        tracker.schedule_check_at = None
        # Keep provenance after SET NULL, without selecting terminal rows every tick.
        tracker.source_check_at = SOURCE_CHECK_DISABLED_AT if (
            source_deleted or tracker.personal_task_id or tracker.linked_task_id
        ) else None
        await db.execute(update(DeadlineTrackerDelivery).where(
            DeadlineTrackerDelivery.tracker_id == tracker.id,
            DeadlineTrackerDelivery.status == "pending",
        ).values(status="cancelled"))
        if not tracker.recurrence or source_deleted:
            await db.execute(update(DeadlineTrackerOccurrence).where(
                DeadlineTrackerOccurrence.tracker_id == tracker.id, DeadlineTrackerOccurrence.status == "pending",
            ).values(status="completed" if tracker.status == "done" else "cancelled", completed_at=tracker.completed_at))
        await db.flush()
        return
    if (tracker.personal_task_id or tracker.linked_task_id) and (
        tracker.source_check_at is None or utc(tracker.source_check_at) == SOURCE_CHECK_DISABLED_AT
    ):
        tracker.source_check_at = now
    reminders = list((await db.execute(select(DeadlineTrackerReminder).where(
        DeadlineTrackerReminder.tracker_id == tracker.id, DeadlineTrackerReminder.is_active.is_(True),
    ))).scalars())
    occurrences = list((await db.execute(select(DeadlineTrackerOccurrence).where(
        DeadlineTrackerOccurrence.tracker_id == tracker.id,
        DeadlineTrackerOccurrence.status == "pending",
        DeadlineTrackerOccurrence.schedule_version == tracker.schedule_version,
    ))).scalars())
    for occurrence in occurrences:
        if not tracker.recurrence and occurrence.schedule_version == tracker.schedule_version:
            old_due = utc(occurrence.due_at)
            occurrence.due_at = effective_due(tracker)
            if old_due != occurrence.due_at:
                record_event(db, tracker, "deadline_changed", occurrence_id=str(occurrence.id), old_due_at=old_due.isoformat(), due_at=occurrence.due_at.isoformat())
    await _schedule_occurrences(db, tracker, occurrences, reminders, now=now)
    await db.flush()
    await expand_tracker(db, tracker, now=now)
    await db.flush()


async def suppress_due_deliveries(db, tracker, *, now=None):
    now = now or datetime.now(timezone.utc)
    tracker.alerts_suppressed_until = now
    await db.execute(update(DeadlineTrackerDelivery).where(
        DeadlineTrackerDelivery.tracker_id == tracker.id,
        DeadlineTrackerDelivery.status == "pending",
        DeadlineTrackerDelivery.scheduled_for <= now,
    ).values(status="suppressed"))


async def reset_series_schedule(db, tracker, *, now=None):
    """An edited recurrence starts a new revision; prior history is retained."""
    now = now or datetime.now(timezone.utc)
    if tracker_source_deleted(tracker):
        await sync_tracker_schedule(db, tracker, now=now)
        return
    tracker.alerts_suppressed_until = max(
        now, utc(tracker.alerts_suppressed_until) if tracker.alerts_suppressed_until else now,
    )
    await db.execute(update(DeadlineTrackerDelivery).where(
        DeadlineTrackerDelivery.tracker_id == tracker.id,
        DeadlineTrackerDelivery.status == "pending",
        DeadlineTrackerDelivery.scheduled_for > now,
    ).values(status="cancelled"))
    await db.execute(update(DeadlineTrackerOccurrence).where(
        DeadlineTrackerOccurrence.tracker_id == tracker.id,
        DeadlineTrackerOccurrence.status == "pending",
        DeadlineTrackerOccurrence.due_at > now,
    ).values(status="cancelled"))
    tracker.schedule_version += 1
    if tracker.recurrence:
        tracker.next_sequence, tracker.next_occurrence_at = first_occurrence_after(
            effective_due(tracker), tracker.recurrence, now,
        )
    else:
        tracker.next_sequence = 1
        tracker.next_occurrence_at = effective_due(tracker)
    await sync_tracker_schedule(db, tracker, now=now)


async def reopen_one_time_tracker(db, tracker, *, now=None):
    """Explicit user reopen creates a new occurrence, retaining terminal history."""
    now = now or datetime.now(timezone.utc)
    if tracker_source_deleted(tracker):
        await sync_tracker_schedule(db, tracker, now=now)
        return
    if tracker.recurrence is not None:
        raise ValueError("Only a one-time tracker can use this reopen action")
    tracker.schedule_version += 1
    tracker.next_sequence = 1
    tracker.next_occurrence_at = effective_due(tracker)
    tracker.completed_at = None
    tracker.alerts_suppressed_until = max(
        now, utc(tracker.alerts_suppressed_until) if tracker.alerts_suppressed_until else now,
    )
    record_event(db, tracker, "reopened", schedule_version=tracker.schedule_version)
    await sync_tracker_schedule(db, tracker, now=now)
