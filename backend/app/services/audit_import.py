"""XLSX preview/commit service for audit atomization slice."""
from __future__ import annotations

import hashlib
import hmac
import io
import posixpath
import re
import uuid
import zipfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from io import BytesIO
from typing import Any
from urllib.parse import urlsplit
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape

from fastapi import HTTPException, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.audit import AuditAtom, AuditCase, AuditEvent, AuditImportBatch
from app.models.user import User
from app.schemas.audit import (
    AuditImportCommitCase,
    AuditImportCommitResponse,
    AuditImportIssue,
    AuditImportPreview,
    AuditImportPreviewGroup,
    AuditImportPreviewRow,
)

OOXML_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_ZIP_MEMBERS = 200
MAX_UNCOMPRESSED_BYTES = 50 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
MAX_SHEETS = 5
MAX_ROWS = 5000
MAX_COLUMNS = 20
MAX_CELL_LENGTH = 20_000
FIELD_MAX_LENGTHS = {
    "Договор": 255,
    "Цифровой продукт": 255,
    "Тип работ": 255,
    "Тип объекта (экран/поток)": 255,
    "Название из договора": 500,
    "Пункт договора": 500,
    "Ссылка на объект в системе": 1000,
    "Наличие объекта в системе": 500,
    "Решение комиссии": 500,
}
SOURCE_SHEET = "5.1 Реестр технических объектов"
EXPECTED_HEADERS = [
    "№",
    "Цифровой продукт",
    "Договор",
    "Дата договора",
    "Тип работ",
    "Тип объекта (экран/поток)",
    "Название из договора",
    "Пункт договора",
    "Ссылка на объект в системе",
    "Наличие объекта в системе",
    "Решение комиссии",
    "Дата альфа проверки",
    "Дата комиссионной проверки",
]
DATE_COLUMNS = {
    "Дата договора",
    "Дата альфа проверки",
    "Дата комиссионной проверки",
}
DISALLOWED_MEMBERS = (
    "xl/externalLinks/",
    "xl/embeddings/",
    "xl/activeX/",
    "xl/queries/",
    "xl/customXml/",
)
DISALLOWED_MEMBER_EXACT = {
    "xl/connections.xml",
    "xl/vbaProject.bin",
}
SYSTEM_URL_SCHEMES = {"http", "https"}


def _xlsx_column_name(column_index: int) -> str:
    letters = ""
    index = column_index
    while True:
        index, remainder = divmod(index, 26)
        letters = chr(ord("A") + remainder) + letters
        if index == 0:
            return letters
        index -= 1


def build_audit_atom_template() -> bytes:
    """Build a macro-free workbook accepted by the deterministic import parser."""
    shared_strings = list(EXPECTED_HEADERS)
    header_cells = "".join(
        f'<c r="{_xlsx_column_name(index)}1" t="s"><v>{index}</v></c>'
        for index in range(len(shared_strings))
    )
    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">'
        + "".join(f"<si><t>{escape(value)}</t></si>" for value in shared_strings)
        + "</sst>"
    )
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        '<cols>'
        + "".join(
            f'<col min="{index + 1}" max="{index + 1}" width="{width}" customWidth="1"/>'
            for index, width in enumerate((7, 24, 22, 15, 20, 24, 42, 22, 34, 24, 24, 18, 22))
        )
        + f'</cols><sheetData><row r="1">{header_cells}</row></sheetData>'
        '<autoFilter ref="A1:M1"/>'
        '</worksheet>'
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{escape(SOURCE_SHEET)}" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" '
        'Target="sharedStrings.xml"/>'
        '</Relationships>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        '</Types>'
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        archive.writestr("xl/sharedStrings.xml", shared_xml)
    return buffer.getvalue()


def build_audit_atom_export(audit_case: AuditCase, atoms: list[AuditAtom]) -> bytes:
    """Build a macro-free snapshot of the reviewed atom registry."""

    headers = [
        "Код аудита",
        "Код атома",
        "Цифровой продукт",
        "Название атома",
        "Тип работ",
        "Тип объекта",
        "Пункт источника",
        "Текстовое основание",
        "Статус",
        "Ссылка на объект в системе",
        "Наличие объекта в системе",
        "Комментарий альфа-проверки",
        "Дата альфа-проверки",
        "Решение комиссии",
        "Дата комиссии",
        "Комментарий",
        "Источник реестра",
    ]

    def clean(value: object | None) -> str:
        if value is None:
            return ""
        if isinstance(value, (date, datetime)):
            value = value.isoformat()
        text_value = str(value)
        return "".join(
            character
            for character in text_value
            if character in "\t\n\r" or ord(character) >= 32
        )[:32_767]

    def cell(reference: str, value: object | None) -> str:
        return f'<c r="{reference}" t="inlineStr"><is><t xml:space="preserve">{escape(clean(value))}</t></is></c>'

    rows = [headers]
    rows.extend(
        [
            audit_case.case_number,
            atom.item_code,
            atom.digital_product,
            atom.title,
            atom.work_type,
            atom.object_type,
            atom.source_clause,
            atom.source_evidence_text,
            atom.state,
            atom.system_url,
            atom.alpha_result_raw or atom.alpha_result,
            getattr(atom, "alpha_comment", None),
            atom.alpha_date,
            atom.commission_result_raw or atom.commission_result,
            atom.commission_date,
            atom.notes,
            atom.source_sheet,
        ]
        for atom in atoms
    )
    row_xml = "".join(
        f'<row r="{row_index}">'
        + "".join(
            cell(f"{_xlsx_column_name(column_index)}{row_index}", value)
            for column_index, value in enumerate(row)
        )
        + "</row>"
        for row_index, row in enumerate(rows, start=1)
    )
    last_column = _xlsx_column_name(len(headers) - 1)
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>'
        '<cols>'
        + "".join(
            f'<col min="{index + 1}" max="{index + 1}" width="{width}" customWidth="1"/>'
            for index, width in enumerate((15, 15, 24, 48, 22, 22, 28, 72, 16, 36, 24, 20, 24, 20, 40, 24))
        )
        + f'</cols><sheetData>{row_xml}</sheetData>'
        f'<autoFilter ref="A1:{last_column}{max(1, len(rows))}"/>'
        '</worksheet>'
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Генеральный реестр" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        '</Relationships>'
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        '</Relationships>'
    )
    content_types = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '</Types>'
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
    return buffer.getvalue()


