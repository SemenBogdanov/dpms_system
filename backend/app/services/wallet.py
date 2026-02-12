"""Начисления и списания Q (запись в q_transactions и обновление кошельков)."""
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.transaction import QTransaction, WalletType


async def credit_q(
    db: AsyncSession,
    user_id: UUID,
    amount: Decimal,
    reason: str,
    task_id: UUID | None = None,
) -> None:
    """
    Начислить Q пользователю. Основная часть идёт в wallet_main.
    Если wallet_main уже >= mpw, излишек идёт в wallet_karma.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("User not found")

    # Сначала начисляем в main до плана (mpw)
    remaining_plan = Decimal(str(user.mpw)) - user.wallet_main
    to_main = min(amount, remaining_plan) if remaining_plan > 0 else Decimal("0")
    to_karma = amount - to_main
    if to_main < 0:
        to_main = Decimal("0")
    if user.mpw == 0:
        # Админ/без плана — всё в main для единообразия или в karma по политике
        to_main = amount
        to_karma = Decimal("0")

    if to_main > 0:
        user.wallet_main += to_main
        db.add(
            QTransaction(
                user_id=user_id,
                amount=to_main,
                wallet_type=WalletType.main,
                reason=reason,
                task_id=task_id,
            )
        )
    if to_karma > 0:
        user.wallet_karma += to_karma
        db.add(
            QTransaction(
                user_id=user_id,
                amount=to_karma,
                wallet_type=WalletType.karma,
                reason=reason,
                task_id=task_id,
            )
        )
    await db.flush()
