"""API калькулятора оценки и создание задачи из расчёта."""
from fastapi import APIRouter, Depends

from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.schemas.calculator import (
    EstimateRequest,
    EstimateResponse,
    CreateTaskFromCalcRequest,
)
from app.schemas.task import TaskRead
from app.services.calculator import calculate_estimate, create_task_from_calc

router = APIRouter()


@router.post("/estimate", response_model=EstimateResponse)
async def estimate(
    body: EstimateRequest,
    db: AsyncSession = Depends(get_db),
):
    """Рассчитать стоимость задачи по выбранным позициям каталога."""
    return await calculate_estimate(db, body)


@router.post("/create-task", response_model=TaskRead)
async def create_task(
    body: CreateTaskFromCalcRequest,
    db: AsyncSession = Depends(get_db),
):
    """Создать задачу из калькулятора и отправить в очередь (in_queue)."""
    task = await create_task_from_calc(db, body)
    return task