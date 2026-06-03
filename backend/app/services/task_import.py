"""CSV import for queued tasks."""
from __future__ import annotations

import csv
import io
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.limits import TASK_TITLE_MAX_LENGTH
from app.models.catalog import CatalogItem
from app.models.task import Task, TaskPriority, TaskStatus, TaskType
from app.models.user import User, UserRole
from app.schemas.task import (
    TaskImportCommitResponse,
    TaskImportIssue,
    TaskImportPreview,
    TaskImportPreviewRow,
)

MAX_IMPORT_BYTES = 256 * 1024
MAX_IMPORT_ROWS = 200
MAX_IMPORT_COLUMNS = 20
MAX_TAGS = 12
MAX_TAG_LENGTH = 50
MAX_DESCRIPTION_LENGTH = 5000
ALLOWED_HEADERS = {
    "title",
    "catalog_item_id",
    "catalog_item_name",
    "quantity",
    "description",
    "priority",
    "due_date",
    "tags",
}
REQUIRED_HEADERS = {"title", "quantity"}
TEXT_FIELDS = {"title", "description", "tags"}
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


@dataclass
class ValidImportRow:
    row_number: int
    title: str
    description: str | None
    catalog_item: CatalogItem
    quantity: int
    priority: TaskPriority
    due_date: datetime | None
    tags: list[str]
    estimated_q: Decimal


@dataclass
class TaskImportParseResult:
    preview: TaskImportPreview
    rows: list[ValidImportRow]


def _normalize_header(value: str) -> str:
    return value.strip().lower().replace(" ", "_")


def _decode_csv(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise HTTPException(
        status_code=400,
        detail="CSV должен быть в UTF-8 или Windows-1251",
    )


def _detect_delimiter(sample: str) -> str:
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;")
        return dialect.delimiter
    except csv.Error:
        return ";" if sample.count(";") > sample.count(",") else ","


def _parse_csv_table(data: bytes, filename: str | None) -> tuple[list[str], list[tuple[int, list[str]]]]:
    if filename and not filename.lower().endswith(".csv"):
        raise HTTPException(
            status_code=400,
            detail="Сейчас поддерживается только CSV (.csv). Excel-файл сохраните как CSV UTF-8.",
        )
    if len(data) > MAX_IMPORT_BYTES:
        raise HTTPException(
            status_code=400,
            detail="CSV слишком большой: максимум 256 КБ и 200 строк",
        )
    if not data.strip():
        raise HTTPException(status_code=400, detail="CSV пустой")

    text = _decode_csv(data)
    if "\x00" in text:
        raise HTTPException(status_code=400, detail="CSV содержит недопустимые бинарные данные")

    delimiter = _detect_delimiter(text[:4096])
    try:
        rows = list(csv.reader(io.StringIO(text), delimiter=delimiter))
    except csv.Error as exc:
        raise HTTPException(status_code=400, detail=f"Не удалось прочитать CSV: {exc}") from exc

    header_index = None
    raw_header: list[str] = []
    for index, row in enumerate(rows):
        if any(cell.strip() for cell in row):
            header_index = index
            raw_header = row
            break
    if header_index is None:
        raise HTTPException(status_code=400, detail="CSV не содержит заголовок")
    if len(raw_header) > MAX_IMPORT_COLUMNS:
        raise HTTPException(status_code=400, detail="В CSV слишком много колонок")

    headers = [_normalize_header(cell) for cell in raw_header]
    if any(not header for header in headers):
        raise HTTPException(status_code=400, detail="В CSV есть пустой заголовок колонки")
    duplicates = sorted({header for header in headers if headers.count(header) > 1})
    if duplicates:
        raise HTTPException(
            status_code=400,
            detail=f"Дублируются колонки: {', '.join(duplicates)}",
        )
    unknown = sorted(set(headers) - ALLOWED_HEADERS)
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"Неизвестные колонки: {', '.join(unknown)}",
        )
    missing = sorted(REQUIRED_HEADERS - set(headers))
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Не хватает обязательных колонок: {', '.join(missing)}",
        )
    if "catalog_item_id" not in headers and "catalog_item_name" not in headers:
        raise HTTPException(
            status_code=400,
            detail="Нужна колонка catalog_item_id или catalog_item_name",
        )

    data_rows: list[tuple[int, list[str]]] = []
    for row_number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        if not any(cell.strip() for cell in row):
            continue
        data_rows.append((row_number, row))
        if len(data_rows) > MAX_IMPORT_ROWS:
            raise HTTPException(status_code=400, detail="В одном импорте максимум 200 строк")
    return headers, data_rows


