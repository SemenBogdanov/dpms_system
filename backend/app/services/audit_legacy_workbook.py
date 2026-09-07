"""Bounded, offline inspection of historical workbooks, without target mutations."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from io import BytesIO
from hashlib import sha256
import json
import posixpath
import re
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from xml.parsers import expat
from zipfile import BadZipFile, ZipFile
from zoneinfo import ZoneInfo

from fastapi import HTTPException

from app.services.audit_import import mask_contract_reference, mask_system_url


PARSER_VERSION = "a19-xlsx-v1"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UNPACKED_BYTES = 40 * 1024 * 1024
MAX_MEMBERS = 1000
MAX_CELLS = 250_000
MAX_ROWS = 30_000
MAX_COLUMNS = 100
MAX_SHEETS = 20
MAX_TEXT = 20_000
MAX_ISSUES = 500
MAX_XML_NODES = 500_000
MAX_RANGES = 2_000
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"

REQUIRED_FIELDS = {
    "cases": {"case_key", "digital_product"},
    "atoms": {"case_key", "atom_key", "title"},
    "assignments": {"case_key", "assignee_email", "assigned_at"},
    "events": {"case_key", "event_key", "event_type", "occurred_at"},
    "daily_totals": {"case_key", "metric_date", "metric_type", "value"},
}
FIELD_ALIASES = {
    "case_key": ("код договора", "договор", "номер договора", "код аудита", "case key"),
    "digital_product": ("цифровой продукт", "название цифрового продукта", "продукт"),
    "contract_date": ("дата договора",),
    "atom_key": ("код атома", "id атома", "номер атома", "№", "atom key"),
    "title": ("название из договора", "название атома", "наименование элемента", "атом"),
    "source_clause": ("пункт договора", "пункт тз", "пункт источника"),
    "work_type": ("тип работ", "вид работ"),
    "object_type": ("тип объекта (экран/поток)", "тип объекта"),
    "state": ("статус атома", "статус", "верификация"),
    "alpha_result": ("наличие объекта в системе", "результат альфа-проверки", "альфа-проверка"),
    "alpha_date": ("дата альфа проверки", "дата альфа-проверки"),
    "commission_result": ("решение комиссии",),
    "commission_date": ("дата комиссионной проверки", "дата комиссии"),
    "system_url": ("ссылка на объект в системе", "ссылка", "url"),
    "assignee_email": ("почта исполнителя", "email исполнителя", "email", "почта сотрудника"),
    "actor_name": ("фио", "сотрудник", "исполнитель", "ответственный"),
    "assigned_at": ("дата назначения",),
    "is_current": ("активное назначение", "текущее назначение"),
    "occurred_at": ("дата события", "дата верификации", "дата проверки"),
    "event_key": ("код события", "id события"),
    "event_type": ("тип события",),
    "metric_date": ("дата", "день"),
    "metric_type": ("метрика", "показатель"),
    "value": ("количество", "значение", "верифицировано"),
    "workflow_stage": ("этап аудита", "этап договора"),
    "contract_reference": ("полный номер договора", "реквизиты договора"),
    "source_evidence_text": ("текстовое основание", "выдержка из тз"),
    "notes": ("примечание", "примечания", "комментарий"),
    "alpha_comment": ("комментарий альфа-проверки", "замечания альфа-проверки"),
    "previous_state": ("предыдущий статус", "статус до изменения"),
    "ended_at": ("дата завершения назначения", "назначение завершено"),
    "assignment_key": ("код назначения", "id назначения"),
}
DATE_FIELDS = {"contract_date", "alpha_date", "commission_date", "assigned_at", "ended_at", "occurred_at", "metric_date"}
STATE_VALUES = {"draft", "ready", "excluded", "черновик", "принят", "готов", "исключен", "исключён"}
ALPHA_VALUES = {"present", "not_present", "partial", "not_applicable", "needs_clarification", "1", "0", "да", "нет", "есть", "частично", "не применимо", "требует уточнения"}
COMMISSION_VALUES = {"confirmed", "not_confirmed", "deferred", "not_applicable", "1", "0", "принято", "принят", "подтверждено", "не подтверждено", "в доработку", "отложено", "исключено", "не применимо"}


def _bad(message: str) -> None:
    raise HTTPException(status_code=400, detail=message)


def _xml(data: bytes, *, validate_only: bool = False) -> ET.Element | None:
    # Reject declarations in the whole document, including after a long comment.
    try:
        value = data.decode("utf-8-sig")
        if "\x00" in value or re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", value, re.I):
            _bad("XLSX содержит небезопасную XML-конструкцию")
        nodes = 0
        depth = 0

        def start(_name, attrs):
            nonlocal nodes, depth
            nodes += 1
            depth += 1
            if nodes > MAX_XML_NODES or depth > 80 or len(attrs) > 100:
                _bad("XML внутри XLSX слишком сложен для безопасной обработки")

        def end(_name):
            nonlocal depth
            depth -= 1

        parser = expat.ParserCreate()
        parser.StartElementHandler = start
        parser.EndElementHandler = end
        # Count before allocating an ElementTree, including unused XML parts.
        for offset in range(0, len(value), 65536):
            parser.Parse(value[offset:offset + 65536], False)
        parser.Parse("", True)
        if validate_only:
            return None
        return ET.fromstring(value)
    except (UnicodeError, ET.ParseError, expat.ExpatError):
        _bad("Не удалось прочитать XML внутри XLSX")


def _column_number(column: str) -> int:
    result = 0
    for character in column:
        result = result * 26 + ord(character) - 64
    return result


def _norm(value: str) -> str:
    return " ".join(value.casefold().replace("ё", "е").split())


@dataclass
class Cell:
    value: str | None
    formula: bool = False
    error: bool = False


@dataclass
class Sheet:
    id: str
    name: str
    rows: dict[int, dict[str, Cell]]
    hidden: bool
    merged_cells: set[tuple[int, int]]


@dataclass
class Workbook:
    sheets: list[Sheet]
    date1904: bool


def _text(value: str | None) -> str | None:
    if value is not None and len(value) > MAX_TEXT:
        _bad("В XLSX есть ячейка длиннее 20 000 символов")
    return (value.strip() or None) if value is not None else None


def _range_cells(reference: str) -> set[tuple[int, int]]:
    match = re.fullmatch(r"([A-Z]{1,3})([0-9]{1,7})(?::([A-Z]{1,3})([0-9]{1,7}))?", reference)
    if not match:
        _bad("Некорректный диапазон объединения или формулы")
    left, top = _column_number(match[1]), int(match[2])
    right, bottom = _column_number(match[3] or match[1]), int(match[4] or match[2])
    if not 1 <= left <= right <= MAX_COLUMNS or not 1 <= top <= bottom <= 1048576:
        _bad("Диапазон объединения или формулы находится вне допустимой области")
    if (right - left + 1) * (bottom - top + 1) > MAX_CELLS:
        _bad("Диапазон объединения или формулы слишком большой")
    return {(row, column) for row in range(top, bottom + 1) for column in range(left, right + 1)}


def _read_workbook(data: bytes) -> Workbook:
    if not data or len(data) > MAX_UPLOAD_BYTES:
        _bad("Нужен непустой XLSX размером не более 10 МБ")
    try:
        with ZipFile(BytesIO(data)) as archive:
            members = archive.infolist()
            if len(members) > MAX_MEMBERS or sum(item.file_size for item in members) > MAX_UNPACKED_BYTES:
                _bad("XLSX превышает допустимый размер распакованной книги")
            names = [item.filename for item in members]
            if len(names) != len(set(names)):
                _bad("XLSX содержит повторяющиеся части архива")
            for item in members:
                path = item.filename
                parts = path.rstrip("/").split("/")
                lowered = path.casefold()
                if "\\" in path or path.startswith("/") or any(part in {"", ".", ".."} for part in parts):
                    _bad("XLSX содержит небезопасный путь")
                if item.flag_bits & 1 or item.file_size > max(1, item.compress_size) * 300:
                    _bad("Зашифрованный или чрезмерно сжатый XLSX не поддерживается")
                if any(word in lowered for word in ("vbaproject", "/embeddings/", "/activex/", "/externallinks/", "/queries/", "/connections.")):
                    _bad("XLSX с макросами, внешними подключениями или вложениями не поддерживается")
                if path.endswith(".xml") or path.endswith(".rels"):
                    root = _xml(archive.read(path), validate_only=not path.endswith(".rels"))
                    if path.endswith(".rels"):
                        for relation in root:
                            external = relation.attrib.get("TargetMode", "").casefold() == "external"
                            hyperlink = relation.attrib.get("Type", "").endswith("/hyperlink")
                            if external and not hyperlink:
                                _bad("XLSX содержит внешнюю зависимость")
                    if path == "[Content_Types].xml" and any(
                        token in archive.read(path).lower() for token in (b"macroenabled", b"vba", b"oleobject")
                    ):
                        _bad("XLSX с макросами или встроенными объектами не поддерживается")
            shared: list[str | None] = []
            if "xl/sharedStrings.xml" in names:
                for item in _xml(archive.read("xl/sharedStrings.xml")):
                    shared.append(_text("".join(node.text or "" for node in item.iter(f"{NS}t"))))
                    if len(shared) > MAX_CELLS:
                        _bad("В книге слишком много текстовых значений")
            workbook = _xml(archive.read("xl/workbook.xml"))
            props = workbook.find(f"{NS}workbookPr")
            date1904 = props is not None and props.attrib.get("date1904", "").lower() in {"1", "true"}
            relations = {node.attrib.get("Id"): node for node in _xml(archive.read("xl/_rels/workbook.xml.rels"))}
            sheet_nodes = workbook.findall(f"{NS}sheets/{NS}sheet")
            if not 1 <= len(sheet_nodes) <= MAX_SHEETS:
                _bad("Книга должна содержать от 1 до 20 листов")
            sheets: list[Sheet] = []
            count_cells = 0
            count_rows = 0
            range_area = 0
            range_count = 0
            for index, node in enumerate(sheet_nodes):
                relation = relations.get(node.attrib.get(f"{REL}id"))
                if relation is None or relation.attrib.get("TargetMode", "").casefold() == "external":
                    _bad("Некорректная связь листа XLSX")
                target = relation.attrib.get("Target", "")
                target = target.lstrip("/") if target.startswith("/") else posixpath.normpath(f"xl/{target}")
                if not target.startswith("xl/worksheets/") or not target.endswith(".xml"):
                    _bad("Поддерживаются только обычные листы XLSX")
                root = _xml(archive.read(target))
                rows: dict[int, dict[str, Cell]] = {}
                formula_refs = []
                for row in root.findall(f"{NS}sheetData/{NS}row"):
                    count_rows += 1
                    if count_rows > MAX_ROWS:
                        _bad("В книге допускается не более 30 000 строк")
                    row_id = int(row.attrib.get("r", "0"))
                    if not 1 <= row_id <= 1_048_576 or row_id in rows:
                        _bad("Некорректный или повторный номер строки XLSX")
                    cells: dict[str, Cell] = {}
                    for cell in row.findall(f"{NS}c"):
                        count_cells += 1
                        if count_cells > MAX_CELLS:
                            _bad("В книге допускается не более 250 000 ячеек")
                        match = re.fullmatch(r"([A-Z]{1,3})([1-9][0-9]{0,6})", cell.attrib.get("r", ""))
                        if not match or int(match[2]) != row_id or _column_number(match[1]) > MAX_COLUMNS or match[1] in cells:
                            _bad("Некорректный адрес ячейки; допускается до 100 столбцов")
                        value_node = cell.find(f"{NS}v")
                        value = value_node.text if value_node is not None else None
                        kind = cell.attrib.get("t")
                        if kind == "s":
                            shared_index = int(value or "-1")
                            if not 0 <= shared_index < len(shared):
                                _bad("Некорректная ссылка на строку XLSX")
                            value = shared[shared_index]
                        elif kind == "inlineStr":
                            value = "".join(part.text or "" for part in cell.iter(f"{NS}t"))
                        formula = cell.find(f"{NS}f")
                        if formula is not None and formula.attrib.get("ref"):
                            formula_refs.append(formula.attrib["ref"])
                        cells[match[1]] = Cell(_text(value), formula is not None, kind == "e")
                    rows[row_id] = cells
                merge_refs = [merge.attrib.get("ref", "") for merge in root.findall(f"{NS}mergeCells/{NS}mergeCell")]
                range_count += len(merge_refs) + len(formula_refs)
                if range_count > MAX_RANGES:
                    _bad("В XLSX слишком много объединений или формул массива")
                merged_cells, formula_cells = set(), set()
                for references, target_cells in ((merge_refs, merged_cells), (formula_refs, formula_cells)):
                    for reference in references:
                        cells_in_range = _range_cells(reference)
                        range_area += len(cells_in_range)
                        if range_area > MAX_CELLS:
                            _bad("Суммарная область объединений и формул слишком большая")
                        target_cells.update(cells_in_range)
                for row_id, cells in rows.items():
                    for column, cell in cells.items():
                        if (row_id, _column_number(column)) in formula_cells:
                            cell.formula = True
                sheets.append(Sheet(str(index + 1), _text(node.attrib.get("name")) or f"Лист {index + 1}", rows, node.attrib.get("state", "visible") != "visible", merged_cells))
            return Workbook(sheets, date1904)
    except HTTPException:
        raise
    except (BadZipFile, KeyError, ValueError, OSError, RuntimeError, NotImplementedError, OverflowError):
        _bad("Не удалось прочитать XLSX: файл поврежден или имеет неподдерживаемую структуру")


def _fields_for_headers(cells: dict[str, Cell]) -> dict[str, str]:
    candidates = defaultdict(list)
    for column, cell in cells.items():
        if cell.formula or cell.error:
            continue
        for field, aliases in FIELD_ALIASES.items():
            if cell.value and _norm(cell.value) in {_norm(alias) for alias in aliases}:
                candidates[field].append(column)
    return {field: columns[0] for field, columns in candidates.items() if len(columns) == 1}


def _header_row(sheet: Sheet) -> int:
    if not sheet.rows:
        return 1
    candidates = sorted(sheet.rows)[:30]
    return max(candidates, key=lambda row: (len(_fields_for_headers(sheet.rows[row])), sum(bool(cell.value) for cell in sheet.rows[row].values()), -row))


def _columns(sheet: Sheet, row: int) -> list[dict]:
    columns = {column for cells in sheet.rows.values() for column, cell in cells.items() if cell.value is not None or cell.formula}
    return [
        {"column": column, "label": ((sheet.rows.get(row, {}).get(column) or Cell(None)).value or f"Столбец {column}")[:160]}
        for column in sorted(columns, key=_column_number)
    ]


def inspect_legacy_workbook(data: bytes) -> dict:
    result = []
    for sheet in _read_workbook(data).sheets:
        header = _header_row(sheet)
        fields = _fields_for_headers(sheet.rows.get(header, {}))
        kind = max(REQUIRED_FIELDS, key=lambda item: len(REQUIRED_FIELDS[item] & fields.keys()) / len(REQUIRED_FIELDS[item]))
        if "title" in fields:
            kind = "atoms"
        result.append({
            "id": sheet.id, "name": sheet.name,
            "row_count": sum(any(cell.value is not None or cell.formula for cell in cells.values()) for row, cells in sheet.rows.items() if row > header),
            "column_count": len(_columns(sheet, header)),
            "formula_count": sum(cell.formula for cells in sheet.rows.values() for cell in cells.values()),
            "header_row": header, "columns": _columns(sheet, header),
            "suggested_mapping": {"kind": kind, "fields": fields},
        })
    return {"parser_version": PARSER_VERSION, "sheets": result}


def _date_key(value: str, date1904: bool, *, timestamp: bool) -> str | None:
    def normalized(parsed: datetime) -> str | None:
        if not 1900 <= parsed.year <= 2200:
            return None
        if not timestamp:
            return parsed.date().isoformat()
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=ZoneInfo("Europe/Moscow"))
        return parsed.astimezone(timezone.utc).isoformat()

    if timestamp:
        try:
            return normalized(datetime.fromisoformat(value.replace("Z", "+00:00")))
        except ValueError:
            pass
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%d.%m.%Y %H:%M", "%d.%m.%Y %H:%M:%S"):
        try:
            return normalized(datetime.strptime(value, fmt))
        except ValueError:
            pass
    try:
        serial = Decimal(value)
        if not serial.is_finite() or not 0 <= serial <= 110000:
            return None
        base = datetime(1904, 1, 1) if date1904 else datetime(1899, 12, 30)
        return normalized(base + timedelta(microseconds=int(serial * 86400 * 1_000_000)))
    except (InvalidOperation, ValueError, OverflowError):
        return None


def preview_legacy_mapping(data: bytes, mapping: dict) -> dict:
    book = _read_workbook(data)
    kind = mapping.get("kind")
    header = mapping.get("header_row")
    fields = mapping.get("fields", {})
    sheet = next((item for item in book.sheets if item.id == mapping.get("sheet_id")), None)
    if sheet is None or kind not in REQUIRED_FIELDS or isinstance(header, bool) or not isinstance(header, int) or header not in sheet.rows:
        _bad("Выберите существующий лист, строку заголовков и тип данных")
    if not isinstance(fields, dict) or any(field not in FIELD_ALIASES or not isinstance(column, str) or not re.fullmatch(r"[A-Z]{1,3}", column) for field, column in fields.items()):
        _bad("Некорректное сопоставление столбцов")
    if len(set(fields.values())) != len(fields):
        _bad("Один столбец нельзя назначить нескольким полям")
    columns = _columns(sheet, header)
    known_columns = {item["column"] for item in columns}
    if any(column not in known_columns for column in fields.values()):
        _bad("Выбранного столбца нет на листе")
    required = REQUIRED_FIELDS[kind]
    issues = []
    error_rows, warning_rows, duplicate_rows = set(), set(), set()
    issue_count = 0

    def issue(row: int | None, column: str | None, code: str, message: str, severity: str = "error") -> None:
        nonlocal issue_count
        issue_count += 1
        if row is not None:
            (error_rows if severity == "error" else warning_rows).add(row)
        if len(issues) < MAX_ISSUES:
            issues.append({"row": row, "column": column, "code": code, "severity": severity, "message": message})

    for field in sorted(required - fields.keys()):
        issue(None, None, "missing_mapping", f"Не выбран столбец: {FIELD_ALIASES[field][0]}")
    missing_mapping = not required.issubset(fields)
    if sheet.hidden:
        issue(None, None, "hidden_sheet", "Выбран скрытый лист; проверьте, что он является источником фактов", "warning")
    invalid_header = False
    for field, column in fields.items():
        cell = sheet.rows.get(header, {}).get(column)
        if cell is not None and (cell.formula or cell.error):
            issue(header, column, "invalid_header", "Заголовок содержит формулу или ошибку Excel")
            invalid_header = True
    keys = defaultdict(list)
    preview_rows = []
    total_rows = 0
    valid_data_rows = set()
    for row_id, cells in sorted(sheet.rows.items()):
        if row_id <= header or not any(cell.value is not None or cell.formula or cell.error for cell in cells.values()):
            continue
        total_rows += 1
        valid_data_rows.add(row_id)
        values = {field: (cells.get(column) or Cell(None)).value for field, column in fields.items()}
        for field, column in fields.items():
            cell = cells.get(column) or Cell(None)
            if cell.formula:
                issue(row_id, column, "formula_not_fact", "Формула не является историческим фактом; укажите исходные значения")
            elif cell.error:
                issue(row_id, column, "excel_error", "В ячейке ошибка Excel")
            elif field in required and not cell.value:
                issue(row_id, column, "required_value", f"Не заполнено поле: {FIELD_ALIASES[field][0]}")
            if (row_id, _column_number(column)) in sheet.merged_cells:
                issue(row_id, column, "merged_value", "Объединенная ячейка: значение для каждой строки нужно подтвердить отдельно")
            value = cell.value
            if not value or cell.formula or cell.error:
                continue
            if field in DATE_FIELDS and not _date_key(value, book.date1904, timestamp=field in {"occurred_at", "assigned_at"}):
                issue(row_id, column, "invalid_date", "Не распознана дата; используйте ДД.ММ.ГГГГ или YYYY-MM-DD")
            if field == "assignee_email" and not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
                issue(row_id, column, "invalid_email", "Для сопоставления сотрудника нужен адрес электронной почты, не ФИО")
            allowed_values = {"state": STATE_VALUES, "alpha_result": ALPHA_VALUES, "commission_result": COMMISSION_VALUES,
                              "is_current": {"true", "false", "да", "нет", "1", "0"}}
            if field in allowed_values and _norm(value) not in {_norm(item) for item in allowed_values[field]}:
                issue(row_id, column, "unknown_value", "Значение не входит в известный набор; требуется отдельное сопоставление")
            if field == "system_url" and not re.fullmatch(r"https?://[^\s]+", value, flags=re.I):
                issue(row_id, column, "invalid_url", "Допускается полная ссылка http:// или https://")
            if field == "value":
                try:
                    number = Decimal(value)
                    if not number.is_finite() or number < 0 or number > 1_000_000_000 or number != number.to_integral_value():
                        raise ValueError
                except (InvalidOperation, ValueError):
                    issue(row_id, column, "invalid_count", "Количество должно быть целым неотрицательным числом")
        if kind == "assignments" and not values.get("is_current"):
            issue(row_id, None, "current_assignment_unknown", "Нет явного признака текущего назначения; оно не станет активным автоматически", "warning")
        if kind == "atoms" and _norm(values.get("state") or "") in {"ready", "принят", "готов"} and not values.get("occurred_at"):
            issue(row_id, None, "verification_date_unknown", "Нет даты верификации; день загрузки не будет принят за дату работы", "warning")
        if kind == "daily_totals":
            issue(row_id, None, "aggregate_only", "Дневной итог не доказывает обработку конкретных атомов", "warning")
        key_fields = {
            "cases": ("case_key",), "atoms": ("case_key", "atom_key"),
            "assignments": ("case_key", "assignee_email", "assigned_at"),
            "events": ("case_key", "event_key"),
            "daily_totals": ("case_key", "metric_date", "metric_type", "assignee_email", "actor_name"),
        }[kind]
        if kind == "daily_totals" and values.get("assignee_email"):
            key_fields = tuple(field for field in key_fields if field != "actor_name")
        if not missing_mapping and all(values.get(field) for field in required):
            key = tuple(
                _date_key(values[field], book.date1904, timestamp=field == "assigned_at") or _norm(values[field])
                if field in DATE_FIELDS and values.get(field) else _norm(values.get(field) or "")
                for field in key_fields
            )
            keys[key].append(row_id)
        if len(preview_rows) < 30:
            safe = {}
            for field, value in values.items():
                if field in {"case_key", "contract_reference"}:
                    value = mask_contract_reference(value)
                elif field == "system_url":
                    value = mask_system_url(value)
                elif field == "assignee_email" and value:
                    value = (value.split("@")[0][:1] + "***@" + value.split("@")[-1]) if "@" in value else "***"
                safe[field] = value[:500] if value else None
            preview_rows.append({"row": row_id, "values": safe})
    for duplicates in keys.values():
        if len(duplicates) > 1:
            for row_id in duplicates:
                duplicate_rows.add(row_id)
                issue(row_id, None, "duplicate_source_key", "Ключ записи повторяется на выбранном листе")
    if total_rows == 0:
        issue(None, None, "empty_dataset", "После строки заголовков нет записей")
    if missing_mapping or invalid_header:
        error_rows.update(valid_data_rows)
    return {
        "sheet_id": sheet.id, "header_row": header, "kind": kind,
        "total_rows": total_rows, "valid_rows": len(valid_data_rows - error_rows),
        "error_rows": len(valid_data_rows & error_rows), "warning_rows": len(valid_data_rows & warning_rows),
        "duplicate_rows": len(duplicate_rows), "issues": issues, "issue_count": issue_count,
        "preview_rows": preview_rows, "columns": columns,
        "unmapped_columns": sorted(known_columns - set(fields.values()), key=_column_number),
        "ready_for_import": False,
    }


TRANSFER_ENUMS = {
    "state": {"draft": "draft", "черновик": "draft", "ready": "ready", "принят": "ready", "готов": "ready", "excluded": "excluded", "исключен": "excluded"},
    "alpha_result": {"present": "present", "да": "present", "есть": "present", "1": "present", "not_present": "not_present", "нет": "not_present", "0": "not_present", "partial": "partial", "частично": "partial", "not_applicable": "not_applicable", "не применимо": "not_applicable", "needs_clarification": "needs_clarification", "требует уточнения": "needs_clarification"},
    "commission_result": {"confirmed": "confirmed", "принято": "confirmed", "принят": "confirmed", "подтверждено": "confirmed", "1": "confirmed", "not_confirmed": "not_confirmed", "не подтверждено": "not_confirmed", "в доработку": "not_confirmed", "0": "not_confirmed", "deferred": "deferred", "отложено": "deferred", "not_applicable": "not_applicable", "не применимо": "not_applicable", "исключено": "not_applicable"},
    "is_current": {"true": True, "да": True, "1": True, "false": False, "нет": False, "0": False},
    "metric_type": {"verified": "verified", "верифицировано": "verified", "alpha_reviewed": "alpha_reviewed", "альфа-проверка": "alpha_reviewed", "commission_reviewed": "commission_reviewed", "комиссия": "commission_reviewed"},
    "event_type": {"atom_status_changed": "atom_status_changed", "изменение статуса": "atom_status_changed", "alpha_reviewed": "alpha_reviewed", "альфа-проверка": "alpha_reviewed", "commission_reviewed": "commission_reviewed", "комиссия": "commission_reviewed", "assignment": "assignment", "назначение": "assignment"},
    "workflow_stage": {"unassigned": "unassigned", "не назначен": "unassigned", "atomization": "atomization", "атомизация": "atomization", "alpha_review": "alpha_review", "альфа-проверка": "alpha_review", "commission_pending": "commission_pending", "ожидает комиссии": "commission_pending", "fixes_required": "fixes_required", "требуется доработка": "fixes_required", "fixing": "fixing", "доработка": "fixing", "recommission_pending": "recommission_pending", "повторная комиссия": "recommission_pending", "ready": "ready", "готов": "ready"},
}
TRANSFER_ENUMS["previous_state"] = TRANSFER_ENUMS["state"]
TRANSFER_LIMITS = {
    "case_key": 500, "atom_key": 40, "event_key": 500, "assignment_key": 500, "digital_product": 255,
    "title": 500, "source_clause": 500, "work_type": 255, "object_type": 255,
    "system_url": 1000, "assignee_email": 255, "actor_name": 255,
    "contract_reference": 255, "notes": 20000, "source_evidence_text": 20000,
    "alpha_comment": 20000,
}


def normalize_legacy_datasets(data: bytes, datasets: list[dict]) -> dict:
    """Server-only canonical rows; never return these unredacted through an API."""
    if not isinstance(datasets, list) or not 1 <= len(datasets) <= 50:
        _bad("Выберите от одного до 50 наборов данных")
    book = _read_workbook(data)
    sheets = {sheet.id: sheet for sheet in book.sheets}
    records = []
    issues_by_severity = {"error": [], "warning": []}
    counts = {"error_count": 0, "warning_count": 0, "issue_count": 0, "total_rows": 0}

    def issue(sheet_id, row, field, code, message, severity="error"):
        counts["issue_count"] += 1
        counts["error_count" if severity == "error" else "warning_count"] += 1
        group = issues_by_severity[severity]
        if len(group) < MAX_ISSUES:
            group.append({"sheet_id": sheet_id, "row": row, "field": field, "code": code, "severity": severity, "message": message})

    for dataset in datasets:
        if not isinstance(dataset, dict):
            _bad("Некорректный набор данных")
        sheet_id, kind = dataset.get("sheet_id"), dataset.get("kind")
        sheet, header = sheets.get(sheet_id), dataset.get("header_row")
        if sheet is None or kind not in REQUIRED_FIELDS or type(header) is not int or header not in sheet.rows:
            _bad("Выберите существующий лист, строку заголовков и тип данных")
        fields, defaults, value_maps = dataset.get("fields", {}), dataset.get("defaults", {}), dataset.get("value_maps", {})
        if any(not isinstance(value, dict) for value in (fields, defaults, value_maps)):
            _bad("Некорректное сопоставление набора")
        if any(field not in FIELD_ALIASES for source in (fields, defaults, value_maps) for field in source):
            _bad("Неизвестное поле сопоставления")
        columns = {item["column"] for item in _columns(sheet, header)}
        if any(not isinstance(column, str) or column not in columns for column in fields.values()):
            _bad("Выберите существующие столбцы")
        if any(not isinstance(value, str) or len(value) > MAX_TEXT for value in defaults.values()):
            _bad("Некорректное значение по умолчанию")
        translations = {}
        for field, pairs in value_maps.items():
            if field not in TRANSFER_ENUMS or not isinstance(pairs, dict) or len(pairs) > 100:
                _bad("Сопоставление значений доступно только для состояний, этапов и типов событий")
            translated = {}
            for label, target in pairs.items():
                if not isinstance(label, str) or not isinstance(target, str) or len(label) > 500 or _norm(target) not in TRANSFER_ENUMS[field]:
                    _bad("Выберите допустимое целевое значение")
                label_key = _norm(label)
                if label_key in translated and translated[label_key] != _norm(target):
                    _bad("Одинаковым исходным значениям назначены разные состояния")
                translated[label_key] = _norm(target)
            translations[field] = translated
        first = dataset.get("row_from") if dataset.get("row_from") is not None else header + 1
        last = dataset.get("row_to") if dataset.get("row_to") is not None else 1048576
        if type(first) is not int or type(last) is not int or not header < first <= last <= 1048576:
            _bad("Некорректный диапазон строк")
        key_mode = dataset.get("atom_key_mode", "column")
        if key_mode not in {"column", "content"}:
            _bad("Выберите способ определения кода атома")
        for field, column in fields.items():
            cell = sheet.rows.get(header, {}).get(column)
            if cell and (cell.formula or cell.error):
                issue(sheet_id, header, field, "invalid_header", "Заголовок содержит формулу или ошибку Excel")
        if sheet.hidden:
            issue(sheet_id, None, None, "hidden_sheet", "Выбран скрытый лист; подтвердите источник фактов", "warning")
        dataset_rows = 0
        for row, cells in sorted(sheet.rows.items()):
            if not first <= row <= last or not any(cell.value is not None or cell.formula or cell.error for cell in cells.values()):
                continue
            counts["total_rows"] += 1
            dataset_rows += 1
            if counts["total_rows"] > MAX_ROWS:
                _bad("Выбранные наборы превышают 30 000 строк; разделите пакет")
            values = {field: _text(value) for field, value in defaults.items()}
            for field, column in fields.items():
                cell = cells.get(column) or Cell(None)
                values[field] = cell.value or values.get(field)
                if cell.formula or cell.error:
                    issue(sheet_id, row, field, "formula_not_fact" if cell.formula else "excel_error", "Нужны исходные значения, не формула или ошибка Excel")
                    values[field] = None
                if (row, _column_number(column)) in sheet.merged_cells:
                    issue(sheet_id, row, field, "merged_value", "Объединенная ячейка: разверните значения по строкам")
            for field, value in list(values.items()):
                if value is None:
                    continue
                if len(value) > TRANSFER_LIMITS.get(field, 500):
                    issue(sheet_id, row, field, "value_too_long", "Значение превышает допустимую длину поля")
                if field in DATE_FIELDS:
                    value = _date_key(value, book.date1904, timestamp=field in {"occurred_at", "assigned_at", "ended_at"})
                    if value is None:
                        issue(sheet_id, row, field, "invalid_date", "Не распознана дата")
                elif field in TRANSFER_ENUMS:
                    label = _norm(value)
                    label = translations.get(field, {}).get(label, label)
                    if label not in TRANSFER_ENUMS[field]:
                        issue(sheet_id, row, field, "unknown_value", "Неизвестное значение; задайте сопоставление")
                        value = None
                    else:
                        value = TRANSFER_ENUMS[field][label]
                elif field == "value":
                    try:
                        number = Decimal(value)
                        if not number.is_finite() or number != number.to_integral_value() or not 0 <= number <= 1_000_000_000:
                            raise ValueError
                        value = int(number)
                    except (InvalidOperation, ValueError):
                        issue(sheet_id, row, field, "invalid_count", "Нужно целое неотрицательное количество до 1 000 000 000")
                        value = None
                elif field == "assignee_email":
                    value = value.casefold()
                    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
                        issue(sheet_id, row, field, "invalid_email", "Укажите email или перенесите ФИО в поле имени участника")
                elif field == "system_url":
                    try:
                        parsed = urlsplit(value)
                        valid = parsed.scheme in {"http", "https"} and parsed.hostname and not parsed.username and not parsed.password
                    except ValueError:
                        valid = False
                    if not valid:
                        issue(sheet_id, row, field, "invalid_url", "Нужна HTTP(S)-ссылка без учетных данных")
                values[field] = value
            required = set(REQUIRED_FIELDS[kind])
            if kind == "atoms" and key_mode == "content" and not values.get("atom_key"):
                identity = [_norm(str(values.get(field) or "")) for field in ("case_key", "title", "source_clause", "work_type", "object_type")]
                values["atom_key"] = "LEG-" + sha256(json.dumps(identity, ensure_ascii=True).encode()).hexdigest()[:32]
            if kind == "assignments":
                required.discard("assignee_email")
                if not values.get("assignee_email") and not values.get("actor_name"):
                    issue(sheet_id, row, "actor_name", "missing_actor", "Для назначения нужен email или имя исторического участника")
            for field in sorted(required):
                if values.get(field) is None or values.get(field) == "":
                    issue(sheet_id, row, field, "required_value", f"Не заполнено поле: {FIELD_ALIASES[field][0]}")
            if kind == "events":
                event_type = values.get("event_type")
                event_required = {"atom_status_changed": ("atom_key", "previous_state", "state"), "alpha_reviewed": ("atom_key", "alpha_result"), "commission_reviewed": ("atom_key", "commission_result"), "assignment": ()}.get(event_type, ())
                for field in event_required:
                    if not values.get(field):
                        issue(sheet_id, row, field, "event_field_required", f"Для события нужно поле: {FIELD_ALIASES[field][0]}")
            if kind == "atoms" and values.get("state") == "ready" and not values.get("occurred_at"):
                issue(sheet_id, row, "occurred_at", "verification_date_unknown", "Дата верификации неизвестна: состояние сохранится без прироста в день загрузки", "warning")
            if kind == "assignments" and not values.get("is_current"):
                issue(sheet_id, row, "is_current", "historical_assignment", "Назначение сохранится в истории, не в текущем календаре", "warning")
            if kind == "assignments" and values.get("ended_at"):
                if values.get("is_current"):
                    issue(sheet_id, row, "is_current", "ended_current_assignment", "Завершенное назначение не может быть текущим")
                if values.get("assigned_at") and values["ended_at"] < values["assigned_at"]:
                    issue(sheet_id, row, "ended_at", "invalid_assignment_period", "Окончание назначения раньше начала")
            records.append({"kind": kind, "sheet_id": sheet_id, "row": row, "values": values})
        if not dataset_rows:
            issue(sheet_id, None, None, "empty_dataset", "В выбранном диапазоне нет данных")
    issues = (issues_by_severity["error"] + issues_by_severity["warning"])[:MAX_ISSUES]
    return {"parser_version": "a19-transfer-v1", "records": records, "issues": issues, **counts}
