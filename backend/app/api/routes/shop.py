"""API магазина бонусов. purchase, purchases, approve защищены JWT."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user, require_role
from app.models.user import User
from app.models.shop import ShopItem
from app.schemas.shop import (
    ShopItemResponse,
    PurchaseRequest,
    PurchaseResponse,
    ApprovePurchaseRequest,
)
from app.services.shop import (
    get_shop_items,
    purchase_item,
    get_user_purchases,
    approve_purchase,
)

router = APIRouter()


@router.get("", response_model=list[ShopItemResponse])
async def list_shop_items(db: AsyncSession = Depends(get_db)):
    """Список активных товаров (публичный)."""
    items = await get_shop_items(db)
    return items


@router.post("/purchase", response_model=PurchaseResponse)
async def create_purchase(
    body: PurchaseRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Купить товар за карму. Возвращает созданную покупку (status=pending)."""
    user_id = body.user_id or user.id
    purchase = await purchase_item(db, user_id, body.shop_item_id)
    shop_item = await db.get(ShopItem, purchase.shop_item_id)
    return PurchaseResponse(
        id=purchase.id,
        user_id=purchase.user_id,
        shop_item_id=purchase.shop_item_id,
        cost_q=purchase.cost_q,
        status=purchase.status,
        created_at=purchase.created_at,
        approved_at=purchase.approved_at,
        approved_by=purchase.approved_by,
        item_name=shop_item.name if shop_item else None,
    )


@router.get("/purchases/{user_id}", response_model=list[PurchaseResponse])
async def list_user_purchases(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """История покупок. Свои — всегда; чужие — только admin/teamlead."""
    if current_user.id != user_id and current_user.role.value not in ("admin", "teamlead"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Недостаточно прав")
    return await get_user_purchases(db, user_id)


@router.post("/approve")
async def approve_purchase_route(
    body: ApprovePurchaseRequest,
    user: User = Depends(require_role("admin", "teamlead")),
    db: AsyncSession = Depends(get_db),
):
    """Тимлид/админ подтверждает покупку."""
    approved_by = body.approved_by or user.id
    purchase = await approve_purchase(db, body.purchase_id, approved_by)
    return purchase
