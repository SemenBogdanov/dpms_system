"""API дашборда: Стакан, сводка по команде, план/факт."""
from fastapi import APIRouter, Depends

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.dashboard import CapacityGauge, TeamSummary
from app.services.analytics import get_capacity_gauge, get_team_summary

router = APIRouter()


@router.get("/capacity", response_model=CapacityGauge)
async def capacity(
    db: AsyncSession = Depends(get_db),
):
    """Метрика «Стакан»: загрузка vs ёмкость команды."""
    return await get_capacity_gauge(db)


@router.get("/team-summary", response_model=TeamSummary)
async def team_summary(
    db: AsyncSession = Depends(get_db),
):
    """Сводка по команде (по лигам, earned vs target)."""
    return await get_team_summary(db)


@router.get("/plan-fact", response_model=TeamSummary)
async def plan_fact(
    db: AsyncSession = Depends(get_db),
):
    """План/факт по сотрудникам (то же что team-summary)."""
    return await get_team_summary(db)
