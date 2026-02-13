"""Начисления Q: split main/karma с округлением до 1 знака."""
from decimal import Decimal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.models.transaction import QTransaction, WalletType


def _round_q(value: Decimal) -> Decimal:
    """Округление Q до 1 знака после запятой."""
    return Decimal(str(round(float(value), 1)))


async def credit_q(
    db: AsyncSession,
    user_id: UUID,
    amount: Decimal,
    reason: str,
    task_id: UUID | None = None,
) -> None:
    """
    Начислить Q пользователю. Три сценария:
    1) wallet_main + amount <= mpw → всё на main
    2) wallet_main >= mpw → всё на karma
    3) иначе → split: часть на main до плана, остаток на karma
    Все суммы округляются до 1 знака.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise ValueError("User not found")

    amount = _round_q(amount)
    mpw = Decimal(str(user.mpw))
    wallet_main = user.wallet_main

    if mpw == 0:
        to_main = amount
        to_karma = Decimal("0")
    elif wallet_main + amount <= mpw:
        to_main = amount
        to_karma = Decimal("0")
    elif wallet_main >= mpw:
        to_main = Decimal("0")
        to_karma = amount
    else:
        to_main = _round_q(mpw - wallet_main)
        to_karma = _round_q(amount - to_main)

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