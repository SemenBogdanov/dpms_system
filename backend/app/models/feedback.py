"""Feedback/change request model."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


class FeedbackCategory(str, enum.Enum):
    """Feedback request category."""

    improvement = "improvement"
    disagreement = "disagreement"
    bug = "bug"
    process = "process"
    other = "other"


class FeedbackStatus(str, enum.Enum):
    """Feedback request workflow status."""

    new = "new"
    in_review = "in_review"
    triage = "triage"
    needs_info = "needs_info"
    accepted = "accepted"
    planned = "planned"
    rejected = "rejected"
    done = "done"
    withdrawn = "withdrawn"


class FeedbackObjectType(str, enum.Enum):
    """What the feedback request refers to."""

    task = "task"
    shop = "shop"
    report = "report"
    rule = "rule"
    kb = "kb"
    other = "other"


class FeedbackPriority(str, enum.Enum):
    """Feedback request priority."""

    low = "low"
    medium = "medium"
    high = "high"


class FeedbackRequest(Base):
    """Formal employee feedback or change request."""

    __tablename__ = "feedback_requests"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    feedback_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        unique=True,
        index=True,
        server_default=text("nextval('feedback_request_number_seq'::regclass)"),
    )
    author_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
        index=True,
    )
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    category: Mapped[FeedbackCategory] = mapped_column(
        Enum(FeedbackCategory, name="feedbackcategory"),
        nullable=False,
        default=FeedbackCategory.improvement,
        index=True,
    )
    status: Mapped[FeedbackStatus] = mapped_column(
        Enum(FeedbackStatus, name="feedbackstatus"),
        nullable=False,
        default=FeedbackStatus.new,
        index=True,
    )
    priority: Mapped[FeedbackPriority] = mapped_column(
        Enum(FeedbackPriority, name="feedbackpriority"),
        nullable=False,
        default=FeedbackPriority.medium,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    object_type: Mapped[FeedbackObjectType] = mapped_column(
        Enum(FeedbackObjectType, name="feedbackobjecttype"),
        nullable=False,
        default=FeedbackObjectType.other,
        index=True,
    )
    object_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    expected_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    impact: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_links: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_action: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_release: Mapped[str | None] = mapped_column(String(64), nullable=True)
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=True,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    author = relationship("User", foreign_keys=[author_id])
    reviewer = relationship("User", foreign_keys=[reviewer_id])
    decided_by = relationship("User", foreign_keys=[decided_by_id])
