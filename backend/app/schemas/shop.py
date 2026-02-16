"""Схемы магазина бонусов."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel


class ShopItemResponse(BaseModel):
    """Товар в каталоге магазина."""
    id: UUID
    name: str
    description: str
    cost_q: float
    category: str
    icon: str
    is_active: bool
    max_per_month: int
    requires_approval: bool = True
    created_at: datetime

    model_config = {"from_attributes": True}


class PurchaseRequest(BaseModel):
    """Запрос на покупку. user_id опционален (из JWT)."""
    user_id: UUID | None = None
    shop_item_id: UUID


class PurchaseResponse(BaseModel):
    """Запись о покупке."""
    id: UUID
    user_id: UUID
    shop_item_id: UUID
    cost_q: float
    status: str
    created_at: datetime
    approved_at: datetime | None
    approved_by: UUID | None
    item_name: str | None = None

    model_config = {"from_attributes": True}


class ApprovePurchaseRequest(BaseModel):
    """Подтверждение покупки тимлидом/админом. approved_by опционален (из JWT)."""
    purchase_id: UUID
    approved_by: UUID | None = None
