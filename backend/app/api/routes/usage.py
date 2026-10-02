"""Authenticated section capture and strictly system-admin usage reports."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from slowapi import Limiter
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_role
from app.models.user import User
from app.schemas.usage import SectionViewCreate, UsageReportRead
from app.services.usage import MAX_OFFSET, get_usage_report, record_section_view


router = APIRouter()
admin_router = APIRouter(dependencies=[Depends(require_role("admin"))])


async def _usage_actor(request: Request, user: User = Depends(get_current_user)) -> User:
    request.state.usage_actor_id = str(user.id)
    return user


def _actor_rate_key(request: Request) -> str:
    # FastAPI resolves _usage_actor before the slowapi endpoint wrapper runs.
    return request.state.usage_actor_id


# Process-local like the existing app limiter; users behind one proxy do not share a bucket.
limiter = Limiter(key_func=_actor_rate_key)


@router.post("/section-views", status_code=204)
@limiter.limit("120/minute")
async def capture_section_view(
    payload: SectionViewCreate,
    request: Request,
    user: User = Depends(_usage_actor),
    db: AsyncSession = Depends(get_db),
):
    await record_section_view(db, user, payload)
    return Response(status_code=204)


@admin_router.get("", response_model=UsageReportRead)
async def usage_report(
    start_date: date = Query(...),
    end_date: date = Query(...),
    user_id: UUID | None = Query(None),
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0, le=MAX_OFFSET),
    db: AsyncSession = Depends(get_db),
):
    try:
        return await get_usage_report(
            db, start_date=start_date, end_date=end_date,
            user_id=user_id, limit=limit, offset=offset,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
