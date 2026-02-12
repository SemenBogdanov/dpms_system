"""Схемы для пользователей."""
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field

from app.models.user import League, UserRole


class UserBase(BaseModel):
    """Базовая схема пользователя."""
    full_name: str = Field(..., max_length=255)
    email: EmailStr
    league: League
    role: UserRole
    mpw: int = Field(..., ge=0)
    wip_limit: int = Field(default=2, ge=1)
    is_active: bool = True


class UserCreate(UserBase):
    """Создание пользователя."""
    pass


class UserUpdate(BaseModel):
    """Обновление пользователя (частичное)."""
    league: League | None = None
    mpw: int | None = Field(None, ge=0)
    wip_limit: int | None = Field(None, ge=1)
    is_active: bool | None = None


class UserRead(UserBase):
    """Чтение пользователя."""
    id: UUID
    wallet_main: Decimal = Decimal("0")
    wallet_karma: Decimal = Decimal("0")
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
