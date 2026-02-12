"""Метрики: Стакан, План/Факт, сводка по команде."""
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskStatus
from app.models.user import User
from app.schemas.dashboard import (
    CapacityGauge,
    TeamMemberSummary,
    TeamSummary,
    UserProgress,
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


async def get_user_progress(db: AsyncSession, user_id) -> UserProgress | None:
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
    """Сводка по команде: по лигам, earned vs target."""
    result = await db.execute(
        select(User).where(User.is_active.is_(True)).order_by(User.league, User.full_name)
    )
    users = result.scalars().all()

    by_league: dict[str, list[TeamMemberSummary]] = {
        "A": [],
        "B": [],
        "C": [],
    }
    total_earned = Decimal("0")
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

    for user in users:
        target = Decimal(str(user.mpw))
        percent = float(user.wallet_main / target * 100) if target > 0 else 0.0
        total_earned += user.wallet_main
        key = user.league.value
        if key not in by_league:
            by_league[key] = []
        by_league[key].append(
            TeamMemberSummary(
                user_id=user.id,
                full_name=user.full_name,
                league=user.league,
                earned=user.wallet_main,
                target=target,
                percent=round(percent, 1),
                karma=user.wallet_karma,
            )
        )

    return TeamSummary(
        by_league=by_league,
        capacity=capacity,
        total_earned=total_earned,
        total_load=total_load,
    )
