"""Read-only admin contract; clock and reason are deliberately unverified."""
from datetime import datetime, timezone
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def as_utc(value: datetime) -> datetime:
    # SQLite loses timezone metadata; all persisted timestamps are normalized UTC.
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


UTCDateTime = Annotated[datetime, AfterValidator(as_utc)]
ImportErrorCode = Literal[
    "directory_missing", "directory_unreadable", "scan_failed", "invalid_files", "conflicting_files",
    "too_many_files",
]


class ServerBootRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    source_id: str
    event_id: str
    boot_time: UTCDateTime
    recorded_at: UTCDateTime
    imported_at: UTCDateTime
    uptime_seconds: float = Field(ge=0, allow_inf_nan=False)
    reason: Literal["unknown"] = "unknown"
    clock: Literal["system_clock_not_independently_verified"] = "system_clock_not_independently_verified"


class ServerBootImportRead(BaseModel):
    state: Literal["waiting", "ok", "degraded", "stale"] = "waiting"
    last_attempt_at: UTCDateTime | None = None
    last_success_at: UTCDateTime | None = None
    invalid_files: int = Field(default=0, ge=0)
    conflicting_files: int = Field(default=0, ge=0)
    checked_files: int = Field(default=0, ge=0)
    error_code: ImportErrorCode | None = None


class ServerBootListRead(BaseModel):
    period_days: int
    total: int
    all_time_count: int
    last_7_days_count: int
    first_imported_at: UTCDateTime | None
    items: list[ServerBootRead]
    import_status: ServerBootImportRead
