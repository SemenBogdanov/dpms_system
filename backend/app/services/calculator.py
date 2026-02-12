"""Логика расчёта Q по каталогу (калькулятор оценки)."""
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import CatalogItem
from app.models.user import League
from app.schemas.calculator import (
    CalculatorBreakdownItem,
    CalculatorRequest,
    CalculatorResponse,
)


# Порядок лиг для определения max min_league: C < B < A
_LEAGUE_ORDER = {League.C: 0, League.B: 1, League.A: 2}


async def calculate_estimate(
    db: AsyncSession,
    payload: CalculatorRequest,
) -> CalculatorResponse:
    """
    Рассчитать стоимость задачи по выбранным позициям каталога.
    total_q = сумма (base_cost_q * quantity) по позициям * complexity_multiplier * urgency_multiplier.
    min_league = максимальный min_league среди выбранных позиций.
    """
    if not payload.items:
        return CalculatorResponse(
            total_q=Decimal("0"),
            breakdown=[],
            min_league=League.C,
        )

    catalog_ids = [item.catalog_id for item in payload.items]
    result = await db.execute(
        select(CatalogItem).where(
            CatalogItem.id.in_(catalog_ids),
            CatalogItem.is_active.is_(True),
        )
    )
    catalog_by_id = {row.id: row for row in result.scalars().all()}

    breakdown: list[CalculatorBreakdownItem] = []
    total_raw = Decimal("0")
    max_league = League.C

    for item in payload.items:
        catalog_item = catalog_by_id.get(item.catalog_id)
        if not catalog_item:
            continue
        subtotal = Decimal(str(catalog_item.base_cost_q)) * item.quantity
        total_raw += subtotal
        if _LEAGUE_ORDER.get(catalog_item.min_league, 0) > _LEAGUE_ORDER.get(max_league, 0):
            max_league = catalog_item.min_league
        breakdown.append(
            CalculatorBreakdownItem(
                catalog_id=catalog_item.id,
                name=catalog_item.name,
                base_cost_q=Decimal(str(catalog_item.base_cost_q)),
                quantity=item.quantity,
                subtotal_q=subtotal,
            )
        )

    total_q = (
        total_raw
        * Decimal(str(payload.complexity_multiplier))
        * Decimal(str(payload.urgency_multiplier))
    )

    return CalculatorResponse(
        total_q=total_q,
        breakdown=breakdown,
        min_league=max_league,
    )
