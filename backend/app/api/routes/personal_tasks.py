"""API for personal tasks."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_current_user, get_db, require_task_workspace_access
from app.models.deadline_tracker import DeadlineTracker
from app.models.personal_task import PersonalTask, PersonalTaskCheckpoint, PersonalTaskEvent
from app.models.personal_task_artifact import (
    PersonalTaskArtifact,
    PersonalTaskArtifactVersion,
    utc_now,
)
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
    PersonalTaskPromotedTaskRead,
    PersonalTaskArtifactRead,
    PersonalTaskArtifactUpdate,
    PersonalTaskArtifactVersionRead,
    PersonalTaskRead,
    PersonalTaskUpdate,
)
from app.schemas.task import TaskRead
from app.services.activity import record_activity_event
from app.services.attachments import stored_attachment_path
from app.services.personal_task_artifacts import (
    add_artifact_version,
    clean_optional,
    clean_title,
    create_artifact,
    ensure_task_accepts_artifact_changes,
    remove_version_file,
)
from app.services.task_policy import ensure_critical_priority_allowed
from app.services.storage_quota import (
    finalize_storage_file_deletion,
    schedule_storage_file_deletion,
)

router = APIRouter()

ACTIVE_STATUSES = {"inbox", "planned", "next", "in_progress", "waiting", "blocked"}
VALID_STATUSES = ACTIVE_STATUSES | {"done", "archived"}
PUBLISHABLE_PERSONAL_TASK_STATUSES = ACTIVE_STATUSES - {"in_progress"}
ACTIVE_QUEUE_HANDOFF_STATUSES = set(TaskStatus) - {TaskStatus.cancelled}


async def _get_owned_task_or_404(
    db: AsyncSession,
    task_id: UUID,
    owner_id: UUID,
    *,
    for_update: bool = False,
) -> PersonalTask:
    statement = select(PersonalTask).where(
        PersonalTask.id == task_id,
        PersonalTask.owner_id == owner_id,
    )
    if for_update:
        statement = statement.with_for_update()
    result = await db.execute(statement)
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Личная задача не найдена")
    return task


async def _get_artifact_or_404(
    db: AsyncSession,
    task_id: UUID,
    artifact_id: UUID,
    *,
    for_update: bool = False,
) -> PersonalTaskArtifact:
    statement = (
        select(PersonalTaskArtifact)
        .options(selectinload(PersonalTaskArtifact.versions))
        .where(
            PersonalTaskArtifact.id == artifact_id,
            PersonalTaskArtifact.task_id == task_id,
        )
    )
    if for_update:
        statement = statement.with_for_update()
    artifact = (await db.execute(statement)).scalar_one_or_none()
    if artifact is None:
        raise HTTPException(status_code=404, detail="Материал не найден")
    return artifact


def _artifact_read(
    task: PersonalTask,
    artifact: PersonalTaskArtifact,
) -> PersonalTaskArtifactRead:
    versions = sorted(
        artifact.versions,
        key=lambda item: item.version_number,
        reverse=True,
    )
    return PersonalTaskArtifactRead(
        id=artifact.id,
        task_id=artifact.task_id,
        artifact_type=artifact.artifact_type,
        title=artifact.title,
        description=artifact.description,
        status=artifact.status,
        current_version=artifact.current_version,
        created_by_id=artifact.created_by_id,
        updated_by_id=artifact.updated_by_id,
        archived_at=artifact.archived_at,
        created_at=artifact.created_at,
        updated_at=artifact.updated_at,
        can_edit=task.status != "archived",
        versions=[PersonalTaskArtifactVersionRead.model_validate(item) for item in versions],
    )


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


def _execution_task_id(task: PersonalTask) -> UUID | None:
    return task.promoted_task_id or task.linked_task_id


def _execution_task_ids_for(
    promoted_task_id: UUID | None,
    linked_task_id: UUID | None,
) -> tuple[UUID, ...]:
    return tuple(
        dict.fromkeys(
            task_id
            for task_id in (promoted_task_id, linked_task_id)
            if task_id is not None
        )
    )


def _execution_task_ids(task: PersonalTask) -> tuple[UUID, ...]:
    return _execution_task_ids_for(task.promoted_task_id, task.linked_task_id)


async def _get_execution_task_states(
    db: AsyncSession,
    execution_task_ids: tuple[UUID, ...],
    *,
    for_update: bool = False,
) -> list[tuple[Task, User | None]]:
    if not execution_task_ids:
        return []
    statement = (
        select(Task, User)
        .outerjoin(User, Task.assignee_id == User.id)
        .where(Task.id.in_(execution_task_ids))
    )
    if for_update:
        statement = statement.with_for_update(of=Task)
    result = await db.execute(statement)
    states_by_id = {
        execution_task.id: (execution_task, assignee)
        for execution_task, assignee in result.all()
    }
    return [
        states_by_id[task_id]
        for task_id in execution_task_ids
        if task_id in states_by_id
    ]


async def _get_execution_task_state(
    db: AsyncSession,
    task: PersonalTask,
    *,
    for_update: bool = False,
) -> tuple[Task | None, User | None]:
    states = await _get_execution_task_states(
        db,
        _execution_task_ids(task),
        for_update=for_update,
    )
    return states[0] if states else (None, None)


def _serialize(
    task: PersonalTask,
    execution_task: Task | None = None,
    assignee: User | None = None,
) -> PersonalTaskRead:
    serialized = PersonalTaskRead.model_validate(task)
    if execution_task is None:
        return serialized
    task_state = PersonalTaskPromotedTaskRead(
        id=execution_task.id,
        task_number=execution_task.task_number,
        status=execution_task.status,
        assignee_id=execution_task.assignee_id,
        assignee_name=assignee.full_name if assignee else None,
        started_at=execution_task.started_at,
        due_date=execution_task.due_date,
    )
    update: dict[str, PersonalTaskPromotedTaskRead] = {"execution_task": task_state}
    if task.promoted_task_id == execution_task.id:
        update["promoted_task"] = task_state
    return serialized.model_copy(
        update=update
    )


def _ensure_status_context(
    status: str,
    waiting_for: str | None,
    blocked_reason: str | None,
) -> None:
    if status == "waiting" and not waiting_for:
        raise HTTPException(status_code=400, detail="Укажите, что или кого ждем")
    if status == "blocked" and not blocked_reason:
        raise HTTPException(status_code=400, detail="Укажите причину блокировки")


def _queue_handoff_conflict_detail(
    execution_task: Task | None,
    assignee: User | None,
) -> str:
    if execution_task is None:
        return (
            "Связанная задача Q недоступна для проверки. "
            "Локальный старт заблокирован, чтобы не создать двойное выполнение."
        )
    task_label = f"Q #{execution_task.task_number}"
    if execution_task.status in {TaskStatus.new, TaskStatus.estimated, TaskStatus.in_queue}:
        return (
            f"Связанная задача {task_label} опубликована в глобальной очереди и ожидает исполнения. "
            "Выполняйте работу через Q-задачу; повторный локальный старт запрещен."
        )
    if execution_task.status == TaskStatus.done:
        return (
            f"Связанная задача {task_label} уже выполнена через глобальную очередь. "
            "Повторный локальный старт запрещен."
        )
    assignee_label = assignee.full_name if assignee else "исполнитель не указан"
    return (
        f"Связанная задача {task_label} уже выполняется: {assignee_label}. "
        "Откройте Q-задачу и согласуйте отдельную часть работы; "
        "параллельный старт той же работы запрещен."
    )


def _task_start_at(task: PersonalTask) -> datetime:
    return task.start_at or task.created_at or datetime.now(timezone.utc)


def _ensure_valid_task_dates(start_at: datetime | None, due_at: datetime | None) -> None:
    if start_at is not None and due_at is not None and due_at <= start_at:
        raise HTTPException(status_code=400, detail="Дедлайн должен быть позже даты старта")


def _safe_tracker_start_at(start_at: datetime, due_at: datetime) -> datetime:
    if start_at >= due_at:
        return due_at - timedelta(minutes=1)
    return start_at


async def _sync_linked_deadline_tracker(db: AsyncSession, task: PersonalTask) -> None:
    """Keep personal-task tracker dates aligned with the parent task."""
    result = await db.execute(
        select(DeadlineTracker).where(
            DeadlineTracker.personal_task_id == task.id,
            DeadlineTracker.owner_id == task.owner_id,
        )
    )
    tracker = result.scalar_one_or_none()
    if tracker is None:
        return
    tracker.title = f"PT-{task.task_number} {task.title}"
    tracker.description = task.description or task.notes
    if task.due_at is None:
        tracker.status = "archived"
        tracker.updated_at = datetime.now(timezone.utc)
        return
    tracker.starts_at = _safe_tracker_start_at(_task_start_at(task), task.due_at)
    tracker.due_at = task.due_at
    tracker.next_action = task.next_step
    tracker.responsible = task.responsible
    tracker.updated_at = datetime.now(timezone.utc)


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
    tasks = list(result.scalars().all())
    execution_ids = {
        execution_id
        for task in tasks
        if (execution_id := _execution_task_id(task)) is not None
    }
    execution_states: dict[UUID, tuple[Task, User | None]] = {}
    if execution_ids:
        state_result = await db.execute(
            select(Task, User)
            .outerjoin(User, Task.assignee_id == User.id)
            .where(Task.id.in_(execution_ids))
        )
        execution_states = {
            execution_task.id: (execution_task, assignee)
            for execution_task, assignee in state_result.all()
        }
    return [
        _serialize(task, *execution_states.get(_execution_task_id(task), (None, None)))
        for task in tasks
    ]


@router.post("", response_model=PersonalTaskRead)
async def create_personal_task(
    body: PersonalTaskCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a private task owned by current user."""
    _ensure_valid_task_dates(body.start_at, body.due_at)
    _ensure_status_context(body.status, body.waiting_for, body.blocked_reason)
    if body.linked_task_id is not None:
        raise HTTPException(
            status_code=409,
            detail=(
                "Ручная связь личной задачи с Q-задачей недоступна. "
                "Опубликуйте личную задачу в глобальную очередь."
            ),
        )
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
        start_at=body.start_at or datetime.now(timezone.utc),
        due_at=body.due_at,
        waiting_for=body.waiting_for,
        blocked_reason=body.blocked_reason,
        impact=body.impact,
        effort=body.effort,
        linked_task_id=None,
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
        metadata_json={"status": task.status, "priority": task.priority, "start_at": task.start_at.isoformat()},
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
                start_at=_task_start_at(task),
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
            PersonalTaskCheckpoint.completed_at.is_(None),
            PersonalTask.status.notin_(["done", "archived"]),
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


