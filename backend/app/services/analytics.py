"""Метрики: Стакан, План/Факт, сводка по команде, burn-down."""
import calendar
from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.task import Task, TaskStatus
from app.models.transaction import QTransaction, WalletType
from app.models.user import User
from app.schemas.dashboard import (
    BurndownData,
    BurndownPoint,
    CapacityGauge,
    RunRate,
    TeamMemberSummary,
    TeamSummary,
    UserProgress,
    PeriodStats,
)
from app.services.planning import current_plan_window, effective_plan_for_user
from app.services.absences import absence_dates_by_user, absence_dates_for_user, global_holiday_dates, is_absent_on, month_bounds_for


def _effective_capacity(users: list[User], now: datetime, absence_map: dict[UUID, set[date]] | None = None) -> Decimal:
    absence_map = absence_map or {}
    return sum(
        (effective_plan_for_user(user, now, absence_map.get(user.id, set())).effective_target for user in users),
        Decimal("0"),
    )


async def _absence_map_for_users(db: AsyncSession, users: list[User], now: datetime) -> dict[UUID, set[date]]:
    month_start, month_end = month_bounds_for(now)
    return await absence_dates_by_user(db, [user.id for user in users], month_start, month_end)

async def get_capacity_gauge(db: AsyncSession) -> CapacityGauge:
    """
    Стакан: capacity = сумма effective target активных пользователей,
    load = сумма estimated_q задач in_queue + in_progress + review.
    """
    now = datetime.now(timezone.utc)
    users_result = await db.execute(select(User).where(User.is_active.is_(True)))
    users = list(users_result.scalars().all())
    absence_map = await _absence_map_for_users(db, users, now)
    capacity = _effective_capacity(users, now, absence_map)

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
    """Прогресс пользователя: earned vs effective target."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return None
    now = datetime.now(timezone.utc)
    month_start, month_end = month_bounds_for(now)
    absence_dates = await absence_dates_for_user(db, user.id, month_start, month_end)
    plan = effective_plan_for_user(user, now, absence_dates)
    earned = user.wallet_main
    target = plan.effective_target
    percent = float(earned / target * 100) if target > 0 else 0.0
    return UserProgress(
        earned=earned,
        target=target,
        full_target=plan.full_target,
        percent=round(percent, 1),
        karma=user.wallet_karma,
        is_new_employee=bool(user.is_new_employee),
        onboarding_active=plan.onboarding_active,
        onboarding_until=plan.onboarding_until,
        plan_started_at=plan.plan_started_at,
        absence_working_days=plan.absence_working_days,
        absent_today=is_absent_on(absence_dates, now),
        adjustment_reasons=plan.adjustment_reasons,
    )


async def get_team_summary(db: AsyncSession) -> TeamSummary:
    """Сводка по команде: earned vs effective target, in_progress_q, is_at_risk."""
    users_result = await db.execute(
        select(User).where(User.is_active.is_(True)).order_by(User.league, User.full_name)
    )
    users = list(users_result.scalars().all())

    by_league: dict[str, list[TeamMemberSummary]] = {
        "A": [],
        "B": [],
        "C": [],
    }
    total_earned = Decimal("0")

    now = datetime.now(timezone.utc)
    absence_map = await _absence_map_for_users(db, users, now)
    capacity = _effective_capacity(users, now, absence_map)
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

    # Наличие просроченных задач по каждому пользователю
    overdue_result = await db.execute(
        select(Task.assignee_id, func.count(Task.id))
        .where(
            Task.is_overdue.is_(True),
            Task.assignee_id.is_not(None),
        )
        .group_by(Task.assignee_id)
    )
    overdue_map: dict[str, int] = {}
    for user_id, count in overdue_result.all():
        if user_id is not None:
            overdue_map[str(user_id)] = int(count or 0)

    for user in users:
        user_absence_dates = absence_map.get(user.id, set())
        plan = effective_plan_for_user(user, now, user_absence_dates)
        target = plan.effective_target
        percent = float(user.wallet_main / target * 100) if target > 0 else 0.0
        total_earned += user.wallet_main

        key = user.league.value
        if key not in by_league:
            by_league[key] = []

        in_progress_q = in_progress_map.get(str(user.id), 0.0)
        has_overdue = overdue_map.get(str(user.id), 0) > 0
        elapsed_days, total_days, _remaining_days = current_plan_window(user, now, user_absence_dates)
        expected_percent = (elapsed_days / total_days * 100) if total_days > 0 else 0.0
        is_at_risk = target > 0 and percent < expected_percent * 0.6

        by_league[key].append(
            TeamMemberSummary(
                id=user.id,
                full_name=user.full_name,
                league=user.league.value,
                mpw=user.mpw,
                effective_mpw=round(float(target), 1),
                earned=round(float(user.wallet_main), 1),
                percent=round(percent, 1),
                karma=round(float(user.wallet_karma), 1),
                in_progress_q=round(in_progress_q, 1),
                is_at_risk=is_at_risk,
                quality_score=float(getattr(user, "quality_score", 100.0)),
                has_overdue=has_overdue,
                is_new_employee=bool(user.is_new_employee),
                onboarding_active=plan.onboarding_active,
                onboarding_until=plan.onboarding_until,
                absence_working_days=plan.absence_working_days,
                absent_today=is_absent_on(user_absence_dates, now),
                adjustment_reasons=plan.adjustment_reasons,
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


def _working_days_in_month(year: int, month: int, excluded_dates: set[date] | None = None) -> int:
    """Количество рабочих дней (пн–пт) в месяце."""
    excluded = excluded_dates or set()
    count = 0
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        current = date(year, month, day)
        if current.weekday() < 5 and current not in excluded:  # 0-4 = пн-пт
            count += 1
    return count


def _working_day_index(year: int, month: int, day: int, excluded_dates: set[date] | None = None) -> int:
    """Порядковый номер рабочего дня в месяце (1-based)."""
    excluded = excluded_dates or set()
    idx = 0
    for d in range(1, day + 1):
        current = date(year, month, d)
        if current.weekday() < 5 and current not in excluded:
            idx += 1
    return idx


async def get_run_rate(db: AsyncSession, user_id: UUID) -> RunRate | None:
    """Прогноз выполнения effective plan для сотрудника."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        return None

    now = datetime.now(timezone.utc)
    month_start, month_end = month_bounds_for(now)
    absence_dates = await absence_dates_for_user(db, user.id, month_start, month_end)
    plan = effective_plan_for_user(user, now, absence_dates)
    days_elapsed, days_total, days_remaining = current_plan_window(user, now, absence_dates)

    earned = float(user.wallet_main)
    mpw = float(plan.effective_target)
    full_mpw = float(plan.full_target)

    if days_elapsed > 0:
        rate_daily = earned / days_elapsed
    else:
        rate_daily = 0.0

    projected = rate_daily * days_total
    run_rate_percent = (projected / mpw * 100) if mpw > 0 else 0.0

    if earned >= mpw:
        required_rate = None
    elif days_remaining > 0:
        required_rate = round((mpw - earned) / days_remaining, 2)
    else:
        required_rate = None

    if run_rate_percent >= 100:
        status = "on_track"
    elif run_rate_percent >= 80:
        status = "slightly_behind"
    elif run_rate_percent >= 60:
        status = "at_risk"
    else:
        status = "critical"

    return RunRate(
        rate_daily=round(rate_daily, 2),
        projected=round(projected, 1),
        mpw=round(mpw, 1),
        full_mpw=round(full_mpw, 1),
        run_rate_percent=round(run_rate_percent, 1),
        required_rate=required_rate,
        status=status,
        days_elapsed=days_elapsed,
        days_total=days_total,
        days_remaining=days_remaining,
        earned=round(earned, 1),
        is_new_employee=bool(user.is_new_employee),
        onboarding_active=plan.onboarding_active,
        onboarding_until=plan.onboarding_until,
        absence_working_days=plan.absence_working_days,
        absent_today=is_absent_on(absence_dates, now),
    )


