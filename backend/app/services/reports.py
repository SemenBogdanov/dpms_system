"""Генерация отчёта за период."""
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityEvent
from app.models.shop import PeriodSnapshot, Purchase
from app.models.task import Task, TaskPriority, TaskStatus
from app.models.user import User, UserRole
from app.schemas.reports import (
    CalibrationSummary,
    EmployeeScorecardResponse,
    EmployeeScorecardRow,
    PeriodReport,
    PerformerSummary,
    ShopActivity,
    TasksOverview,
)
from app.services.calibration import get_calibration_report
from app.services.absences import absence_dates_by_user
from app.services.activity import date_window, effective_target_for_date_range
from app.services.planning import effective_plan_for_user

SCORECARD_WEIGHTS = {
    "efficiency": 0.35,
    "acceptance": 0.25,
    "reliability": 0.20,
    "focus": 0.10,
    "quality": 0.10,
}

FOCUS_START_EVENTS = {"focus_start"}
FOCUS_PAUSE_EVENTS = {"focus_pause", "focus_auto_pause"}
FOCUS_SECONDS_EVENTS = FOCUS_PAUSE_EVENTS | {"focus_time_corrected"}


def _metadata_int(event: ActivityEvent, key: str) -> int:
    data = event.event_data or {}
    try:
        return int(data.get(key) or 0)
    except (TypeError, ValueError):
        return 0


def _score_efficiency(efficiency_percent: float) -> float:
    return round(min(max(efficiency_percent, 0.0), 150.0) / 1.5, 1)


def _score_reliability(active_overdue_count: int, completed_late_count: int) -> float:
    return round(max(0.0, 100.0 - active_overdue_count * 25.0 - completed_late_count * 15.0), 1)


def _score_focus(focus_task_coverage_percent: float, avg_pauses_per_task: float, completed_tasks_count: int) -> float:
    if completed_tasks_count <= 0:
        return 0.0
    pause_score = max(0.0, 100.0 - avg_pauses_per_task * 20.0)
    return round(focus_task_coverage_percent * 0.7 + pause_score * 0.3, 1)


def _weighted_score(
    *,
    efficiency_score: float,
    acceptance_score: float,
    reliability_score: float,
    focus_score: float,
    quality_score: float,
) -> float:
    score = (
        efficiency_score * SCORECARD_WEIGHTS["efficiency"]
        + acceptance_score * SCORECARD_WEIGHTS["acceptance"]
        + reliability_score * SCORECARD_WEIGHTS["reliability"]
        + focus_score * SCORECARD_WEIGHTS["focus"]
        + quality_score * SCORECARD_WEIGHTS["quality"]
    )
    return round(score, 1)


