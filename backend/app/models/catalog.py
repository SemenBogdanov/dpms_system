"""Модель справочника операций (каталог)."""
import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, Numeric, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base
from app.models.user import League


class CatalogCategory(str, enum.Enum):
    """Категория операции."""
    widget = "widget"
    etl = "etl"
    api = "api"
    docs = "docs"
    proactive = "proactive"


class Complexity(str, enum.Enum):
    """Уровень сложности."""
    S = "S"
    M = "M"
    L = "L"
    XL = "XL"


class CatalogItem(Base):
    """Позиция справочника операций («меню» калькулятора)."""

    __tablename__ = "catalog_items"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    category: Mapped[CatalogCategory] = mapped_column(Enum(CatalogCategory), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    complexity: Mapped[Complexity] = mapped_column(Enum(Complexity), nullable=False)
    base_cost_q: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    min_league: Mapped[League] = mapped_column(Enum(League), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
