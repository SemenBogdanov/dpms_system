"""API дашборда: Стакан, сводка по команде, план/факт, периодическая статистика. calibration — admin/teamlead."""
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user, require_role
from app.models.user import User
from app.models.transaction import QTransaction, WalletType
from app.schemas.dashboard import CapacityGauge, TeamSummary, PeriodStats, BurndownData
from app.schemas.calibration import CalibrationReportNew, TeamleadAccuracy
from app.schemas.task import FocusStatus
from app.services.analytics import (
    get_capacity_gauge,
    get_team_summary,
    get_period_stats,
    get_burndown_data,
)
from app.services.calibration import get_teamlead_accuracy
from app.services.queue import check_overdue_tasks, check_stale_tasks
from app.services.focus import auto_pause_stale_focuses, get_focus_statuses
from app.models.task import Task, TaskStatus
from app.models.catalog import CatalogItem

router = APIRouter()


@router.get("/capacity", response_model=CapacityGauge)
async def capacity(
    db: AsyncSession = Depends(get_db),
):
    """Метрика «Стакан»: загрузка vs ёмкость команды."""
    await check_overdue_tasks(db)
    await check_stale_tasks(db)
    return await get_capacity_gauge(db)


@router.get("/team-summary", response_model=TeamSummary)
async def team_summary(
    db: AsyncSession = Depends(get_db),
):
    """Сводка по команде (по лигам, earned vs target, in_progress_q, is_at_risk)."""
    await check_overdue_tasks(db)
    await check_stale_tasks(db)
    return await get_team_summary(db)


@router.get("/plan-fact", response_model=TeamSummary)
async def plan_fact(
    db: AsyncSession = Depends(get_db),
):
    """План/факт по сотрудникам (то же что team-summary)."""
    await check_overdue_tasks(db)
    await check_stale_tasks(db)
    return await get_team_summary(db)


@router.get("/period-stats", response_model=PeriodStats)
async def period_stats(
    db: AsyncSession = Depends(get_db),
):
    """Статистика текущего месяца для дашборда руководителя."""
    await check_overdue_tasks(db)
    await check_stale_tasks(db)
    return await get_period_stats(db)


@router.get("/burndown", response_model=BurndownData)
async def burndown(
    db: AsyncSession = Depends(get_db),
):
    """Данные для графика burn-down текущего месяца."""
    await check_overdue_tasks(db)
    await check_stale_tasks(db)
    return await get_burndown_data(db)


