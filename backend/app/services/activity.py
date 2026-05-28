"""Activity/audit event helpers."""
from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityEvent
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.schemas.activity import (
    ActivityEventListResponse,
    ActivityEventRead,
    EmployeePeriodSummary,
    EmployeeSummaryTask,
    FocusActivitySummary,
)
from app.services.absences import absence_dates_for_user
from app.services.planning import working_days_in_month

FOCUS_START_EVENTS = {"focus_start"}
FOCUS_PAUSE_EVENTS = {"focus_pause"}
FOCUS_AUTO_PAUSE_EVENTS = {"focus_auto_pause"}
FOCUS_SECONDS_EVENTS = FOCUS_PAUSE_EVENTS | FOCUS_AUTO_PAUSE_EVENTS | {"focus_time_corrected"}
PUBLIC_METADATA_KEYS = {
    "active_seconds",
    "added_seconds",
    "brief_rating",
    "category",
    "due_date",
    "estimated_q",
    "feedback_id",
    "fields",
    "priority",
    "reason",
    "reviewer_id",
    "source",
    "status",
}


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def date_window(start_date: date, end_date: date) -> tuple[datetime, datetime]:
    if end_date < start_date:
        raise ValueError("end_date_before_start_date")
    start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
    return start, end


def _json_safe(value: Any) -> Any:
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, datetime):
        return _to_utc(value).isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(v) for v in value]
    return value


def _event_metadata(metadata: dict | None) -> dict | None:
    if not metadata:
        return None
    return _json_safe(metadata)


async def record_activity_event(
    db: AsyncSession,
    actor_id: uuid.UUID | None,
    event_type: str,
    *,
    task_id: uuid.UUID | None = None,
    metadata: dict | None = None,
    occurred_at: datetime | None = None,
) -> ActivityEvent | None:
    """Append an activity event without committing the transaction."""
    if actor_id is None:
        return None
    event = ActivityEvent(
        actor_id=actor_id,
        event_type=event_type,
        task_id=task_id,
        event_data=_event_metadata(metadata),
        occurred_at=_to_utc(occurred_at or datetime.now(timezone.utc)),
    )
    db.add(event)
    return event


def _event_to_read(event: ActivityEvent, actor: User | None = None, task: Task | None = None) -> ActivityEventRead:
    actor_obj = actor or getattr(event, "actor", None)
    task_obj = task or getattr(event, "task", None)
    metadata = event.event_data or {}
    public_metadata = {key: metadata[key] for key in PUBLIC_METADATA_KEYS if key in metadata}
    return ActivityEventRead(
        id=event.id,
        actor_id=event.actor_id,
        actor_name=actor_obj.full_name if actor_obj else "—",
        event_type=event.event_type,
        task_id=event.task_id,
        task_number=task_obj.task_number if task_obj else None,
        task_title=task_obj.title if task_obj else None,
        metadata=public_metadata or None,
        occurred_at=event.occurred_at,
    )


async def list_activity_events(
    db: AsyncSession,
    *,
    user_id: uuid.UUID | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    event_type: str | None = None,
    limit: int = 200,
) -> ActivityEventListResponse:
    limit = min(max(limit, 1), 500)
    stmt = select(ActivityEvent).order_by(ActivityEvent.occurred_at.desc())
    count_stmt = select(func.count(ActivityEvent.id))

    filters = []
    if user_id is not None:
        filters.append(ActivityEvent.actor_id == user_id)
    if start is not None:
        filters.append(ActivityEvent.occurred_at >= _to_utc(start))
    if end is not None:
        filters.append(ActivityEvent.occurred_at < _to_utc(end))
    if event_type:
        filters.append(ActivityEvent.event_type == event_type)
    if filters:
        stmt = stmt.where(*filters)
        count_stmt = count_stmt.where(*filters)

    result = await db.execute(stmt.limit(limit))
    events = list(result.scalars().all())
    total = int((await db.execute(count_stmt)).scalar() or 0)
    actor_ids = {event.actor_id for event in events}
    task_ids = {event.task_id for event in events if event.task_id}

    actors: dict[uuid.UUID, User] = {}
    if actor_ids:
        actor_result = await db.execute(select(User).where(User.id.in_(actor_ids)))
        actors = {user.id: user for user in actor_result.scalars().all()}

    tasks: dict[uuid.UUID, Task] = {}
    if task_ids:
        task_result = await db.execute(select(Task).where(Task.id.in_(task_ids)))
        tasks = {task.id: task for task in task_result.scalars().all()}

    return ActivityEventListResponse(
        items=[_event_to_read(event, actors.get(event.actor_id), tasks.get(event.task_id)) for event in events],
        total=total,
        limit=limit,
    )


