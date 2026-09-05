"""Run with python -m app.workers.deadline_reminders; --healthcheck checks heartbeat.

No process-local hub is required: notifications and Important projections commit
atomically with delivery rows. The API's existing resync reads those durable rows.
"""
import argparse
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
import time

from sqlalchemy import select

from app.models.deadline_tracker import (
    DeadlineTracker, DeadlineTrackerDelivery, DeadlineTrackerOccurrence, DeadlineTrackerReminder,
)
from app.models.user import User
from app.services.deadline_tracker_notifications import deliver_tracker_alert
from app.services.deadline_tracker_schedule import expand_tracker, record_event
from app.services.deadline_tracker_sources import reconcile_linked_tracker

logger = logging.getLogger("deadline_reminders")


async def expand_due_schedules(db, *, now, limit=20, tracker_ids=None):
    rows = list((await db.execute(select(DeadlineTracker).where(
        DeadlineTracker.schedule_check_at <= now,
        DeadlineTracker.status.not_in(["done", "archived"]),
        DeadlineTracker.id.in_(tracker_ids) if tracker_ids is not None else True,
    ).order_by(DeadlineTracker.schedule_check_at, DeadlineTracker.id).limit(limit)
        .with_for_update(skip_locked=True))).scalars())
    for tracker in rows:
        await expand_tracker(db, tracker, now=now)
    return len(rows)


async def reconcile_due_sources(db, *, now, limit=20, tracker_ids=None):
    rows = list((await db.execute(select(DeadlineTracker).where(
        DeadlineTracker.source_check_at <= now,
        DeadlineTracker.status.not_in(["done", "archived"]),
        DeadlineTracker.id.in_(tracker_ids) if tracker_ids is not None else True,
    ).order_by(DeadlineTracker.source_check_at, DeadlineTracker.id).limit(limit)
        .with_for_update(skip_locked=True))).scalars())
    for tracker in rows:
        await reconcile_linked_tracker(db, tracker, now=now)
    return len(rows)


def due_delivery_query(now, limit, tracker_ids=None):
    return select(DeadlineTrackerDelivery.id, DeadlineTrackerDelivery.tracker_id).where(
        DeadlineTrackerDelivery.status == "pending",
        DeadlineTrackerDelivery.scheduled_for <= now,
        DeadlineTrackerDelivery.tracker_id.in_(tracker_ids) if tracker_ids is not None else True,
    ).order_by(DeadlineTrackerDelivery.scheduled_for, DeadlineTrackerDelivery.id).limit(limit)


async def deliver_due(db, *, now, limit=50, tracker_ids=None):
    candidates = (await db.execute(due_delivery_query(now, limit, tracker_ids))).all()
    sent = 0
    for delivery_id, tracker_id in candidates:
        # Lock order is tracker -> delivery everywhere; concurrent workers skip busy rows.
        tracker = (await db.execute(select(DeadlineTracker).where(
            DeadlineTracker.id == tracker_id,
        ).with_for_update(skip_locked=True).execution_options(populate_existing=True))).scalar_one_or_none()
        if tracker is None:
            continue
        accessible = await reconcile_linked_tracker(db, tracker, now=now)
        delivery = (await db.execute(select(DeadlineTrackerDelivery).where(
            DeadlineTrackerDelivery.id == delivery_id,
            DeadlineTrackerDelivery.status == "pending",
            DeadlineTrackerDelivery.scheduled_for <= now,
        ).with_for_update(skip_locked=True).execution_options(populate_existing=True))).scalar_one_or_none()
        if delivery is None:
            continue
        occurrence = await db.get(DeadlineTrackerOccurrence, delivery.occurrence_id)
        reminder = await db.get(DeadlineTrackerReminder, delivery.reminder_id)
        owner_active = (await db.execute(select(User.is_active).where(User.id == tracker.owner_id))).scalar_one_or_none()
        if not (accessible and owner_active and tracker.status == "active" and
                occurrence and occurrence.status == "pending" and reminder and reminder.is_active):
            delivery.status = "suppressed"
            record_event(db, tracker, "reminder_suppressed", delivery_id=str(delivery.id))
            continue
        delivery.notification_id = await deliver_tracker_alert(db, tracker, occurrence, delivery)
        delivery.status = "sent"
        delivery.delivered_at = now
        record_event(db, tracker, "reminder_sent", delivery_id=str(delivery.id), occurrence_id=str(occurrence.id))
        sent += 1
    await db.flush()
    return sent


async def run_once(session_factory, *, now=None, batch_size=50, tracker_ids=None):
    now = now or datetime.now(timezone.utc)
    # Short transactions bound lock duration; interrupted transactions are retried intact.
    async with session_factory() as db, db.begin():
        await reconcile_due_sources(db, now=now, limit=min(batch_size, 20), tracker_ids=tracker_ids)
    async with session_factory() as db, db.begin():
        await expand_due_schedules(db, now=now, limit=min(batch_size, 20), tracker_ids=tracker_ids)
    async with session_factory() as db, db.begin():
        return await deliver_due(db, now=now, limit=batch_size, tracker_ids=tracker_ids)


def heartbeat_path():
    return Path(os.environ.get("DEADLINE_WORKER_HEARTBEAT", "/tmp/deadline-worker.heartbeat"))


async def run():
    from app.database import AsyncSessionLocal
    poll = max(0.5, float(os.environ.get("DEADLINE_WORKER_POLL_SECONDS", "5")))
    batch_size = max(1, min(200, int(os.environ.get("DEADLINE_WORKER_BATCH_SIZE", "50"))))
    while True:
        try:
            sent = await run_once(AsyncSessionLocal, batch_size=batch_size)
            heartbeat_path().touch()
            if sent:
                logger.info("delivered=%d", sent)
        except Exception as exc:
            # SQLAlchemy exception messages may contain connection parameters or SQL data.
            logger.error("tick_failed error_type=%s", type(exc).__name__)
        await asyncio.sleep(poll)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args()
    if args.healthcheck:
        try:
            age = time.time() - heartbeat_path().stat().st_mtime
            raise SystemExit(0 if age < max(120, float(os.environ.get("DEADLINE_WORKER_POLL_SECONDS", "5")) * 4) else 1)
        except OSError:
            raise SystemExit(1)
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())


if __name__ == "__main__":
    main()
