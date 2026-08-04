"""Structured acceptance criteria for global Q tasks."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import (
    Task,
    TaskAcceptanceCriterion,
    TaskAcceptanceCriterionEvent,
    TaskReviewEvent,
    TaskReviewEventType,
    TaskStatus,
)
from app.models.user import User, UserRole
from app.schemas.task_acceptance import (
    AcceptanceCriteriaReviewRequest,
    AcceptanceCriteriaSubmitRequest,
    AcceptanceCriterionCreate,
    AcceptanceCriterionEventRead,
    AcceptanceCriterionRead,
    AcceptancePlanUpdate,
    TaskAcceptanceRead,
)
from app.services.activity import record_activity_event
from app.services.notifications import create_notification


REQUIRED_CRITERION_KINDS = {"required", "quality_gate"}
PLAN_EDITABLE_STATUSES = {TaskStatus.new, TaskStatus.estimated, TaskStatus.in_queue}


def acceptance_plan_locked(task: Task) -> bool:
    return task.assignee_id is not None or task.status not in PLAN_EDITABLE_STATUSES


async def _ensure_acceptance_owner(
    db: AsyncSession,
    owner_id: UUID | None,
) -> User | None:
    if owner_id is None:
        return None
    result = await db.execute(
        select(User).where(User.id == owner_id, User.is_active.is_(True))
    )
    owner = result.scalar_one_or_none()
    if not owner:
        raise HTTPException(status_code=400, detail="Владелец приемки не найден или отключен")
    if not owner.task_workspace_enabled:
        raise HTTPException(status_code=400, detail="Владельцу приемки недоступен раздел задач")
    return owner


def _add_criterion_event(
    db: AsyncSession,
    task: Task,
    criterion: TaskAcceptanceCriterion,
    actor_id: UUID,
    event_type: str,
    from_status: str | None,
    to_status: str,
    *,
    comment: str | None = None,
    evidence_url: str | None = None,
    created_at: datetime | None = None,
) -> None:
    db.add(
        TaskAcceptanceCriterionEvent(
            task_id=task.id,
            criterion_id=criterion.id,
            actor_id=actor_id,
            event_type=event_type,
            from_status=from_status,
            to_status=to_status,
            comment=comment,
            evidence_url=evidence_url,
            acceptance_revision=task.acceptance_revision,
            created_at=created_at or datetime.now(timezone.utc),
        )
    )


def sync_acceptance_summary(
    task: Task,
    criteria: list[TaskAcceptanceCriterion],
) -> None:
    task.acceptance_total_count = len(criteria)
    task.acceptance_required_count = sum(
        item.kind in REQUIRED_CRITERION_KINDS for item in criteria
    )
    task.acceptance_accepted_count = sum(item.status == "accepted" for item in criteria)
    task.acceptance_required_accepted_count = sum(
        item.kind in REQUIRED_CRITERION_KINDS and item.status == "accepted"
        for item in criteria
    )
    task.acceptance_submitted_count = sum(item.status == "submitted" for item in criteria)
    task.acceptance_returned_count = sum(item.status == "returned" for item in criteria)

    if task.acceptance_mode == "full":
        if task.status == TaskStatus.done:
            task.acceptance_state = "accepted"
        elif task.status == TaskStatus.review:
            task.acceptance_state = "submitted"
        elif task.rejection_comment:
            task.acceptance_state = "returned"
        else:
            task.acceptance_state = "none"
        return

    if task.status == TaskStatus.done:
        task.acceptance_state = "accepted"
    elif (
        task.status == TaskStatus.review
        and task.acceptance_required_accepted_count >= task.acceptance_required_count
    ):
        task.acceptance_state = "submitted"
    elif task.acceptance_accepted_count > 0:
        task.acceptance_state = "partially_accepted"
    elif task.acceptance_returned_count > 0:
        task.acceptance_state = "returned"
    elif task.acceptance_submitted_count > 0 or task.status == TaskStatus.review:
        task.acceptance_state = "submitted"
    else:
        task.acceptance_state = "none"


async def refresh_acceptance_summary(
    db: AsyncSession,
    task: Task,
) -> None:
    """Refresh denormalized acceptance counters after a task workflow transition."""
    criteria = await _load_criteria(db, task.id)
    sync_acceptance_summary(task, criteria)


async def initialize_acceptance_plan(
    db: AsyncSession,
    task: Task,
    *,
    owner_id: UUID,
    mode: str,
    criteria: list[AcceptanceCriterionCreate],
) -> None:
    await _ensure_acceptance_owner(db, owner_id)
    task.acceptance_owner_id = owner_id
    task.acceptance_mode = mode
    task.acceptance_state = "none"
    task.acceptance_revision = 1
    rows: list[TaskAcceptanceCriterion] = []
    for position, item in enumerate(criteria):
        row = TaskAcceptanceCriterion(
            task_id=task.id,
            position=position,
            title=item.title,
            description=item.description,
            kind=item.kind,
            status="pending",
            baseline_revision=1,
        )
        db.add(row)
        rows.append(row)
    sync_acceptance_summary(task, rows)
    await db.flush()


async def replace_acceptance_plan(
    db: AsyncSession,
    task_id: UUID,
    body: AcceptancePlanUpdate,
    actor: User,
) -> TaskAcceptanceRead:
    result = await db.execute(
        select(Task).where(Task.id == task_id).with_for_update()
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if acceptance_plan_locked(task):
        raise HTTPException(
            status_code=409,
            detail="План приемки зафиксирован после назначения исполнителя",
        )
    if actor.role != UserRole.admin and actor.id not in {
        task.estimator_id,
        task.acceptance_owner_id,
    }:
        raise HTTPException(status_code=403, detail="Недостаточно прав для изменения плана приемки")
    if body.expected_revision != task.acceptance_revision:
        raise HTTPException(
            status_code=409,
            detail="План приемки уже изменен. Обновите задачу и повторите действие",
        )

    owner_id = body.acceptance_owner_id or task.acceptance_owner_id or task.estimator_id
    await _ensure_acceptance_owner(db, owner_id)
    task.acceptance_owner_id = owner_id
    task.acceptance_mode = body.mode
    task.acceptance_revision += 1
    task.acceptance_state = "none"
    await db.execute(
        delete(TaskAcceptanceCriterion).where(TaskAcceptanceCriterion.task_id == task.id)
    )
    rows: list[TaskAcceptanceCriterion] = []
    for position, item in enumerate(body.criteria):
        row = TaskAcceptanceCriterion(
            task_id=task.id,
            position=position,
            title=item.title,
            description=item.description,
            kind=item.kind,
            status="pending",
            baseline_revision=task.acceptance_revision,
        )
        db.add(row)
        rows.append(row)
    sync_acceptance_summary(task, rows)
    await record_activity_event(
        db,
        actor.id,
        "task_acceptance_plan_updated",
        task_id=task.id,
        metadata={
            "acceptance_mode": task.acceptance_mode,
            "acceptance_revision": task.acceptance_revision,
            "criteria_count": len(rows),
            "acceptance_owner_id": str(owner_id),
        },
    )
    await db.flush()
    return await get_task_acceptance(db, task.id, actor)


async def _load_criteria(
    db: AsyncSession,
    task_id: UUID,
    *,
    for_update: bool = False,
) -> list[TaskAcceptanceCriterion]:
    stmt = (
        select(TaskAcceptanceCriterion)
        .where(TaskAcceptanceCriterion.task_id == task_id)
        .order_by(TaskAcceptanceCriterion.position)
    )
    if for_update:
        stmt = stmt.with_for_update()
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_task_acceptance(
    db: AsyncSession,
    task_id: UUID,
    actor: User,
) -> TaskAcceptanceRead:
    result = await db.execute(
        select(Task, User)
        .outerjoin(User, User.id == Task.acceptance_owner_id)
        .where(Task.id == task_id)
    )
    row = result.one_or_none()
    if not row:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    task, owner = row
    criteria = await _load_criteria(db, task.id)
    events_result = await db.execute(
        select(TaskAcceptanceCriterionEvent, User)
        .outerjoin(User, User.id == TaskAcceptanceCriterionEvent.actor_id)
        .where(TaskAcceptanceCriterionEvent.task_id == task.id)
        .order_by(TaskAcceptanceCriterionEvent.created_at, TaskAcceptanceCriterionEvent.id)
    )
    events_by_criterion: dict[UUID, list[AcceptanceCriterionEventRead]] = {}
    for event, event_actor in events_result.all():
        events_by_criterion.setdefault(event.criterion_id, []).append(
            AcceptanceCriterionEventRead(
                id=event.id,
                actor_id=event.actor_id,
                actor_name=event_actor.full_name if event_actor else None,
                event_type=event.event_type,
                from_status=event.from_status,
                to_status=event.to_status,
                comment=event.comment,
                evidence_url=event.evidence_url,
                acceptance_revision=event.acceptance_revision,
                created_at=event.created_at,
            )
        )
    can_manage_plan = (
        not acceptance_plan_locked(task)
        and (
            actor.role == UserRole.admin
            or actor.id in {task.estimator_id, task.acceptance_owner_id}
        )
    )
    can_submit = task.assignee_id == actor.id and task.status == TaskStatus.in_progress
    can_review = (
        actor.id != task.assignee_id
        and (actor.id == task.acceptance_owner_id or actor.role == UserRole.admin)
    )
    criterion_reads: list[AcceptanceCriterionRead] = []
    for item in criteria:
        criterion_reads.append(
            AcceptanceCriterionRead(
                id=item.id,
                task_id=item.task_id,
                position=item.position,
                title=item.title,
                description=item.description,
                kind=item.kind,
                status=item.status,
                baseline_revision=item.baseline_revision,
                evidence_comment=item.evidence_comment,
                evidence_url=item.evidence_url,
                reviewer_comment=item.reviewer_comment,
                submitted_at=item.submitted_at,
                reviewed_at=item.reviewed_at,
                return_count=item.return_count,
                events=events_by_criterion.get(item.id, []),
            )
        )
    return TaskAcceptanceRead(
        task_id=task.id,
        mode=task.acceptance_mode,
        state=task.acceptance_state,
        revision=task.acceptance_revision,
        owner_id=task.acceptance_owner_id,
        owner_name=owner.full_name if owner else None,
        locked=acceptance_plan_locked(task),
        can_manage_plan=can_manage_plan,
        can_submit=can_submit,
        can_review=can_review,
        criteria=criterion_reads,
    )


async def submit_acceptance_criteria(
    db: AsyncSession,
    task_id: UUID,
    body: AcceptanceCriteriaSubmitRequest,
    actor: User,
) -> TaskAcceptanceRead:
    result = await db.execute(
        select(Task).where(Task.id == task_id).with_for_update()
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if task.acceptance_mode != "criteria":
        raise HTTPException(status_code=409, detail="Для задачи не включена приемка по критериям")
    if task.assignee_id != actor.id:
        raise HTTPException(status_code=403, detail="Критерии может сдавать только исполнитель")
    if task.status != TaskStatus.in_progress:
        raise HTTPException(status_code=409, detail="Задача должна находиться в работе")

    criteria = await _load_criteria(db, task.id, for_update=True)
    criteria_by_id = {item.id: item for item in criteria}
    now = datetime.now(timezone.utc)
    for item in body.items:
        criterion = criteria_by_id.get(item.criterion_id)
        if not criterion:
            raise HTTPException(status_code=404, detail="Критерий приемки не найден")
        if criterion.status not in {"pending", "returned"}:
            raise HTTPException(
                status_code=409,
                detail=f"Критерий «{criterion.title}» уже отправлен или принят",
            )
        previous_status = criterion.status
        criterion.status = "submitted"
        criterion.evidence_comment = item.evidence_comment
        criterion.evidence_url = item.evidence_url
        criterion.reviewer_comment = None
        criterion.submitted_by_id = actor.id
        criterion.submitted_at = now
        criterion.reviewed_by_id = None
        criterion.reviewed_at = None
        _add_criterion_event(
            db,
            task,
            criterion,
            actor.id,
            "submitted",
            previous_status,
            "submitted",
            comment=item.evidence_comment,
            evidence_url=item.evidence_url,
            created_at=now,
        )

    sync_acceptance_summary(task, criteria)
    await record_activity_event(
        db,
        actor.id,
        "task_acceptance_criteria_submitted",
        task_id=task.id,
        metadata={"criteria_ids": [str(item.criterion_id) for item in body.items]},
        occurred_at=now,
    )
    if task.acceptance_owner_id and task.acceptance_owner_id != actor.id:
        await create_notification(
            db,
            task.acceptance_owner_id,
            "task_acceptance_criteria_submitted",
            "Критерии готовы к проверке",
            message=f"«{task.title}»: отправлено критериев — {len(body.items)}",
            link="/my-tasks",
        )
    await db.flush()
    return await get_task_acceptance(db, task.id, actor)


async def review_acceptance_criteria(
    db: AsyncSession,
    task_id: UUID,
    body: AcceptanceCriteriaReviewRequest,
    actor: User,
) -> TaskAcceptanceRead:
    result = await db.execute(
        select(Task).where(Task.id == task_id).with_for_update()
    )
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if task.acceptance_mode != "criteria":
        raise HTTPException(status_code=409, detail="Для задачи не включена приемка по критериям")
    if actor.id == task.assignee_id:
        raise HTTPException(status_code=403, detail="Нельзя принимать собственную задачу")
    is_owner = actor.id == task.acceptance_owner_id
    if not is_owner and actor.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Критерии принимает постановщик задачи")
    if not is_owner and any(not item.comment for item in body.decisions):
        raise HTTPException(
            status_code=400,
            detail="Admin override требует комментарий к каждому решению",
        )
    if task.status not in {TaskStatus.in_progress, TaskStatus.review}:
        raise HTTPException(status_code=409, detail="Задача недоступна для проверки критериев")

    criteria = await _load_criteria(db, task.id, for_update=True)
    criteria_by_id = {item.id: item for item in criteria}
    now = datetime.now(timezone.utc)
    returned_titles: list[str] = []
    for decision in body.decisions:
        criterion = criteria_by_id.get(decision.criterion_id)
        if not criterion:
            raise HTTPException(status_code=404, detail="Критерий приемки не найден")
        if criterion.status != "submitted":
            raise HTTPException(
                status_code=409,
                detail=f"Критерий «{criterion.title}» не ожидает проверки",
            )
        previous_status = criterion.status
        criterion.status = "accepted" if decision.approved else "returned"
        criterion.reviewer_comment = decision.comment
        criterion.reviewed_by_id = actor.id
        criterion.reviewed_at = now
        if not decision.approved:
            criterion.return_count += 1
            returned_titles.append(criterion.title)
        _add_criterion_event(
            db,
            task,
            criterion,
            actor.id,
            "accepted" if decision.approved else "returned",
            previous_status,
            criterion.status,
            comment=decision.comment,
            created_at=now,
        )

    if returned_titles and task.status == TaskStatus.review:
        task.status = TaskStatus.in_progress
        task.completed_at = None
        task.validator_id = None
        task.validated_at = None
        task.focus_started_at = None
        comment = "Возвращены критерии: " + ", ".join(returned_titles)
        db.add(
            TaskReviewEvent(
                task_id=task.id,
                actor_id=actor.id,
                event_type=TaskReviewEventType.returned,
                comment=comment,
                created_at=now,
            )
        )

    sync_acceptance_summary(task, criteria)
    await record_activity_event(
        db,
        actor.id,
        "task_acceptance_criteria_reviewed",
        task_id=task.id,
        metadata={
            "accepted_ids": [str(item.criterion_id) for item in body.decisions if item.approved],
            "returned_ids": [str(item.criterion_id) for item in body.decisions if not item.approved],
        },
        occurred_at=now,
    )
    if task.assignee_id:
        await create_notification(
            db,
            task.assignee_id,
            "task_acceptance_criteria_reviewed",
            "Критерии проверены",
            message=(
                f"«{task.title}»: возвращено — {len(returned_titles)}"
                if returned_titles
                else f"«{task.title}»: приняты новые критерии"
            ),
            link="/my-tasks",
        )
    await db.flush()
    return await get_task_acceptance(db, task.id, actor)


async def ensure_criteria_ready_for_submission(
    db: AsyncSession,
    task: Task,
) -> None:
    if task.acceptance_mode != "criteria":
        return
    criteria = await _load_criteria(db, task.id)
    blocking = [
        item.title
        for item in criteria
        if item.kind in REQUIRED_CRITERION_KINDS
        and item.status not in {"submitted", "accepted"}
    ]
    if blocking:
        raise HTTPException(
            status_code=409,
            detail="Сначала отправьте обязательные критерии: " + ", ".join(blocking[:5]),
        )


async def ensure_criteria_ready_for_final_acceptance(
    db: AsyncSession,
    task: Task,
) -> None:
    if task.acceptance_mode != "criteria":
        return
    criteria = await _load_criteria(db, task.id)
    pending_review = [item.title for item in criteria if item.status == "submitted"]
    if pending_review:
        raise HTTPException(
            status_code=409,
            detail="Сначала завершите проверку отправленных критериев: "
            + ", ".join(pending_review[:5]),
        )
    blocking = [
        item.title
        for item in criteria
        if item.kind in REQUIRED_CRITERION_KINDS and item.status != "accepted"
    ]
    if blocking:
        raise HTTPException(
            status_code=409,
            detail="Нельзя принять задачу: не приняты критерии — " + ", ".join(blocking[:5]),
        )
