"""Модель задачи и enum статуса/типа."""
import enum
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, CheckConstraint, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint, text
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


class TaskReviewEventType(str, enum.Enum):
    """Тип события приемочного цикла задачи."""
    submitted = "submitted"
    returned = "returned"
    accepted = "accepted"


class Task(Base):
    """Задача в глобальной очереди."""

    __tablename__ = "tasks"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        unique=True,
        server_default=text("nextval('tasks_task_number_seq'::regclass)"),
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
    acceptance_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    acceptance_mode: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="full",
    )
    acceptance_state: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="none",
    )
    acceptance_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    acceptance_total_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    acceptance_required_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    acceptance_accepted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    acceptance_required_accepted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    acceptance_submitted_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    acceptance_returned_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    validator_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
    )
    estimation_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    result_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    brief_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    brief_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
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
    acceptance_owner = relationship("User", foreign_keys=[acceptance_owner_id])
    validator = relationship("User", back_populates="validated_tasks", foreign_keys=[validator_id])
    transactions = relationship("QTransaction", back_populates="task")
    attachments = relationship(
        "TaskAttachment",
        back_populates="task",
        cascade="all, delete-orphan",
    )
    acceptance_criteria = relationship(
        "TaskAcceptanceCriterion",
        back_populates="task",
        cascade="all, delete-orphan",
        order_by="TaskAcceptanceCriterion.position",
    )

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


class TaskReviewEvent(Base):
    """Событие приемочного цикла задачи."""
    __tablename__ = "task_review_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[TaskReviewEventType] = mapped_column(Enum(TaskReviewEventType), nullable=False, index=True)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    result_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    brief_rating: Mapped[int | None] = mapped_column(Integer, nullable=True)
    brief_feedback: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)


class TaskAcceptanceCriterion(Base):
    """One verifiable condition in a task acceptance plan."""

    __tablename__ = "task_acceptance_criteria"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('required', 'optional', 'quality_gate')",
            name="ck_task_acceptance_criteria_kind",
        ),
        CheckConstraint(
            "status IN ('pending', 'submitted', 'accepted', 'returned', 'not_applicable')",
            name="ck_task_acceptance_criteria_status",
        ),
        UniqueConstraint("task_id", "position", name="uq_task_acceptance_criteria_task_position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False, default="required")
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="pending", index=True)
    baseline_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    evidence_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    reviewer_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    submitted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reviewed_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    return_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )

    task = relationship("Task", back_populates="acceptance_criteria")
    events = relationship(
        "TaskAcceptanceCriterionEvent",
        back_populates="criterion",
        cascade="all, delete-orphan",
    )


class TaskAcceptanceCriterionEvent(Base):
    """Append-only audit event for one acceptance criterion."""

    __tablename__ = "task_acceptance_criterion_events"
    __table_args__ = (
        CheckConstraint(
            "event_type IN ('submitted', 'accepted', 'returned', 'not_applicable')",
            name="ck_task_acceptance_criterion_events_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    criterion_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("task_acceptance_criteria.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    from_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    acceptance_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)

    criterion = relationship("TaskAcceptanceCriterion", back_populates="events")