def _safe_text(value: str, field: str, errors: list[TaskImportIssue], row_number: int) -> None:
    stripped = value.lstrip(" ")
    if stripped.startswith(FORMULA_PREFIXES):
        errors.append(
            TaskImportIssue(
                row_number=row_number,
                field=field,
                message="Значение похоже на формулу Excel и не может быть импортировано",
            )
        )


def _parse_tags(value: str, row_number: int, errors: list[TaskImportIssue]) -> list[str]:
    if not value.strip():
        return []
    tags: list[str] = []
    seen: set[str] = set()
    for raw in value.replace("|", ";").replace(",", ";").split(";"):
        tag = raw.strip()
        if not tag:
            continue
        _safe_text(tag, "tags", errors, row_number)
        if len(tag) > MAX_TAG_LENGTH:
            errors.append(
                TaskImportIssue(
                    row_number=row_number,
                    field="tags",
                    message=f"Тег длиннее {MAX_TAG_LENGTH} символов",
                )
            )
        key = tag.casefold()
        if key not in seen:
            tags.append(tag)
            seen.add(key)
    if len(tags) > MAX_TAGS:
        errors.append(
            TaskImportIssue(
                row_number=row_number,
                field="tags",
                message=f"Максимум {MAX_TAGS} тегов на задачу",
            )
        )
    return tags[:MAX_TAGS]


def _parse_due_date(value: str, row_number: int, errors: list[TaskImportIssue]) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    try:
        normalized = raw.replace("Z", "+00:00")
        if len(normalized) == 10 and normalized[4] == "-" and normalized[7] == "-":
            due_date = datetime.combine(datetime.fromisoformat(normalized).date(), time(23, 59, 59))
        else:
            due_date = datetime.fromisoformat(normalized)
    except ValueError:
        errors.append(
            TaskImportIssue(
                row_number=row_number,
                field="due_date",
                message="Дата должна быть в ISO-формате, например 2026-05-31 или 2026-05-31T18:00:00+03:00",
            )
        )
        return None
    if due_date.tzinfo is None:
        due_date = due_date.replace(tzinfo=timezone.utc)
    else:
        due_date = due_date.astimezone(timezone.utc)
    if due_date <= datetime.now(timezone.utc):
        errors.append(
            TaskImportIssue(
                row_number=row_number,
                field="due_date",
                message="Дедлайн должен быть в будущем",
            )
        )
    return due_date


def _parse_quantity(value: str, row_number: int, errors: list[TaskImportIssue]) -> int | None:
    raw = value.strip()
    if not raw:
        errors.append(TaskImportIssue(row_number=row_number, field="quantity", message="Количество обязательно"))
        return None
    if not raw.isdigit():
        errors.append(TaskImportIssue(row_number=row_number, field="quantity", message="Количество должно быть целым числом"))
        return None
    quantity = int(raw)
    if quantity < 1 or quantity > 50:
        errors.append(TaskImportIssue(row_number=row_number, field="quantity", message="Количество должно быть от 1 до 50"))
    return quantity


def _task_q(catalog_item: CatalogItem, quantity: int) -> Decimal:
    return (Decimal(catalog_item.base_cost_q) * Decimal(quantity)).quantize(
        Decimal("0.1"),
        rounding=ROUND_HALF_UP,
    )


def _breakdown(catalog_item: CatalogItem, quantity: int, estimated_q: Decimal) -> dict:
    return {
        "catalog_id": str(catalog_item.id),
        "name": catalog_item.name,
        "category": catalog_item.category.value,
        "complexity": catalog_item.complexity.value,
        "base_cost_q": float(catalog_item.base_cost_q),
        "quantity": quantity,
        "subtotal_q": float(estimated_q),
    }


