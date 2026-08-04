"""API админки: закрытие периода, история периодов, оценка лиг. Все эндпоинты — только admin."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.user import User
from app.schemas.admin import (
    PeriodSnapshotResponse,
    RolloverRequest,
    RolloverResponse,
)
from app.schemas.leagues import LeagueEvaluation, LeagueChange
from app.services.admin import (
    auto_close_previous_period,
    cancel_period_closure,
    get_period_details,
    get_period_history,
    rollover_period,
)
from app.services.leagues import evaluate_league_change, apply_league_changes

router = APIRouter()


@router.post("/rollover-period", response_model=RolloverResponse)
async def rollover_period_route(
    body: RolloverRequest,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Закрыть выбранный период: снимки, списание базового плана, перенос сверхплана и karma."""
    result = await rollover_period(db, user.id, period=body.period, mode=body.mode)
    return RolloverResponse(**result)


@router.post("/period-close/auto", response_model=RolloverResponse)
async def auto_close_previous_period_route(
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Автоматически закрыть предыдущий месяц, если он еще открыт."""
    result = await auto_close_previous_period(db, user.id)
    return RolloverResponse(**result)


@router.post("/period-history/{period}/cancel", response_model=RolloverResponse)
async def cancel_period_closure_route(
    period: str,
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Отменить закрытие периода и восстановить списанные по базовому плану баллы."""
    result = await cancel_period_closure(db, user.id, period)
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
    user: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Применить изменения лиг. Только admin."""
    return await apply_league_changes(db, user.id)
