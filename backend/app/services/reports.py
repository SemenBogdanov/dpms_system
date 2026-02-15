"""Генерация отчёта за период."""
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shop import PeriodSnapshot, Purchase
from app.models.task import Task, TaskStatus
from app.models.user import User
from app.schemas.reports import (
    CalibrationSummary,
    PeriodReport,
    PerformerSummary,
    ShopActivity,
    TasksOverview,
)
from app.services.calibration import get_calibration_report


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
            pct = (float(s.earned_main) / s.mpw * 100) if s.mpw > 0 else 0.0
            total_capacity += float(s.mpw)
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
        for u in users_result.scalars().all():
            total_capacity += float(u.mpw)
            total_earned += float(u.wallet_main)
            pct = (float(u.wallet_main) / u.mpw * 100) if u.mpw > 0 else 0.0
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