@dataclass
class ParsedAuditRow:
    row_number: int
    item_code: str
    contract_reference_raw: str | None
    contract_reference_mask: str | None
    contract_reference_fingerprint: str | None
    contract_date: date | None
    title: str | None
    digital_product: str | None
    work_type: str | None
    object_type: str | None
    source_clause: str | None
    system_url: str | None
    system_url_mask: str | None
    source_sheet: str
    source_row: int | None
    alpha_result: str | None
    alpha_result_raw: str | None
    alpha_date: date | None
    commission_result: str | None
    commission_result_raw: str | None
    commission_date: date | None
    source_fingerprint: str | None
    issues: list[AuditImportIssue]

    @property
    def is_valid(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)

    @property
    def has_warnings(self) -> bool:
        return any(issue.severity == "warning" for issue in self.issues)


@dataclass
class ParsedWorkbook:
    sha256: str
    filename: str | None
    file_size_bytes: int
    source_sheet: str
    rows: list[ParsedAuditRow]

    @property
    def total_rows(self) -> int:
        return len(self.rows)

    @property
    def valid_rows(self) -> int:
        return sum(1 for row in self.rows if row.is_valid)

    @property
    def error_rows(self) -> int:
        return self.total_rows - self.valid_rows

    @property
    def warning_rows(self) -> int:
        return sum(row.has_warnings for row in self.rows)

    def to_preview(self) -> AuditImportPreview:
        groups: dict[str, dict[str, Any]] = defaultdict(
            lambda: {
                "contract_reference_mask": None,
                "total_rows": 0,
                "valid_rows": 0,
                "error_rows": 0,
                "warning_rows": 0,
                "digital_products": set(),
            }
        )
        group_keys = sorted(
            {
                row.contract_reference_fingerprint or f"unknown:{row.row_number}"
                for row in self.rows
            }
        )
        group_ids = {key: f"contract-{index:03d}" for index, key in enumerate(group_keys, start=1)}
        preview_rows: list[AuditImportPreviewRow] = []
        for row in self.rows:
            group_key = row.contract_reference_fingerprint or f"unknown:{row.row_number}"
            group = groups[group_key]
            group["contract_reference_mask"] = row.contract_reference_mask
            group["total_rows"] += 1
            group["valid_rows"] += int(row.is_valid)
            group["error_rows"] += int(not row.is_valid)
            group["warning_rows"] += int(row.has_warnings)
            if row.digital_product:
                group["digital_products"].add(row.digital_product)
            preview_rows.append(
                AuditImportPreviewRow(
                    group_id=group_ids[group_key],
                    row_number=row.row_number,
                    item_code=row.item_code,
                    contract_reference_mask=row.contract_reference_mask,
                    contract_date=row.contract_date,
                    title=row.title,
                    digital_product=row.digital_product,
                    work_type=row.work_type,
                    object_type=row.object_type,
                    source_clause=row.source_clause,
                    system_url_mask=row.system_url_mask,
                    state="draft",
                    source_sheet=row.source_sheet,
                    source_row=row.source_row,
                    alpha_result=row.alpha_result,
                    alpha_result_raw=row.alpha_result_raw,
                    alpha_date=row.alpha_date,
                    commission_result=row.commission_result,
                    commission_result_raw=row.commission_result_raw,
                    commission_date=row.commission_date,
                    issues=row.issues,
                )
            )
        grouped_counts = [
            AuditImportPreviewGroup(
                group_id=group_ids[group_key],
                contract_reference_mask=data["contract_reference_mask"] or "Не указан",
                total_rows=data["total_rows"],
                valid_rows=data["valid_rows"],
                error_rows=data["error_rows"],
                warning_rows=data["warning_rows"],
                digital_products=sorted(data["digital_products"]),
            )
            for group_key, data in sorted(groups.items(), key=lambda item: group_ids[item[0]])
        ]
        return AuditImportPreview(
            sha256=self.sha256,
            source_sheet=self.source_sheet,
            total_rows=self.total_rows,
            valid_rows=self.valid_rows,
            error_rows=self.error_rows,
            warning_rows=self.warning_rows,
            has_errors=self.error_rows > 0,
            grouped_counts=grouped_counts,
            rows=preview_rows,
        )


