"""Native audit calendar; system-admin setup is separate from calendar ACL."""
from datetime import date
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query
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
