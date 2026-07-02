"""API for personal tasks."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_task_workspace_access
from app.models.personal_task import PersonalTask, PersonalTaskCheckpoint, PersonalTaskEvent
from app.models.quick_note import QuickNote
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.schemas.personal_task import (
    PersonalTaskCreate,
    PersonalTaskCheckpointCreate,
    PersonalTaskCheckpointRead,
    PersonalTaskCheckpointUpdate,
    PersonalTaskDeadlineRead,
    PersonalTaskEventCreate,
    PersonalTaskEventRead,
    PersonalTaskPromoteRequest,
    PersonalTaskRead,
    PersonalTaskUpdate,
)
from app.schemas.task import TaskRead
from app.services.activity import record_activity_event
from app.services.task_policy import ensure_critical_priority_allowed

router = APIRouter()

ACTIVE_STATUSES = {"inbox", "planned", "next", "in_progress", "waiting", "blocked"}
VALID_STATUSES = ACTIVE_STATUSES | {"done", "archived"}


async def _get_owned_task_or_404(db: AsyncSession, task_id: UUID, owner_id: UUID) -> PersonalTask:
    result = await db.execute(
        select(PersonalTask).where(PersonalTask.id == task_id, PersonalTask.owner_id == owner_id)
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Личная задача не найдена")
    return task


async def _ensure_linked_task_exists(db: AsyncSession, task_id: UUID | None) -> None:
    if task_id is None:
        return
    result = await db.execute(select(Task.id).where(Task.id == task_id))
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Связанная DPMS-задача не найдена")


async def _get_owned_note_or_404(db: AsyncSession, note_id: UUID | None, owner_id: UUID) -> QuickNote | None:
    if note_id is None:
        return None
    result = await db.execute(
        select(QuickNote).where(QuickNote.id == note_id, QuickNote.owner_id == owner_id)
    )
    note = result.scalar_one_or_none()
    if note is None:
        raise HTTPException(status_code=404, detail="Связанная заметка не найдена")
    return note


def _serialize(task: PersonalTask) -> PersonalTaskRead:
    return PersonalTaskRead.model_validate(task)


def _add_event(
    db: AsyncSession,
    task: PersonalTask,
    user: User,
    event_type: str,
    *,
    title: str | None = None,
    body: str | None = None,
    from_status: str | None = None,
    to_status: str | None = None,
    next_step: str | None = None,
    waiting_for: str | None = None,
    due_at: datetime | None = None,
    metadata_json: dict | None = None,
) -> PersonalTaskEvent:
    event = PersonalTaskEvent(
        task_id=task.id,
        actor_id=user.id,
        event_type=event_type,
        title=title,
        body=body,
        from_status=from_status,
        to_status=to_status,
        next_step=next_step,
        waiting_for=waiting_for,
        due_at=due_at,
        metadata_json=metadata_json,
    )
    db.add(event)
    return event


def _task_description(task: PersonalTask) -> str | None:
    parts: list[str] = []
    if task.description:
        parts.append(task.description)
    if task.acceptance_criteria:
        parts.append(f"Критерии приемки:\n{task.acceptance_criteria}")
    if task.next_step:
        parts.append(f"Следующий шаг:\n{task.next_step}")
    if task.notes:
        parts.append(f"Рабочие заметки:\n{task.notes}")
    return "\n\n".join(parts) or None


@router.get("", response_model=list[PersonalTaskRead])
async def list_personal_tasks(
    status: str | None = Query("active"),
    search: str | None = Query(None),
    category: str | None = Query(None),
    priority: str | None = Query(None),
    limit: int = Query(100, ge=1, le=300),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List current user's personal issue-lite tasks."""
    query = select(PersonalTask).where(PersonalTask.owner_id == user.id)
    if status and status != "all":
        if status == "active":
            query = query.where(PersonalTask.status.in_(ACTIVE_STATUSES))
        elif status in VALID_STATUSES:
            query = query.where(PersonalTask.status == status)
        else:
            raise HTTPException(status_code=400, detail="Некорректный статус личной задачи")
    if category:
        query = query.where(PersonalTask.category == category)
    if priority:
        query = query.where(PersonalTask.priority == priority)
    if search:
        pattern = f"%{search.strip()}%"
        query = query.where(
            or_(
                PersonalTask.title.ilike(pattern),
                PersonalTask.description.ilike(pattern),
                PersonalTask.notes.ilike(pattern),
                PersonalTask.project.ilike(pattern),
                PersonalTask.context.ilike(pattern),
                PersonalTask.next_step.ilike(pattern),
            )
        )
    query = query.order_by(
        PersonalTask.due_at.is_(None),
        PersonalTask.due_at.asc(),
        PersonalTask.next_step_at.is_(None),
        PersonalTask.next_step_at.asc(),
        PersonalTask.created_at.desc(),
    ).limit(limit)
    result = await db.execute(query)
    return [_serialize(task) for task in result.scalars().all()]


