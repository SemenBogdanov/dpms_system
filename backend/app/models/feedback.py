"""Feedback/change request model."""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
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
    accepted = "accepted"
    rejected = "rejected"
    done = "done"


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
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    author = relationship("User", foreign_keys=[author_id])
    reviewer = relationship("User", foreign_keys=[reviewer_id])
