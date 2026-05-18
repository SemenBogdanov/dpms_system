"""Модели магазина бонусов и снимков периода."""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, Numeric, String, Text, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


class ShopItem(Base):
    """Товар в магазине бонусов."""
    __tablename__ = "shop_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    cost_q: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    category: Mapped[str] = mapped_column(String(50), default="perk")
    icon: Mapped[str] = mapped_column(String(50), default="🎁")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    max_per_month: Mapped[int] = mapped_column(Integer, default=1)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())


class Purchase(Base):
    """Журнал покупок в магазине."""
    __tablename__ = "purchases"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    shop_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("shop_items.id"),
        nullable=False,
    )
    cost_q: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )


class PeriodSnapshot(Base):
    """Снимок показателей сотрудника за завершённый период."""
    __tablename__ = "period_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    mpw: Mapped[Decimal] = mapped_column(Numeric(10, 1), nullable=False)
    earned_main: Mapped[Decimal] = mapped_column(Numeric(10, 1), nullable=False)
    earned_karma: Mapped[Decimal] = mapped_column(Numeric(10, 1), nullable=False)
    tasks_completed: Mapped[int] = mapped_column(Integer, default=0)
    league: Mapped[str] = mapped_column(String(1), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=func.now())
