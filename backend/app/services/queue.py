"""Логика глобальной очереди: доступные задачи, pull, submit, validate."""
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskStatus
from app.models.user import User, League
from app.services.wallet import credit_q


# Порядок лиг для сравнения: C < B < A
_LEAGUE_ORDER = {League.C: 0, League.B: 1, League.A: 2}


async def get_available_tasks(db: AsyncSession, user_id) -> list[Task]:
    """
    Задачи в очереди (status=in_queue), доступные пользователю по лиге.
    Сортировка: priority DESC, created_at ASC.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return []

    # min_league <= user.league значит пользователь может взять задачу
    # Сравниваем по порядку лиг
    stmt = (
        select(Task)
        .where(Task.status == TaskStatus.in_queue)
        .order_by(Task.priority.desc(), Task.created_at.asc())
    )
    result = await db.execute(stmt)
    tasks = list(result.scalars().all())
    # Фильтр по лиге: user.league >= task.min_league
    return [
        t
        for t in tasks
        if _LEAGUE_ORDER.get(user.league, 0) >= _LEAGUE_ORDER.get(t.min_league, 0)
    ]


async def pull_task(db: AsyncSession, user_id, task_id) -> Task:
    """
    Взять задачу в работу. Проверка WIP-лимита и лиги.
    """
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    task_result = await db.execute(select(Task).where(Task.id == task_id))
    task = task_result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.in_queue:
        raise HTTPException(status_code=400, detail="Task is not in queue")
    if _LEAGUE_ORDER.get(user.league, 0) < _LEAGUE_ORDER.get(task.min_league, 0):
        raise HTTPException(status_code=403, detail="League too low for this task")

    # WIP-лимит: количество задач in_progress у пользователя
    count_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.assignee_id == user_id,
            Task.status == TaskStatus.in_progress,
        )
    )
    wip_count = count_result.scalar() or 0
    if wip_count >= user.wip_limit:
        raise HTTPException(
            status_code=400,
            detail=f"WIP limit reached ({user.wip_limit})",
        )

    task.status = TaskStatus.in_progress
    task.assignee_id = user_id
    task.started_at = datetime.now(timezone.utc)
    await db.flush()
    return task


async def submit_for_review(db: AsyncSession, user_id, task_id) -> Task:
    """Сдать задачу на проверку."""
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.assignee_id != user_id:
        raise HTTPException(status_code=403, detail="Not the assignee")
    if task.status != TaskStatus.in_progress:
        raise HTTPException(status_code=400, detail="Task is not in progress")

    task.status = TaskStatus.review
    task.completed_at = datetime.now(timezone.utc)
    await db.flush()
    return task


async def validate_task(
    db: AsyncSession,
    validator_id,
    task_id,
    approved: bool,
) -> Task:
    """
    Принять или отклонить задачу. При принятии — начисление Q.
    """
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task.status != TaskStatus.review:
        raise HTTPException(status_code=400, detail="Task is not in review")

    if approved:
        task.status = TaskStatus.done
        task.validator_id = validator_id
        task.validated_at = datetime.now(timezone.utc)
        if task.assignee_id:
            await credit_q(
                db,
                task.assignee_id,
                task.estimated_q,
                reason=f"Task #{task.id} completion",
                task_id=task.id,
            )
    else:
        task.status = TaskStatus.in_progress
        task.completed_at = None
    await db.flush()
    return task
