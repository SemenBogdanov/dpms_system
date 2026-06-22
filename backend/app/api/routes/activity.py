"""Activity/audit log API. Only admin/teamlead."""
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_task_workspace_role
from app.models.user import User
from app.schemas.activity import ActivityEventListResponse
from app.services.activity import list_activity_events

router = APIRouter()


def _start_of_day(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value, time.min, tzinfo=timezone.utc)


def _end_exclusive(value: date | None) -> datetime | None:
    if value is None:
        return None
    return datetime.combine(value + timedelta(days=1), time.min, tzinfo=timezone.utc)


@router.get("", response_model=ActivityEventListResponse)
async def activity_events(
    user_id: UUID | None = Query(None),
    start_date: date | None = Query(None),
    end_date: date | None = Query(None),
    event_type: str | None = Query(None),
    limit: int = Query(200, ge=1, le=500),
    user: User = Depends(require_task_workspace_role("admin", "teamlead")),
    db: AsyncSession = Depends(get_db),
):
    """Журнал активности с фильтрами по сотруднику, периоду и типу события."""
    if start_date and end_date and end_date < start_date:
        raise HTTPException(status_code=400, detail="Дата окончания не может быть раньше даты начала")
    return await list_activity_events(
        db,
        user_id=user_id,
        start=_start_of_day(start_date),
        end=_end_exclusive(end_date),
        event_type=event_type,
        limit=limit,
    )
