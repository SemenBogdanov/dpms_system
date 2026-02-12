"""Модель пользователя и enum Лиги/Роли."""
import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class League(str, enum.Enum):
    """Лига сотрудника (план в Q и права)."""
    C = "C"
    B = "B"
    A = "A"


class UserRole(str, enum.Enum):
    """Роль в системе."""
    executor = "executor"
    teamlead = "teamlead"
    admin = "admin"


class User(Base):
    """Сотрудник дата-офиса."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False, index=True)
    league: Mapped[League] = mapped_column(Enum(League), nullable=False)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), nullable=False)
    mpw: Mapped[int] = mapped_column(Integer, nullable=False, default=0)  # план на месяц в Q
    wip_limit: Mapped[int] = mapped_column(Integer, nullable=False, default=2)
    wallet_main: Mapped[Decimal] = mapped_column(Numeric(10, 1), nullable=False, default=Decimal("0"))
    wallet_karma: Mapped[Decimal] = mapped_column(Numeric(10, 1), nullable=False, default=Decimal("0"))
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    # Связи
    assigned_tasks = relationship("Task", back_populates="assignee", foreign_keys="Task.assignee_id")
    estimated_tasks = relationship("Task", back_populates="estimator", foreign_keys="Task.estimator_id")
    validated_tasks = relationship("Task", back_populates="validator", foreign_keys="Task.validator_id")
    transactions = relationship("QTransaction", back_populates="user")
