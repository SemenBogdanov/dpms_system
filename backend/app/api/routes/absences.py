"""API for employee absences and capacity calendar."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.user import User
from app.schemas.absence import AbsenceCreate, AbsenceRead, AbsenceUpdate, HolidayCreate, HolidayRead, HolidayUpdate
from app.services.absences import (
    create_absence,
    create_holiday,
    delete_absence,
    delete_holiday,
    list_absences,
    list_holidays,
    update_absence,
    update_holiday,
)

router = APIRouter()


@router.get("", response_model=list[AbsenceRead])
async def get_absences(
    date_from: date = Query(..., alias="from"),
    date_to: date = Query(..., alias="to"),
    user_id: UUID | None = Query(None),
    _: User = Depends(require_role("admin", "teamlead")),
    db: AsyncSession = Depends(get_db),
):
    """Calendar/list of absences. Admin and teamlead can view."""
    return await list_absences(db, date_from, date_to, user_id)


@router.post("", response_model=AbsenceRead)
async def post_absence(
    body: AbsenceCreate,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Create absence manually. Admin only."""
    return await create_absence(db, body, admin)


@router.get("/holidays", response_model=list[HolidayRead])
async def get_holidays(
    date_from: date = Query(..., alias="from"),
    date_to: date = Query(..., alias="to"),
    _: User = Depends(require_role("admin", "teamlead")),
    db: AsyncSession = Depends(get_db),
):
    """Global non-working days that reduce plan for everyone."""
    return await list_holidays(db, date_from, date_to)


@router.post("/holidays", response_model=HolidayRead)
async def post_holiday(
    body: HolidayCreate,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Create a global holiday. Admin only."""
    return await create_holiday(db, body, admin)


@router.patch("/holidays/{holiday_id}", response_model=HolidayRead)
async def patch_holiday(
    holiday_id: UUID,
    body: HolidayUpdate,
    _: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Update a global holiday. Admin only."""
    return await update_holiday(db, holiday_id, body)


@router.delete("/holidays/{holiday_id}", status_code=204)
async def remove_holiday(
    holiday_id: UUID,
    _: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Delete a global holiday. Admin only."""
    await delete_holiday(db, holiday_id)
    return Response(status_code=204)


@router.patch("/{absence_id}", response_model=AbsenceRead)
async def patch_absence(
    absence_id: UUID,
    body: AbsenceUpdate,
    _: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Update manual absence. Admin only."""
    return await update_absence(db, absence_id, body)


@router.delete("/{absence_id}", status_code=204)
async def remove_absence(
    absence_id: UUID,
    _: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Delete absence. Admin only."""
    await delete_absence(db, absence_id)
    return Response(status_code=204)