@router.get("/{task_id}", response_model=PersonalTaskRead)
async def get_personal_task(
    task_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Read a personal task with the current state of its promoted queue task."""
    task = await _get_owned_task_or_404(db, task_id, user.id)
    execution_task, assignee = await _get_execution_task_state(db, task)
    return _serialize(task, execution_task, assignee)


@router.patch("/{task_id}", response_model=PersonalTaskRead)
async def update_personal_task(
    task_id: UUID,
    body: PersonalTaskUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Patch current user's personal task."""
    task = await _get_owned_task_or_404(db, task_id, user.id, for_update=True)
    old_status = task.status
    old_waiting_for = task.waiting_for
    old_blocked_reason = task.blocked_reason
    update_data = body.model_dump(exclude_unset=True)
    required_fields = {"title", "status", "priority", "category", "tags", "start_at"}
    invalid_null_fields = sorted(field for field in required_fields if field in update_data and update_data[field] is None)
    if invalid_null_fields:
        raise HTTPException(
            status_code=422,
            detail=f"Обязательные поля нельзя очистить: {', '.join(invalid_null_fields)}",
        )
    if "linked_task_id" in update_data:
        if body.linked_task_id != task.linked_task_id:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Ручное изменение связи личной задачи с Q-задачей недоступно. "
                    "Связь создается системой при публикации в глобальную очередь."
                ),
            )
        # Cached clients may still echo the existing read-only relation.
        update_data.pop("linked_task_id")
    if "source_quick_note_id" in update_data:
        await _get_owned_note_or_404(db, body.source_quick_note_id, user.id)
    target_status = update_data.get("status", task.status)
    waiting_for = update_data.get("waiting_for", task.waiting_for)
    blocked_reason = update_data.get("blocked_reason", task.blocked_reason)
    execution_task_ids = _execution_task_ids_for(
        task.promoted_task_id,
        task.linked_task_id,
    )
    _ensure_status_context(target_status, waiting_for, blocked_reason)
    if target_status == "in_progress" and target_status != old_status and execution_task_ids:
        if len(execution_task_ids) > 1:
            raise HTTPException(
                status_code=409,
                detail=(
                    "С личной задачей связаны две разные Q-задачи. "
                    "Устраните неоднозначную связь до начала работы."
                ),
            )
        execution_states = await _get_execution_task_states(
            db,
            execution_task_ids,
            for_update=True,
        )
        conflict = next(
            (
                state
                for state in execution_states
                if state[0].status in ACTIVE_QUEUE_HANDOFF_STATUSES
            ),
            None,
        )
        if conflict or not execution_states:
            execution_task, assignee = conflict if conflict else (None, None)
            raise HTTPException(
                status_code=409,
                detail=_queue_handoff_conflict_detail(execution_task, assignee),
            )
    if "status" in update_data and update_data["status"] != old_status:
        if target_status == "waiting":
            update_data["blocked_reason"] = None
        elif target_status == "blocked":
            update_data["waiting_for"] = None
        else:
            update_data.setdefault("waiting_for", None)
            update_data.setdefault("blocked_reason", None)
    for field, value in update_data.items():
        setattr(task, field, value)
    task.updated_at = datetime.now(timezone.utc)
    changed_fields = sorted(update_data.keys())
    if "start_at" in update_data or "due_at" in update_data:
        _ensure_valid_task_dates(task.start_at, task.due_at)
    if {"title", "description", "notes", "next_step", "responsible", "start_at", "due_at"} & set(changed_fields):
        await _sync_linked_deadline_tracker(db, task)
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
            metadata_json={
                "fields": changed_fields,
                "previous_waiting_for": old_waiting_for,
                "previous_blocked_reason": old_blocked_reason,
                "blocked_reason": task.blocked_reason,
            },
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
    await db.commit()
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
    await db.commit()
    return {"deleted": True, "checkpoint_id": str(checkpoint_id)}


