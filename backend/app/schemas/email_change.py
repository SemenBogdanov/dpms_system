"""Schemas for verified changes of the email login."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


EmailChangeKind = Literal["self", "admin_assisted"]
EmailChangeStatus = Literal[
    "pending",
    "confirmed",
    "cancelled",
    "expired",
    "superseded",
]


class EmailChangeSelfRequest(BaseModel):
    new_email: EmailStr
    current_password: str = Field(..., min_length=1, max_length=128)


class EmailChangeAdminRequest(BaseModel):
    new_email: EmailStr
    reason: str = Field(..., min_length=3, max_length=500)


class EmailChangeTokenRequest(BaseModel):
    token: str = Field(..., min_length=20, max_length=2048)


class EmailChangeRequestRead(BaseModel):
    id: UUID
    user_id: UUID
    requested_by_id: UUID | None
    request_kind: EmailChangeKind
    old_email: str
    new_email: str
    status: EmailChangeStatus
    reason: str | None
    expires_at: datetime
    confirmed_at: datetime | None
    cancelled_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class EmailChangePendingRead(BaseModel):
    request: EmailChangeRequestRead | None


class EmailChangeActionResult(BaseModel):
    message: str
    reauth_required: bool = False
