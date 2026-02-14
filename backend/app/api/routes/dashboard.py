"""API дашборда: Стакан, сводка по команде, план/факт, периодическая статистика."""
from fastapi import APIRouter, Depends, Query

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.dashboard import CapacityGauge, TeamSummary, PeriodStats, BurndownData
from app.schemas.calibration import CalibrationReport
from app.services.analytics import (
    get_capacity_gauge,
    get_team_summary,
    get_period_stats,
    get_burndown_data,
)
from app.services.calibration import get_calibration_report

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
    """Сводка по команде (по лигам, earned vs target, in_progress_q, is_at_risk)."""
    return await get_team_summary(db)


@router.get("/plan-fact", response_model=TeamSummary)
async def plan_fact(
    db: AsyncSession = Depends(get_db),
):
    """План/факт по сотрудникам (то же что team-summary)."""
    return await get_team_summary(db)


@router.get("/period-stats", response_model=PeriodStats)
async def period_stats(
    db: AsyncSession = Depends(get_db),
):
    """Статистика текущего месяца для дашборда руководителя."""
    return await get_period_stats(db)


@router.get("/burndown", response_model=BurndownData)
async def burndown(
    db: AsyncSession = Depends(get_db),
):
    """Данные для графика burn-down текущего месяца."""
    return await get_burndown_data(db)


@router.get("/calibration", response_model=CalibrationReport)
async def calibration(
    period: str | None = Query(None, description="YYYY-MM или all"),
    db: AsyncSession = Depends(get_db),
):
    """Калибровочный отчёт: сравнение оценки и факта по операциям."""
    return await get_calibration_report(db, period=period)
