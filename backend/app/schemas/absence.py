"""Schemas for user absences."""
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.models.absence import AbsenceType


class AbsenceBase(BaseModel):
    user_id: UUID
    start_date: date
    end_date: date
    type: AbsenceType = AbsenceType.vacation
    affects_plan: bool = True
    comment: str | None = Field(None, max_length=1000)

    @model_validator(mode="after")
    def validate_dates(self) -> "AbsenceBase":
        if self.end_date < self.start_date:
            raise ValueError("Дата окончания не может быть раньше даты начала")
        return self


class AbsenceCreate(AbsenceBase):
    pass


class AbsenceUpdate(BaseModel):
    user_id: UUID | None = None
    start_date: date | None = None
    end_date: date | None = None
    type: AbsenceType | None = None
    affects_plan: bool | None = None
    comment: str | None = Field(None, max_length=1000)


class AbsenceRead(BaseModel):
    id: UUID
    user_id: UUID
    user_name: str
    user_email: str
    start_date: date
    end_date: date
    type: AbsenceType
    affects_plan: bool
    comment: str | None = None
    source: str
    working_days: int
    created_by_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class AbsenceSummary(BaseModel):
    period: str
    total_absence_days: int
    active_absences_today: int
