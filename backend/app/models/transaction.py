"""Журнал начислений Q (immutable log)."""
import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class WalletType(str, enum.Enum):
    """Тип кошелька."""
    main = "main"
    karma = "karma"


class QTransaction(Base):
    """Запись в журнале начислений/списаний Q. Только INSERT, без UPDATE/DELETE."""

    __tablename__ = "q_transactions"

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
    amount: Mapped[Decimal] = mapped_column(Numeric(5, 1), nullable=False)
    wallet_type: Mapped[WalletType] = mapped_column(Enum(WalletType), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    user = relationship("User", back_populates="transactions")
    task = relationship("Task", back_populates="transactions")
