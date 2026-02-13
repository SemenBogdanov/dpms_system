"""Очередь: список с can_pull/locked, pull (FOR UPDATE), submit, validate."""
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskStatus
from app.models.user import User, League, UserRole
from app.schemas.queue import QueueTaskResponse
from app.services.wallet import credit_q

_LEAGUE_ORDER = {League.C: 0, League.B: 1, League.A: 2}


async def get_available_tasks(db: AsyncSession, user_id: UUID) -> list[QueueTaskResponse]:
    """
    Все задачи in_queue. Для каждой: can_pull, locked, lock_reason, estimator_name.
    Задачи с min_league > user.league возвращаются с locked=True.
    Сортировка: priority DESC, created_at ASC.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return []

    stmt = (
        select(Task)
        .where(Task.status == TaskStatus.in_queue)
        .order_by(Task.priority.desc(), Task.created_at.asc())
    )
    result = await db.execute(stmt)
    tasks = list(result.scalars().all())

    wip_count_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.assignee_id == user_id,
            Task.status == TaskStatus.in_progress,
        )
    )
    wip_count = wip_count_result.scalar() or 0
    user_league_order = _LEAGUE_ORDER.get(user.league, 0)
    can_pull_by_wip = wip_count < user.wip_limit

    estimator_ids = {t.estimator_id for t in tasks if t.estimator_id}
    estimator_map: dict[UUID, str] = {}
    if estimator_ids:
        est_result = await db.execute(
            select(User.id, User.full_name).where(User.id.in_(estimator_ids))
        )
        estimator_map = {row.id: row.full_name for row in est_result.all()}

    out: list[QueueTaskResponse] = []
    for task in tasks:
        task_league_order = _LEAGUE_ORDER.get(task.min_league, 0)
        league_ok = user_league_order >= task_league_order
        if not league_ok:
            can_pull = False
            locked = True
            lock_reason = f"Требуется Лига {task.min_league.value}"
        elif not can_pull_by_wip:
            can_pull = False
            locked = False
            lock_reason = "WIP-лимит исчерпан"
        else:
            can_pull = True
            locked = False
            lock_reason = None

        estimator_name = estimator_map.get(task.estimator_id) if task.estimator_id else None

        out.append(
            QueueTaskResponse(
                id=task.id,
                title=task.title,
                description=task.description,
                task_type=task.task_type.value,
                complexity=task.complexity.value,
                estimated_q=float(task.estimated_q),
                priority=task.priority.value,
                min_league=task.min_league.value,
                created_at=task.created_at,
                estimator_name=estimator_name,
                can_pull=can_pull,
                locked=locked,
                lock_reason=lock_reason,
            )
        )
    return out


async def pull_task(db: AsyncSession, user_id: UUID, task_id: UUID) -> Task:
    """Взять задачу. Атомарная блокировка SELECT FOR UPDATE."""
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    task_result = await db.execute(
        select(Task).where(Task.id == task_id).with_for_update()
    )
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if task.status != TaskStatus.in_queue:
        raise HTTPException(status_code=400, detail="Задача уже взята другим")
    if _LEAGUE_ORDER.get(user.league, 0) < _LEAGUE_ORDER.get(task.min_league, 0):
        raise HTTPException(status_code=400, detail="Недостаточный уровень лиги")
    wip_count_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.assignee_id == user_id,
            Task.status == TaskStatus.in_progress,
        )
    )
    wip_count = wip_count_result.scalar() or 0
    if wip_count >= user.wip_limit:
        raise HTTPException(status_code=400, detail="WIP-лимит исчерпан")

    task.status = TaskStatus.in_progress
    task.assignee_id = user_id
    task.started_at = datetime.now(timezone.utc)
    await db.flush()
    return task


async def submit_for_review(
    db: AsyncSession,
    user_id: UUID,
    task_id: UUID,
    result_url: str | None = None,
    comment: str | None = None,
) -> Task:
    """Сдать задачу на проверку."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if task.assignee_id != user_id:
        raise HTTPException(status_code=400, detail="Это не ваша задача")
    if task.status != TaskStatus.in_progress:
        raise HTTPException(status_code=400, detail="Задача не в работе")

    task.status = TaskStatus.review
    task.completed_at = datetime.now(timezone.utc)
    if result_url is not None:
        task.result_url = result_url
    await db.flush()
    return task


async def validate_task(
    db: AsyncSession,
    validator_id: UUID,
    task_id: UUID,
    approved: bool,
    comment: str | None = None,
) -> Task:
    """
    Принять или отклонить. Запрет самовалидации. При reject comment обязателен.
    Валидатор — teamlead или admin.
    """
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if task.status != TaskStatus.review:
        raise HTTPException(status_code=400, detail="Задача не на проверке")

    validator_result = await db.execute(select(User).where(User.id == validator_id))
    validator = validator_result.scalar_one_or_none()
    if not validator:
        raise HTTPException(status_code=404, detail="Валидатор не найден")
    if validator.role not in (UserRole.teamlead, UserRole.admin):
        raise HTTPException(status_code=400, detail="Валидировать могут только тимлид или админ")
    if task.assignee_id == validator_id:
        raise HTTPException(status_code=400, detail="Нельзя валидировать свою задачу")

    if not approved:
        if not (comment and comment.strip()):
            raise HTTPException(status_code=400, detail="При возврате комментарий обязателен")
        task.status = TaskStatus.in_progress
        task.validator_id = None
        task.validated_at = None
        task.completed_at = None
        task.rejection_comment = comment.strip()
        await db.flush()
        return task

    task.status = TaskStatus.done
    task.validator_id = validator_id
    task.validated_at = datetime.now(timezone.utc)
    task.rejection_comment = None
    if task.assignee_id:
        await credit_q(
            db,
            task.assignee_id,
            task.estimated_q,
            reason=f"Задача #{task.id} принята",
            task_id=task.id,
        )
    await db.flush()
    return task