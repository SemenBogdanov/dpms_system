"""Админка: закрытие периода (rollover), история периодов."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shop import PeriodSnapshot
from app.models.task import Task, TaskStatus
from app.models.transaction import QTransaction, WalletType
from app.models.user import User, UserRole
from app.services.absences import absence_dates_by_user
from app.services.planning import effective_plan_for_user


def _round_q(value: float) -> float:
    return round(value, 1)


async def rollover_period(db: AsyncSession, admin_id: UUID) -> dict:
    """
    Смена месяца. Только для admin.
    Предыдущий месяц закрывается: снимки и обнуление main.
    Karma полностью переносится в следующий период.
    Всё в одной транзакции БД. Повторный rollover за тот же период — 400.
    """
    result = await db.execute(select(User).where(User.id == admin_id))
    admin = result.scalar_one_or_none()
    if not admin:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if admin.role != UserRole.admin:
        raise HTTPException(status_code=400, detail="Закрывать период может только администратор")

    now = datetime.now(timezone.utc)
    if now.month == 1:
        prev_year, prev_month = now.year - 1, 12
    else:
        prev_year, prev_month = now.year, now.month - 1
    period = f"{prev_year}-{prev_month:02d}"
    month_start = now.replace(
        year=prev_year, month=prev_month, day=1,
        hour=0, minute=0, second=0, microsecond=0,
    )
    if prev_month == 12:
        month_end = now.replace(
            year=prev_year + 1, month=1, day=1,
            hour=0, minute=0, second=0, microsecond=0,
        )
    else:
        month_end = now.replace(
            year=prev_year, month=prev_month + 1, day=1,
            hour=0, minute=0, second=0, microsecond=0,
        )

    exists = await db.execute(
        select(PeriodSnapshot.id).where(PeriodSnapshot.period == period).limit(1)
    )
    if exists.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Период уже закрыт")

    users_result = await db.execute(
        select(User).where(User.is_active.is_(True))
    )
    users = list(users_result.scalars().all())
    period_end_date = (month_end - timedelta(days=1)).date()
    absence_map = await absence_dates_by_user(db, [user.id for user in users], month_start.date(), period_end_date)
    total_main_reset = 0.0
    total_karma_burned = 0.0

    for user in users:
        earned_main = _round_q(float(user.wallet_main))
        earned_karma = _round_q(float(user.wallet_karma))

        tasks_count_result = await db.execute(
            select(func.count(Task.id)).where(
                Task.assignee_id == user.id,
                Task.status == TaskStatus.done,
                Task.validated_at.is_not(None),
                Task.validated_at >= month_start,
                Task.validated_at < month_end,
            )
        )
        tasks_completed = int(tasks_count_result.scalar() or 0)

        period_plan = effective_plan_for_user(user, month_start, absence_map.get(user.id, set()))

        db.add(
            PeriodSnapshot(
                user_id=user.id,
                period=period,
                mpw=period_plan.effective_target,
                earned_main=Decimal(str(earned_main)),
                earned_karma=Decimal(str(earned_karma)),
                tasks_completed=tasks_completed,
                league=user.league.value,
            )
        )

        if earned_main > 0:
            user.wallet_main = Decimal("0")
            db.add(
                QTransaction(
                    user_id=user.id,
                    amount=Decimal(str(-earned_main)),
                    wallet_type=WalletType.main,
                    reason=f"Rollover {period}: обнуление",
                )
            )
            total_main_reset += earned_main

    from app.services.notifications import create_notification
    for user in users:
        await create_notification(
            db,
            user.id,
            "rollover",
            "Период закрыт",
            message=f"Период {period} завершён. Main обнулён, Karma перенесена.",
            link="/profile",
        )
    await db.flush()
    return {
        "period": period,
        "users_processed": len(users),
        "total_main_reset": _round_q(total_main_reset),
        "total_karma_burned": _round_q(total_karma_burned),
    }


async def get_period_history(db: AsyncSession) -> list[dict]:
    """История периодов: группировка по period, агрегаты."""
    result = await db.execute(
        select(
            PeriodSnapshot.period,
            func.min(PeriodSnapshot.created_at).label("closed_at"),
            func.count(PeriodSnapshot.id).label("users_count"),
            func.sum(PeriodSnapshot.earned_main).label("total_main"),
        )
        .group_by(PeriodSnapshot.period)
        .order_by(PeriodSnapshot.period.desc())
    )
    rows = result.all()
    return [
        {
            "period": r.period,
            "closed_at": r.closed_at,
            "users_count": r.users_count,
            "total_main_reset": round(float(r.total_main or 0), 1),
            "total_karma_burned": 0.0,
        }
        for r in rows
    ]


async def get_period_details(db: AsyncSession, period: str) -> list[PeriodSnapshot]:
    """Детали по периоду: все снимки сотрудников."""
    result = await db.execute(
        select(PeriodSnapshot).where(PeriodSnapshot.period == period)
    )
    return list(result.scalars().all())
