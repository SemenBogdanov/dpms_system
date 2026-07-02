"""API for universal private deadline trackers."""
from datetime import datetime, timedelta, timezone
import math
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.deadline_tracker import DeadlineTracker
from app.models.personal_task import PersonalTask
from app.models.task import Task
from app.models.user import User
from app.schemas.deadline_tracker import (
    DeadlineTrackerCreate,
    DeadlineTrackerRead,
    DeadlineTrackerStatus,
    DeadlineTrackerType,
    DeadlineTrackerUpdate,
)

router = APIRouter()


async def _get_owned_tracker_or_404(
    db: AsyncSession,
    tracker_id: UUID,
    owner_id: UUID,
) -> DeadlineTracker:
    result = await db.execute(
        select(DeadlineTracker).where(
            DeadlineTracker.id == tracker_id,
            DeadlineTracker.owner_id == owner_id,
        )
    )
    tracker = result.scalar_one_or_none()
    if not tracker:
        raise HTTPException(status_code=404, detail="Трекер срока не найден")
    return tracker


async def _ensure_personal_task_owner(
    db: AsyncSession,
    personal_task_id: UUID | None,
    owner_id: UUID,
) -> None:
    if personal_task_id is None:
        return
    result = await db.execute(
        select(PersonalTask.id).where(
            PersonalTask.id == personal_task_id,
            PersonalTask.owner_id == owner_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Связанная личная задача не найдена")


async def _ensure_linked_task_exists(db: AsyncSession, task_id: UUID | None) -> None:
    if task_id is None:
        return
    result = await db.execute(select(Task.id).where(Task.id == task_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Связанная DPMS-задача не найдена")

async def _get_task_or_404(db: AsyncSession, task_id: UUID) -> Task:
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="DPMS-задача не найдена")
    return task

async def _get_owned_personal_task_or_404(
    db: AsyncSession,
    task_id: UUID,
    owner_id: UUID,
) -> PersonalTask:
    result = await db.execute(
        select(PersonalTask).where(PersonalTask.id == task_id, PersonalTask.owner_id == owner_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Личная задача не найдена")
    return task

async def _get_tracker_by_link(
    db: AsyncSession,
    owner_id: UUID,
    linked_task_id: UUID | None = None,
    personal_task_id: UUID | None = None,
) -> DeadlineTracker | None:
    stmt = select(DeadlineTracker).where(DeadlineTracker.owner_id == owner_id)
    if linked_task_id is not None:
        stmt = stmt.where(DeadlineTracker.linked_task_id == linked_task_id)
    if personal_task_id is not None:
        stmt = stmt.where(DeadlineTracker.personal_task_id == personal_task_id)
    result = await db.execute(stmt.order_by(DeadlineTracker.created_at.desc()).limit(1))
    return result.scalar_one_or_none()


async def _read_payload(
    db: AsyncSession,
    trackers: list[DeadlineTracker],
) -> list[DeadlineTrackerRead]:
    now = datetime.now(timezone.utc)
    task_ids = [tracker.personal_task_id for tracker in trackers if tracker.personal_task_id]
    personal_tasks: dict[UUID, PersonalTask] = {}
    if task_ids:
        result = await db.execute(select(PersonalTask).where(PersonalTask.id.in_(task_ids)))
        personal_tasks = {task.id: task for task in result.scalars().all()}

    items: list[DeadlineTrackerRead] = []
    for tracker in trackers:
        personal_task = personal_tasks.get(tracker.personal_task_id) if tracker.personal_task_id else None
        item = DeadlineTrackerRead.model_validate(tracker)
        item.total_pause_seconds = _total_pause_seconds(tracker, now)
        item.shifted_due_at = tracker.due_at + timedelta(days=_pause_days(item.total_pause_seconds))
        if personal_task:
            item.personal_task_key = f"PT-{personal_task.task_number}"
            item.personal_task_title = personal_task.title
        items.append(item)
    return items


def _total_pause_seconds(tracker: DeadlineTracker, now: datetime | None = None) -> int:
    total = max(0, tracker.paused_seconds or 0)
    if tracker.status == "paused" and tracker.pause_started_at is not None:
        current = now or datetime.now(timezone.utc)
        total += max(1, int((current - tracker.pause_started_at).total_seconds()))
    return total


def _pause_days(total_pause_seconds: int) -> int:
    if total_pause_seconds <= 0:
        return 0
    return max(1, math.ceil(total_pause_seconds / 86_400))


def _close_pause_period(tracker: DeadlineTracker, now: datetime | None = None) -> None:
    if tracker.pause_started_at is None:
        return
    current = now or datetime.now(timezone.utc)
    tracker.paused_seconds = max(0, tracker.paused_seconds or 0) + max(
        0,
        int((current - tracker.pause_started_at).total_seconds()),
    )
    tracker.pause_started_at = None


def _apply_status_side_effects(tracker: DeadlineTracker, new_status: str | None) -> None:
    now = datetime.now(timezone.utc)
    if new_status == "done" and tracker.completed_at is None:
        _close_pause_period(tracker, now)
        tracker.completed_at = now
    elif new_status == "paused":
        tracker.completed_at = None
        if tracker.pause_started_at is None:
            tracker.pause_started_at = now
    elif new_status == "active":
        _close_pause_period(tracker, now)
        tracker.completed_at = None
    elif new_status == "archived":
        _close_pause_period(tracker, now)

def _activate_tracker(tracker: DeadlineTracker) -> None:
    _close_pause_period(tracker)
    tracker.status = "active"
    tracker.completed_at = None
    tracker.updated_at = datetime.now(timezone.utc)

def _safe_starts_at(candidate: datetime | None, due_at: datetime) -> datetime:
    starts_at = candidate or datetime.now(timezone.utc)
    if starts_at >= due_at:
        return due_at - timedelta(minutes=1)
    return starts_at


@router.get("", response_model=list[DeadlineTrackerRead])
async def list_deadline_trackers(
    status_filter: DeadlineTrackerStatus | None = Query(None, alias="status"),
    tracker_type: DeadlineTrackerType | None = Query(None),
    search: str | None = Query(None, min_length=1, max_length=100),
    include_archived: bool = Query(False),
    limit: int = Query(100, ge=1, le=300),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List current user's deadline trackers."""
    stmt = select(DeadlineTracker).where(DeadlineTracker.owner_id == user.id)
    if status_filter:
        stmt = stmt.where(DeadlineTracker.status == status_filter)
    elif not include_archived:
        stmt = stmt.where(DeadlineTracker.status != "archived")
    if tracker_type:
        stmt = stmt.where(DeadlineTracker.tracker_type == tracker_type)
    if search:
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                DeadlineTracker.title.ilike(pattern),
                DeadlineTracker.description.ilike(pattern),
                DeadlineTracker.next_action.ilike(pattern),
                DeadlineTracker.responsible.ilike(pattern),
            )
        )
    result = await db.execute(stmt.order_by(DeadlineTracker.due_at.asc()).limit(limit))
    return await _read_payload(db, list(result.scalars().all()))


@router.post("", response_model=DeadlineTrackerRead)
async def create_deadline_tracker(
    payload: DeadlineTrackerCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create deadline tracker for current user."""
    await _ensure_personal_task_owner(db, payload.personal_task_id, user.id)
    await _ensure_linked_task_exists(db, payload.linked_task_id)
    tracker = DeadlineTracker(
        owner_id=user.id,
        title=payload.title,
        description=payload.description,
        tracker_type=payload.tracker_type,
        status=payload.status,
        starts_at=payload.starts_at,
        due_at=payload.due_at,
        next_action=payload.next_action,
        responsible=payload.responsible,
        tags=payload.tags,
        personal_task_id=payload.personal_task_id,
        linked_task_id=payload.linked_task_id,
    )
    _apply_status_side_effects(tracker, payload.status)
    db.add(tracker)
    await db.commit()
    await db.refresh(tracker)
    return (await _read_payload(db, [tracker]))[0]


@router.post("/from-task/{task_id}", response_model=DeadlineTrackerRead)
async def create_tracker_from_task(
    task_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Put a DPMS task into current user's tracker without exposing UUID in UI."""
    task = await _get_task_or_404(db, task_id)
    if task.due_date is None:
        raise HTTPException(status_code=400, detail="У задачи не задан дедлайн")

    tracker = await _get_tracker_by_link(db, owner_id=user.id, linked_task_id=task.id)
    starts_at = _safe_starts_at(task.started_at or task.created_at, task.due_date)
    if tracker is None:
        tracker = DeadlineTracker(
            owner_id=user.id,
            title=f"#{task.task_number} {task.title}",
            description=task.description,
            tracker_type="task",
            status="active",
            starts_at=starts_at,
            due_at=task.due_date,
            next_action="Контроль выполнения DPMS-задачи",
            responsible=None,
            tags=["dpms"],
            linked_task_id=task.id,
        )
        db.add(tracker)
    else:
        tracker.title = f"#{task.task_number} {task.title}"
        tracker.description = task.description
        tracker.tracker_type = "task"
        tracker.starts_at = starts_at
        tracker.due_at = task.due_date
        tracker.next_action = tracker.next_action or "Контроль выполнения DPMS-задачи"
        tracker.tags = tracker.tags or ["dpms"]
        _activate_tracker(tracker)

    await db.commit()
    await db.refresh(tracker)
    return (await _read_payload(db, [tracker]))[0]


@router.delete("/by-task/{task_id}")
async def delete_tracker_by_task(
    task_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove current user's tracker linked to a DPMS task."""
    tracker = await _get_tracker_by_link(db, owner_id=user.id, linked_task_id=task_id)
    if tracker is None:
        raise HTTPException(status_code=404, detail="Связанный трекер не найден")
    await db.delete(tracker)
    await db.commit()
    return {"status": "deleted"}


@router.post("/from-personal-task/{task_id}", response_model=DeadlineTrackerRead)
async def create_tracker_from_personal_task(
    task_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Put a personal task into current user's tracker without entering UUID manually."""
    task = await _get_owned_personal_task_or_404(db, task_id, user.id)
    if task.due_at is None:
        raise HTTPException(status_code=400, detail="У личной задачи не задан дедлайн")

    tracker = await _get_tracker_by_link(db, owner_id=user.id, personal_task_id=task.id)
    starts_at = _safe_starts_at(task.created_at, task.due_at)
    if tracker is None:
        tracker = DeadlineTracker(
            owner_id=user.id,
            title=f"PT-{task.task_number} {task.title}",
            description=task.description or task.notes,
            tracker_type="task",
            status="active",
            starts_at=starts_at,
            due_at=task.due_at,
            next_action=task.next_step,
            responsible=task.responsible,
            tags=["личная-задача", *task.tags],
            personal_task_id=task.id,
        )
        db.add(tracker)
    else:
        tracker.title = f"PT-{task.task_number} {task.title}"
        tracker.description = task.description or task.notes
        tracker.tracker_type = "task"
        tracker.starts_at = starts_at
        tracker.due_at = task.due_at
        tracker.next_action = task.next_step
        tracker.responsible = task.responsible
        tracker.tags = tracker.tags or ["личная-задача", *task.tags]
        _activate_tracker(tracker)

    await db.commit()
    await db.refresh(tracker)
    return (await _read_payload(db, [tracker]))[0]


@router.delete("/by-personal-task/{task_id}")
async def delete_tracker_by_personal_task(
    task_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove current user's tracker linked to a personal task."""
    tracker = await _get_tracker_by_link(db, owner_id=user.id, personal_task_id=task_id)
    if tracker is None:
        raise HTTPException(status_code=404, detail="Связанный трекер не найден")
    await db.delete(tracker)
    await db.commit()
    return {"status": "deleted"}


@router.patch("/{tracker_id}", response_model=DeadlineTrackerRead)
async def update_deadline_tracker(
    tracker_id: UUID,
    payload: DeadlineTrackerUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Patch current user's deadline tracker."""
    tracker = await _get_owned_tracker_or_404(db, tracker_id, user.id)
    data = payload.model_dump(exclude_unset=True)
    personal_task_id = data.get("personal_task_id", tracker.personal_task_id)
    linked_task_id = data.get("linked_task_id", tracker.linked_task_id)
    starts_at = data.get("starts_at", tracker.starts_at)
    due_at = data.get("due_at", tracker.due_at)

    if due_at <= starts_at:
        raise HTTPException(status_code=400, detail="Дедлайн должен быть позже даты старта")

    await _ensure_personal_task_owner(db, personal_task_id, user.id)
    await _ensure_linked_task_exists(db, linked_task_id)

    for field, value in data.items():
        setattr(tracker, field, value)
    _apply_status_side_effects(tracker, data.get("status"))
    tracker.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(tracker)
    return (await _read_payload(db, [tracker]))[0]


@router.delete("/{tracker_id}")
async def delete_deadline_tracker(
    tracker_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete current user's deadline tracker."""
    tracker = await _get_owned_tracker_or_404(db, tracker_id, user.id)
    await db.delete(tracker)
    await db.commit()
    return {"status": "deleted"}
