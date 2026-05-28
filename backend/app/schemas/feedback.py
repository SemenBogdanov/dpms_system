"""Schemas for feedback/change requests."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.feedback import FeedbackCategory, FeedbackPriority, FeedbackStatus


class FeedbackRequestCreate(BaseModel):
    """Create feedback request."""

    category: FeedbackCategory = FeedbackCategory.improvement
    priority: FeedbackPriority = FeedbackPriority.medium
    title: str = Field(..., min_length=3, max_length=255)
    description: str = Field(..., min_length=5)


class FeedbackRequestUpdate(BaseModel):
    """Manager update for feedback request."""

    status: FeedbackStatus | None = None
    reviewer_id: UUID | None = None
    priority: FeedbackPriority | None = None
    resolution: str | None = None


class FeedbackRequestRead(BaseModel):
    """Feedback request read model."""

    id: UUID
    author_id: UUID
    author_name: str
    reviewer_id: UUID | None = None
    reviewer_name: str | None = None
    category: FeedbackCategory
    status: FeedbackStatus
    priority: FeedbackPriority
    title: str
    description: str
    resolution: str | None = None
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None = None
    closed_at: datetime | None = None


class FeedbackRequestListResponse(BaseModel):
    """List with total count."""

    items: list[FeedbackRequestRead]
    total: int
    limit: int