def normalize_contract_reference(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = re.sub(r"\s+", " ", value).strip().upper()
    return cleaned or None


def mask_contract_reference(value: str | None) -> str | None:
    normalized = normalize_contract_reference(value)
    if not normalized:
        return None
    compact = re.sub(r"\s+", "", normalized)
    if len(compact) <= 4:
        return "*" * len(compact)
    return f"{compact[:2]}****{compact[-2:]}"


def fingerprint_contract_reference(value: str | None) -> str | None:
    normalized = normalize_contract_reference(value)
    if not normalized:
        return None
    return hmac.new(
        settings.DPMS_SECRET_KEY.encode("utf-8"),
        normalized.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def mask_system_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in SYSTEM_URL_SCHEMES or not parsed.netloc:
        return None
    path = parsed.path or "/"
    if path == "/":
        masked_path = "/"
    else:
        parts = [part for part in path.split("/") if part]
        masked_path = "/" + "/".join(part[:2] + "***" if len(part) > 2 else "***" for part in parts[:2])
        if len(parts) > 2:
            masked_path += "/..."
    return f"{parsed.scheme.lower()}://{parsed.netloc}{masked_path}"


def build_contract_fields(contract_reference: str | None) -> tuple[str | None, str | None]:
    return fingerprint_contract_reference(contract_reference), mask_contract_reference(contract_reference)


def normalize_text(value: Any) -> str | None:
    if value is None:
        return None
    text_value = re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()
    if len(text_value) > MAX_CELL_LENGTH:
        raise HTTPException(status_code=400, detail="XLSX содержит слишком длинную ячейку")
    return text_value or None


def add_max_length_issue(
    value: str | None,
    *,
    row_number: int,
    field: str,
    issues: list[AuditImportIssue],
) -> None:
    max_length = FIELD_MAX_LENGTHS[field]
    if value is not None and len(value) > max_length:
        issues.append(
            AuditImportIssue(
                row_number=row_number,
                field=field,
                message=f"Допускается не более {max_length} символов (сейчас {len(value)})",
            )
        )


def normalize_url(value: Any, row_number: int, issues: list[AuditImportIssue]) -> str | None:
    url = normalize_text(value)
    if url is None:
        return None
    parsed = urlsplit(url)
    if parsed.scheme.lower() not in SYSTEM_URL_SCHEMES or not parsed.netloc:
        issues.append(
            AuditImportIssue(
                row_number=row_number,
                field="Ссылка на объект в системе",
                message="Поддерживаются только абсолютные http/https ссылки",
            )
        )
        return None
    return url


def normalize_result_code(value: Any, *, row_number: int, field: str, mapping: dict[str, str], issues: list[AuditImportIssue]) -> str | None:
    text_value = normalize_text(value)
    if text_value is None:
        return None
    normalized = text_value.lower().replace(" ", "_")
    if normalized in mapping:
        return mapping[normalized]
    # Legacy result text is retained separately. Unknown labels must not block atomization.
    return None


def build_source_fingerprint(
    *,
    contract_reference_fingerprint: str | None,
    digital_product: str | None,
    work_type: str | None,
    object_type: str | None,
    title: str | None,
    source_clause: str | None,
    source_sheet: str | None,
) -> str | None:
    parts = [
        contract_reference_fingerprint or "",
        (digital_product or "").strip().casefold(),
        (work_type or "").strip().casefold(),
        (object_type or "").strip().casefold(),
        (title or "").strip().casefold(),
        (source_clause or "").strip().casefold(),
        (source_sheet or "").strip().casefold(),
    ]
    if not any(parts):
        return None
    payload = "\u241f".join(parts)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def excel_serial_to_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    try:
        serial = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    if not serial.is_finite():
        return None
    base = date(1899, 12, 30)
    try:
        return base + timedelta(days=int(serial))
    except (OverflowError, ValueError):
        return None


def parse_excel_date(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    serial_date = excel_serial_to_date(value)
    if serial_date is not None:
        return serial_date
    text_value = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text_value, fmt).date()
        except ValueError:
            continue
    return None


def build_case_title_for_import(digital_products: set[str], contract_mask: str | None) -> str:
    if len(digital_products) == 1:
        return f"Аудит: {next(iter(digital_products))}"[:255]
    if contract_mask:
        return f"Аудит: {contract_mask}"
    return "Аудит: импортированный договор"


def choose_contract_date(rows: list[ParsedAuditRow]) -> date | None:
    counts = Counter(row.contract_date for row in rows if row.contract_date is not None)
    if not counts:
        return None
    return sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0][0]


def build_manual_source_fingerprint(atom: AuditAtom | ParsedAuditRow) -> str | None:
    return build_source_fingerprint(
        contract_reference_fingerprint=None,
        digital_product=getattr(atom, "digital_product", None),
        work_type=getattr(atom, "work_type", None),
        object_type=getattr(atom, "object_type", None),
        title=getattr(atom, "title", None),
        source_clause=getattr(atom, "source_clause", None),
        source_sheet=getattr(atom, "source_sheet", None),
    )


def _validate_zip_member(name: str) -> None:
    if name.startswith("/") or name.startswith("\\"):
        raise HTTPException(status_code=400, detail="Недопустимый путь внутри XLSX")
    normalized = posixpath.normpath(name)
    if normalized.startswith("../") or normalized == "..":
        raise HTTPException(status_code=400, detail="Недопустимый путь внутри XLSX")
    lowered = name.casefold()
    if any(lowered.startswith(prefix.casefold()) for prefix in DISALLOWED_MEMBERS):
        raise HTTPException(status_code=400, detail="XLSX содержит запрещенные внешние или встроенные объекты")
    if any(lowered == item.casefold() for item in DISALLOWED_MEMBER_EXACT) or "vbaproject" in lowered:
        raise HTTPException(status_code=400, detail="XLSX с макросами не поддерживается")


def _xml_root(data: bytes, label: str) -> ET.Element:
    head = data[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in head:
        raise HTTPException(status_code=400, detail="XLSX содержит недопустимую XML-конструкцию")
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise HTTPException(status_code=400, detail=f"Не удалось прочитать структуру XLSX: {label}") from exc


def _load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []
    root = _xml_root(archive.read("xl/sharedStrings.xml"), "shared strings")
    values: list[str] = []
    for item in root:
        parts = [node.text or "" for node in item.iter(f"{OOXML_NS}t")]
        value = "".join(parts)
        if len(value) > MAX_CELL_LENGTH:
            raise HTTPException(status_code=400, detail="XLSX содержит слишком длинную ячейку")
        values.append(value)
        if len(values) > MAX_ROWS * MAX_COLUMNS:
            raise HTTPException(status_code=400, detail="XLSX содержит слишком много текстовых значений")
    return values


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str | None:
    inline = cell.find(f"{OOXML_NS}is")
    if inline is not None:
        return "".join(node.text or "" for node in inline.iter(f"{OOXML_NS}t"))
    value_node = cell.find(f"{OOXML_NS}v")
    if value_node is None:
        return None
    value = value_node.text
    if value is None:
        return None
    if cell.attrib.get("t") == "s":
        try:
            index = int(value)
            if index < 0:
                raise ValueError
            return shared_strings[index]
        except (ValueError, IndexError) as exc:
            raise HTTPException(status_code=400, detail="XLSX содержит некорректную ссылку на текстовую ячейку") from exc
    return value


def _worksheet_rows(worksheet_xml: bytes, shared_strings: list[str]) -> tuple[dict[int, dict[str, str | None]], dict[tuple[int, str], bool]]:
    root = _xml_root(worksheet_xml, "worksheet")
    rows: dict[int, dict[str, str | None]] = {}
    formulas: dict[tuple[int, str], bool] = {}
    for row_node in root.iter(f"{OOXML_NS}row"):
        if len(rows) >= MAX_ROWS:
            raise HTTPException(status_code=400, detail=f"В реестре допускается не более {MAX_ROWS} строк")
        try:
            row_number = int(row_node.attrib["r"])
        except (KeyError, ValueError) as exc:
            raise HTTPException(status_code=400, detail="XLSX содержит строку без корректного номера") from exc
        if row_number < 1:
            raise HTTPException(status_code=400, detail="XLSX содержит некорректный номер строки")
        row_map: dict[str, str | None] = {}
        for cell in row_node.findall(f"{OOXML_NS}c"):
            ref = cell.attrib.get("r", "")
            column = "".join(char for char in ref if char.isalpha())
            if not column:
                continue
            column_number = 0
            for char in column.upper():
                column_number = column_number * 26 + ord(char) - ord("A") + 1
            if column_number > MAX_COLUMNS:
                raise HTTPException(status_code=400, detail=f"В реестре допускается не более {MAX_COLUMNS} колонок")
            if cell.find(f"{OOXML_NS}f") is not None:
                formulas[(row_number, column)] = True
            row_map[column] = _cell_value(cell, shared_strings)
        rows[row_number] = row_map
    return rows, formulas


def _resolve_first_sheet(archive: zipfile.ZipFile) -> tuple[str, bytes]:
    try:
        workbook_data = archive.read("xl/workbook.xml")
        relations_data = archive.read("xl/_rels/workbook.xml.rels")
    except (KeyError, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=400, detail="XLSX не содержит обязательную структуру книги") from exc
    workbook = _xml_root(workbook_data, "workbook")
    workbook_rels = _xml_root(relations_data, "workbook relations")
    rel_map = {
        node.attrib.get("Id", ""): (node.attrib.get("Target", ""), node.attrib.get("TargetMode"))
        for node in workbook_rels
        if node.attrib.get("Id")
    }
    sheets = workbook.find(f"{OOXML_NS}sheets")
    if sheets is None or not list(sheets):
        raise HTTPException(status_code=400, detail="XLSX не содержит листов")
    if len(list(sheets)) > MAX_SHEETS:
        raise HTTPException(status_code=400, detail=f"В XLSX допускается не более {MAX_SHEETS} листов")
    source_sheet = next((sheet for sheet in sheets if sheet.attrib.get("name") == SOURCE_SHEET), None)
    if source_sheet is None:
        raise HTTPException(status_code=400, detail=f"Не найден лист «{SOURCE_SHEET}»")
    sheet_name = source_sheet.attrib.get("name", SOURCE_SHEET)
    rel_id = source_sheet.attrib.get(f"{REL_NS}id")
    relation = rel_map.get(rel_id or "")
    if not relation or relation[1] == "External":
        raise HTTPException(status_code=400, detail="Не удалось прочитать исходный лист XLSX")
    target = relation[0]
    target_path = target.lstrip("/") if target.startswith("/") else posixpath.normpath(f"xl/{target}")
    if not target_path.startswith("xl/worksheets/"):
        raise HTTPException(status_code=400, detail="Некорректная связь исходного листа XLSX")
    try:
        return sheet_name, archive.read(target_path)
    except (KeyError, zipfile.BadZipFile) as exc:
        raise HTTPException(status_code=400, detail="Не удалось прочитать исходный лист XLSX") from exc


def parse_audit_xlsx_bytes(data: bytes, filename: str | None = None) -> ParsedWorkbook:
    safe_filename = (filename or "audit.xlsx").replace("\\", "/").rsplit("/", 1)[-1][:255]
    if not safe_filename.casefold().endswith(".xlsx"):
        raise HTTPException(status_code=400, detail="Поддерживается только файл .xlsx")
    if not data:
        raise HTTPException(status_code=400, detail="Файл пустой")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=400, detail="XLSX слишком большой: максимум 10 МБ")
    if not data.startswith(b"PK\x03\x04"):
        raise HTTPException(status_code=400, detail="Файл не является корректным XLSX")
    sha256 = hashlib.sha256(data).hexdigest()
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise HTTPException(status_code=400, detail="Файл не является корректным XLSX") from exc
    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_ZIP_MEMBERS:
            raise HTTPException(status_code=400, detail="XLSX содержит слишком много внутренних файлов")
        total_uncompressed = 0
        for info in infos:
            _validate_zip_member(info.filename)
            if info.flag_bits & 0x1:
                raise HTTPException(status_code=400, detail="Зашифрованные XLSX не поддерживаются")
            total_uncompressed += info.file_size
            if total_uncompressed > MAX_UNCOMPRESSED_BYTES:
                raise HTTPException(status_code=400, detail="XLSX слишком большой после распаковки")
            if info.file_size > 0:
                if info.compress_size == 0 or info.file_size / max(info.compress_size, 1) > MAX_COMPRESSION_RATIO:
                    raise HTTPException(status_code=400, detail="XLSX отклонен по признакам zip bomb")
        try:
            shared_strings = _load_shared_strings(archive)
            source_sheet, worksheet_xml = _resolve_first_sheet(archive)
            rows_map, formulas = _worksheet_rows(worksheet_xml, shared_strings)
        except zipfile.BadZipFile as exc:
            raise HTTPException(status_code=400, detail="Не удалось прочитать поврежденный XLSX") from exc
    header_row_number = None
    header_columns = [chr(ord("A") + idx) for idx in range(len(EXPECTED_HEADERS))]
    for row_number in sorted(rows_map):
        candidate = [rows_map[row_number].get(column) or "" for column in header_columns]
        if candidate == EXPECTED_HEADERS:
            header_row_number = row_number
            break
    if header_row_number is None:
        raise HTTPException(status_code=400, detail=f"Заголовки листа «{SOURCE_SHEET}» не совпадают с шаблоном audit_example.xlsx")

    alpha_mapping = {
        "1": "present",
        "0": "not_present",
        "да": "present",
        "есть": "present",
        "имеется": "present",
        "подтверждено": "present",
        "нет": "not_present",
        "отсутствует": "not_present",
        "частично": "partial",
        "не_применимо": "not_applicable",
        "не_требуется": "not_applicable",
        "требуется_уточнение": "needs_clarification",
        "present": "present",
        "not_present": "not_present",
        "partial": "partial",
        "not_applicable": "not_applicable",
        "needs_clarification": "needs_clarification",
    }
    commission_mapping = {
        "1": "confirmed",
        "0": "not_confirmed",
        "да": "confirmed",
        "принято": "confirmed",
        "подтверждено": "confirmed",
        "согласовано": "confirmed",
        "нет": "not_confirmed",
        "не_принято": "not_confirmed",
        "не_подтверждено": "not_confirmed",
        "отклонено": "not_confirmed",
        "перенесено": "deferred",
        "отложено": "deferred",
        "не_применимо": "not_applicable",
        "не_требуется": "not_applicable",
        "confirmed": "confirmed",
        "not_confirmed": "not_confirmed",
        "deferred": "deferred",
        "not_applicable": "not_applicable",
    }
    parsed_rows: list[ParsedAuditRow] = []
    for row_number in sorted(number for number in rows_map if number > header_row_number):
        row = rows_map[row_number]
        values = {header: row.get(column) for header, column in zip(EXPECTED_HEADERS, header_columns, strict=True)}
        if not any(normalize_text(value) for value in values.values()):
            continue
        issues: list[AuditImportIssue] = []
        for header, column in zip(EXPECTED_HEADERS, header_columns, strict=True):
            if formulas.get((row_number, column)):
                issues.append(
                    AuditImportIssue(
                        row_number=row_number,
                        field=header,
                        message="Формулы в основной таблице запрещены",
                    )
                )
        # Колонка «№» — только порядок в исходной таблице, не идентификатор атома.
        source_row = row_number
        item_code = f"NEW-R{row_number}"
        contract_reference = normalize_text(values["Договор"])
        contract_fingerprint, contract_mask = build_contract_fields(contract_reference)
        contract_date = parse_excel_date(values["Дата договора"])
        if values["Дата договора"] not in (None, "") and contract_date is None:
            issues.append(
                AuditImportIssue(
                    row_number=row_number,
                    field="Дата договора",
                    message="Дата договора должна быть Excel serial date или строкой даты",
                )
            )
        title = normalize_text(values["Название из договора"])
        digital_product = normalize_text(values["Цифровой продукт"])
        work_type = normalize_text(values["Тип работ"])
        object_type = normalize_text(values["Тип объекта (экран/поток)"])
        source_clause = normalize_text(values["Пункт договора"])
        system_url = normalize_url(values["Ссылка на объект в системе"], row_number, issues)
        system_url_mask = mask_system_url(system_url)
        alpha_result_raw = normalize_text(values["Наличие объекта в системе"])
        alpha_result = normalize_result_code(
            alpha_result_raw,
            row_number=row_number,
            field="Наличие объекта в системе",
            mapping=alpha_mapping,
            issues=issues,
        )
        commission_result_raw = normalize_text(values["Решение комиссии"])
        commission_result = normalize_result_code(
            commission_result_raw,
            row_number=row_number,
            field="Решение комиссии",
            mapping=commission_mapping,
            issues=issues,
        )
        alpha_date = parse_excel_date(values["Дата альфа проверки"])
        if values["Дата альфа проверки"] not in (None, "") and alpha_date is None:
            issues.append(
                AuditImportIssue(
                    row_number=row_number,
                    field="Дата альфа проверки",
                    message="Дата альфа проверки должна быть Excel serial date или строкой даты",
                )
            )
        commission_date = parse_excel_date(values["Дата комиссионной проверки"])
        if values["Дата комиссионной проверки"] not in (None, "") and commission_date is None:
            issues.append(
                AuditImportIssue(
                    row_number=row_number,
                    field="Дата комиссионной проверки",
                    message="Дата комиссионной проверки должна быть Excel serial date или строкой даты",
                )
            )
        if contract_reference is None:
            issues.append(
                AuditImportIssue(row_number=row_number, field="Договор", message="Номер договора обязателен")
            )
        if digital_product is None:
            issues.append(
                AuditImportIssue(
                    row_number=row_number,
                    field="Цифровой продукт",
                    message="Цифровой продукт обязателен",
                )
            )
        if title is None:
            issues.append(
                AuditImportIssue(
                    row_number=row_number,
                    field="Название из договора",
                    message="Название из договора обязательно",
                )
            )
        for field, value in (
            ("Договор", contract_reference),
            ("Цифровой продукт", digital_product),
            ("Тип работ", work_type),
            ("Тип объекта (экран/поток)", object_type),
            ("Название из договора", title),
            ("Пункт договора", source_clause),
            ("Ссылка на объект в системе", system_url),
            ("Наличие объекта в системе", alpha_result_raw),
            ("Решение комиссии", commission_result_raw),
        ):
            add_max_length_issue(value, row_number=row_number, field=field, issues=issues)
        parsed_rows.append(
            ParsedAuditRow(
                row_number=row_number,
                item_code=item_code,
                contract_reference_raw=contract_reference,
                contract_reference_mask=contract_mask,
                contract_reference_fingerprint=contract_fingerprint,
                contract_date=contract_date,
                title=title,
                digital_product=digital_product,
                work_type=work_type,
                object_type=object_type,
                source_clause=source_clause,
                system_url=system_url,
                system_url_mask=system_url_mask,
                source_sheet=source_sheet,
                source_row=source_row,
                alpha_result=alpha_result,
                alpha_result_raw=alpha_result_raw,
                alpha_date=alpha_date,
                commission_result=commission_result,
                commission_result_raw=commission_result_raw,
                commission_date=commission_date,
                source_fingerprint=build_source_fingerprint(
                    contract_reference_fingerprint=contract_fingerprint,
                    digital_product=digital_product,
                    work_type=work_type,
                    object_type=object_type,
                    title=title,
                    source_clause=source_clause,
                    source_sheet=source_sheet,
                ),
                issues=issues,
            )
        )

    rows_by_source: dict[str, list[ParsedAuditRow]] = defaultdict(list)
    rows_by_contract: dict[str, list[ParsedAuditRow]] = defaultdict(list)
    for parsed_row in parsed_rows:
        if parsed_row.source_fingerprint:
            rows_by_source[parsed_row.source_fingerprint].append(parsed_row)
        if parsed_row.contract_reference_fingerprint:
            rows_by_contract[parsed_row.contract_reference_fingerprint].append(parsed_row)

    for duplicate_rows in rows_by_source.values():
        if len(duplicate_rows) < 2:
            continue
        source_rows = ", ".join(str(row.row_number) for row in duplicate_rows)
        for duplicate_row in duplicate_rows:
            duplicate_row.issues.append(
                AuditImportIssue(
                    row_number=duplicate_row.row_number,
                    field="Название из договора",
                    message=f"Один и тот же атом повторяется в строках {source_rows}",
                )
            )

    for contract_rows in rows_by_contract.values():
        contract_dates = {row.contract_date for row in contract_rows if row.contract_date is not None}
        if len(contract_dates) < 2:
            continue
        selected_date = choose_contract_date(contract_rows)
        for contract_row in contract_rows:
            if contract_row.contract_date is None or contract_row.contract_date == selected_date:
                continue
            contract_row.issues.append(
                AuditImportIssue(
                    row_number=contract_row.row_number,
                    field="Дата договора",
                    message=f"Отличается от даты карточки {selected_date.strftime('%d.%m.%Y') if selected_date else '—'}",
                    severity="warning",
                )
            )
    return ParsedWorkbook(
        sha256=sha256,
        filename=safe_filename,
        file_size_bytes=len(data),
        source_sheet=source_sheet,
        rows=parsed_rows,
    )


async def parse_audit_upload(upload: UploadFile) -> ParsedWorkbook:
    data = await upload.read(MAX_UPLOAD_BYTES + 1)
    await upload.close()
    return parse_audit_xlsx_bytes(data, upload.filename)


async def generate_next_item_code(db: AsyncSession, case_id: uuid.UUID) -> str:
    result = await db.execute(
        select(AuditAtom.item_code)
        .where(AuditAtom.case_id == case_id, AuditAtom.item_code.like("ITEM-%"))
        .order_by(AuditAtom.item_code.desc())
        .limit(1)
    )
    current = result.scalar_one_or_none()
    if not current:
        return "ITEM-001"
    try:
        next_number = int(current.split("-")[-1]) + 1
    except ValueError:
        next_number = 1
    return f"ITEM-{next_number:03d}"


def record_audit_event(
    db: AsyncSession,
    *,
    case_id: uuid.UUID,
    actor_id: uuid.UUID | None,
    event_type: str,
    message: str,
    atom_id: uuid.UUID | None = None,
    import_batch_id: uuid.UUID | None = None,
    payload_json: dict | None = None,
) -> AuditEvent:
    event = AuditEvent(
        case_id=case_id,
        atom_id=atom_id,
        import_batch_id=import_batch_id,
        actor_id=actor_id,
        event_type=event_type,
        message=message,
        payload_json=payload_json,
    )
    db.add(event)
    return event


def _same_atom_payload(atom: AuditAtom, row: ParsedAuditRow) -> bool:
    return (
        atom.title == row.title
        and atom.digital_product == row.digital_product
        and atom.work_type == row.work_type
        and atom.object_type == row.object_type
        and atom.source_clause == row.source_clause
        and atom.system_url == row.system_url
        and atom.source_sheet == row.source_sheet
        and atom.source_row == row.source_row
        and atom.alpha_result == row.alpha_result
        and atom.alpha_result_raw == row.alpha_result_raw
        and atom.alpha_date == row.alpha_date
        and atom.commission_result == row.commission_result
        and atom.commission_result_raw == row.commission_result_raw
        and atom.commission_date == row.commission_date
    )


async def _validate_target_case_import(
    db: AsyncSession,
    parsed: ParsedWorkbook,
    target_case_id: uuid.UUID,
    *,
    lock: bool,
) -> AuditCase:
    query = select(AuditCase).where(AuditCase.id == target_case_id)
    if lock:
        query = query.with_for_update()
    target_case = await db.scalar(query)
    if target_case is None:
        raise HTTPException(status_code=404, detail="Аудит не найден")
    if target_case.status == "archived":
        raise HTTPException(status_code=409, detail="Нельзя импортировать атомы в архивный аудит")

    fingerprints = {
        row.contract_reference_fingerprint
        for row in parsed.rows
        if row.contract_reference_fingerprint
    }
    if len(fingerprints) > 1:
        raise HTTPException(
            status_code=422,
            detail="В карточку одного договора можно загрузить реестр только по одному договору",
        )
    if not fingerprints:
        return target_case

    fingerprint = next(iter(fingerprints))
    if (
        target_case.contract_reference_fingerprint
        and target_case.contract_reference_fingerprint != fingerprint
    ):
        raise HTTPException(
            status_code=409,
            detail="Договор в Excel не совпадает с выбранной карточкой аудита",
        )
    duplicate_case_id = await db.scalar(
        select(AuditCase.id).where(
            AuditCase.contract_reference_fingerprint == fingerprint,
            AuditCase.id != target_case.id,
        )
    )
    if duplicate_case_id is not None:
        raise HTTPException(
            status_code=409,
            detail="Для договора из Excel уже существует другая карточка аудита",
        )

    workbook_date = choose_contract_date(parsed.rows)
    if target_case.contract_date and workbook_date and target_case.contract_date != workbook_date:
        raise HTTPException(
            status_code=409,
            detail="Дата договора в Excel не совпадает с выбранной карточкой аудита",
        )
    return target_case


async def preview_audit_import(
    db: AsyncSession,
    upload: UploadFile,
    user: User,
    target_case_id: uuid.UUID | None = None,
) -> AuditImportPreview:
    del user
    parsed = await parse_audit_upload(upload)
    if target_case_id is not None:
        await _validate_target_case_import(db, parsed, target_case_id, lock=False)
    return parsed.to_preview()


async def commit_audit_import(
    db: AsyncSession,
    upload: UploadFile,
    user: User,
    expected_sha256: str,
    target_case_id: uuid.UUID | None = None,
) -> AuditImportCommitResponse:
    parsed = await parse_audit_upload(upload)
    if parsed.sha256 != expected_sha256.strip().lower():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="SHA-256 файла не совпадает с ожидаемым значением preview",
        )
    if parsed.error_rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Импорт содержит ошибки. Исправьте файл и запустите preview заново.",
        )

    target_case = None
    if target_case_id is not None:
        target_case = await _validate_target_case_import(
            db,
            parsed,
            target_case_id,
            lock=True,
        )

    existing_batch_result = await db.execute(
        select(AuditImportBatch).where(AuditImportBatch.sha256 == parsed.sha256)
    )
    existing_batch = existing_batch_result.scalar_one_or_none()
    if existing_batch is not None:
        summary = existing_batch.summary_json or {}
        existing_cases = [AuditImportCommitCase(**item) for item in summary.get("cases", [])]
        if target_case_id is not None and (
            len(existing_cases) != 1 or existing_cases[0].case_id != target_case_id
        ):
            raise HTTPException(
                status_code=409,
                detail="Этот Excel уже был импортирован в другую карточку аудита",
            )
        reused_cases = [
            item.model_copy(
                update={
                    "created": False,
                    "atoms_created": 0,
                    "atoms_reused": item.atoms_created + item.atoms_reused,
                }
            )
            for item in existing_cases
        ]
        return AuditImportCommitResponse(
            batch_id=existing_batch.id,
            sha256=existing_batch.sha256,
            already_committed=True,
            case_count=int(summary.get("case_count", 0)),
            created_case_count=0,
            created_atom_count=0,
            reused_atom_count=sum(item.atoms_reused for item in reused_cases),
            cases=reused_cases,
        )

    batch = AuditImportBatch(
        sha256=parsed.sha256,
        # A filename can contain a confidential contract number, so it is not persisted.
        source_filename=None,
        source_sheet=parsed.source_sheet,
        file_size_bytes=parsed.file_size_bytes,
        total_rows=parsed.total_rows,
        valid_rows=parsed.valid_rows,
        error_rows=parsed.error_rows,
        status="committed",
        created_by_id=user.id,
        summary_json={},
    )
    db.add(batch)
    await db.flush()

    grouped_rows: dict[str, list[ParsedAuditRow]] = defaultdict(list)
    for row in parsed.rows:
        grouped_rows[row.contract_reference_fingerprint or f"unknown:{row.row_number}"].append(row)

    commit_cases: list[AuditImportCommitCase] = []
    created_case_count = 0
    created_atom_count = 0
    reused_atom_count = 0

    for contract_fingerprint, group_rows in grouped_rows.items():
        first_row = group_rows[0]
        group_contract_date = choose_contract_date(group_rows)
        if target_case is not None:
            case = target_case
        else:
            case_result = await db.execute(
                select(AuditCase).where(AuditCase.contract_reference_fingerprint == contract_fingerprint)
            )
            case = case_result.scalar_one_or_none()
        case_created = False
        if case is None:
            digital_products = {row.digital_product for row in group_rows if row.digital_product}
            case = AuditCase(
                created_by_id=user.id,
                title=build_case_title_for_import(digital_products, first_row.contract_reference_mask),
                digital_product=next(iter(digital_products)) if len(digital_products) == 1 else "Несколько продуктов",
                contract_reference_fingerprint=first_row.contract_reference_fingerprint,
                contract_reference_mask=first_row.contract_reference_mask,
                contract_date=group_contract_date,
                status="atomization",
                notes="Создано из импортированного реестра технических объектов.",
            )
            db.add(case)
            await db.flush()
            case_created = True
            created_case_count += 1
            record_audit_event(
                db,
                case_id=case.id,
                actor_id=user.id,
                event_type="case_imported",
                message="Карточка аудита создана из XLSX-импорта",
                import_batch_id=batch.id,
                payload_json={"sha256": parsed.sha256},
            )
        elif case.contract_date and group_contract_date and case.contract_date != group_contract_date:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Дата договора для строки {first_row.row_number} не совпадает с существующим аудитом",
            )
        elif case.contract_date is None and group_contract_date is not None:
            case.contract_date = group_contract_date

        if target_case is not None and case.contract_reference_fingerprint is None:
            case.contract_reference_fingerprint = first_row.contract_reference_fingerprint
            case.contract_reference_mask = first_row.contract_reference_mask
        digital_products = {row.digital_product for row in group_rows if row.digital_product}
        if case.digital_product == "Требует заполнения" and len(digital_products) == 1:
            case.digital_product = next(iter(digital_products))
            if case.title.startswith("Аудит:"):
                case.title = f"Аудит: {case.digital_product}"

        group_created = 0
        group_reused = 0
        for row in group_rows:
            if row.source_fingerprint:
                existing_atom_result = await db.execute(
                    select(AuditAtom).where(
                        AuditAtom.case_id == case.id,
                        AuditAtom.source_fingerprint == row.source_fingerprint,
                    )
                )
                existing_atom = existing_atom_result.scalar_one_or_none()
            else:
                existing_atom = None
            if existing_atom is not None:
                if not _same_atom_payload(existing_atom, row):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail=f"Для строки {row.row_number} уже существует конфликтующий атом",
                    )
                group_reused += 1
                reused_atom_count += 1
                continue

            item_code = await generate_next_item_code(db, case.id)

            atom = AuditAtom(
                case_id=case.id,
                item_code=item_code,
                title=row.title or "Без названия",
                digital_product=row.digital_product or case.digital_product,
                work_type=row.work_type,
                object_type=row.object_type,
                source_clause=row.source_clause,
                system_url=row.system_url,
                state="draft",
                source_sheet=row.source_sheet,
                source_row=row.source_row,
                source_fingerprint=row.source_fingerprint,
                import_batch_id=batch.id,
                alpha_result=row.alpha_result,
                alpha_result_raw=row.alpha_result_raw,
                alpha_date=row.alpha_date,
                commission_result=row.commission_result,
                commission_result_raw=row.commission_result_raw,
                commission_date=row.commission_date,
                sort_order=row.source_row or row.row_number,
            )
            db.add(atom)
            await db.flush()
            group_created += 1
            created_atom_count += 1
            record_audit_event(
                db,
                case_id=case.id,
                actor_id=user.id,
                atom_id=atom.id,
                import_batch_id=batch.id,
                event_type="atom_imported",
                message=f"Атом {atom.item_code} импортирован из XLSX",
                payload_json={"row_number": row.row_number, "sha256": parsed.sha256},
            )

        record_audit_event(
            db,
            case_id=case.id,
            actor_id=user.id,
            import_batch_id=batch.id,
            event_type="import_committed",
            message="Импорт XLSX подтвержден",
            payload_json={"sha256": parsed.sha256, "rows": len(group_rows)},
        )
        if case.status in {"draft", "ready"}:
            case.status = "atomization"
        if group_created and case.workflow_stage not in {"unassigned", "atomization"}:
            previous_stage = case.workflow_stage
            case.workflow_stage = "atomization"
            case.status = "atomization"
            record_audit_event(
                db,
                case_id=case.id,
                actor_id=user.id,
                import_batch_id=batch.id,
                event_type="workflow_stage_changed",
                message="Новые атомы вернули аудит к этапу атомизации",
                payload_json={
                    "previous_workflow_stage": previous_stage,
                    "workflow_stage": case.workflow_stage,
                    "fields": ["atom_imported"],
                },
            )
        await db.flush()
        await db.refresh(case)
        commit_cases.append(
            AuditImportCommitCase(
                case_id=case.id,
                case_number=case.case_number,
                contract_reference_mask=case.contract_reference_mask,
                digital_product=case.digital_product,
                created=case_created,
                atoms_created=group_created,
                atoms_reused=group_reused,
            )
        )

    summary_json = {
        "case_count": len(commit_cases),
        "created_case_count": created_case_count,
        "created_atom_count": created_atom_count,
        "reused_atom_count": reused_atom_count,
        "cases": [item.model_dump(mode="json") for item in commit_cases],
    }
    batch.summary_json = summary_json
    await db.flush()

    return AuditImportCommitResponse(
        batch_id=batch.id,
        sha256=batch.sha256,
        already_committed=False,
        case_count=len(commit_cases),
        created_case_count=created_case_count,
        created_atom_count=created_atom_count,
        reused_atom_count=reused_atom_count,
        cases=commit_cases,
    )
