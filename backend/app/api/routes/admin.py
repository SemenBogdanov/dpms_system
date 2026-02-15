"""API админки: закрытие периода, история периодов, оценка лиг. Все эндпоинты — только admin."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.user import User
from app.schemas.admin import RolloverRequest, RolloverResponse, PeriodSnapshotResponse
from app.schemas.leagues import LeagueEvaluation, LeagueChange, ApplyLeagueChangesRequest
from app.services.admin import rollover_period, get_period_history, get_period_details
from app.services.leagues import evaluate_league_change, apply_league_changes

router = APIRouter()


@router.post("/rollover-period", response_model=RolloverResponse)
async def rollover_period_route(
    body: RolloverRequest,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Закрыть предыдущий месяц: снимки, обнуление main, сгорание 50% кармы. Только admin."""
    admin_id = body.admin_id or user.id
    result = await rollover_period(db, admin_id)
    return RolloverResponse(**result)


@router.get("/period-history")
async def period_history(
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """История закрытых периодов (агрегаты по каждому периоду)."""
    return await get_period_history(db)


@router.get("/period-history/{period}", response_model=list[PeriodSnapshotResponse])
async def period_history_detail(
    period: str,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Детали периода: снимки по каждому сотруднику."""
    return await get_period_details(db, period)


@router.get("/league-evaluation", response_model=list[LeagueEvaluation])
async def league_evaluation_route(
    user_id: UUID | None = Query(None, description="Один пользователь или все"),
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Список всех пользователей с оценкой смены лиги. Опционально user_id — только один."""
    if user_id:
        ev = await evaluate_league_change(db, user_id)
        return [ev] if ev.full_name else []
    result = await db.execute(select(User).where(User.is_active.is_(True)))
    users = result.scalars().all()
    return [await evaluate_league_change(db, u.id) for u in users]


@router.post("/apply-league-changes", response_model=list[LeagueChange])
async def apply_league_changes_route(
    body: ApplyLeagueChangesRequest,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Применить изменения лиг. Только admin."""
    admin_id = body.admin_id or user.id
    return await apply_league_changes(db, admin_id)