def _month_starts(start_date: date, end_date: date) -> list[date]:
    cursor = date(start_date.year, start_date.month, 1)
    out: list[date] = []
    while cursor <= end_date:
        out.append(cursor)
        if cursor.month == 12:
            cursor = date(cursor.year + 1, 1, 1)
        else:
            cursor = date(cursor.year, cursor.month + 1, 1)
    return out


def _onboarding_factor_for_day(user: User, day: date) -> Decimal:
    if not getattr(user, "is_new_employee", False):
        return Decimal("1")
    until = getattr(user, "onboarding_until", None)
    if until is None:
        return Decimal("0.5")
    until_date = until.date() if isinstance(until, datetime) else until
    return Decimal("0.5") if day < until_date else Decimal("1")


def effective_target_for_date_range(
    user: User,
    start_date: date,
    end_date: date,
    absence_dates: set[date] | None = None,
) -> Decimal:
    if end_date < start_date:
        return Decimal("0")
    monthly_target = Decimal(str(getattr(user, "mpw", 0) or 0))
    if monthly_target <= 0:
        return Decimal("0")

    plan_started_at = getattr(user, "plan_started_at", None)
    plan_start_date = plan_started_at.date() if isinstance(plan_started_at, datetime) else None
    excluded_dates = absence_dates or set()
    target = Decimal("0")

    for month_start in _month_starts(start_date, end_date):
        working_days = working_days_in_month(month_start.year, month_start.month)
        if working_days <= 0:
            continue
        daily_target = monthly_target / Decimal(working_days)
        month_end_day = (date(month_start.year + 1, 1, 1) - timedelta(days=1)) if month_start.month == 12 else (date(month_start.year, month_start.month + 1, 1) - timedelta(days=1))
        current = max(start_date, month_start)
        current_end = min(end_date, month_end_day)
        while current <= current_end:
            if current.weekday() < 5 and current not in excluded_dates and (plan_start_date is None or current >= plan_start_date):
                target += daily_target * _onboarding_factor_for_day(user, current)
            current += timedelta(days=1)

    return target.quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)