@router.get("/capacity-history")
async def capacity_history(
    weeks: int = Query(default=6, ge=1, le=12),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    История ёмкости команды за последние N недель.
    Возвращает [{week: "10-14 фев", earned: 45.5, capacity: 120, percent: 38}]
    """
    now = datetime.now(timezone.utc)

    cap_result = await db.execute(
        select(func.sum(User.mpw)).where(User.is_active.is_(True), User.mpw > 0)
    )
    total_capacity = float(cap_result.scalar() or 0)

    month_names = {
        1: "янв", 2: "фев", 3: "мар", 4: "апр", 5: "май", 6: "июн",
        7: "июл", 8: "авг", 9: "сен", 10: "окт", 11: "ноя", 12: "дек",
    }
    points = []
    for i in range(weeks - 1, -1, -1):
        week_end = now - timedelta(weeks=i)
        week_start = week_end - timedelta(weeks=1)

        earned_result = await db.execute(
            select(func.sum(QTransaction.amount)).where(
                QTransaction.wallet_type == WalletType.main,
                QTransaction.amount > 0,
                QTransaction.created_at >= week_start,
                QTransaction.created_at < week_end,
            )
        )
        earned = float(earned_result.scalar() or 0)
        percent = round(earned / total_capacity * 100, 0) if total_capacity > 0 else 0

        start_day = week_start.day
        end_day = (week_end - timedelta(days=1)).day
        month_label = month_names.get(week_start.month, "")

        points.append({
            "week": f"{start_day}-{end_day} {month_label}",
            "earned": round(earned, 1),
            "capacity": round(total_capacity, 1),
            "percent": int(percent),
        })

    return {"weeks": points, "total_capacity": total_capacity}


@router.get("/focus-status", response_model=list[FocusStatus])
async def focus_status(
    user: User = Depends(require_role("teamlead")),
    db: AsyncSession = Depends(get_db),
):
    """Статусы фокуса всех исполнителей (для дашборда тимлида/админа)."""
    await auto_pause_stale_focuses(db)
    return await get_focus_statuses(db)


@router.get("/calibration", response_model=CalibrationReportNew)
async def calibration(
    period: str = Query(default="", description="YYYY-MM, пусто = текущий"),
    user: User = Depends(require_role("admin", "teamlead")),
    db: AsyncSession = Depends(get_db),
):
    """
    Калибровочный отчёт:
    1. Отклонение по задачам (estimated_q vs actual_hours)
    2. Точность оценщиков
    3. Популярность операций каталога
    """
    now = datetime.now(timezone.utc)
    use_period_filter = True
    if period and period.lower() == "all":
        start = None
        end = None
        use_period_filter = False
    elif period:
        try:
            year, month = int(period[:4]), int(period[5:7])
            start = datetime(year, month, 1, tzinfo=timezone.utc)
            end = (
                datetime(year, month + 1, 1, tzinfo=timezone.utc)
                if month < 12
                else datetime(year + 1, 1, 1, tzinfo=timezone.utc)
            )
        except (ValueError, IndexError):
            start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            end = now
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        end = now

    # --- 1. Калибровка по задачам ---
    done_stmt = select(Task).where(
        Task.status == TaskStatus.done,
        Task.started_at.isnot(None),
        Task.completed_at.isnot(None),
    )
    if use_period_filter and start is not None and end is not None:
        done_stmt = done_stmt.where(
            Task.completed_at >= start,
            Task.completed_at < end,
        )
    done_stmt = done_stmt.order_by(Task.completed_at.desc())
    done_result = await db.execute(done_stmt)
    done_list = list(done_result.scalars().all())

    user_ids = set()
    for t in done_list:
        if t.assignee_id:
            user_ids.add(t.assignee_id)
        if t.estimator_id:
            user_ids.add(t.estimator_id)
    users_map = {}
    if user_ids:
        u_res = await db.execute(select(User.id, User.full_name).where(User.id.in_(user_ids)))
        users_map = {row.id: row.full_name for row in u_res.all()}

    task_calibrations = []
    for t in done_list:
        # Продуктивное время: сначала active_seconds, для старых задач — wall-clock
        if getattr(t, "active_seconds", 0) and t.active_seconds > 0:
            actual_hours = t.active_seconds / 3600
        else:
            actual_hours = (t.completed_at - t.started_at).total_seconds() / 3600
        estimated_hours = float(t.estimated_q)
        deviation_pct = (
            round((actual_hours - estimated_hours) / estimated_hours * 100, 0)
            if estimated_hours > 0
            else 0
        )
        task_calibrations.append({
            "task_id": str(t.id),
            "title": t.title,
            "task_type": t.task_type.value,
            "complexity": t.complexity.value,
            "estimated_q": float(t.estimated_q),
            "actual_hours": round(actual_hours, 1),
            "deviation_pct": int(deviation_pct),
            "assignee_name": users_map.get(t.assignee_id, "—"),
            "estimator_name": users_map.get(t.estimator_id, "—"),
            "tags": t.tags or [],
        })

    # --- 2. Калибровка по оценщикам ---
    estimator_stats: dict = {}
    for tc in task_calibrations:
        name = tc["estimator_name"]
        if name == "—":
            continue
        if name not in estimator_stats:
            estimator_stats[name] = {
                "tasks": 0,
                "total_deviation": 0.0,
                "overestimates": 0,
                "underestimates": 0,
            }
        s = estimator_stats[name]
        s["tasks"] += 1
        s["total_deviation"] += tc["deviation_pct"]
        if tc["deviation_pct"] > 10:
            s["underestimates"] += 1
        elif tc["deviation_pct"] < -10:
            s["overestimates"] += 1

    estimator_calibrations = []
    for name, s in estimator_stats.items():
        avg_dev = round(s["total_deviation"] / s["tasks"], 0) if s["tasks"] > 0 else 0
        accuracy = max(0, 100 - abs(avg_dev))
        bias = "завышает" if avg_dev < -10 else "занижает" if avg_dev > 10 else "точно"
        estimator_calibrations.append({
            "estimator_name": name,
            "tasks_count": s["tasks"],
            "avg_deviation_pct": int(avg_dev),
            "accuracy_pct": int(accuracy),
            "bias": bias,
            "overestimates": s["overestimates"],
            "underestimates": s["underestimates"],
        })

    # --- 3. Популярность операций каталога ---
    all_tasks_stmt = select(Task).where(Task.estimation_details.isnot(None))
    if use_period_filter and start is not None and end is not None:
        all_tasks_stmt = all_tasks_stmt.where(
            Task.created_at >= start,
            Task.created_at < end,
        )
    all_tasks_result = await db.execute(all_tasks_stmt)
    all_with_details = list(all_tasks_result.scalars().all())
    total_tasks_with_breakdown = 0
    widget_usage: dict[str, int] = {}

    catalog_result = await db.execute(select(CatalogItem.id, CatalogItem.name))
    catalog_id_to_name = {str(row.id): row.name for row in catalog_result.all()}

    for t in all_with_details:
        details = t.estimation_details
        if not isinstance(details, dict):
            continue
        breakdown = details.get("breakdown", [])
        if not breakdown:
            continue
        total_tasks_with_breakdown += 1
        seen_names: set[str] = set()
        for item in breakdown:
            if not isinstance(item, dict):
                continue
            name = item.get("name")
            if not name and item.get("catalog_id"):
                name = catalog_id_to_name.get(str(item["catalog_id"]), "Unknown")
            if not name:
                name = "Unknown"
            if name not in seen_names:
                widget_usage[name] = widget_usage.get(name, 0) + 1
                seen_names.add(name)

    widget_popularity = sorted(
        [
            {
                "name": name,
                "tasks_count": count,
                "usage_percent": round(count / total_tasks_with_breakdown * 100, 0)
                if total_tasks_with_breakdown > 0
                else 0,
            }
            for name, count in widget_usage.items()
        ],
        key=lambda x: x["tasks_count"],
        reverse=True,
    )

    total_tasks = len(task_calibrations)
    avg_deviation = (
        round(sum(tc["deviation_pct"] for tc in task_calibrations) / total_tasks, 0)
        if total_tasks > 0
        else 0
    )
    accurate_count = sum(1 for tc in task_calibrations if abs(tc["deviation_pct"]) <= 15)
    accuracy_overall = round(accurate_count / total_tasks * 100, 0) if total_tasks > 0 else 0

    period_display = "all" if (period and period.lower() == "all") else (period or now.strftime("%Y-%m"))
    return CalibrationReportNew(
        period=period_display,
        total_tasks_analyzed=total_tasks,
        overall_accuracy_pct=int(accuracy_overall),
        avg_deviation_pct=int(avg_deviation),
        task_calibrations=task_calibrations,
        estimator_calibrations=estimator_calibrations,
        widget_popularity=widget_popularity,
        total_tasks_with_breakdown=total_tasks_with_breakdown,
    )


@router.get("/teamlead-accuracy", response_model=list[TeamleadAccuracy])
async def teamlead_accuracy(
    user: User = Depends(require_role("admin", "teamlead")),
    db: AsyncSession = Depends(get_db),
):
    """Точность оценок тимлидов. Только admin/teamlead."""
    return await get_teamlead_accuracy(db)
