"""Schemas for feedback/change requests."""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.feedback import FeedbackCategory, FeedbackObjectType, FeedbackPriority, FeedbackStatus


def _clean_optional(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned or None


class FeedbackRequestCreate(BaseModel):
    """Create feedback request."""

    category: FeedbackCategory = FeedbackCategory.improvement
    priority: FeedbackPriority = FeedbackPriority.medium
    title: str = Field(..., min_length=3, max_length=255)
    description: str = Field(..., min_length=5)
    object_type: FeedbackObjectType = FeedbackObjectType.other
    object_ref: str | None = Field(None, max_length=255)
    expected_result: str | None = None
    impact: str | None = None
    evidence_links: list[str] = Field(default_factory=list, max_length=10)

    @field_validator("object_ref", "expected_result", "impact", mode="before")
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @field_validator("evidence_links")
    @classmethod
    def clean_links(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for link in value:
            item = link.strip()
            if item and item not in cleaned:
                cleaned.append(item[:500])
        return cleaned[:10]


class FeedbackRequestUpdate(BaseModel):
    """Manager update for feedback request."""

    status: FeedbackStatus | None = None
    reviewer_id: UUID | None = None
    priority: FeedbackPriority | None = None
    resolution: str | None = None
    object_type: FeedbackObjectType | None = None
    object_ref: str | None = Field(None, max_length=255)
    expected_result: str | None = None
    impact: str | None = None
    evidence_links: list[str] | None = Field(None, max_length=10)
    decision_summary: str | None = None
    decision_reason: str | None = None
    next_action: str | None = None
    target_release: str | None = Field(None, max_length=64)

    @field_validator(
        "resolution",
        "object_ref",
        "expected_result",
        "impact",
        "decision_summary",
        "decision_reason",
        "next_action",
        "target_release",
        mode="before",
    )
    @classmethod
    def clean_optional_text(cls, value: str | None) -> str | None:
        return _clean_optional(value)

    @field_validator("evidence_links")
    @classmethod
    def clean_links(cls, value: list[str] | None) -> list[str] | None:
        if value is None:
            return None
        cleaned: list[str] = []
        for link in value:
            item = link.strip()
            if item and item not in cleaned:
                cleaned.append(item[:500])
        return cleaned[:10]


class FeedbackRequestRead(BaseModel):
    """Feedback request read model."""

    id: UUID
    feedback_number: int
    feedback_code: str
    author_id: UUID
    author_name: str
    reviewer_id: UUID | None = None
    reviewer_name: str | None = None
    decided_by_id: UUID | None = None
    decided_by_name: str | None = None
    category: FeedbackCategory
    status: FeedbackStatus
    priority: FeedbackPriority
    title: str
    description: str
    object_type: FeedbackObjectType
    object_ref: str | None = None
    expected_result: str | None = None
    impact: str | None = None
    evidence_links: list[str] = Field(default_factory=list)
    resolution: str | None = None
    decision_summary: str | None = None
    decision_reason: str | None = None
    next_action: str | None = None
    target_release: str | None = None
    created_at: datetime
    updated_at: datetime
    reviewed_at: datetime | None = None
    closed_at: datetime | None = None
    decided_at: datetime | None = None


class FeedbackRequestListResponse(BaseModel):
    """List with total count."""

    items: list[FeedbackRequestRead]
    total: int
    limit: int
