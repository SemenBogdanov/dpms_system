"""Магазин бонусов: каталог, покупка за карму, подтверждение тимлидом."""
from datetime import datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.shop import Purchase, ShopItem
from app.models.transaction import QTransaction, WalletType
from app.models.user import User, UserRole
from app.schemas.shop import PurchaseResponse


def _round_q(value: Decimal) -> Decimal:
    return Decimal(str(round(float(value), 1)))


def _purchase_response(
    purchase: Purchase,
    item_name: str | None = None,
    user: User | None = None,
) -> PurchaseResponse:
    return PurchaseResponse(
        id=purchase.id,
        user_id=purchase.user_id,
        shop_item_id=purchase.shop_item_id,
        cost_q=purchase.cost_q,
        status=purchase.status,
        created_at=purchase.created_at,
        approved_at=purchase.approved_at,
        approved_by=purchase.approved_by,
        item_name=item_name,
        user_name=user.full_name if user else None,
        user_email=user.email if user else None,
    )


async def get_shop_items(db: AsyncSession) -> list[ShopItem]:
    """Все активные товары."""
    result = await db.execute(
        select(ShopItem).where(ShopItem.is_active.is_(True)).order_by(ShopItem.cost_q)
    )
    return list(result.scalars().all())


async def purchase_item(
    db: AsyncSession,
    user_id: UUID,
    shop_item_id: UUID,
) -> Purchase:
    """
    Купить товар за карму.
    Если item.requires_approval == False: списать карму сразу, Purchase(approved), уведомление пользователю.
    Если item.requires_approval == True: не списывать, Purchase(pending), уведомление тимлидам.
    """
    result = await db.execute(select(ShopItem).where(ShopItem.id == shop_item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Товар не найден")
    if not item.is_active:
        raise HTTPException(status_code=400, detail="Товар недоступен для покупки")

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    cost = _round_q(item.cost_q)
    if float(user.wallet_karma) < float(cost):
        need = round(float(cost) - float(user.wallet_karma), 1)
        raise HTTPException(
            status_code=400,
            detail=f"Недостаточно кармы. Нужно ещё {need} Q",
        )

    now = datetime.now(timezone.utc)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    count_result = await db.execute(
        select(func.count(Purchase.id)).where(
            Purchase.user_id == user_id,
            Purchase.shop_item_id == shop_item_id,
            Purchase.created_at >= month_start,
        )
    )
    count_this_month = count_result.scalar() or 0
    if count_this_month >= item.max_per_month:
        raise HTTPException(
            status_code=400,
            detail="Лимит покупок этого товара в этом месяце исчерпан",
        )

    from app.services.notifications import create_notification

    if not getattr(item, "requires_approval", True):
        # Мгновенная покупка: списать карму, статус approved, уведомление пользователю
        user.wallet_karma -= cost
        db.add(
            QTransaction(
                user_id=user_id,
                amount=-cost,
                wallet_type=WalletType.karma,
                reason=f"Покупка: {item.name}",
            )
        )
        purchase = Purchase(
            user_id=user_id,
            shop_item_id=shop_item_id,
            cost_q=cost,
            status="approved",
        )
        db.add(purchase)
        await db.flush()
        await db.refresh(purchase)
        await create_notification(
            db, user_id,
            "purchase_approved",
            "Покупка выполнена",
            message=f"Покупка «{item.name}» выполнена. Списано {float(cost):.1f} кармы.",
            link="/shop",
        )
        return purchase

    # Требует одобрения: не списывать, pending, уведомление тимлидам
    purchase = Purchase(
        user_id=user_id,
        shop_item_id=shop_item_id,
        cost_q=cost,
        status="pending",
    )
    db.add(purchase)
    await db.flush()
    await db.refresh(purchase)
    teamleads_result = await db.execute(
        select(User.id).where(User.role.in_([UserRole.teamlead, UserRole.admin]))
    )
    for (tid,) in teamleads_result.all():
        await create_notification(
            db, tid,
            "purchase_pending",
            "Новая покупка",
            message=f"{user.full_name} купил «{item.name}»",
            link="/my-tasks",
        )
    return purchase


async def get_user_purchases(
    db: AsyncSession,
    user_id: UUID,
) -> list[PurchaseResponse]:
    """История покупок пользователя с названием товара."""
    result = await db.execute(
        select(Purchase, ShopItem.name)
        .join(ShopItem, Purchase.shop_item_id == ShopItem.id)
        .where(Purchase.user_id == user_id)
        .order_by(Purchase.created_at.desc())
    )
    rows = result.all()
    out = []
    for p, item_name in rows:
        out.append(_purchase_response(p, item_name=item_name))
    return out


async def get_pending_purchase_approvals(db: AsyncSession) -> list[PurchaseResponse]:
    """Ожидающие согласования покупки для экрана «Мои задачи» тимлида."""
    result = await db.execute(
        select(Purchase, ShopItem.name, User)
        .join(ShopItem, Purchase.shop_item_id == ShopItem.id)
        .join(User, Purchase.user_id == User.id)
        .where(Purchase.status == "pending")
        .order_by(Purchase.created_at.asc())
    )
    return [
        _purchase_response(purchase, item_name=item_name, user=user)
        for purchase, item_name, user in result.all()
    ]


async def approve_purchase(
    db: AsyncSession,
    purchase_id: UUID,
    approved_by: UUID,
) -> PurchaseResponse:
    """Тимлид/админ подтверждает покупку."""
    approver_result = await db.execute(select(User).where(User.id == approved_by))
    approver = approver_result.scalar_one_or_none()
    if not approver:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if approver.role not in (UserRole.teamlead, UserRole.admin):
        raise HTTPException(
            status_code=400,
            detail="Подтверждать покупки могут только тимлид или админ",
        )

    result = await db.execute(select(Purchase).where(Purchase.id == purchase_id).with_for_update())
    purchase = result.scalar_one_or_none()
    if not purchase:
        raise HTTPException(status_code=404, detail="Покупка не найдена")
    if purchase.status != "pending":
        raise HTTPException(status_code=400, detail="Покупка уже обработана")

    item_result = await db.execute(select(ShopItem).where(ShopItem.id == purchase.shop_item_id))
    item = item_result.scalar_one_or_none()
    item_name = item.name if item else "Товар"
    buyer_result = await db.execute(select(User).where(User.id == purchase.user_id))
    buyer = buyer_result.scalar_one_or_none()
    if not buyer:
        raise HTTPException(status_code=404, detail="Покупатель не найден")
    if float(buyer.wallet_karma) < float(purchase.cost_q):
        raise HTTPException(status_code=400, detail="У сотрудника недостаточно кармы для подтверждения покупки")

    buyer.wallet_karma -= purchase.cost_q
    db.add(
        QTransaction(
            user_id=purchase.user_id,
            amount=-purchase.cost_q,
            wallet_type=WalletType.karma,
            reason=f"Покупка: {item_name}",
        )
    )
    purchase.status = "approved"
    purchase.approved_at = datetime.now(timezone.utc)
    purchase.approved_by = approved_by
    await db.flush()
    await db.refresh(purchase)
    from app.services.notifications import create_notification
    await create_notification(
        db,
        purchase.user_id,
        "purchase_approved",
        "Покупка подтверждена",
        message=f"«{item_name}» одобрена",
        link="/shop",
    )
    return _purchase_response(purchase, item_name=item_name, user=buyer)


async def reject_purchase(
    db: AsyncSession,
    purchase_id: UUID,
    rejected_by: UUID,
    comment: str | None = None,
) -> PurchaseResponse:
    """Тимлид/админ отклоняет покупку без списания кармы."""
    approver_result = await db.execute(select(User).where(User.id == rejected_by))
    approver = approver_result.scalar_one_or_none()
    if not approver:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if approver.role not in (UserRole.teamlead, UserRole.admin):
        raise HTTPException(status_code=400, detail="Отклонять покупки могут только тимлид или админ")

    result = await db.execute(select(Purchase).where(Purchase.id == purchase_id).with_for_update())
    purchase = result.scalar_one_or_none()
    if not purchase:
        raise HTTPException(status_code=404, detail="Покупка не найдена")
    if purchase.status != "pending":
        raise HTTPException(status_code=400, detail="Покупка уже обработана")

    item_result = await db.execute(select(ShopItem).where(ShopItem.id == purchase.shop_item_id))
    item = item_result.scalar_one_or_none()
    item_name = item.name if item else "Товар"
    buyer_result = await db.execute(select(User).where(User.id == purchase.user_id))
    buyer = buyer_result.scalar_one_or_none()

    purchase.status = "rejected"
    purchase.approved_at = datetime.now(timezone.utc)
    purchase.approved_by = rejected_by
    await db.flush()
    await db.refresh(purchase)

    from app.services.notifications import create_notification
    message = f"«{item_name}» отклонена"
    if comment:
        message = f"{message}: {comment}"
    await create_notification(
        db,
        purchase.user_id,
        "purchase_rejected",
        "Покупка отклонена",
        message=message,
        link="/shop",
    )
    return _purchase_response(purchase, item_name=item_name, user=buyer)
