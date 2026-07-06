"""Schemas for reusable user contacts."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

ContactStatus = Literal["pending", "accepted", "rejected"]


class ContactCreate(BaseModel):
    """Invite a user to contacts by email."""

    email: str = Field(..., min_length=3, max_length=255)

    @field_validator("email", mode="before")
    @classmethod
    def clean_email(cls, value: str) -> str:
        return (value or "").strip().lower()


class ContactRead(BaseModel):
    """Read contact request/contact."""

    id: UUID
    requester_id: UUID
    recipient_id: UUID
    requester_name: str
    requester_email: str
    recipient_name: str
    recipient_email: str
    status: ContactStatus
    direction: Literal["incoming", "outgoing"]
    created_at: datetime
    updated_at: datetime
