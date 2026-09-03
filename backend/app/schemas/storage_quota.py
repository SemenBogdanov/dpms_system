"""API schemas for personal file storage quotas."""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


StorageQuotaWarningLevel = Literal["normal", "warning", "critical", "blocked"]
StorageQuotaRequestStatus = Literal["pending", "approved", "rejected", "cancelled"]


class StorageQuotaRequestCreate(BaseModel):
    requested_limit_bytes: int = Field(..., gt=0, le=10 * 1024 * 1024 * 1024)
    reason: str = Field(..., min_length=10, max_length=1000)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 10:
            raise ValueError("Опишите причину минимум в 10 символах")
        return value


class StorageQuotaRequestRead(BaseModel):
    id: UUID
    user_id: UUID
    current_limit_bytes: int
    requested_limit_bytes: int
    approved_limit_bytes: int | None
    reason: str
    status: StorageQuotaRequestStatus
    decision_comment: str | None
    decided_by_id: UUID | None
    decided_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class StorageQuotaSummaryRead(BaseModel):
    quota_bytes: int
    used_bytes: int
    reserved_bytes: int
    available_bytes: int
    usage_percent: float
    warning_level: StorageQuotaWarningLevel
    warning_message: str
    pending_request: StorageQuotaRequestRead | None


class StorageQuotaRequestDecision(BaseModel):
    decision: Literal["approved", "rejected"]
    comment: str = Field(..., min_length=3, max_length=1000)
    approved_limit_bytes: int | None = Field(
        None,
        gt=0,
        le=10 * 1024 * 1024 * 1024,
    )

    @field_validator("comment")
    @classmethod
    def validate_comment(cls, value: str) -> str:
        value = value.strip()
        if len(value) < 3:
            raise ValueError("Комментарий должен содержать минимум 3 символа")
        return value

    @model_validator(mode="after")
    def validate_approved_limit(self):
        if self.decision == "rejected" and self.approved_limit_bytes is not None:
            raise ValueError("Для отказа не указывают новый лимит")
        return self


class AdminStorageQuotaRequestRead(StorageQuotaRequestRead):
    user_name: str
    user_email: str
    used_bytes: int
    reserved_bytes: int
