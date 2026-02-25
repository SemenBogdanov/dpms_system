from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskStatus
from app.models.user import User, UserRole
from app.schemas.task import FocusStatus
from app.services.notifications import create_notification


async def _get_user(db: AsyncSession, user_id) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def start_focus(db: AsyncSession, user_id, task_id) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    user = await _get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if task.assignee_id != user_id:
        raise HTTPException(status_code=400, detail="Задача принадлежит другому пользователю")
    if task.status != TaskStatus.in_progress:
        raise HTTPException(status_code=400, detail="В фокус можно поставить только задачу в работе")
    if task.focus_started_at is not None:
        raise HTTPException(status_code=400, detail="Задача уже в фокусе")

    paused_task_id = None

    # Автопауза другой задачи пользователя, если есть
    current_focus_result = await db.execute(
        select(Task).where(
            Task.assignee_id == user_id,
            Task.status == TaskStatus.in_progress,
            Task.focus_started_at.is_not(None),
            Task.id != task.id,
        )
    )
    current_focus = current_focus_result.scalar_one_or_none()
    if current_focus:
        delta = (now - current_focus.focus_started_at).total_seconds()
        if delta > 0:
            current_focus.active_seconds += int(delta)
        current_focus.focus_started_at = None
        paused_task_id = current_focus.id

    # Первый фокус: при необходимости запустить SLA от момента фокуса
    if task.active_seconds == 0 and task.started_at is None:
        task.started_at = now
        # due_date / sla_hours могут быть пересчитаны отдельной логикой, здесь не трогаем

    task.focus_started_at = now
    await db.flush()

    active_hours = task.active_seconds / 3600
    return {
        "task_id": task.id,
        "action": "focused",
        "active_seconds": task.active_seconds,
        "active_hours": active_hours,
        "paused_task_id": paused_task_id,
    }


async def pause_focus(db: AsyncSession, user_id, task_id) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    user = await _get_user(db, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    if task.assignee_id != user_id:
        raise HTTPException(status_code=400, detail="Задача принадлежит другому пользователю")
    if task.status != TaskStatus.in_progress:
        raise HTTPException(status_code=400, detail="Поставить на паузу можно только задачу в работе")
    if task.focus_started_at is None:
        raise HTTPException(status_code=400, detail="Задача уже на паузе")

    delta = (now - task.focus_started_at).total_seconds()
    if delta > 0:
        task.active_seconds += int(delta)
    task.focus_started_at = None

    await db.flush()
    active_hours = task.active_seconds / 3600
    return {
        "task_id": task.id,
        "action": "paused",
        "active_seconds": task.active_seconds,
        "active_hours": active_hours,
        "paused_task_id": None,
    }


async def auto_pause_stale_focuses(db: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=4)

    result = await db.execute(
        select(Task).where(
            Task.focus_started_at.is_not(None),
            Task.focus_started_at < cutoff,
        )
    )
    tasks = list(result.scalars().all())
    count = 0
    max_delta = 4 * 3600

    for task in tasks:
        if not task.focus_started_at:
            continue
        delta = (now - task.focus_started_at).total_seconds()
        bounded = min(max(int(delta), 0), max_delta)
        task.active_seconds += bounded
        task.focus_started_at = None
        count += 1

        if task.assignee_id:
            await create_notification(
                db,
                task.assignee_id,
                "focus_auto_paused",
                "⏸ Фокус приостановлен",
                f"Фокус на «{task.title}» приостановлен автоматически (нет активности >4ч)",
                "/my-tasks",
            )

    await db.flush()
    return count


async def correct_active_time(
    db: AsyncSession,
    corrector_id,
    task_id,
    new_active_seconds: int,
    reason: str,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)

    corrector = await _get_user(db, corrector_id)
    if not corrector:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")

    if corrector.id != task.assignee_id and corrector.role not in (
        UserRole.teamlead,
        UserRole.admin,
    ):
        raise HTTPException(status_code=403, detail="Нет прав на коррекцию времени")

    old_seconds = task.active_seconds
    if new_active_seconds < 0:
        raise HTTPException(status_code=400, detail="Время не может быть отрицательным")

    details = task.estimation_details or {}
    corrections = list(details.get("time_corrections", []))
    corrections.append(
        {
            "corrector_id": str(corrector.id),
            "old_seconds": int(old_seconds),
            "new_seconds": int(new_active_seconds),
            "reason": reason,
            "corrected_at": now.isoformat(),
        }
    )
    details["time_corrections"] = corrections
    task.estimation_details = details

    task.active_seconds = int(new_active_seconds)

    if task.focus_started_at is not None:
        task.focus_started_at = now

    await db.flush()
    active_hours = task.active_seconds / 3600
    return {
        "task_id": task.id,
        "action": "corrected",
        "active_seconds": task.active_seconds,
        "active_hours": active_hours,
        "paused_task_id": None,
    }


async def get_focus_statuses(db: AsyncSession) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)

    users_result = await db.execute(
        select(User).where(User.role.in_([UserRole.executor, UserRole.teamlead]))
    )
    users = list(users_result.scalars().all())
    if not users:
        return []

    user_ids = [u.id for u in users]
    tasks_result = await db.execute(
        select(Task).where(
            and_(
                Task.assignee_id.in_(user_ids),
                Task.status.in_([TaskStatus.in_progress]),
            )
        )
    )
    tasks = list(tasks_result.scalars().all())

    by_user: dict[Any, list[Task]] = {}
    for t in tasks:
        by_user.setdefault(t.assignee_id, []).append(t)

    statuses: list[dict[str, Any]] = []
    for u in users:
        user_tasks = by_user.get(u.id, [])
        focused = [t for t in user_tasks if t.focus_started_at]

        if focused:
            task = focused[0]
            elapsed = task.active_seconds
            if task.focus_started_at:
                elapsed += int((now - task.focus_started_at).total_seconds())
            minutes = round(elapsed / 60, 1)
            status = FocusStatus(
                user_id=u.id,
                full_name=u.full_name,
                league=u.league.value if hasattr(u.league, "value") else str(u.league),
                focused_task_id=task.id,
                focused_task_title=task.title,
                focus_duration_minutes=minutes,
                status="focused",
            )
        elif user_tasks:
            status = FocusStatus(
                user_id=u.id,
                full_name=u.full_name,
                league=u.league.value if hasattr(u.league, "value") else str(u.league),
                focused_task_id=None,
                focused_task_title=None,
                focus_duration_minutes=0.0,
                status="paused",
            )
        else:
            status = FocusStatus(
                user_id=u.id,
                full_name=u.full_name,
                league=u.league.value if hasattr(u.league, "value") else str(u.league),
                focused_task_id=None,
                focused_task_title=None,
                focus_duration_minutes=0.0,
                status="idle",
            )

        statuses.append(status.model_dump())

    return statuses

