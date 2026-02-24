"""Схемы для каталога операций."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.catalog import CatalogCategory, Complexity
from app.models.user import League


class CatalogItemBase(BaseModel):
    """Базовая схема позиции каталога."""
    category: CatalogCategory
    name: str = Field(..., max_length=255)
    complexity: Complexity
    base_cost_q: float = Field(..., ge=0)
    description: str | None = None
    min_league: League
    is_active: bool = True


class CatalogItemCreate(CatalogItemBase):
    """Создание позиции каталога."""
    pass


class CatalogItemUpdate(BaseModel):
    """Обновление позиции (частично)."""
    name: str | None = Field(None, max_length=255)
    category: CatalogCategory | None = None
    complexity: Complexity | None = None
    base_cost_q: float | None = Field(None, gt=0)
    min_league: League | None = None
    description: str | None = None
    is_active: bool | None = None


class CatalogItemRead(CatalogItemBase):
    """Чтение позиции каталога."""
    id: UUID
    sort_order: int = 100
    created_at: datetime

    model_config = {"from_attributes": True}