async def generate_period_report(db: AsyncSession, period: str) -> PeriodReport:
    """
    Полный отчёт за период.
    Если период закрыт — данные из PeriodSnapshot; иначе live из текущих пользователей и задач.
    """
    now = datetime.now(timezone.utc)
    generated_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    try:
        year, month = int(period[:4]), int(period[5:7].lstrip("0") or "1")
        month_start = now.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
        if month == 12:
            month_end = now.replace(year=year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            month_end = now.replace(year=year, month=month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
    except (ValueError, IndexError):
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_end = now

    # Проверяем, закрыт ли период (есть снимки)
    snap_result = await db.execute(
        select(PeriodSnapshot).where(PeriodSnapshot.period == period).limit(1)
    )
    snap_exists = snap_result.scalar_one_or_none()

    team_members: list[PerformerSummary] = []
    total_capacity = 0.0
    total_earned = 0.0

    if snap_exists:
        snap_list = (await db.execute(
            select(PeriodSnapshot).where(PeriodSnapshot.period == period)
        )).scalars().all()
        for s in snap_list:
            target = float(s.mpw)
            pct = (float(s.earned_main) / target * 100) if target > 0 else 0.0
            total_capacity += target
            total_earned += float(s.earned_main)
            user_r = await db.execute(select(User).where(User.id == s.user_id))
            u = user_r.scalar_one_or_none()
            name = u.full_name if u else str(s.user_id)
            team_members.append(
                PerformerSummary(
                    full_name=name,
                    league=s.league,
                    percent=round(pct, 1),
                    tasks_completed=s.tasks_completed,
                )
            )
    else:
        users_result = await db.execute(select(User).where(User.is_active.is_(True)))
        users = list(users_result.scalars().all())
        period_end_date = (month_end - timedelta(days=1)).date()
        absence_map = await absence_dates_by_user(db, [u.id for u in users], month_start.date(), period_end_date)
        plan_time = now if period == now.strftime("%Y-%m") else month_start
        for u in users:
            plan = effective_plan_for_user(u, plan_time, absence_map.get(u.id, set()))
            target = float(plan.effective_target)
            total_capacity += target
            total_earned += float(u.wallet_main)
            pct = (float(u.wallet_main) / target * 100) if target > 0 else 0.0
            tasks_done = await db.execute(
                select(func.count(Task.id)).where(
                    Task.assignee_id == u.id,
                    Task.status == TaskStatus.done,
                    Task.validated_at >= month_start,
                    Task.validated_at < month_end,
                )
            )
            team_members.append(
                PerformerSummary(
                    full_name=u.full_name,
                    league=u.league.value,
                    percent=round(pct, 1),
                    tasks_completed=int(tasks_done.scalar() or 0),
                )
            )

    sorted_members = sorted(team_members, key=lambda x: x.percent, reverse=True)
    top_performers = sorted_members[:3]
    underperformers = [m for m in team_members if m.percent < 50]

    # Задачи за период
    created_q = await db.execute(
        select(func.count(Task.id)).where(
            Task.created_at >= month_start,
            Task.created_at < month_end,
        )
    )
    completed_q = await db.execute(
        select(func.count(Task.id)).where(
            Task.status == TaskStatus.done,
            Task.validated_at.is_not(None),
            Task.validated_at >= month_start,
            Task.validated_at < month_end,
        )
    )
    total_created = int(created_q.scalar() or 0)
    total_completed = int(completed_q.scalar() or 0)

    avg_hours_result = await db.execute(
        select(
            func.avg(
                func.extract("epoch", Task.completed_at - Task.started_at) / 3600
            ).label("avg_h")
        ).where(
            Task.status == TaskStatus.done,
            Task.started_at.is_not(None),
            Task.completed_at.is_not(None),
            Task.validated_at >= month_start,
            Task.validated_at < month_end,
        )
    )
    avg_h = avg_hours_result.scalar()
    avg_time_hours = round(float(avg_h), 1) if avg_h is not None else None

    by_cat_result = await db.execute(
        select(Task.task_type, func.count(Task.id))
        .where(
            Task.status == TaskStatus.done,
            Task.validated_at >= month_start,
            Task.validated_at < month_end,
        )
        .group_by(Task.task_type)
    )
    by_category = {row[0].value: row[1] for row in by_cat_result.all()}

    tasks_overview = TasksOverview(
        total_created=total_created,
        total_completed=total_completed,
        avg_time_hours=avg_time_hours,
        by_category=by_category,
    )

    # Магазин за период
    purchases_result = await db.execute(
        select(func.count(Purchase.id), func.coalesce(func.sum(Purchase.cost_q), 0)).where(
            Purchase.created_at >= month_start,
            Purchase.created_at < month_end,
        )
    )
    row = purchases_result.one()
    total_purchases = int(row[0] or 0)
    total_karma_spent = round(float(row[1] or 0), 1)
    popular_result = await db.execute(
        select(Purchase.shop_item_id, func.count(Purchase.id))
        .where(
            Purchase.created_at >= month_start,
            Purchase.created_at < month_end,
        )
        .group_by(Purchase.shop_item_id)
    )
    popular_items = [{"shop_item_id": str(r[0]), "count": r[1]} for r in popular_result.all()]
    shop_activity = ShopActivity(
        total_purchases=total_purchases,
        total_karma_spent=total_karma_spent,
        popular_items=popular_items,
    )

    # Калибровка за период
    cal = await get_calibration_report(db, period=period)
    accurate = sum(1 for i in cal.items if i.recommendation == "OK")
    overestimated = sum(1 for i in cal.items if i.recommendation == "Завышена")
    underestimated = sum(1 for i in cal.items if i.recommendation == "Занижена")
    calibration_summary = CalibrationSummary(
        accurate_count=accurate,
        overestimated_count=overestimated,
        underestimated_count=underestimated,
    )

    utilization_percent = (total_earned / total_capacity * 100) if total_capacity > 0 else 0.0

    return PeriodReport(
        period=period,
        generated_at=generated_at,
        team_members=team_members,
        top_performers=top_performers,
        underperformers=underperformers,
        tasks_overview=tasks_overview,
        shop_activity=shop_activity,
        calibration_summary=calibration_summary,
        total_capacity=total_capacity,
        total_earned=total_earned,
        utilization_percent=round(utilization_percent, 1),
    )


async def generate_employee_scorecard(
    db: AsyncSession,
    *,
    start_date: date,
    end_date: date,
) -> EmployeeScorecardResponse:
    """Рейтинг v1: прозрачная scorecard по активным исполнителям и тимлидам."""
    start, end = date_window(start_date, end_date)
    now = datetime.now(timezone.utc)
    generated_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")

    users_result = await db.execute(
        select(User)
        .where(
            User.is_active.is_(True),
            User.role.in_([UserRole.executor, UserRole.teamlead]),
        )
        .order_by(User.full_name)
    )
    users = list(users_result.scalars().all())
    user_ids = [user.id for user in users]
    if not user_ids:
        return EmployeeScorecardResponse(
            start_date=start_date.isoformat(),
            end_date=end_date.isoformat(),
            generated_at=generated_at,
            weights=SCORECARD_WEIGHTS,
            rows=[],
        )

    absence_map = await absence_dates_by_user(db, user_ids, start_date, end_date)

    completed_by_user: dict = defaultdict(list)
    completed_result = await db.execute(
        select(Task).where(
            Task.assignee_id.in_(user_ids),
            Task.status == TaskStatus.done,
            Task.validated_at.is_not(None),
            Task.validated_at >= start,
            Task.validated_at < end,
        )
    )
    for task in completed_result.scalars().all():
        if task.assignee_id:
            completed_by_user[task.assignee_id].append(task)

    active_overdue_result = await db.execute(
        select(Task.assignee_id, func.count(Task.id))
        .where(
            Task.assignee_id.in_(user_ids),
            Task.status == TaskStatus.in_progress,
            or_(Task.is_overdue.is_(True), Task.due_date < now),
        )
        .group_by(Task.assignee_id)
    )
    active_overdue_by_user = {row[0]: int(row[1] or 0) for row in active_overdue_result.all()}

    rejection_result = await db.execute(
        select(Task.assignee_id, func.count(ActivityEvent.id))
        .join(Task, ActivityEvent.task_id == Task.id)
        .where(
            Task.assignee_id.in_(user_ids),
            ActivityEvent.event_type == "task_rejected",
            ActivityEvent.occurred_at >= start,
            ActivityEvent.occurred_at < end,
        )
        .group_by(Task.assignee_id)
    )
    rejection_by_user = {row[0]: int(row[1] or 0) for row in rejection_result.all()}

    focus_result = await db.execute(
        select(ActivityEvent).where(
            ActivityEvent.actor_id.in_(user_ids),
            ActivityEvent.event_type.in_(FOCUS_START_EVENTS | FOCUS_PAUSE_EVENTS | FOCUS_SECONDS_EVENTS),
            ActivityEvent.occurred_at >= start,
            ActivityEvent.occurred_at < end,
        )
    )
    focus_by_user: dict = defaultdict(lambda: {"seconds": 0, "starts": 0, "pauses": 0, "task_ids": set()})
    for event in focus_result.scalars().all():
        stats = focus_by_user[event.actor_id]
        if event.event_type in FOCUS_START_EVENTS:
            stats["starts"] += 1
            if event.task_id:
                stats["task_ids"].add(event.task_id)
        if event.event_type in FOCUS_PAUSE_EVENTS:
            stats["pauses"] += 1
            if event.task_id:
                stats["task_ids"].add(event.task_id)
        if event.event_type in FOCUS_SECONDS_EVENTS:
            stats["seconds"] += _metadata_int(event, "added_seconds")

    rows: list[EmployeeScorecardRow] = []
    for user in users:
        completed_tasks = completed_by_user.get(user.id, [])
        completed_tasks_count = len(completed_tasks)
        completed_q = sum((Decimal(str(task.estimated_q)) for task in completed_tasks), Decimal("0"))
        plan_q = effective_target_for_date_range(user, start_date, end_date, absence_map.get(user.id, set()))
        efficiency_percent = round(float(completed_q / plan_q * Decimal("100")), 1) if plan_q > 0 else 0.0

        first_pass_tasks_count = sum(1 for task in completed_tasks if (task.rejection_count or 0) == 0)
        first_pass_rate = round(first_pass_tasks_count / completed_tasks_count * 100, 1) if completed_tasks_count else 0.0
        completed_late_count = sum(
            1
            for task in completed_tasks
            if task.due_date is not None and task.completed_at is not None and task.completed_at > task.due_date
        )
        high_priority_completed_count = sum(1 for task in completed_tasks if task.priority == TaskPriority.high)
        critical_completed_count = sum(1 for task in completed_tasks if task.priority == TaskPriority.critical)
        focus_stats = focus_by_user.get(user.id, {"seconds": 0, "starts": 0, "pauses": 0, "task_ids": set()})
        focus_task_ids = focus_stats["task_ids"]
        focus_task_coverage_percent = round(
            sum(1 for task in completed_tasks if (task.active_seconds or 0) > 0) / completed_tasks_count * 100,
            1,
        ) if completed_tasks_count else 0.0
        avg_pauses_per_task = round(focus_stats["pauses"] / len(focus_task_ids), 2) if focus_task_ids else 0.0

        efficiency_score = _score_efficiency(efficiency_percent)
        acceptance_score = first_pass_rate
        reliability_score = _score_reliability(
            active_overdue_by_user.get(user.id, 0),
            completed_late_count,
        )
        focus_score = _score_focus(focus_task_coverage_percent, avg_pauses_per_task, completed_tasks_count)
        quality_score = round(float(user.quality_score or 0), 1)
        score = _weighted_score(
            efficiency_score=efficiency_score,
            acceptance_score=acceptance_score,
            reliability_score=reliability_score,
            focus_score=focus_score,
            quality_score=quality_score,
        )

        rows.append(
            EmployeeScorecardRow(
                rank=0,
                user_id=str(user.id),
                full_name=user.full_name,
                role=user.role.value,
                league=user.league.value,
                plan_q=round(float(plan_q), 1),
                completed_q=round(float(completed_q), 1),
                efficiency_percent=efficiency_percent,
                completed_tasks_count=completed_tasks_count,
                first_pass_tasks_count=first_pass_tasks_count,
                first_pass_rate=first_pass_rate,
                rejection_events_count=rejection_by_user.get(user.id, 0),
                active_overdue_count=active_overdue_by_user.get(user.id, 0),
                completed_late_count=completed_late_count,
                high_priority_completed_count=high_priority_completed_count,
                critical_completed_count=critical_completed_count,
                focus_hours=round(float(focus_stats["seconds"]) / 3600, 2),
                focus_start_count=int(focus_stats["starts"]),
                focus_pause_count=int(focus_stats["pauses"]),
                avg_pauses_per_task=avg_pauses_per_task,
                focus_task_coverage_percent=focus_task_coverage_percent,
                quality_score=quality_score,
                efficiency_score=efficiency_score,
                acceptance_score=acceptance_score,
                reliability_score=reliability_score,
                focus_score=focus_score,
                score=score,
            )
        )

    rows.sort(key=lambda row: (row.score, row.completed_q, row.completed_tasks_count), reverse=True)
    for index, row in enumerate(rows, start=1):
        row.rank = index

    return EmployeeScorecardResponse(
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        generated_at=generated_at,
        weights=SCORECARD_WEIGHTS,
        rows=rows,
    )
