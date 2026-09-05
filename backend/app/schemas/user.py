"""Схемы для пользователей."""
from datetime import datetime
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator, model_validator

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
    audit_enabled: bool = False
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
    audit_enabled: bool = False
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
    audit_enabled: bool | None = None
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


SidebarMenuImportId = Annotated[str, Field(strict=True, min_length=1, max_length=64)]
SidebarMenuImportLabel = Annotated[str, Field(strict=True, min_length=1, max_length=80)]
SidebarMenuImportItemIds = Annotated[
    list[SidebarMenuImportId],
    Field(max_length=64),
]


class SidebarMenuImportGroup(BaseModel):
    """Одна пользовательская кнопка импортируемого меню."""

    model_config = ConfigDict(extra="forbid", strict=True)

    id: SidebarMenuImportId
    label: SidebarMenuImportLabel
    item_ids: SidebarMenuImportItemIds | None = None

    @field_validator("id", "label")
    @classmethod
    def strip_non_empty_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Значение не может быть пустым")
        return cleaned

    @field_validator("item_ids")
    @classmethod
    def strip_item_ids(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned = [item_id.strip() for item_id in value]
        if any(not item_id for item_id in cleaned):
            raise ValueError("Идентификатор раздела не может быть пустым")
        return cleaned


class SidebarMenuImportLayout(BaseModel):
    """Ограниченный формат раскладки внутри файла импорта."""

    model_config = ConfigDict(extra="forbid", strict=True)

    version: int = Field(..., strict=True, ge=1, le=100)
    groups: list[SidebarMenuImportGroup] = Field(..., min_length=1, max_length=32)
    items: dict[SidebarMenuImportId, SidebarMenuImportItemIds] = Field(
        default_factory=dict,
        max_length=32,
    )
    item_labels: dict[SidebarMenuImportId, SidebarMenuImportLabel] = Field(
        default_factory=dict,
        max_length=64,
    )

    @field_validator("items")
    @classmethod
    def strip_legacy_items(cls, value: dict[str, list[str]]) -> dict[str, list[str]]:
        cleaned: dict[str, list[str]] = {}
        for group_id, item_ids in value.items():
            normalized_group_id = group_id.strip()
            normalized_item_ids = [item_id.strip() for item_id in item_ids]
            if not normalized_group_id or any(not item_id for item_id in normalized_item_ids):
                raise ValueError("Идентификаторы меню не могут быть пустыми")
            cleaned[normalized_group_id] = normalized_item_ids
        return cleaned

    @field_validator("item_labels")
    @classmethod
    def strip_item_labels(cls, value: dict[str, str]) -> dict[str, str]:
        cleaned: dict[str, str] = {}
        for item_id, label in value.items():
            normalized_item_id = item_id.strip()
            normalized_label = label.strip()
            if not normalized_item_id or not normalized_label:
                raise ValueError("Подпись раздела не может быть пустой")
            cleaned[normalized_item_id] = normalized_label
        return cleaned

    @model_validator(mode="after")
    def validate_layout_limits(self):
        group_ids = [group.id for group in self.groups]
        if len(set(group_ids)) != len(group_ids):
            raise ValueError("Идентификаторы кнопок меню не должны повторяться")

        references = sum(len(group.item_ids or []) for group in self.groups)
        references += sum(len(item_ids) for item_ids in self.items.values())
        if references > 256:
            raise ValueError("В раскладке слишком много ссылок на разделы")
        return self


class SidebarMenuImportRequest(BaseModel):
    """Версионированный безопасный envelope файла меню."""

    model_config = ConfigDict(extra="forbid", strict=True)

    format: Literal["dpms-sidebar-menu"]
    version: Literal[1]
    menu_schema_version: int | None = Field(default=None, strict=True, ge=1, le=100)
    exported_at: Annotated[str, Field(strict=True, min_length=1, max_length=40)] | None = None
    layout: SidebarMenuImportLayout

    @field_validator("exported_at")
    @classmethod
    def validate_exported_at(cls, value: str | None) -> str | None:
        if value is None:
            return None
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("Некорректная дата экспорта") from exc
        if parsed.tzinfo is None:
            raise ValueError("Дата экспорта должна содержать часовой пояс")
        return value

    @model_validator(mode="after")
    def validate_menu_schema_version(self):
        if (
            self.menu_schema_version is not None
            and self.menu_schema_version != self.layout.version
        ):
            raise ValueError("Версия схемы меню не совпадает с версией раскладки")
        return self


class SidebarMenuImportPreview(BaseModel):
    """Проекция импортированной раскладки без сохранения в профиль."""

    sidebar_menu_order: SidebarMenuImportLayout
    referenced_item_count: int = Field(..., ge=0)
    imported_count: int = Field(..., ge=0)
    skipped_unknown_count: int = Field(..., ge=0)
    skipped_inaccessible_count: int = Field(..., ge=0)
    skipped_duplicate_count: int = Field(..., ge=0)
    required_added_count: int = Field(..., ge=0)


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