@router.post("", response_model=PersonalTaskRead)
async def create_personal_task(
    body: PersonalTaskCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a private task owned by current user."""
    await _ensure_linked_task_exists(db, body.linked_task_id)
    note = await _get_owned_note_or_404(db, body.source_quick_note_id, user.id)
    task = PersonalTask(
        owner_id=user.id,
        title=body.title,
        description=body.description,
        notes=body.notes,
        status=body.status,
        priority=body.priority,
        category=body.category,
        project=body.project,
        context=body.context,
        responsible=body.responsible,
        tags=body.tags,
        acceptance_criteria=body.acceptance_criteria,
        next_step=body.next_step,
        next_step_at=body.next_step_at,
        due_at=body.due_at,
        waiting_for=body.waiting_for,
        blocked_reason=body.blocked_reason,
        impact=body.impact,
        effort=body.effort,
        linked_task_id=body.linked_task_id,
        source_quick_note_id=body.source_quick_note_id,
    )
    db.add(task)
    if note and note.status == "draft":
        note.status = "processed"
        note.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(task)
    _add_event(
        db,
        task,
        user,
        "task_created",
        title="Задача создана",
        metadata_json={"status": task.status, "priority": task.priority},
    )
    await db.flush()
    return _serialize(task)


@router.get("/deadlines", response_model=list[PersonalTaskDeadlineRead])
async def list_personal_task_deadlines(
    limit: int = Query(50, ge=1, le=200),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List current user's upcoming task/checkpoint deadlines for tracker strips."""
    now = datetime.now(timezone.utc)
    task_result = await db.execute(
        select(PersonalTask)
        .where(
            PersonalTask.owner_id == user.id,
            PersonalTask.due_at.is_not(None),
            PersonalTask.status.notin_(["done", "archived"]),
        )
        .order_by(PersonalTask.due_at.asc())
        .limit(limit)
    )
    items: list[PersonalTaskDeadlineRead] = []
    for task in task_result.scalars().all():
        if task.due_at is None:
            continue
        items.append(
            PersonalTaskDeadlineRead(
                item_type="task",
                item_id=task.id,
                task_id=task.id,
                task_key=f"PT-{task.task_number}",
                task_title=task.title,
                title=task.next_step or task.title,
                status=task.status,
                due_at=task.due_at,
                start_at=task.created_at or now,
                responsible=task.responsible,
                waiting_for=task.waiting_for,
                project=task.project,
            )
        )

    checkpoint_result = await db.execute(
        select(PersonalTaskCheckpoint, PersonalTask)
        .join(PersonalTask, PersonalTaskCheckpoint.task_id == PersonalTask.id)
        .where(
            PersonalTask.owner_id == user.id,
            PersonalTaskCheckpoint.due_at.is_not(None),
            PersonalTaskCheckpoint.status != "done",
            PersonalTask.status != "archived",
        )
        .order_by(PersonalTaskCheckpoint.due_at.asc())
        .limit(limit)
    )
    for checkpoint, task in checkpoint_result.all():
        if checkpoint.due_at is None:
            continue
        items.append(
            PersonalTaskDeadlineRead(
                item_type="checkpoint",
                item_id=checkpoint.id,
                task_id=task.id,
                task_key=f"PT-{task.task_number}",
                task_title=task.title,
                title=checkpoint.title,
                status=checkpoint.status,
                due_at=checkpoint.due_at,
                start_at=checkpoint.created_at or task.created_at or now,
                responsible=task.responsible,
                waiting_for=checkpoint.waiting_for,
                project=task.project,
            )
        )
    items.sort(key=lambda item: item.due_at)
    return items[:limit]


@router.patch("/{task_id}", response_model=PersonalTaskRead)
async def update_personal_task(
    task_id: UUID,
    body: PersonalTaskUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Patch current user's personal task."""
    task = await _get_owned_task_or_404(db, task_id, user.id)
    old_status = task.status
    update_data = body.model_dump(exclude_unset=True)
    if "linked_task_id" in update_data:
        await _ensure_linked_task_exists(db, body.linked_task_id)
    if "source_quick_note_id" in update_data:
        await _get_owned_note_or_404(db, body.source_quick_note_id, user.id)
    for field, value in update_data.items():
        setattr(task, field, value)
    task.updated_at = datetime.now(timezone.utc)
    changed_fields = sorted(update_data.keys())
    if "status" in update_data and update_data["status"] != old_status:
        _add_event(
            db,
            task,
            user,
            "status_changed",
            title="Статус изменен",
            from_status=old_status,
            to_status=update_data["status"],
            next_step=task.next_step,
            waiting_for=task.waiting_for,
            due_at=task.due_at,
            metadata_json={"fields": changed_fields},
        )
    elif changed_fields:
        _add_event(
            db,
            task,
            user,
            "task_updated",
            title="Задача обновлена",
            metadata_json={"fields": changed_fields},
        )
    await db.flush()
    await db.refresh(task)
    return _serialize(task)


@router.get("/{task_id}/events", response_model=list[PersonalTaskEventRead])
async def list_personal_task_events(
    task_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Read task timeline."""
    await _get_owned_task_or_404(db, task_id, user.id)
    result = await db.execute(
        select(PersonalTaskEvent)
        .where(PersonalTaskEvent.task_id == task_id)
        .order_by(PersonalTaskEvent.created_at.desc(), PersonalTaskEvent.id.desc())
    )
    return result.scalars().all()


@router.post("/{task_id}/events", response_model=PersonalTaskEventRead)
async def create_personal_task_event(
    task_id: UUID,
    body: PersonalTaskEventCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Append meeting/follow-up/note to task timeline."""
    task = await _get_owned_task_or_404(db, task_id, user.id)
    event = _add_event(
        db,
        task,
        user,
        body.event_type,
        title=body.title,
        body=body.body,
        next_step=body.next_step,
        waiting_for=body.waiting_for,
        due_at=body.due_at,
        metadata_json=body.metadata_json,
    )
    if body.next_step is not None:
        task.next_step = body.next_step
    if body.waiting_for is not None:
        task.waiting_for = body.waiting_for
        if task.status not in ("done", "archived"):
            task.status = "waiting"
    task.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(event)
    return event


@router.get("/{task_id}/checkpoints", response_model=list[PersonalTaskCheckpointRead])
async def list_personal_task_checkpoints(
    task_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Read task control checkpoints."""
    await _get_owned_task_or_404(db, task_id, user.id)
    result = await db.execute(
        select(PersonalTaskCheckpoint)
        .where(PersonalTaskCheckpoint.task_id == task_id)
        .order_by(
            PersonalTaskCheckpoint.status == "done",
            PersonalTaskCheckpoint.due_at.is_(None),
            PersonalTaskCheckpoint.due_at.asc(),
            PersonalTaskCheckpoint.sort_order.asc(),
            PersonalTaskCheckpoint.created_at.desc(),
        )
    )
    return result.scalars().all()


@router.post("/{task_id}/checkpoints", response_model=PersonalTaskCheckpointRead)
async def create_personal_task_checkpoint(
    task_id: UUID,
    body: PersonalTaskCheckpointCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create new task control checkpoint/stage."""
    task = await _get_owned_task_or_404(db, task_id, user.id)
    checkpoint = PersonalTaskCheckpoint(
        task_id=task.id,
        title=body.title,
        status=body.status,
        next_step=body.next_step,
        waiting_for=body.waiting_for,
        notes=body.notes,
        due_at=body.due_at,
        completed_at=datetime.now(timezone.utc) if body.status == "done" else None,
        sort_order=body.sort_order,
    )
    db.add(checkpoint)
    if body.next_step:
        task.next_step = body.next_step
    if body.waiting_for:
        task.waiting_for = body.waiting_for
    if body.due_at and (task.due_at is None or body.due_at < task.due_at):
        task.due_at = body.due_at
    if task.status == "inbox":
        task.status = "planned"
    task.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(checkpoint)
    _add_event(
        db,
        task,
        user,
        "checkpoint_created",
        title=checkpoint.title,
        body=checkpoint.notes,
        next_step=checkpoint.next_step,
        waiting_for=checkpoint.waiting_for,
        due_at=checkpoint.due_at,
        metadata_json={"checkpoint_id": str(checkpoint.id), "status": checkpoint.status},
    )
    await db.flush()
    return checkpoint


@router.patch("/{task_id}/checkpoints/{checkpoint_id}", response_model=PersonalTaskCheckpointRead)
async def update_personal_task_checkpoint(
    task_id: UUID,
    checkpoint_id: UUID,
    body: PersonalTaskCheckpointUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Patch task control checkpoint/stage."""
    task = await _get_owned_task_or_404(db, task_id, user.id)
    result = await db.execute(
        select(PersonalTaskCheckpoint).where(
            PersonalTaskCheckpoint.id == checkpoint_id,
            PersonalTaskCheckpoint.task_id == task.id,
        )
    )
    checkpoint = result.scalar_one_or_none()
    if checkpoint is None:
        raise HTTPException(status_code=404, detail="Этап не найден")
    update_data = body.model_dump(exclude_unset=True)
    old_status = checkpoint.status
    for field, value in update_data.items():
        setattr(checkpoint, field, value)
    if "status" in update_data:
        checkpoint.completed_at = datetime.now(timezone.utc) if checkpoint.status == "done" else None
    checkpoint.updated_at = datetime.now(timezone.utc)
    if checkpoint.next_step:
        task.next_step = checkpoint.next_step
    if checkpoint.waiting_for:
        task.waiting_for = checkpoint.waiting_for
    if checkpoint.due_at and (task.due_at is None or checkpoint.due_at < task.due_at):
        task.due_at = checkpoint.due_at
    task.updated_at = datetime.now(timezone.utc)
    event_type = "checkpoint_done" if checkpoint.status == "done" and old_status != "done" else "checkpoint_updated"
    _add_event(
        db,
        task,
        user,
        event_type,
        title=checkpoint.title,
        body=checkpoint.notes,
        next_step=checkpoint.next_step,
        waiting_for=checkpoint.waiting_for,
        due_at=checkpoint.due_at,
        metadata_json={"checkpoint_id": str(checkpoint.id), "old_status": old_status, "status": checkpoint.status},
    )
    await db.flush()
    await db.refresh(checkpoint)
    return checkpoint


@router.delete("/{task_id}/checkpoints/{checkpoint_id}")
async def delete_personal_task_checkpoint(
    task_id: UUID,
    checkpoint_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete task control checkpoint/stage."""
    task = await _get_owned_task_or_404(db, task_id, user.id)
    result = await db.execute(
        select(PersonalTaskCheckpoint).where(
            PersonalTaskCheckpoint.id == checkpoint_id,
            PersonalTaskCheckpoint.task_id == task.id,
        )
    )
    checkpoint = result.scalar_one_or_none()
    if checkpoint is None:
        raise HTTPException(status_code=404, detail="Этап не найден")
    await db.delete(checkpoint)
    await db.flush()
    return {"deleted": True, "checkpoint_id": str(checkpoint_id)}


@router.post("/{task_id}/promote", response_model=TaskRead)
async def promote_personal_task(
    task_id: UUID,
    body: PersonalTaskPromoteRequest,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Create a global DPMS queue task from a personal task."""
    personal_task = await _get_owned_task_or_404(db, task_id, user.id)
    if personal_task.promoted_task_id:
        result = await db.execute(select(Task).where(Task.id == personal_task.promoted_task_id))
        existing = result.scalar_one_or_none()
        if existing:
            return existing

    ensure_critical_priority_allowed(user, body.priority)
    if body.task_type.value == "proactive" and body.priority.value in ("high", "critical"):
        raise HTTPException(
            status_code=400,
            detail="Проактивные задачи не могут иметь приоритет выше medium",
        )

    tags = body.tags if body.tags is not None else personal_task.tags
    task = Task(
        title=personal_task.title,
        description=_task_description(personal_task),
        task_type=body.task_type,
        complexity=body.complexity,
        estimated_q=Decimal(str(body.estimated_q)),
        priority=body.priority,
        status=TaskStatus.in_queue,
        min_league=body.min_league,
        assignee_id=None,
        estimator_id=user.id,
        validator_id=None,
        estimation_details={
            "source": "personal_task",
            "personal_task_id": str(personal_task.id),
            "personal_task_key": f"PT-{personal_task.task_number}",
            "promoted_at": datetime.now(timezone.utc).isoformat(),
        },
        due_date=body.due_date or personal_task.due_at,
        tags=tags,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)

    personal_task.promoted_task_id = task.id
    personal_task.linked_task_id = task.id
    personal_task.promoted_at = datetime.now(timezone.utc)
    personal_task.status = "planned" if personal_task.status == "inbox" else personal_task.status
    personal_task.updated_at = datetime.now(timezone.utc)
    _add_event(
        db,
        personal_task,
        user,
        "promoted",
        title=f"Выведено в глобальную очередь #{task.task_number}",
        metadata_json={"global_task_id": str(task.id), "global_task_number": task.task_number},
    )
    await record_activity_event(
        db,
        user.id,
        "personal_task_promoted",
        task_id=task.id,
        metadata={"personal_task_id": str(personal_task.id), "personal_task_key": f"PT-{personal_task.task_number}"},
    )
    await db.flush()
    return task


@router.delete("/{task_id}")
async def delete_personal_task(
    task_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete current user's personal task."""
    task = await _get_owned_task_or_404(db, task_id, user.id)
    await db.delete(task)
    await db.flush()
    return {"deleted": True, "task_id": str(task_id)}
