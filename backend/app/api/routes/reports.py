"""API отчётов за период. Только admin/teamlead."""
from fastapi import APIRouter, Depends

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.user import User
from app.schemas.reports import PeriodReport
from app.services.reports import generate_period_report

router = APIRouter()


@router.get("/{period}", response_model=PeriodReport)
async def get_period_report(
    period: str,
    user: User = Depends(require_role("admin", "teamlead")),
    db: AsyncSession = Depends(get_db),
):
    """Отчёт за период (YYYY-MM)."""
    return await generate_period_report(db, period)
