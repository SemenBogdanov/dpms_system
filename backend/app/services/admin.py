"""Админка: закрытие периода (rollover), история периодов."""
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shop import PeriodClosure, PeriodSnapshot
from app.models.task import Task, TaskStatus
from app.models.transaction import QTransaction, WalletType
from app.models.user import User, UserRole
from app.services.absences import absence_dates_by_user
from app.services.planning import effective_plan_for_user


def _round_q(value: float) -> float:
    return round(value, 1)


def _period_bounds(period: str) -> tuple[datetime, datetime]:
    try:
        year, month = int(period[:4]), int(period[5:7])
    except (TypeError, ValueError):
        raise HTTPException(status_code=422, detail="Период должен быть в формате YYYY-MM")
    if len(period) != 7 or period[4] != "-" or month < 1 or month > 12:
        raise HTTPException(status_code=422, detail="Период должен быть в формате YYYY-MM")
    start = datetime(year, month, 1, tzinfo=timezone.utc)
    if month == 12:
        end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(year, month + 1, 1, tzinfo=timezone.utc)
    return start, end


def _previous_period(now: datetime) -> str:
    if now.month == 1:
        return f"{now.year - 1}-12"
    return f"{now.year}-{now.month - 1:02d}"


async def _ensure_admin(db: AsyncSession, admin_id: UUID) -> User:
    result = await db.execute(select(User).where(User.id == admin_id))
    admin = result.scalar_one_or_none()
    if not admin:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if admin.role != UserRole.admin:
        raise HTTPException(status_code=400, detail="Закрывать период может только администратор")
    return admin


async def rollover_period(db: AsyncSession, admin_id: UUID, period: str | None = None, mode: str = "manual") -> dict:
    """
    Смена месяца. Только для admin.
    Закрывается выбранный период: создаются снимки, базовый план списывается из main.
    Баллы сверх базового плана и Karma переносятся в следующий период.
    """
    await _ensure_admin(db, admin_id)
    now = datetime.now(timezone.utc)
    period = period or _previous_period(now)
    month_start, month_end = _period_bounds(period)
    current_month_start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if month_start > current_month_start:
        raise HTTPException(status_code=400, detail="Нельзя закрыть будущий период")
    mode = mode if mode in {"manual", "auto"} else "manual"

    closure_result = await db.execute(select(PeriodClosure).where(PeriodClosure.period == period))
    closure = closure_result.scalar_one_or_none()
    if closure and closure.status == "closed":
        raise HTTPException(status_code=400, detail="Период уже закрыт")
    snapshots_exists = await db.execute(select(PeriodSnapshot.id).where(PeriodSnapshot.period == period).limit(1))
    if snapshots_exists.scalar_one_or_none():
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

        effective_target = _round_q(float(period_plan.effective_target or 0))
        rollover_burn = min(earned_main, effective_target) if effective_target > 0 else 0.0
        carry_over = _round_q(max(0.0, earned_main - rollover_burn))

        if rollover_burn > 0:
            user.wallet_main = Decimal(str(carry_over))
            db.add(
                QTransaction(
                    user_id=user.id,
                    amount=Decimal(str(-rollover_burn)),
                    wallet_type=WalletType.main,
                    reason=f"Rollover {period}: закрытие базового плана",
                )
            )
            total_main_reset += rollover_burn

    from app.services.notifications import create_notification
    for user in users:
        await create_notification(
            db,
            user.id,
            "rollover",
            "Период закрыт",
            message=f"Период {period} завершён. Базовый план закрыт, сверхплан и Karma перенесены.",
            link="/profile",
        )
    if closure:
        closure.status = "closed"
        closure.mode = mode
        closure.closed_by_id = admin_id
        closure.cancelled_by_id = None
        closure.closed_at = now
        closure.cancelled_at = None
        closure.users_processed = len(users)
        closure.total_main_reset = Decimal(str(_round_q(total_main_reset)))
        closure.total_karma_burned = Decimal(str(_round_q(total_karma_burned)))
    else:
        db.add(
            PeriodClosure(
                period=period,
                status="closed",
                mode=mode,
                closed_by_id=admin_id,
                closed_at=now,
                users_processed=len(users),
                total_main_reset=Decimal(str(_round_q(total_main_reset))),
                total_karma_burned=Decimal(str(_round_q(total_karma_burned))),
            )
        )
    await db.flush()
    return {
        "period": period,
        "users_processed": len(users),
        "total_main_reset": _round_q(total_main_reset),
        "total_karma_burned": _round_q(total_karma_burned),
    }


