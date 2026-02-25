"""Модель задачи и enum статуса/типа."""
import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base
from app.models.user import League
from app.models.catalog import CatalogCategory, Complexity


class TaskType(str, enum.Enum):
    """Тип задачи (совпадает с категорией каталога)."""
    widget = "widget"
    etl = "etl"
    api = "api"
    docs = "docs"
    proactive = "proactive"
    bugfix = "bugfix"


class TaskStatus(str, enum.Enum):
    """Статус задачи в жизненном цикле."""
    new = "new"
    estimated = "estimated"
    in_queue = "in_queue"
    in_progress = "in_progress"
    review = "review"
    done = "done"
    cancelled = "cancelled"


class TaskPriority(str, enum.Enum):
    """Приоритет задачи."""
    low = "low"
    medium = "medium"
    high = "high"
    critical = "critical"


class Task(Base):
    """Задача в глобальной очереди."""

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    task_type: Mapped[TaskType] = mapped_column(Enum(TaskType), nullable=False)
    complexity: Mapped[Complexity] = mapped_column(Enum(Complexity), nullable=False)
    estimated_q: Mapped[Decimal] = mapped_column(
        Numeric(5, 1),
        nullable=False,
        default=Decimal("0"),
    )
    priority: Mapped[TaskPriority] = mapped_column(
        Enum(TaskPriority),
        nullable=False,
        default=TaskPriority.medium,
    )
    status: Mapped[TaskStatus] = mapped_column(
        Enum(TaskStatus),
        nullable=False,
        default=TaskStatus.new,
    )
    min_league: Mapped[League] = mapped_column(Enum(League), nullable=False)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    assigned_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    estimator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    validator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    estimation_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    rejection_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    rejection_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    validated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    focus_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    active_seconds: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    is_proactive: Mapped[bool] = mapped_column(Boolean, default=False)
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    sla_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_overdue: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    parent_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id"),
        nullable=True,
    )
    tags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    assignee = relationship("User", back_populates="assigned_tasks", foreign_keys=[assignee_id])
    assigned_by = relationship("User", foreign_keys=[assigned_by_id])
    estimator = relationship("User", back_populates="estimated_tasks", foreign_keys=[estimator_id])
    validator = relationship("User", back_populates="validated_tasks", foreign_keys=[validator_id])
    transactions = relationship("QTransaction", back_populates="task")

    @property
    def deadline_zone(self) -> str | None:
        """Вычисляемая зона дедлайна для сериализации в API."""
        if self.due_date is None:
            return None
        now = datetime.now(timezone.utc)
        if now > self.due_date:
            return "red"
        if self.started_at:
            total = (self.due_date - self.started_at).total_seconds()
            remaining = (self.due_date - now).total_seconds()
            if total > 0 and remaining / total <= 0.5:
                return "yellow"
        return "green"
