"""Tracker adapter for the existing notification and Important-message services."""
from sqlalchemy import select

from app.models.notification import Notification
from app.services.messages import emit_attention_event, notification_is_important
from app.services.notifications import create_notification, mark_as_read
from app.services.deadline_tracker_calendar import utc


async def deliver_tracker_alert(db, tracker, occurrence, delivery):
    dedupe = f"tracker:{tracker.id}:{occurrence.id}:{delivery.reminder_id}"
    notification_type = "deadline_tracker_reminder"
    title = f"Напоминание: {tracker.title}"[:255]
    message = f"Срок: {utc(occurrence.due_at).isoformat()}"
    link = f"/deadline-trackers?tracker={tracker.id}"
    notification = await create_notification(
        db, tracker.owner_id, notification_type, title, message, link,
        source_type="notification", dedupe_key=dedupe,
    )
    if not notification_is_important(notification_type):
        # The dedicated event uses the same idempotency key as a future whitelist mirror.
        await emit_attention_event(
            db, target_user_ids=[tracker.owner_id], kind="important",
            event_type=notification_type, source_type="notification", source_key=str(notification.id),
            title=title, body=message, link=link, dedupe_key=dedupe,
            idempotency_key=f"notification:{notification.id}",
        )
    return notification.id


async def mark_tracker_alerts_read(db, tracker):
    from app.models.deadline_tracker import DeadlineTrackerDelivery
    identifiers = list((await db.execute(select(Notification.id).join(
        DeadlineTrackerDelivery, DeadlineTrackerDelivery.notification_id == Notification.id,
    ).where(
        DeadlineTrackerDelivery.tracker_id == tracker.id,
        Notification.user_id == tracker.owner_id, Notification.is_read.is_(False),
    ))).scalars())
    for notification_id in identifiers:
        await mark_as_read(db, notification_id, tracker.owner_id)
    return len(identifiers)