async def auto_close_previous_period(db: AsyncSession, admin_id: UUID) -> dict:
    """Закрыть предыдущий месяц в режиме auto, если он еще открыт."""
    period = _previous_period(datetime.now(timezone.utc))
    return await rollover_period(db, admin_id, period=period, mode="auto")


async def cancel_period_closure(db: AsyncSession, admin_id: UUID, period: str) -> dict:
    """Отменить закрытие периода: snapshots удаляются, списание main компенсируется обратными транзакциями."""
    await _ensure_admin(db, admin_id)
    _period_bounds(period)
    closure_result = await db.execute(select(PeriodClosure).where(PeriodClosure.period == period))
    closure = closure_result.scalar_one_or_none()
    if not closure or closure.status != "closed":
        raise HTTPException(status_code=400, detail="Период не закрыт")

    rollover_reason = f"Rollover {period}: закрытие базового плана"
    cancel_reason = f"Cancel rollover {period}: отмена закрытия периода"
    tx_result = await db.execute(
        select(QTransaction.user_id, func.coalesce(func.sum(QTransaction.amount), 0)).where(
            QTransaction.wallet_type == WalletType.main,
            QTransaction.reason.in_([rollover_reason, cancel_reason]),
        ).group_by(QTransaction.user_id)
    )
    reversal_rows = tx_result.all()
    users_by_id: dict[UUID, User] = {}
    if reversal_rows:
        users_result = await db.execute(select(User).where(User.id.in_([row[0] for row in reversal_rows])))
        users_by_id = {user.id: user for user in users_result.scalars().all()}

    restored_main = 0.0
    for user_id, amount in reversal_rows:
        reversal = _round_q(max(0.0, -float(amount or 0)))
        if reversal <= 0:
            continue
        user = users_by_id.get(user_id)
        if not user:
            continue
        user.wallet_main += Decimal(str(reversal))
        db.add(
            QTransaction(
                user_id=user.id,
                amount=Decimal(str(reversal)),
                wallet_type=WalletType.main,
                reason=cancel_reason,
            )
        )
        restored_main += reversal

    await db.execute(delete(PeriodSnapshot).where(PeriodSnapshot.period == period))
    now = datetime.now(timezone.utc)
    closure.status = "cancelled"
    closure.cancelled_by_id = admin_id
    closure.cancelled_at = now

    from app.services.notifications import create_notification
    for user in users_by_id.values():
        await create_notification(
            db,
            user.id,
            "rollover",
            "Закрытие периода отменено",
            message=f"Закрытие периода {period} отменено. Списанные по базовому плану баллы восстановлены.",
            link="/profile",
        )

    await db.flush()
    return {
        "period": period,
        "users_processed": closure.users_processed,
        "total_main_reset": _round_q(restored_main),
        "total_karma_burned": 0.0,
    }


async def get_period_history(db: AsyncSession) -> list[dict]:
    """История периодов: группировка по period, агрегаты."""
    result = await db.execute(
        select(
            PeriodClosure.period,
            PeriodClosure.closed_at,
            PeriodClosure.status,
            PeriodClosure.mode,
            PeriodClosure.cancelled_at,
            PeriodClosure.users_processed,
            PeriodClosure.total_main_reset,
            PeriodClosure.total_karma_burned,
        )
        .order_by(PeriodClosure.period.desc())
    )
    rows = result.all()
    return [
        {
            "period": r.period,
            "closed_at": r.closed_at,
            "status": r.status,
            "mode": r.mode,
            "cancelled_at": r.cancelled_at,
            "users_count": r.users_processed,
            "total_main_reset": round(float(r.total_main_reset or 0), 1),
            "total_karma_burned": round(float(r.total_karma_burned or 0), 1),
        }
        for r in rows
    ]


async def get_period_details(db: AsyncSession, period: str) -> list[PeriodSnapshot]:
    """Детали по периоду: все снимки сотрудников."""
    result = await db.execute(
        select(PeriodSnapshot).where(PeriodSnapshot.period == period)
    )
    return list(result.scalars().all())
