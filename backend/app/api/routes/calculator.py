"""API калькулятора оценки."""
from fastapi import APIRouter, Depends

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.calculator import CalculatorRequest, CalculatorResponse
from app.services.calculator import calculate_estimate

router = APIRouter()


@router.post("/estimate", response_model=CalculatorResponse)
async def estimate(
    body: CalculatorRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Рассчитать стоимость задачи по выбранным позициям каталога.
    Возвращает total_q, breakdown, min_league.
    """
    return await calculate_estimate(db, body)
