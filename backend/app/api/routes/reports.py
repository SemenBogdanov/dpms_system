"""API отчётов за период. Только admin/teamlead."""
from datetime import date
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.user import User
from app.schemas.activity import EmployeePeriodSummary
from app.schemas.reports import PeriodReport
from app.services.activity import generate_employee_period_summary
from app.services.reports import generate_period_report

router = APIRouter()


@router.get("/employee-summary", response_model=EmployeePeriodSummary)
async def get_employee_summary(
    user_id: UUID = Query(...),
    start_date: date = Query(...),
    end_date: date = Query(...),
    user: User = Depends(require_role("admin", "teamlead")),
    db: AsyncSession = Depends(get_db),
):
    """Сводка по сотруднику за дату или период."""
    if end_date < start_date:
        raise HTTPException(status_code=400, detail="Дата окончания не может быть раньше даты начала")
    try:
        return await generate_employee_period_summary(
            db,
            user_id=user_id,
            start_date=start_date,
            end_date=end_date,
        )
    except ValueError as exc:
        if str(exc) == "user_not_found":
            raise HTTPException(status_code=404, detail="Пользователь не найден")
        raise


@router.get("/{period}", response_model=PeriodReport)
async def get_period_report(
    period: str,
    user: User = Depends(require_role("admin", "teamlead")),
    db: AsyncSession = Depends(get_db),
):
    """Отчёт за период (YYYY-MM)."""
    return await generate_period_report(db, period)
