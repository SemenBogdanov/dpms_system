"""Minimal collection payload and admin-only usage report contract."""
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.services.sidebar_menu import CUSTOMIZABLE_SIDEBAR_ITEM_IDS


USAGE_SECTION_IDS = CUSTOMIZABLE_SIDEBAR_ITEM_IDS | {
    "settings", "profile", "admin-users", "admin-integrations",
}


class SectionViewCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: UUID
    section: str = Field(strict=True)

    @field_validator("section")
    @classmethod
    def known_section(cls, value: str) -> str:
        if value not in USAGE_SECTION_IDS:
            raise ValueError("Unknown usage section")
        return value


class UsageSectionRead(BaseModel):
    section: str
    label: str
    views: int
    users: int


class UsageUserRead(BaseModel):
    id: UUID
    name: str
    email: str
    logins: int


class UsageDailyRead(BaseModel):
    date: date
    logins: int
    section_views: int


class UsageLoginRead(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    email: str
    occurred_at: datetime
    device: str
    browser: str
    os: str


class UsageLoginsRead(BaseModel):
    total: int
    items: list[UsageLoginRead]


class UsageReportRead(BaseModel):
    start_date: date
    end_date: date
    timezone: Literal["Europe/Moscow"] = "Europe/Moscow"
    login_count: int
    login_users: int
    section_view_count: int
    section_users: int
    # Earliest retained records, not a guarantee of complete historical coverage.
    first_login_at: datetime | None
    first_section_view_at: datetime | None
    sections: list[UsageSectionRead]
    users: list[UsageUserRead]
    daily: list[UsageDailyRead]
    logins: UsageLoginsRead
