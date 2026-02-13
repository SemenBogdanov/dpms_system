"""API админки: закрытие периода, история периодов."""
from fastapi import APIRouter, Depends

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.admin import RolloverRequest, RolloverResponse, PeriodSnapshotResponse
from app.services.admin import rollover_period, get_period_history, get_period_details

router = APIRouter()


@router.post("/rollover-period", response_model=RolloverResponse)
async def rollover_period_route(
    body: RolloverRequest,
    db: AsyncSession = Depends(get_db),
):
    """Закрыть предыдущий месяц: снимки, обнуление main, сгорание 50% кармы. Только admin."""
    result = await rollover_period(db, body.admin_id)
    return RolloverResponse(**result)


@router.get("/period-history")
async def period_history(db: AsyncSession = Depends(get_db)):
    """История закрытых периодов (агрегаты по каждому периоду)."""
    return await get_period_history(db)


@router.get("/period-history/{period}", response_model=list[PeriodSnapshotResponse])
async def period_history_detail(
    period: str,
    db: AsyncSession = Depends(get_db),
):
    """Детали периода: снимки по каждому сотруднику."""
    return await get_period_details(db, period)