async def parse_task_import(
    db: AsyncSession,
    upload: UploadFile,
    user: User,
) -> TaskImportParseResult:
    """Parse and validate a CSV task import without writing tasks."""
    content = await upload.read()
    headers, raw_rows = _parse_csv_table(content, upload.filename)

    result = await db.execute(select(CatalogItem).where(CatalogItem.is_active.is_(True)))
    catalog_items = list(result.scalars().all())
    catalog_by_id = {item.id: item for item in catalog_items}
    names: dict[str, list[CatalogItem]] = {}
    for item in catalog_items:
        names.setdefault(item.name.strip().casefold(), []).append(item)

    preview_rows: list[TaskImportPreviewRow] = []
    valid_rows: list[ValidImportRow] = []
    warnings: list[str] = []
    seen_keys: dict[tuple[str, str, int, str], int] = {}

    for row_number, row in raw_rows:
        values = {
            header: (row[index].strip(" ") if index < len(row) else "")
            for index, header in enumerate(headers)
        }
        errors: list[TaskImportIssue] = []
        if len(row) > len(headers):
            errors.append(
                TaskImportIssue(
                    row_number=row_number,
                    field="_row",
                    message="В строке больше колонок, чем в заголовке",
                )
            )

        for field in TEXT_FIELDS:
            value = values.get(field, "")
            if value:
                _safe_text(value, field, errors, row_number)

        title = values.get("title", "").strip()
        if not title:
            errors.append(TaskImportIssue(row_number=row_number, field="title", message="Название обязательно"))
        elif len(title) < 5:
            errors.append(TaskImportIssue(row_number=row_number, field="title", message="Название должно быть не короче 5 символов"))
        elif len(title) > TASK_TITLE_MAX_LENGTH:
            errors.append(
                TaskImportIssue(
                    row_number=row_number,
                    field="title",
                    message=f"Название длиннее {TASK_TITLE_MAX_LENGTH} символов",
                )
            )

        description = values.get("description", "").strip() or None
        if description and len(description) > MAX_DESCRIPTION_LENGTH:
            errors.append(
                TaskImportIssue(
                    row_number=row_number,
                    field="description",
                    message=f"Описание длиннее {MAX_DESCRIPTION_LENGTH} символов",
                )
            )

        quantity = _parse_quantity(values.get("quantity", ""), row_number, errors)

        priority_raw = values.get("priority", "").strip() or TaskPriority.medium.value
        try:
            priority = TaskPriority(priority_raw)
        except ValueError:
            priority = TaskPriority.medium
            errors.append(
                TaskImportIssue(
                    row_number=row_number,
                    field="priority",
                    message="Приоритет должен быть low, medium, high или critical",
                )
            )
        if priority == TaskPriority.critical and user.role != UserRole.admin:
            errors.append(
                TaskImportIssue(
                    row_number=row_number,
                    field="priority",
                    message="Критический приоритет может установить только администратор",
                )
            )

        due_date = _parse_due_date(values.get("due_date", ""), row_number, errors)
        tags = _parse_tags(values.get("tags", ""), row_number, errors)

        catalog_item: CatalogItem | None = None
        catalog_id: UUID | None = None
        catalog_item_id_raw = values.get("catalog_item_id", "").strip()
        catalog_name_raw = values.get("catalog_item_name", "").strip()
        if catalog_item_id_raw:
            try:
                catalog_id = UUID(catalog_item_id_raw)
                catalog_item = catalog_by_id.get(catalog_id)
                if catalog_item is None:
                    errors.append(
                        TaskImportIssue(
                            row_number=row_number,
                            field="catalog_item_id",
                            message="Активная позиция каталога с таким id не найдена",
                        )
                    )
            except ValueError:
                errors.append(
                    TaskImportIssue(
                        row_number=row_number,
                        field="catalog_item_id",
                        message="catalog_item_id должен быть UUID",
                    )
                )
        elif catalog_name_raw:
            matches = names.get(catalog_name_raw.casefold(), [])
            if len(matches) == 1:
                catalog_item = matches[0]
                catalog_id = catalog_item.id
            elif len(matches) > 1:
                errors.append(
                    TaskImportIssue(
                        row_number=row_number,
                        field="catalog_item_name",
                        message="Название найдено несколько раз, укажите catalog_item_id",
                    )
                )
            else:
                errors.append(
                    TaskImportIssue(
                        row_number=row_number,
                        field="catalog_item_name",
                        message="Активная позиция каталога с таким названием не найдена",
                    )
                )
        else:
            errors.append(
                TaskImportIssue(
                    row_number=row_number,
                    field="catalog_item_id",
                    message="Укажите catalog_item_id или catalog_item_name",
                )
            )

        estimated_q: Decimal | None = None
        if catalog_item and quantity is not None:
            estimated_q = _task_q(catalog_item, quantity)
            if catalog_item.category.value == TaskType.proactive.value and priority in (
                TaskPriority.high,
                TaskPriority.critical,
            ):
                errors.append(
                    TaskImportIssue(
                        row_number=row_number,
                        field="priority",
                        message="Проактивные задачи не могут иметь приоритет выше medium",
                    )
                )
            duplicate_key = (
                title.casefold(),
                str(catalog_item.id),
                quantity,
                priority.value,
            )
            duplicate_row = seen_keys.get(duplicate_key)
            if duplicate_row is not None:
                errors.append(
                    TaskImportIssue(
                        row_number=row_number,
                        field="_row",
                        message=f"Похоже на дубль строки {duplicate_row}",
                    )
                )
            else:
                seen_keys[duplicate_key] = row_number

        row_preview = TaskImportPreviewRow(
            row_number=row_number,
            title=title,
            catalog_item_id=catalog_id,
            catalog_item_name=catalog_item.name if catalog_item else catalog_name_raw or None,
            quantity=quantity,
            priority=priority.value,
            due_date=due_date,
            tags=tags,
            task_type=catalog_item.category.value if catalog_item else None,
            complexity=catalog_item.complexity.value if catalog_item else None,
            estimated_q=float(estimated_q) if estimated_q is not None else None,
            min_league=catalog_item.min_league.value if catalog_item else None,
            errors=errors,
        )
        preview_rows.append(row_preview)
        if not errors and catalog_item is not None and quantity is not None and estimated_q is not None:
            valid_rows.append(
                ValidImportRow(
                    row_number=row_number,
                    title=title,
                    description=description,
                    catalog_item=catalog_item,
                    quantity=quantity,
                    priority=priority,
                    due_date=due_date,
                    tags=tags,
                    estimated_q=estimated_q,
                )
            )

    critical_count = sum(1 for row in valid_rows if row.priority == TaskPriority.critical)
    if critical_count:
        warnings.append(
            f"В файле {critical_count} критических задач: после импорта они будут блокировать взятие некритических задач."
        )

    error_rows = sum(1 for row in preview_rows if row.errors)
    preview = TaskImportPreview(
        batch_id=str(uuid.uuid4()),
        total_rows=len(preview_rows),
        valid_rows=len(preview_rows) - error_rows,
        error_rows=error_rows,
        has_errors=error_rows > 0,
        warnings=warnings,
        rows=preview_rows,
    )
    return TaskImportParseResult(preview=preview, rows=valid_rows)