def _metadata_int(event: ActivityEvent, key: str) -> int:
    data = event.event_data or {}
    try:
        return int(data.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _summarize_focus(events: list[ActivityEvent]) -> FocusActivitySummary:
    starts = [event for event in events if event.event_type in FOCUS_START_EVENTS]
    pauses = [event for event in events if event.event_type in FOCUS_PAUSE_EVENTS]
    auto_pauses = [event for event in events if event.event_type in FOCUS_AUTO_PAUSE_EVENTS]
    task_ids = {event.task_id for event in starts + pauses + auto_pauses if event.task_id}
    total_seconds = sum(_metadata_int(event, "added_seconds") for event in events if event.event_type in FOCUS_SECONDS_EVENTS)
    avg_pauses = round((len(pauses) + len(auto_pauses)) / len(task_ids), 2) if task_ids else 0.0
    return FocusActivitySummary(
        total_focus_seconds=total_seconds,
        total_focus_hours=round(total_seconds / 3600, 2),
        focus_start_count=len(starts),
        focus_pause_count=len(pauses),
        focus_auto_pause_count=len(auto_pauses),
        focused_tasks_count=len(task_ids),
        avg_pauses_per_task=avg_pauses,
    )


def _task_focus_counts(events: list[ActivityEvent]) -> dict[uuid.UUID, dict[str, int]]:
    counts: dict[uuid.UUID, dict[str, int]] = defaultdict(lambda: {"focus_sessions": 0, "pause_count": 0, "auto_pause_count": 0})
    for event in events:
        if not event.task_id:
            continue
        if event.event_type in FOCUS_START_EVENTS:
            counts[event.task_id]["focus_sessions"] += 1
        elif event.event_type in FOCUS_PAUSE_EVENTS:
            counts[event.task_id]["pause_count"] += 1
        elif event.event_type in FOCUS_AUTO_PAUSE_EVENTS:
            counts[event.task_id]["auto_pause_count"] += 1
    return counts


def _task_to_summary(task: Task, focus_counts: dict[uuid.UUID, dict[str, int]]) -> EmployeeSummaryTask:
    counts = focus_counts.get(task.id, {})
    return EmployeeSummaryTask(
        id=task.id,
        task_number=task.task_number,
        title=task.title,
        status=task.status.value if hasattr(task.status, "value") else str(task.status),
        priority=task.priority.value if hasattr(task.priority, "value") else str(task.priority),
        task_type=task.task_type.value if hasattr(task.task_type, "value") else str(task.task_type),
        estimated_q=float(task.estimated_q),
        started_at=task.started_at,
        completed_at=task.completed_at,
        validated_at=task.validated_at,
        active_seconds=int(task.active_seconds or 0),
        focus_sessions=counts.get("focus_sessions", 0),
        pause_count=counts.get("pause_count", 0),
        auto_pause_count=counts.get("auto_pause_count", 0),
        result_url=task.result_url,
    )


async def generate_employee_period_summary(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> EmployeePeriodSummary:
    start, end = date_window(start_date, end_date)
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise ValueError("user_not_found")
    absence_dates = await absence_dates_for_user(db, user_id, start_date, end_date)

    actor_events_result = await db.execute(
        select(ActivityEvent).where(
            ActivityEvent.actor_id == user_id,
            ActivityEvent.occurred_at >= start,
            ActivityEvent.occurred_at < end,
        ).order_by(ActivityEvent.occurred_at.desc())
    )
    actor_events = list(actor_events_result.scalars().all())

    related_events_result = await db.execute(
        select(ActivityEvent)
        .join(Task, ActivityEvent.task_id == Task.id)
        .where(
            Task.assignee_id == user_id,
            ActivityEvent.actor_id != user_id,
            ActivityEvent.occurred_at >= start,
            ActivityEvent.occurred_at < end,
            ActivityEvent.event_type.in_(("task_assigned", "task_rejected", "task_verified")),
        )
        .order_by(ActivityEvent.occurred_at.desc())
    )
    related_events = list(related_events_result.scalars().all())
    events = sorted(actor_events + related_events, key=lambda event: event.occurred_at, reverse=True)
    focus_counts = _task_focus_counts(events)

    completed_result = await db.execute(
        select(Task).where(
            Task.assignee_id == user_id,
            Task.status == TaskStatus.done,
            Task.validated_at.is_not(None),
            Task.validated_at >= start,
            Task.validated_at < end,
        ).order_by(Task.validated_at.desc())
    )
    completed_tasks = list(completed_result.scalars().all())

    in_progress_result = await db.execute(
        select(Task).where(
            Task.assignee_id == user_id,
            Task.status == TaskStatus.in_progress,
        ).order_by(Task.started_at.desc().nullslast(), Task.created_at.desc())
    )
    in_progress_tasks = list(in_progress_result.scalars().all())

    review_result = await db.execute(
        select(Task).where(
            Task.assignee_id == user_id,
            Task.status == TaskStatus.review,
        ).order_by(Task.completed_at.desc().nullslast(), Task.created_at.desc())
    )
    review_tasks = list(review_result.scalars().all())

    rejection_events = [event for event in events if event.event_type == "task_rejected" and event.task_id]
    rejected_task_ids = list(dict.fromkeys(event.task_id for event in rejection_events if event.task_id))
    rejected_tasks: list[Task] = []
    if rejected_task_ids:
        rejected_result = await db.execute(select(Task).where(Task.id.in_(rejected_task_ids)))
        rejected_map = {task.id: task for task in rejected_result.scalars().all()}
        rejected_tasks = [rejected_map[task_id] for task_id in rejected_task_ids if task_id in rejected_map]

    completed_q = sum(Decimal(str(task.estimated_q)) for task in completed_tasks)
    plan_q = effective_target_for_date_range(user, start_date, end_date, absence_dates)
    efficiency = (completed_q / plan_q * Decimal("100")) if plan_q > 0 else Decimal("0")

    recent_events = events[:50]
    actor_ids = {event.actor_id for event in recent_events}
    actors: dict[uuid.UUID, User] = {}
    if actor_ids:
        actors_result = await db.execute(select(User).where(User.id.in_(actor_ids)))
        actors = {actor.id: actor for actor in actors_result.scalars().all()}

    task_ids = {event.task_id for event in recent_events if event.task_id}
    tasks_map: dict[uuid.UUID, Task] = {}
    if task_ids:
        tasks_result = await db.execute(select(Task).where(Task.id.in_(task_ids)))
        tasks_map = {task.id: task for task in tasks_result.scalars().all()}
    recent_activity = [_event_to_read(event, actors.get(event.actor_id), tasks_map.get(event.task_id)) for event in recent_events]

    return EmployeePeriodSummary(
        user_id=user.id,
        full_name=user.full_name,
        role=user.role.value,
        league=user.league.value,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        plan_q=float(plan_q),
        completed_q=round(float(completed_q), 1),
        efficiency_percent=round(float(efficiency), 1),
        completed_tasks_count=len(completed_tasks),
        in_progress_tasks_count=len(in_progress_tasks),
        review_tasks_count=len(review_tasks),
        rejected_tasks_count=len(rejection_events),
        absence_working_days=len(absence_dates),
        focus=_summarize_focus(events),
        completed_tasks=[_task_to_summary(task, focus_counts) for task in completed_tasks],
        in_progress_tasks=[_task_to_summary(task, focus_counts) for task in in_progress_tasks],
        review_tasks=[_task_to_summary(task, focus_counts) for task in review_tasks],
        rejected_tasks=[_task_to_summary(task, focus_counts) for task in rejected_tasks],
        recent_activity=recent_activity,
    )