@router.get("/{task_id}/artifacts", response_model=list[PersonalTaskArtifactRead])
async def list_personal_task_artifacts(
    task_id: UUID,
    include_archived: bool = Query(True),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List versioned materials inherited from an owned personal task."""
    task = await _get_owned_task_or_404(db, task_id, user.id)
    statement = (
        select(PersonalTaskArtifact)
        .options(selectinload(PersonalTaskArtifact.versions))
        .where(PersonalTaskArtifact.task_id == task.id)
    )
    if not include_archived:
        statement = statement.where(PersonalTaskArtifact.status == "active")
    statement = statement.order_by(
        (PersonalTaskArtifact.status == "archived").asc(),
        PersonalTaskArtifact.updated_at.desc(),
        PersonalTaskArtifact.id.desc(),
    )
    artifacts = list((await db.execute(statement)).scalars().all())
    return [_artifact_read(task, artifact) for artifact in artifacts]


@router.post(
    "/{task_id}/artifacts",
    response_model=PersonalTaskArtifactRead,
    status_code=201,
)
async def create_personal_task_artifact(
    task_id: UUID,
    artifact_type: str = Form(...),
    title: str = Form(...),
    description: str | None = Form(None),
    change_note: str | None = Form(None),
    url: str | None = Form(None),
    file: UploadFile | None = File(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a document, link, or result with immutable version one."""
    task = await _get_owned_task_or_404(db, task_id, user.id, for_update=True)
    artifact, version = await create_artifact(
        db,
        task=task,
        user=user,
        artifact_type=artifact_type,
        title=title,
        description=description,
        change_note=change_note,
        upload=file,
        url=url,
    )
    try:
        _add_event(
            db,
            task,
            user,
            "artifact_created",
            title=f"Добавлен материал: {artifact.title}",
            metadata_json={
                "artifact_id": str(artifact.id),
                "artifact_type": artifact.artifact_type,
                "version": version.version_number,
                "source_kind": version.source_kind,
                "size_bytes": version.size_bytes,
                "sha256": version.sha256,
            },
        )
        task.updated_at = utc_now()
        await db.flush()
        await db.commit()
    except Exception:
        remove_version_file(version)
        raise
    return _artifact_read(task, artifact)


@router.post(
    "/{task_id}/artifacts/{artifact_id}/versions",
    response_model=PersonalTaskArtifactRead,
    status_code=201,
)
async def create_personal_task_artifact_version(
    task_id: UUID,
    artifact_id: UUID,
    change_note: str | None = Form(None),
    url: str | None = Form(None),
    file: UploadFile | None = File(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Append a new immutable file or link revision."""
    task = await _get_owned_task_or_404(db, task_id, user.id, for_update=True)
    artifact = await _get_artifact_or_404(db, task.id, artifact_id, for_update=True)
    version = await add_artifact_version(
        db,
        task=task,
        artifact=artifact,
        user=user,
        change_note=change_note,
        upload=file,
        url=url,
    )
    try:
        _add_event(
            db,
            task,
            user,
            "artifact_version_added",
            title=f"Новая версия v{version.version_number}: {artifact.title}",
            metadata_json={
                "artifact_id": str(artifact.id),
                "artifact_type": artifact.artifact_type,
                "version": version.version_number,
                "source_kind": version.source_kind,
                "size_bytes": version.size_bytes,
                "sha256": version.sha256,
            },
        )
        task.updated_at = utc_now()
        await db.flush()
        await db.commit()
    except Exception:
        remove_version_file(version)
        raise
    return _artifact_read(task, artifact)


@router.patch(
    "/{task_id}/artifacts/{artifact_id}",
    response_model=PersonalTaskArtifactRead,
)
async def update_personal_task_artifact(
    task_id: UUID,
    artifact_id: UUID,
    body: PersonalTaskArtifactUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Edit metadata or explicitly archive/restore one material."""
    task = await _get_owned_task_or_404(db, task_id, user.id, for_update=True)
    ensure_task_accepts_artifact_changes(task)
    artifact = await _get_artifact_or_404(db, task.id, artifact_id, for_update=True)
    changes = body.model_dump(exclude_unset=True)
    if "title" in changes:
        if changes["title"] is None:
            raise HTTPException(status_code=422, detail="Название материала нельзя очистить")
        changes["title"] = clean_title(changes["title"])
    if "description" in changes:
        changes["description"] = clean_optional(changes["description"])
    if "status" in changes and changes["status"] is None:
        raise HTTPException(status_code=422, detail="Статус материала нельзя очистить")

    before = {field: getattr(artifact, field) for field in changes}
    actual_changes = {
        field: value for field, value in changes.items() if before[field] != value
    }
    if not actual_changes:
        return _artifact_read(task, artifact)
    for field, value in actual_changes.items():
        setattr(artifact, field, value)
    if "status" in actual_changes:
        artifact.archived_at = utc_now() if artifact.status == "archived" else None
    artifact.updated_by_id = user.id
    artifact.updated_at = utc_now()
    task.updated_at = utc_now()

    event_type = "artifact_updated"
    if before.get("status") != artifact.status:
        event_type = "artifact_archived" if artifact.status == "archived" else "artifact_restored"
    _add_event(
        db,
        task,
        user,
        event_type,
        title=(
            f"Материал архивирован: {artifact.title}"
            if event_type == "artifact_archived"
            else f"Материал восстановлен: {artifact.title}"
            if event_type == "artifact_restored"
            else f"Материал обновлен: {artifact.title}"
        ),
        metadata_json={
            "artifact_id": str(artifact.id),
            "artifact_type": artifact.artifact_type,
            "fields": sorted(actual_changes),
        },
    )
    await db.flush()
    return _artifact_read(task, artifact)


@router.get("/{task_id}/artifacts/{artifact_id}/versions/{version_id}/content")
async def download_personal_task_artifact_version(
    task_id: UUID,
    artifact_id: UUID,
    version_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download a file revision after owner access and path containment checks."""
    task = await _get_owned_task_or_404(db, task_id, user.id)
    artifact = await _get_artifact_or_404(db, task.id, artifact_id)
    version = next((item for item in artifact.versions if item.id == version_id), None)
    if version is None:
        raise HTTPException(status_code=404, detail="Версия материала не найдена")
    if version.source_kind != "file" or not version.stored_filename:
        raise HTTPException(status_code=409, detail="Эта версия является ссылкой")
    file_path = stored_attachment_path(version.stored_filename)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Файл материала не найден")
    return FileResponse(
        str(file_path),
        media_type=version.content_type or "application/octet-stream",
        filename=version.original_filename or "artifact",
        content_disposition_type="attachment",
        headers={
            "Cache-Control": "private, no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox",
        },
    )


@router.delete("/{task_id}/artifacts/{artifact_id}")
async def delete_personal_task_artifact(
    task_id: UUID,
    artifact_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Permanently delete only an archived material from an archived task."""
    task = await _get_owned_task_or_404(db, task_id, user.id, for_update=True)
    artifact = await _get_artifact_or_404(db, task.id, artifact_id, for_update=True)
    if task.status != "archived" or artifact.status != "archived":
        raise HTTPException(
            status_code=409,
            detail="Для удаления сначала архивируйте материал и личную задачу",
        )
    versions = list(artifact.versions)
    storage_file_ids = [
        await schedule_storage_file_deletion(
            db,
            owner_id=task.owner_id,
            stored_filename=version.stored_filename,
        )
        for version in versions
        if version.source_kind == "file" and version.stored_filename
    ]
    _add_event(
        db,
        task,
        user,
        "artifact_deleted",
        title=f"Материал удален: {artifact.title}",
        metadata_json={
            "artifact_id": str(artifact.id),
            "artifact_type": artifact.artifact_type,
            "versions_count": len(versions),
        },
    )
    task.updated_at = utc_now()
    await db.delete(artifact)
    await db.flush()
    await db.commit()
    for storage_file_id in storage_file_ids:
        await finalize_storage_file_deletion(storage_file_id)
    return {"deleted": True, "artifact_id": str(artifact_id)}


@router.post("/{task_id}/promote", response_model=TaskRead)
async def promote_personal_task(
    task_id: UUID,
    body: PersonalTaskPromoteRequest,
    user: User = Depends(require_task_workspace_access),
    db: AsyncSession = Depends(get_db),
):
    """Create a global DPMS queue task from a personal task."""
    personal_task = await _get_owned_task_or_404(db, task_id, user.id, for_update=True)
    if personal_task.promoted_task_id:
        result = await db.execute(select(Task).where(Task.id == personal_task.promoted_task_id))
        existing = result.scalar_one_or_none()
        if existing:
            return existing

    if personal_task.linked_task_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "Личная задача уже имеет прежнюю Q-связь. "
                "Устраните эту связь до новой публикации."
            ),
        )
    if personal_task.status not in PUBLISHABLE_PERSONAL_TASK_STATUSES:
        if personal_task.status == "in_progress":
            detail = (
                "Нельзя публиковать в Q личную задачу, которую создатель уже выполняет. "
                "Сначала остановите локальное выполнение и переведите задачу в план, ожидание или блокировку."
            )
        else:
            detail = "Завершенную или архивную личную задачу нельзя публиковать в глобальную очередь."
        raise HTTPException(status_code=409, detail=detail)

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
        acceptance_owner_id=user.id,
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
    if task.status != "archived":
        raise HTTPException(
            status_code=409,
            detail="Сначала перенесите задачу в архив",
        )
    artifacts_count = int(
        await db.scalar(
            select(func.count(PersonalTaskArtifact.id)).where(
                PersonalTaskArtifact.task_id == task.id
            )
        )
        or 0
    )
    if artifacts_count:
        raise HTTPException(
            status_code=409,
            detail=(
                "В задаче остались материалы. Архивируйте и удалите их перед удалением задачи."
            ),
        )
    await db.delete(task)
    await db.flush()
    return {"deleted": True, "task_id": str(task_id)}
