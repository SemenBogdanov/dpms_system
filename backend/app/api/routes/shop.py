"""API магазина бонусов."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
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
    """Список активных товаров."""
    items = await get_shop_items(db)
    return items


@router.post("/purchase", response_model=PurchaseResponse)
async def create_purchase(
    body: PurchaseRequest,
    db: AsyncSession = Depends(get_db),
):
    """Купить товар за карму. Возвращает созданную покупку (status=pending)."""
    purchase = await purchase_item(db, body.user_id, body.shop_item_id)
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
    db: AsyncSession = Depends(get_db),
):
    """История покупок пользователя."""
    return await get_user_purchases(db, user_id)


@router.post("/approve")
async def approve_purchase_route(
    body: ApprovePurchaseRequest,
    db: AsyncSession = Depends(get_db),
):
    """Тимлид/админ подтверждает покупку."""
    purchase = await approve_purchase(db, body.purchase_id, body.approved_by)
    return purchase
