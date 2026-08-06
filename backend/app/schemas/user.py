"""Схемы для пользователей."""
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, model_validator

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
    can_link_queue_tasks_to_projects: bool = False
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
    password: str = Field(..., min_length=8, max_length=128)
    is_new_employee: bool = False
    task_workspace_enabled: bool = False
    can_link_queue_tasks_to_projects: bool = False
    feedback_enabled: bool = False
    competency_development_enabled: bool = True
    competency_constructor_enabled: bool = False

    @model_validator(mode="after")
    def validate_project_queue_capability(self):
        if self.can_link_queue_tasks_to_projects and not self.task_workspace_enabled:
            raise ValueError(
                "Привязка Q-задач к проектам требует доступа к разделу задач"
            )
        return self


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
    can_link_queue_tasks_to_projects: bool | None = None
    feedback_enabled: bool | None = None
    competency_development_enabled: bool | None = None
    competency_constructor_enabled: bool | None = None


class UserRead(UserBase):
    """Чтение пользователя."""
    id: UUID
    wallet_main: float = 0
    wallet_karma: float = 0
    quality_score: float = 100.0
    plan_started_at: datetime | None = None
    onboarding_started_at: datetime | None = None
    onboarding_until: datetime | None = None
    sidebar_menu_order: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AuthenticatedUserRead(UserRead):
    """Данные текущего пользователя, включая состояние первого входа."""

    needs_password_change: bool = False


class AdminUserRead(AuthenticatedUserRead):
    """Административное представление состояния учетной записи."""

    temporary_password_expires_at: datetime | None = None


class SidebarMenuOrderUpdate(BaseModel):
    """Пользовательский порядок левого меню."""

    sidebar_menu_order: dict[str, Any] | None = None


class TemporaryPasswordRequest(BaseModel):
    """Выдать пользователю новый временный пароль."""

    temporary_password: str = Field(..., min_length=8, max_length=128)


AdminUserAuditAction = Literal["created", "updated", "temporary_password_issued"]


class AdminUserAuditChangeRead(BaseModel):
    """Одно безопасное изменение поля сотрудника."""

    field: str
    before: Any | None = None
    after: Any | None = None


class AdminUserAuditEventRead(BaseModel):
    """Типизированное событие истории администрирования сотрудника."""

    id: UUID
    actor_id: UUID
    actor_name: str
    target_user_id: UUID
    action: AdminUserAuditAction
    changes: list[AdminUserAuditChangeRead]
    sessions_revoked: bool = False
    occurred_at: datetime


class AdminUserAuditHistoryRead(BaseModel):
    """Ограниченная история административных изменений сотрудника."""

    items: list[AdminUserAuditEventRead]
    total: int
    limit: int
