"""
Калибровочный отчёт: сравнение оценки (estimated_q) и реального времени выполнения.
На основе estimation_details.breakdown и завершённых задач.
Точность тимлидов: по задачам, где validator_id = teamlead.
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalog import CatalogItem
from app.models.task import Task, TaskStatus
from app.models.user import User, UserRole
from app.schemas.calibration import CalibrationItem, CalibrationReport, TeamleadAccuracy


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


async def get_teamlead_accuracy(db: AsyncSession) -> list[TeamleadAccuracy]:
    """
    Точность оценок тимлидов. Используем validator_id как прокси оценщика.
    Для каждого teamlead/admin: задачи с validator_id = user, завершённые.
    Точность = 1 - sum(|estimated - proportional_actual|) / sum(estimated).
    proportional_actual в Q = actual_hours / avg_hours_per_q (глобальное ср. часов на 1 Q).
    """
    teamleads_result = await db.execute(
        select(User.id, User.full_name).where(User.role.in_([UserRole.teamlead, UserRole.admin]))
    )
    teamleads = list(teamleads_result.all())
    if not teamleads:
        return []

    now = datetime.now(timezone.utc)
    this_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.month == 1:
        last_month_start = this_month_start.replace(year=now.year - 1, month=12)
    else:
        last_month_start = this_month_start.replace(month=now.month - 1)

    all_done = await db.execute(
        select(Task)
        .where(
            Task.status == TaskStatus.done,
            Task.validator_id.is_not(None),
            Task.started_at.is_not(None),
            Task.completed_at.is_not(None),
        )
    )
    all_tasks = list(all_done.scalars().all())

    total_q = sum(float(t.estimated_q) for t in all_tasks)
    total_hours = sum(_task_actual_hours(t) or 0 for t in all_tasks)
    avg_hours_per_q = total_hours / total_q if total_q > 0 else 0.0

    out: list[TeamleadAccuracy] = []
    for uid, full_name in teamleads:
        my_tasks = [t for t in all_tasks if t.validator_id == uid]
        if not my_tasks:
            out.append(
                TeamleadAccuracy(
                    user_id=str(uid),
                    full_name=full_name,
                    tasks_evaluated=0,
                    accuracy_percent=0.0,
                    bias="neutral",
                    bias_percent=0.0,
                    trend="stable",
                    trend_delta=0.0,
                )
            )
            continue
        sum_estimated = sum(float(t.estimated_q) for t in my_tasks)
        sum_abs_error = 0.0
        sum_diff = 0.0
        for t in my_tasks:
            ah = _task_actual_hours(t)
            if ah is None:
                continue
            eq = float(t.estimated_q)
            proportional_q = ah / avg_hours_per_q if avg_hours_per_q > 0 else 0
            sum_abs_error += abs(eq - proportional_q)
            sum_diff += eq - proportional_q
        accuracy = (1 - sum_abs_error / sum_estimated) * 100 if sum_estimated > 0 else 0.0
        accuracy = max(0.0, min(100.0, accuracy))
        bias_pct = (sum_diff / sum_estimated * 100) if sum_estimated > 0 else 0.0
        if bias_pct > 5:
            bias = "overestimates"
        elif bias_pct < -5:
            bias = "underestimates"
        else:
            bias = "neutral"

        this_month_tasks = [t for t in my_tasks if t.completed_at and t.completed_at >= this_month_start]
        last_month_tasks = [t for t in my_tasks if t.completed_at and last_month_start <= t.completed_at < this_month_start]
        acc_this = 0.0
        if this_month_tasks:
            s = sum(float(t.estimated_q) for t in this_month_tasks)
            err = sum(
                abs(float(t.estimated_q) - (_task_actual_hours(t) or 0) / avg_hours_per_q)
                for t in this_month_tasks
                if avg_hours_per_q > 0
            )
            acc_this = (1 - err / s * 100) if s > 0 else 0
        acc_last = 0.0
        if last_month_tasks:
            s = sum(float(t.estimated_q) for t in last_month_tasks)
            err = sum(
                abs(float(t.estimated_q) - (_task_actual_hours(t) or 0) / avg_hours_per_q)
                for t in last_month_tasks
                if avg_hours_per_q > 0
            )
            acc_last = (1 - err / s * 100) if s > 0 else 0
        trend_delta = acc_this - acc_last
        if trend_delta > 2:
            trend = "improving"
        elif trend_delta < -2:
            trend = "declining"
        else:
            trend = "stable"

        out.append(
            TeamleadAccuracy(
                user_id=str(uid),
                full_name=full_name,
                tasks_evaluated=len(my_tasks),
                accuracy_percent=round(accuracy, 1),
                bias=bias,
                bias_percent=round(bias_pct, 1),
                trend=trend,
                trend_delta=round(trend_delta, 1),
            )
        )
    return out