async def preview_task_import(
    db: AsyncSession,
    upload: UploadFile,
    user: User,
) -> TaskImportPreview:
    """Return validated task import preview; no database writes."""
    return (await parse_task_import(db, upload, user)).preview


async def commit_task_import(
    db: AsyncSession,
    upload: UploadFile,
    user: User,
) -> TaskImportCommitResponse:
    """Validate and create queued tasks in one transaction."""
    parsed = await parse_task_import(db, upload, user)
    if parsed.preview.has_errors:
        raise HTTPException(
            status_code=400,
            detail="Файл содержит ошибки. Сначала исправьте строки и повторите предпросмотр.",
        )
    if not parsed.rows:
        raise HTTPException(status_code=400, detail="В файле нет строк для импорта")

    batch_id = str(uuid.uuid4())
    imported_at = datetime.now(timezone.utc)
    tasks: list[Task] = []
    for row in parsed.rows:
        catalog_item = row.catalog_item
        task = Task(
            title=row.title,
            description=row.description,
            task_type=TaskType(catalog_item.category.value),
            complexity=catalog_item.complexity,
            estimated_q=row.estimated_q,
            priority=row.priority,
            status=TaskStatus.in_queue,
            min_league=catalog_item.min_league,
            assignee_id=None,
            assigned_by_id=None,
            estimator_id=user.id,
            validator_id=None,
            estimation_details={
                "source": "task_import_csv",
                "import_batch_id": batch_id,
                "row_number": row.row_number,
                "imported_by_id": str(user.id),
                "imported_at": imported_at.isoformat(),
                "breakdown": [_breakdown(catalog_item, row.quantity, row.estimated_q)],
                "total_q": float(row.estimated_q),
            },
            due_date=row.due_date,
            tags=row.tags,
        )
        db.add(task)
        tasks.append(task)

    await db.flush()
    for task in tasks:
        await db.refresh(task)

    return TaskImportCommitResponse(
        batch_id=batch_id,
        created_count=len(tasks),
        tasks=tasks,
    )
