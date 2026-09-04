"""Local user schemas compatible with the Development frontend."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.user import League, UserRole


class UserRead(BaseModel):
    id: UUID
    full_name: str
    email: EmailStr
    league: League
    role: UserRole
    mpw: int = 0
    wip_limit: int = 2
    wallet_main: float = 0
    wallet_karma: float = 0
    quality_score: float = 100
    is_active: bool
    is_new_employee: bool = False
    task_workspace_enabled: bool = False
    can_link_queue_tasks_to_projects: bool = False
    feedback_enabled: bool = False
    audit_enabled: bool = False
    competency_development_enabled: bool = True
    competency_constructor_enabled: bool = False
    plan_started_at: datetime | None = None
    onboarding_started_at: datetime | None = None
    onboarding_until: datetime | None = None
    sidebar_menu_order: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AuthenticatedUserRead(UserRead):
    needs_password_change: bool = False


class UserCreate(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=10, max_length=128)
    role: UserRole = UserRole.executor
    competency_constructor_enabled: bool = False

    @field_validator("full_name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        return value.strip()


class UserUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=2, max_length=255)
    email: EmailStr | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    competency_constructor_enabled: bool | None = None


class SetupAdminRequest(BaseModel):
    full_name: str = Field(..., min_length=2, max_length=255)
    email: EmailStr
    password: str = Field(..., min_length=10, max_length=128)


class SetupStatus(BaseModel):
    setup_required: bool
    catalog_competencies: int
    catalog_questions: int
