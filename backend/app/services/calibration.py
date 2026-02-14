"""
Калибровочный отчёт: сравнение оценки (estimated_q) и реального времени выполнения.
На основе estimation_details.breakdown и завершённых задач.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import CatalogItem
from app.models.task import Task, TaskStatus
from app.schemas.calibration import CalibrationItem, CalibrationReport


def _task_actual_hours(task: Task) -> float | None:
    """Фактическое время выполнения задачи в часах."""
    if not task.started_at or not task.completed_at:
        return None
    delta = task.completed_at - task.started_at
    return delta.total_seconds() / 3600.0


async def get_calibration_report(
    db: AsyncSession,
    period: str | None = None,
) -> CalibrationReport:
    """
    Калибровочный отчёт. period: "YYYY-MM" или "all".
    Для каждой операции каталога: сколько задач использовали, ср. оценка, ср. факт часов, отклонение.
    """
    now = datetime.now(timezone.utc)
    if not period:
        period = now.strftime("%Y-%m")
    if period != "all":
        try:
            year, month = int(period[:4]), int(period[5:7].lstrip("0") or "1")
            month_start = now.replace(year=year, month=month, day=1, hour=0, minute=0, second=0, microsecond=0)
            if month == 12:
                month_end = now.replace(year=year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            else:
                month_end = now.replace(year=year, month=month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
        except (ValueError, IndexError):
            month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            month_end = now
            period = now.strftime("%Y-%m")
    else:
        month_start = None
        month_end = None
        period = "all"

    stmt = select(Task).where(
        Task.status == TaskStatus.done,
        Task.estimation_details.is_not(None),
        Task.started_at.is_not(None),
        Task.completed_at.is_not(None),
    )
    if month_start is not None:
        stmt = stmt.where(Task.completed_at >= month_start, Task.completed_at < month_end)
    result = await db.execute(stmt)
    tasks = list(result.scalars().all())

    catalog_result = await db.execute(select(CatalogItem))
    catalog_items = {str(item.id): item for item in catalog_result.scalars().all()}

    # По каждому catalog_id собираем: список (estimated_share, actual_hours_share)
    item_data: dict[str, list[tuple[float, float]]] = {}

    tasks_analyzed = 0
    for task in tasks:
        details = task.estimation_details or {}
        breakdown = details.get("breakdown") or []
        if not breakdown:
            continue
        actual_hours = _task_actual_hours(task)
        if actual_hours is None:
            continue
        tasks_analyzed += 1
        estimated_total = float(task.estimated_q)
        if estimated_total <= 0:
            continue
        for row in breakdown:
            if not isinstance(row, dict):
                continue
            cid = row.get("catalog_id")
            subtotal = row.get("subtotal_q")
            if cid is None or subtotal is None:
                continue
            cid_str = str(cid)
            share = float(subtotal) / estimated_total
            hours_share = actual_hours * share
            if cid_str not in item_data:
                item_data[cid_str] = []
            item_data[cid_str].append((float(subtotal), hours_share))

    items_out: list[CalibrationItem] = []
    total_ok = 0
    total_with_deviation = 0

    for catalog_id, cat_item in catalog_items.items():
        rows = item_data.get(catalog_id, [])
        tasks_count = len(rows)
        if tasks_count == 0:
            items_out.append(
                CalibrationItem(
                    catalog_item_id=catalog_id,
                    name=cat_item.name,
                    category=cat_item.category.value,
                    complexity=cat_item.complexity.value,
                    base_cost_q=round(float(cat_item.base_cost_q), 1),
                    tasks_count=0,
                    avg_estimated_q=0.0,
                    avg_actual_hours=None,
                    deviation_percent=None,
                    recommendation="OK",
                )
            )
            continue
        avg_estimated = sum(r[0] for r in rows) / tasks_count
        avg_actual = sum(r[1] for r in rows) / tasks_count
        base_q = float(cat_item.base_cost_q)
        if base_q > 0:
            deviation = (avg_actual - base_q) / base_q * 100
        else:
            deviation = 0.0
        if abs(deviation) < 20:
            recommendation = "OK"
            total_ok += 1
        elif deviation < 0:
            recommendation = "Завышена"
            total_with_deviation += 1
        else:
            recommendation = "Занижена"
            total_with_deviation += 1
        items_out.append(
            CalibrationItem(
                catalog_item_id=catalog_id,
                name=cat_item.name,
                category=cat_item.category.value,
                complexity=cat_item.complexity.value,
                base_cost_q=round(base_q, 1),
                tasks_count=tasks_count,
                avg_estimated_q=round(avg_estimated, 1),
                avg_actual_hours=round(avg_actual, 1),
                deviation_percent=round(deviation, 1),
                recommendation=recommendation,
            )
        )

    total_items_with_tasks = sum(1 for i in items_out if i.tasks_count > 0)
    overall_accuracy = (total_ok / total_items_with_tasks * 100) if total_items_with_tasks else 100.0

    items_out.sort(key=lambda x: (abs(x.deviation_percent or 0), 0), reverse=True)

    return CalibrationReport(
        period=period,
        items=items_out,
        total_tasks_analyzed=tasks_analyzed,
        overall_accuracy_percent=round(overall_accuracy, 1),
    )
