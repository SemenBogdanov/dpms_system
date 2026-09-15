"""Native audit calendar; system-admin setup is separate from calendar ACL."""
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.audit_calendar import Command, ImportApply, ImportPreview, MemberSave, Setup
from app.services.audit_calendar import CalendarService
from app.services.audit_calendar_imports import CalendarImportService


router = APIRouter()
DB = Annotated[AsyncSession, Depends(get_db)]
Actor = Annotated[User, Depends(get_current_user)]


@router.get("/admin")
async def admin_state(db: DB, actor: Actor):
    return await CalendarService(db, actor).admin_state()


@router.post("/admin/setup")
async def setup(body: Setup, db: DB, actor: Actor):
    return await CalendarService(db, actor).setup(body)


@router.post("/admin/members")
async def members(body: MemberSave, db: DB, actor: Actor):
    return await CalendarService(db, actor).save_member(body)


@router.get("/state")
async def state(db: DB, actor: Actor, date_from: date = Query(alias="from"), date_to: date = Query(alias="to"),
                group: UUID | None = None, person: UUID | None = None, q: str = Query("", max_length=200)):
    return await CalendarService(db, actor).state(date_from, date_to, group_id=group, person_id=person, query=q)


@router.post("/commands")
async def command(body: Command, db: DB, actor: Actor):
    return await CalendarService(db, actor).command(body)


@router.get("/readiness")
async def readiness(db: DB, actor: Actor, date_from: date = Query(alias="from"), date_to: date = Query(alias="to"),
                    duration: int = Query(30, ge=30, le=480, multiple_of=30)):
    return await CalendarService(db, actor).readiness(date_from, date_to, duration)


@router.get("/availability-timeline")
async def availability_timeline(db: DB, actor: Actor,
                                timeline_date: str = Query(alias="date", min_length=10, max_length=10,
                                                           pattern=r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")):
    try:
        day = date.fromisoformat(timeline_date)
    except ValueError:
        raise HTTPException(422, "Укажите корректную дату в формате ГГГГ-ММ-ДД") from None
    return await CalendarService(db, actor).availability_timeline(day)


@router.get("/meeting-options")
async def meeting_options(db: DB, actor: Actor, meeting_date: date = Query(alias="date"),
                          start: int = Query(ge=0, le=1410, multiple_of=30),
                          duration: int = Query(ge=30, le=1440, multiple_of=30),
                          speaker_id: UUID | None = None, plan_id: UUID | None = None):
    return await CalendarService(db, actor).meeting_options(meeting_date, start, duration, speaker_id=speaker_id, plan_id=plan_id)


@router.get("/workload")
async def workload(db: DB, actor: Actor, date_from: date = Query(alias="from"), date_to: date = Query(alias="to"),
                   group: UUID | None = None):
    return await CalendarService(db, actor).workload(date_from, date_to, group_id=group)


@router.get("/meeting-windows")
async def meeting_windows(db: DB, actor: Actor, date_from: date = Query(alias="from"), date_to: date = Query(alias="to"),
                          duration: int = Query(30, ge=30, le=480, multiple_of=30), group: UUID | None = None,
                          speaker_id: UUID | None = None, full_day: bool = False):
    return await CalendarService(db, actor).meeting_windows(date_from, date_to, duration,
        group_id=group, speaker_id=speaker_id, full_day=full_day)


@router.get("/meeting-window-options")
async def meeting_window_options(db: DB, actor: Actor, meeting_date: date = Query(alias="date"),
                                 start: int = Query(ge=0, le=1410, multiple_of=30),
                                 duration: int = Query(30, ge=30, le=480, multiple_of=30),
                                 group: UUID | None = None, speaker_id: UUID | None = None):
    return await CalendarService(db, actor).meeting_window_options(meeting_date, start, duration,
        group_id=group, speaker_id=speaker_id)


@router.get("/history")
async def history(db: DB, actor: Actor, limit: int = Query(100, ge=1, le=1000)):
    return await CalendarService(db, actor).history(limit)


@router.get("/imports")
async def imports(db: DB, actor: Actor):
    return await CalendarImportService(db, actor).imports()


@router.post("/imports/preview")
async def preview(body: ImportPreview, db: DB, actor: Actor):
    return await CalendarImportService(db, actor).preview(body)


@router.post("/imports/{batch_id}/apply")
async def apply(batch_id: UUID, body: ImportApply, db: DB, actor: Actor):
    return await CalendarImportService(db, actor).apply(batch_id, body)
