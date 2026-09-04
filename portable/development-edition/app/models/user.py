"""Local users for the standalone Development Edition."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class League(str, enum.Enum):
    C = "C"
    B = "B"
    A = "A"


class UserRole(str, enum.Enum):
    executor = "executor"
    teamlead = "teamlead"
    admin = "admin"


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    league: Mapped[League] = mapped_column(Enum(League, native_enum=False), nullable=False, default=League.C)
    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, native_enum=False), nullable=False, default=UserRole.executor
    )
    mpw: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    wip_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    is_new_employee: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    task_workspace_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_link_queue_tasks_to_projects: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    feedback_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    audit_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    competency_development_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    competency_constructor_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    password_hash: Mapped[str] = mapped_column(String(512), nullable=False)
    auth_version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    password_change_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    @property
    def needs_password_change(self) -> bool:
        return self.password_change_required