async def get_burndown_data(db: AsyncSession) -> BurndownData:
    """
    Данные для графика burn-down текущего месяца.
    Для каждого дня: ideal (линейный план), actual (накопительный итог по main, amount>0).
    Рабочие дни = пн–пт. Будущие даты: actual=None.
    """
    now = datetime.now(timezone.utc)
    period = now.strftime("%Y-%m")
    year, month = now.year, now.month
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    _, last_day = calendar.monthrange(year, month)
    month_end = now.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999999)
    holiday_dates = await global_holiday_dates(db, month_start.date(), month_end.date())

    users_result = await db.execute(select(User).where(User.is_active.is_(True)))
    users = list(users_result.scalars().all())
    absence_map = await _absence_map_for_users(db, users, now)
    total_capacity = float(_effective_capacity(users, now, absence_map))
    working_days = _working_days_in_month(year, month, holiday_dates)
    if working_days == 0:
        return BurndownData(period=period, total_capacity=total_capacity, working_days=0, points=[])

    # Ежедневные суммы: date -> sum(amount) за этот день (main, amount > 0)

    day_col = func.date_trunc("day", QTransaction.created_at)
    daily_stmt = (
        select(
            day_col.label("d"),
            func.coalesce(func.sum(QTransaction.amount), 0).label("total"),
        )
        .where(
            QTransaction.wallet_type == WalletType.main,
            QTransaction.amount > 0,
            QTransaction.created_at >= month_start,
            QTransaction.created_at <= month_end,
        )
        .group_by(day_col)
    )
    daily_result = await db.execute(daily_stmt)
    daily_totals = {}
    for row in daily_result.all():
        dt = row.d
        if hasattr(dt, "date"):
            d = dt.date()
        else:
            d = date(dt.year, dt.month, dt.day) if hasattr(dt, "year") else date.today()
        daily_totals[d] = float(row.total)

    today = now.date()
    points: list[BurndownPoint] = []
    cumulative_actual = 0.0

    for day in range(1, last_day + 1):
        d = date(year, month, day)
        day_str = d.strftime("%Y-%m-%d")
        work_idx = _working_day_index(year, month, day, holiday_dates)
        ideal = round(total_capacity / working_days * work_idx, 1) if working_days else 0.0

        if d <= today:
            cumulative_actual += daily_totals.get(d, 0.0)
            actual = round(cumulative_actual, 1)
        else:
            actual = None

        points.append(BurndownPoint(day=day_str, ideal=ideal, actual=actual))

    return BurndownData(
        period=period,
        total_capacity=round(total_capacity, 1),
        working_days=working_days,
        points=points,
    )
