"""Логика расчёта Q по каталогу и создание задачи из калькулятора."""
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import CatalogItem, CatalogCategory, Complexity
from app.models.task import Task, TaskStatus, TaskType, TaskPriority
from app.models.user import League
from app.schemas.calculator import (
    EstimateRequest,
    EstimateResponse,
    EstimateBreakdownItem,
    CreateTaskFromCalcRequest,
)

_LEAGUE_ORDER = {League.C: 0, League.B: 1, League.A: 2}
_COMPLEXITY_ORDER = {Complexity.S: 0, Complexity.M: 1, Complexity.L: 2, Complexity.XL: 3}


async def calculate_estimate(
    db: AsyncSession,
    request: EstimateRequest,
) -> EstimateResponse:
    """
        Рассчитать стоимость задачи по выбранным позициям каталога.
        total_q = round(Σ(subtotal_q), 1).
    """
    if not request.items:
        return EstimateResponse(
            total_q=0.0,
            min_league="C",
            breakdown=[],
        )

    catalog_ids = [item.catalog_id for item in request.items]
    result = await db.execute(
        select(CatalogItem).where(
            CatalogItem.id.in_(catalog_ids),
            CatalogItem.is_active.is_(True),
        )
    )
    catalog_by_id = {row.id: row for row in result.scalars().all()}

    breakdown: list[EstimateBreakdownItem] = []
    raw_total = 0.0
    max_league = League.C

    for item in request.items:
        catalog_item = catalog_by_id.get(item.catalog_id)
        if not catalog_item:
            continue
        base = float(catalog_item.base_cost_q)
        subtotal_q = base * item.quantity
        raw_total += subtotal_q
        if _LEAGUE_ORDER.get(catalog_item.min_league, 0) > _LEAGUE_ORDER.get(max_league, 0):
            max_league = catalog_item.min_league
        breakdown.append(
            EstimateBreakdownItem(
                catalog_id=catalog_item.id,
                name=catalog_item.name,
                category=catalog_item.category.value,
                complexity=catalog_item.complexity.value,
                base_cost_q=round(base, 1),
                quantity=item.quantity,
                subtotal_q=round(subtotal_q, 1),
            )
        )

    total_q = round(raw_total, 1)

    return EstimateResponse(
        total_q=total_q,
        min_league=max_league.value,
        breakdown=breakdown,
    )


def _task_type_from_categories(categories: set[str]) -> str:
    """Определить task_type по категориям каталога (если смесь — widget)."""
    if not categories:
        return "widget"
    if len(categories) == 1:
        return next(iter(categories))
    return "widget"


def _max_complexity(complexities: list[str]) -> str:
    """Максимальная сложность: S < M < L < XL."""
    order = {"S": 0, "M": 1, "L": 2, "XL": 3}
    return max(complexities, key=lambda c: order.get(c, 0), default="S")


async def create_task_from_calc(
    db: AsyncSession,
    request: CreateTaskFromCalcRequest,
) -> Task:
    """
    Создать задачу из калькулятора: расчёт + создание Task со статусом in_queue.
    """
    estimate = await calculate_estimate(
        db,
        EstimateRequest(items=request.items),
    )

    categories = {b.category for b in estimate.breakdown}
    complexities = [b.complexity for b in estimate.breakdown]
    task_type_str = _task_type_from_categories(categories)
    complexity_str = _max_complexity(complexities)

    try:
        task_type = TaskType(task_type_str)
    except ValueError:
        task_type = TaskType.widget
    complexity_enum = Complexity(complexity_str) if complexity_str in ("S", "M", "L", "XL") else Complexity.S
    priority_enum = TaskPriority(request.priority) if request.priority in ("low", "medium", "high", "critical") else TaskPriority.medium
    if task_type == TaskType.proactive and priority_enum in (TaskPriority.critical, TaskPriority.high):
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail="Проактивные задачи не могут иметь приоритет выше medium",
        )
    league_enum = League(estimate.min_league) if estimate.min_league in ("C", "B", "A") else League.C

    estimation_details = {
        "breakdown": [b.model_dump(mode="json") for b in estimate.breakdown],
        "total_q": estimate.total_q,
        "estimated_at": datetime.now(timezone.utc).isoformat(),
    }

    tags_list = getattr(request, "tags", None) or []
    task = Task(
        title=request.title,
        description=request.description or None,
        task_type=task_type,
        complexity=complexity_enum,
        estimated_q=Decimal(str(estimate.total_q)),
        priority=priority_enum,
        status=TaskStatus.in_queue,
        min_league=league_enum,
        assignee_id=None,
        estimator_id=request.estimator_id,
        validator_id=None,
        estimation_details=estimation_details,
        tags=tags_list,
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    return task
