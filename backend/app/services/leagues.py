"""Прогресс перехода между лигами."""
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shop import PeriodSnapshot
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.schemas.leagues import (
    CriteriaPeriod,
    LeagueCriterion,
    LeagueProgress,
)


def _periods_for_criteria() -> tuple[list[str], str]:
    """Два последних закрытых месяца и текущий (YYYY-MM) — всего 3 периода для критерия «3 месяца подряд»."""
    now = datetime.now(timezone.utc)
    current = now.strftime("%Y-%m")
    closed = []
    y, m = now.year, now.month
    for _ in range(2):
        m -= 1
        if m < 1:
            m += 12
            y -= 1
        closed.append(f"{y}-{m:02d}")
    return closed, current


async def get_league_progress(db: AsyncSession, user_id: UUID) -> LeagueProgress | None:
    """
    Детальный прогресс пользователя к следующей лиге.
    C→B: план ≥90% за 3 месяца подряд + 10 задач за текущий месяц.
    B→A: план ≥95% за 3 месяца подряд + 15 задач за текущий месяц.
    A: at_max.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return None

    current_league = user.league.value if hasattr(user.league, "value") else str(user.league)

    if current_league == "A":
        return LeagueProgress(
            user_id=str(user_id),
            current_league=current_league,
            next_league=None,
            at_max=True,
            criteria=[],
            overall_progress=100.0,
            message="Вы достигли лиги A — высшего уровня.",
        )

    if current_league == "C":
        threshold = 90
        next_league = "B"
        tasks_required = 10
    else:  # B
        threshold = 95
        next_league = "A"
        tasks_required = 15

    closed_periods, current_period = _periods_for_criteria()

    # Снимки за закрытые месяцы (для этого пользователя)
    snap_result = await db.execute(
        select(PeriodSnapshot)
        .where(
            PeriodSnapshot.user_id == user_id,
            PeriodSnapshot.period.in_(closed_periods),
        )
        .order_by(PeriodSnapshot.period.desc())
    )
    snapshots = {s.period: s for s in snap_result.scalars().all()}

    # Текущий месяц: live percent
    target = float(user.mpw) if user.mpw else 1.0
    earned = float(user.wallet_main)
    current_percent = round(earned / target * 100, 1) if target > 0 else 0.0
    current_met = current_percent >= threshold

    # Детали по месяцам: 2 закрытых + текущий (всего 3 периода)
    details_plan: list[CriteriaPeriod] = []
    completed_months = 0
    for period in closed_periods:
        snap = snapshots.get(period)
        if snap:
            pct = round(float(snap.earned_main) / float(snap.mpw) * 100, 1) if snap.mpw else 0.0
            met = pct >= threshold
            if met:
                completed_months += 1
            details_plan.append(CriteriaPeriod(period=period, value=pct, met=met, current=False))
        else:
            details_plan.append(CriteriaPeriod(period=period, value=None, met=False, current=False))
    details_plan.append(
        CriteriaPeriod(period=current_period, value=current_percent, met=current_met, current=True)
    )
    if current_met:
        completed_months += 1
    plan_met = completed_months >= 3
    plan_progress = min(100.0, (completed_months / 3) * 100) if completed_months < 3 else 100.0

    criterion_plan = LeagueCriterion(
        name=f"Выполнение плана ≥ {threshold}%",
        description="Необходимо 3 месяца подряд",
        required=3,
        completed=completed_months,
        met=plan_met,
        progress_percent=round(plan_progress, 1),
        details=details_plan,
    )

    # Задачи за текущий месяц
    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    count_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.assignee_id == user_id,
            Task.status == TaskStatus.done,
            Task.completed_at >= month_start,
        )
    )
    tasks_done = count_result.scalar() or 0
    tasks_met = tasks_done >= tasks_required
    tasks_progress = min(100.0, (tasks_done / tasks_required) * 100) if tasks_required else 100.0

    criterion_tasks = LeagueCriterion(
        name=f"Минимум {tasks_required} задач за последний месяц",
        description=f"Завершённых задач в текущем месяце: {tasks_done}",
        required=tasks_required,
        completed=tasks_done,
        met=tasks_met,
        progress_percent=round(tasks_progress, 1),
        details=[
            CriteriaPeriod(period=current_period, value=float(tasks_done), met=tasks_met, current=True)
        ],
    )

    criteria = [criterion_plan, criterion_tasks]
    overall = (criterion_plan.progress_percent + criterion_tasks.progress_percent) / 2
    parts = []
    if completed_months < 3:
        parts.append(f"ещё {3 - completed_months} мес. ≥{threshold}%")
    if tasks_done < tasks_required:
        parts.append(f"{tasks_required - tasks_done} задач")
    message = f"До лиги {next_league} осталось: {', '.join(parts)}" if parts else f"Критерии выполнены. Переход в лигу {next_league} по решению админа."

    return LeagueProgress(
        user_id=str(user_id),
        current_league=current_league,
        next_league=next_league,
        at_max=False,
        criteria=criteria,
        overall_progress=round(overall, 1),
        message=message,
    )
