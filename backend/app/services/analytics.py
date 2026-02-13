"""Метрики: Стакан, План/Факт, сводка по команде."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskStatus
from app.models.user import User
from app.schemas.dashboard import (
    CapacityGauge,
    TeamMemberSummary,
    TeamSummary,
    UserProgress,
    PeriodStats,
)


async def get_capacity_gauge(db: AsyncSession) -> CapacityGauge:
    """
    Стакан: capacity = сумма mpw активных пользователей,
    load = сумма estimated_q задач in_queue + in_progress + review.
    """
    cap_result = await db.execute(
        select(func.coalesce(func.sum(User.mpw), 0)).where(User.is_active.is_(True))
    )
    capacity = Decimal(str(cap_result.scalar() or 0))

    load_result = await db.execute(
        select(func.coalesce(func.sum(Task.estimated_q), 0)).where(
            Task.status.in_(
                [TaskStatus.in_queue, TaskStatus.in_progress, TaskStatus.review]
            )
        )
    )
    load = Decimal(str(load_result.scalar() or 0))

    utilization = float(load / capacity * 100) if capacity > 0 else 0.0
    if utilization < 70:
        status = "green"
    elif utilization < 100:
        status = "yellow"
    else:
        status = "red"

    return CapacityGauge(
        capacity=capacity,
        load=load,
        utilization=round(utilization, 1),
        status=status,
    )


async def get_user_progress(db: AsyncSession, user_id: UUID) -> UserProgress | None:
    """Прогресс пользователя: earned (wallet_main), target (mpw), karma."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return None
    earned = user.wallet_main
    target = Decimal(str(user.mpw))
    percent = float(earned / target * 100) if target > 0 else 0.0
    return UserProgress(
        earned=earned,
        target=target,
        percent=round(percent, 1),
        karma=user.wallet_karma,
    )


async def get_team_summary(db: AsyncSession) -> TeamSummary:
    """Сводка по команде: по лигам, earned vs target, in_progress_q, is_at_risk."""
    users_result = await db.execute(
        select(User).where(User.is_active.is_(True)).order_by(User.league, User.full_name)
    )
    users = users_result.scalars().all()

    by_league: dict[str, list[TeamMemberSummary]] = {
        "A": [],
        "B": [],
        "C": [],
    }
    total_earned = Decimal("0")

    # Ёмкость и текущая загрузка (как в стакане)
    cap_result = await db.execute(
        select(func.coalesce(func.sum(User.mpw), 0)).where(User.is_active.is_(True))
    )
    capacity = Decimal(str(cap_result.scalar() or 0))
    load_result = await db.execute(
        select(func.coalesce(func.sum(Task.estimated_q), 0)).where(
            Task.status.in_(
                [TaskStatus.in_queue, TaskStatus.in_progress, TaskStatus.review]
            )
        )
    )
    total_load = Decimal(str(load_result.scalar() or 0))

    # Q в работе по каждому пользователю
    in_progress_result = await db.execute(
        select(Task.assignee_id, func.coalesce(func.sum(Task.estimated_q), 0))
        .where(Task.status == TaskStatus.in_progress)
        .group_by(Task.assignee_id)
    )
    in_progress_map: dict[str, float] = {}
    for user_id, q_sum in in_progress_result.all():
        if user_id is not None:
            in_progress_map[str(user_id)] = float(q_sum)

    # Расчёт ожидаемого процента и статуса риска
    now = datetime.now(timezone.utc)
    # Для упрощения считаем, что в месяце 22 рабочих дня
    WORKING_DAYS = 22
    day = now.day
    expected_percent = (day / WORKING_DAYS) * 100

    for user in users:
        target = Decimal(str(user.mpw))
        percent = float(user.wallet_main / target * 100) if target > 0 else 0.0
        total_earned += user.wallet_main

        key = user.league.value
        if key not in by_league:
            by_league[key] = []

        in_progress_q = in_progress_map.get(str(user.id), 0.0)
        # is_at_risk: percent < expected_percent * 0.6
        is_at_risk = percent < expected_percent * 0.6

        by_league[key].append(
            TeamMemberSummary(
                id=user.id,
                full_name=user.full_name,
                league=user.league.value,
                mpw=user.mpw,
                earned=round(float(user.wallet_main), 1),
                percent=round(percent, 1),
                karma=round(float(user.wallet_karma), 1),
                in_progress_q=round(in_progress_q, 1),
                is_at_risk=is_at_risk,
            )
        )

    utilization = float(total_load / capacity * 100) if capacity > 0 else 0.0

    return TeamSummary(
        by_league=by_league,
        total_capacity=round(float(capacity), 1),
        total_load=round(float(total_load), 1),
        total_earned=round(float(total_earned), 1),
        utilization=round(utilization, 1),
    )


async def get_period_stats(db: AsyncSession) -> PeriodStats:
    """
    Статистика текущего месяца для дашборда руководителя.
    - tasks_created: сколько задач создано в текущем месяце
    - tasks_completed: сколько завершено (done)
    - total_q_earned: сколько Q заработала команда
    - avg_completion_time_hours: среднее время выполнения (started_at → completed_at)
    """
    now = datetime.now(timezone.utc)
    period = now.strftime("%Y-%m")
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # Созданные задачи в этом месяце
    created_q = await db.execute(
        select(func.count(Task.id)).where(Task.created_at >= month_start)
    )
    tasks_created = int(created_q.scalar() or 0)

    # Завершённые задачи (done) в этом месяце
    completed_q = await db.execute(
        select(func.count(Task.id)).where(
            Task.status == TaskStatus.done,
            Task.completed_at.is_not(None),
            Task.completed_at >= month_start,
        )
    )
    tasks_completed = int(completed_q.scalar() or 0)

    # Заработанные Q (по факту валидации)
    earned_q = await db.execute(
        select(func.coalesce(func.sum(Task.estimated_q), 0)).where(
            Task.status == TaskStatus.done,
            Task.validated_at.is_not(None),
            Task.validated_at >= month_start,
        )
    )
    total_q_earned = float(earned_q.scalar() or 0.0)

    # Среднее время выполнения (часы)
    duration_q = await db.execute(
        select(
            func.avg(
                func.extract("epoch", Task.completed_at - Task.started_at) / 3600.0
            )
        ).where(
            Task.status == TaskStatus.done,
            Task.completed_at.is_not(None),
            Task.started_at.is_not(None),
            Task.completed_at >= month_start,
        )
    )
    avg_hours = duration_q.scalar()
    avg_completion_time_hours = float(avg_hours) if avg_hours is not None else None

    return PeriodStats(
        period=period,
        tasks_created=tasks_created,
        tasks_completed=tasks_completed,
        total_q_earned=round(total_q_earned, 1),
        avg_completion_time_hours=round(avg_completion_time_hours, 1)
        if avg_completion_time_hours is not None
        else None,
    )
