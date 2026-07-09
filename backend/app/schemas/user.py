"""Схемы для пользователей."""
from datetime import datetime
from decimal import Decimal
from typing import Any
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
    is_new_employee: bool = False
    task_workspace_enabled: bool = False
    feedback_enabled: bool = False
    competency_development_enabled: bool = True
    competency_constructor_enabled: bool = False
    is_active: bool = True


class UserCreate(BaseModel):
    """Создание пользователя (admin)."""
    full_name: str = Field(..., max_length=255)
    email: EmailStr
    role: UserRole = UserRole.executor
    league: League = League.C
    mpw: int = Field(60, ge=0)
    password: str = Field(..., min_length=6)
    is_new_employee: bool = False
    task_workspace_enabled: bool = False
    feedback_enabled: bool = False
    competency_development_enabled: bool = False
    competency_constructor_enabled: bool = False


class UserUpdate(BaseModel):
    """Обновление пользователя (частичное, admin)."""
    full_name: str | None = None
    email: EmailStr | None = None
    role: UserRole | None = None
    league: League | None = None
    mpw: int | None = Field(None, ge=0)
    is_active: bool | None = None
    is_new_employee: bool | None = None
    task_workspace_enabled: bool | None = None
    feedback_enabled: bool | None = None
    competency_development_enabled: bool | None = None
    competency_constructor_enabled: bool | None = None


class UserRead(UserBase):
    """Чтение пользователя."""
    id: UUID
    wallet_main: float = 0
    wallet_karma: float = 0
    quality_score: float = 100.0
    needs_password_change: bool = False
    plan_started_at: datetime | None = None
    onboarding_started_at: datetime | None = None
    onboarding_until: datetime | None = None
    sidebar_menu_order: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SidebarMenuOrderUpdate(BaseModel):
    """Пользовательский порядок левого меню."""

    sidebar_menu_order: dict[str, Any] | None = None
