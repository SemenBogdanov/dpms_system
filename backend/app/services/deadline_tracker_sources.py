"""Owner-scoped source lookup. No source mutation occurs in tracker code."""
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.models.personal_task import PersonalTask
from app.models.task import Task
from app.models.user import User, UserRole
from app.services.deadline_tracker_calendar import utc


def task_access_clause(user):
    # GET /tasks/{id} uses workspace access without an additional row-level filter.
    return user.role == UserRole.admin or user.task_workspace_enabled


async def get_source(db, tracker, user):
    if tracker.personal_task_id:
        return (await db.execute(select(PersonalTask).where(
            PersonalTask.id == tracker.personal_task_id, PersonalTask.owner_id == user.id,
        ))).scalar_one_or_none()
    if tracker.linked_task_id:
        return (await db.execute(select(Task).where(
            Task.id == tracker.linked_task_id, task_access_clause(user),
        ))).scalar_one_or_none()
    return None


async def reconcile_linked_tracker(db, tracker, *, user=None, now=None):
    """Refresh source-owned dates and metadata; return accessibility, never commit."""
    now = now or datetime.now(timezone.utc)
    if not (tracker.personal_task_id or tracker.linked_task_id):
        from app.services.deadline_tracker_schedule import sync_tracker_schedule, tracker_source_deleted
        if tracker_source_deleted(tracker):
            await sync_tracker_schedule(db, tracker, now=now)
            return False
        return True
    if user is None:
        user = (await db.execute(select(User).where(User.id == tracker.owner_id))).scalar_one_or_none()
    source = await get_source(db, tracker, user) if user and user.is_active else None
    tracker.source_check_at = now + timedelta(seconds=60)
    if source is None:
        return False
    due = source.due_at if tracker.personal_task_id else source.due_date
    if due is None:
        return False
    starts = (source.start_at if tracker.personal_task_id else source.started_at) or source.created_at
    tracker.starts_at = min(utc(starts), utc(due) - timedelta(minutes=1))
    tracker.due_at = due
    prefix = f"PT-{source.task_number}" if tracker.personal_task_id else f"#{source.task_number}"
    tracker.title = f"{prefix} {source.title}"[:200]
    tracker.description = (source.description or source.notes) if tracker.personal_task_id else source.description
    if tracker.personal_task_id:
        tracker.responsible = source.responsible
        tracker.next_action = source.next_step
    else:
        tracker.responsible = (await db.execute(select(User.full_name).where(User.id == source.assignee_id))).scalar_one_or_none() if source.assignee_id else None
    source_status = getattr(source.status, "value", source.status)
    if source_status in {"done", "completed", "validated", "cancelled", "archived"} and tracker.status not in {"done", "archived"}:
        tracker.status = "done"
        tracker.completed_at = now
    from app.services.deadline_tracker_schedule import sync_tracker_schedule
    await sync_tracker_schedule(db, tracker, now=now)
    return True
