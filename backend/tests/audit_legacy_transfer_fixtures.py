"""Synthetic A1.9 workbooks only; no filesystem or application dependencies."""

from copy import deepcopy
from datetime import date, timedelta
from io import BytesIO
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


KINDS = ("cases", "atoms", "assignments", "events", "daily_totals")
HISTORICAL_ACTOR = "Synthetic Former Reviewer"
CURRENT_ACTOR = "Synthetic Current Reviewer"
FIELDS = {
    "cases": ("case_key", "title", "digital_product", "contract_date", "contract_reference"),
    "atoms": (
        "case_key", "atom_key", "title", "state", "occurred_at",
        "alpha_result", "alpha_date", "commission_result", "commission_date",
        "source_clause", "work_type", "object_type",
    ),
    "assignments": (
        "case_key", "assignment_key", "actor_name", "assigned_at", "is_current",
    ),
    "events": (
        "case_key", "atom_key", "event_key", "event_type", "occurred_at",
        "actor_name", "previous_state", "state", "alpha_result", "commission_result",
    ),
    "daily_totals": ("case_key", "metric_date", "metric_type", "value"),
}


def combined_rows(today: date) -> dict[str, list[dict]]:
    day = lambda offset: (today - timedelta(days=offset)).isoformat()
    return {
        "cases": [
            {"case_key": "DETAIL", "title": "Synthetic source detail", "digital_product": "Synthetic source product", "contract_date": day(30)},
            {"case_key": "NEW", "title": "Synthetic imported case", "digital_product": "Synthetic new product", "contract_date": day(30)},
            {"case_key": "TOTAL", "title": "Synthetic aggregate case", "digital_product": "Synthetic aggregate product", "contract_date": day(30)},
        ],
        "atoms": [
            {"case_key": "DETAIL", "atom_key": "A-1", "title": "Synthetic dated atom", "state": "ready", "occurred_at": day(7), "alpha_result": "present", "alpha_date": day(6), "commission_result": "confirmed", "commission_date": day(5), "source_clause": "1.1", "work_type": "Synthetic work", "object_type": "Synthetic object"},
            {"case_key": "NEW", "atom_key": "B-1", "title": "Synthetic undated atom", "state": "ready", "source_clause": "2.1"},
        ],
        "assignments": [
            {"case_key": "DETAIL", "assignment_key": "OLD-1", "actor_name": HISTORICAL_ACTOR, "assigned_at": day(9), "is_current": "false"},
            {"case_key": "NEW", "assignment_key": "CURRENT-1", "actor_name": CURRENT_ACTOR, "assigned_at": day(2), "is_current": "true"},
        ],
        "events": [
            {"case_key": "DETAIL", "atom_key": "A-1", "event_key": "VERIFY-1", "event_type": "atom_status_changed", "occurred_at": day(7), "actor_name": HISTORICAL_ACTOR, "previous_state": "draft", "state": "ready"},
            {"case_key": "DETAIL", "atom_key": "A-1", "event_key": "ALPHA-1", "event_type": "alpha_reviewed", "occurred_at": day(6), "actor_name": HISTORICAL_ACTOR, "alpha_result": "present"},
            {"case_key": "DETAIL", "atom_key": "A-1", "event_key": "COMMISSION-1", "event_type": "commission_reviewed", "occurred_at": day(5), "actor_name": HISTORICAL_ACTOR, "commission_result": "confirmed"},
        ],
        "daily_totals": [
            {"case_key": "TOTAL", "metric_date": day(8), "metric_type": kind, "value": value}
            for kind, value in (("verified", 7), ("alpha_reviewed", 5), ("commission_reviewed", 3))
        ],
    }


def workbook(rows: dict[str, list[dict]], *, reordered: bool = False) -> tuple[bytes, list[dict]]:
    """Create deterministic valid XLSX, changing sheets, columns and row order on retry."""
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    package = "http://schemas.openxmlformats.org/package/2006/relationships"
    types = "http://schemas.openxmlformats.org/package/2006/content-types"
    book = ET.Element(f"{{{ns}}}workbook")
    sheets = ET.SubElement(book, f"{{{ns}}}sheets")
    relationships = ET.Element(f"{{{package}}}Relationships")
    content_types = ET.Element(f"{{{types}}}Types")
    ET.SubElement(content_types, f"{{{types}}}Default", Extension="rels", ContentType="application/vnd.openxmlformats-package.relationships+xml")
    ET.SubElement(content_types, f"{{{types}}}Default", Extension="xml", ContentType="application/xml")
    ET.SubElement(content_types, f"{{{types}}}Override", PartName="/xl/workbook.xml", ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml")
    root_relationships = ET.Element(f"{{{package}}}Relationships")
    ET.SubElement(root_relationships, f"{{{package}}}Relationship", Id="rId1", Type=f"{rel}/officeDocument", Target="xl/workbook.xml")
    parts, mappings = {}, []
    kinds = list(rows)
    if reordered:
        kinds.reverse()
    for index, kind in enumerate(kinds, 1):
        fields = list(FIELDS[kind])
        records = deepcopy(rows[kind])
        if reordered:
            fields.reverse()
            records.reverse()
        ET.SubElement(sheets, f"{{{ns}}}sheet", {"name": f"Synthetic {kind}", "sheetId": str(index), f"{{{rel}}}id": f"rId{index}"})
        part_name = f"xl/worksheets/sheet{index}.xml"
        ET.SubElement(relationships, f"{{{package}}}Relationship", Id=f"rId{index}", Type=f"{rel}/worksheet", Target=f"worksheets/sheet{index}.xml")
        ET.SubElement(content_types, f"{{{types}}}Override", PartName=f"/{part_name}", ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml")
        sheet = ET.Element(f"{{{ns}}}worksheet")
        sheet_data = ET.SubElement(sheet, f"{{{ns}}}sheetData")
        values = [fields] + [[row.get(field) for field in fields] for row in records]
        for row_number, row_values in enumerate(values, 1):
            row = ET.SubElement(sheet_data, f"{{{ns}}}row", r=str(row_number))
            for column, value in enumerate(row_values):
                if value is not None:
                    cell = ET.SubElement(row, f"{{{ns}}}c", r=f"{chr(65 + column)}{row_number}", t="inlineStr")
                    inline = ET.SubElement(cell, f"{{{ns}}}is")
                    ET.SubElement(inline, f"{{{ns}}}t").text = str(value)
        parts[part_name] = sheet
        mappings.append({"sheet_id": str(index), "header_row": 1, "kind": kind, "fields": {field: chr(65 + column) for column, field in enumerate(fields)}})
    parts.update({"[Content_Types].xml": content_types, "_rels/.rels": root_relationships, "xl/workbook.xml": book, "xl/_rels/workbook.xml.rels": relationships})
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        for name, element in sorted(parts.items()):
            info = ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            archive.writestr(info, ET.tostring(element, encoding="utf-8", xml_declaration=True))
    return output.getvalue(), mappings


def transfer_config(datasets, existing_case_id, eligible_user_id, *, namespace="a19-acceptance"):
    return {
        "namespace": namespace,
        "datasets": deepcopy(datasets),
        "cases": {
            "DETAIL": {"mode": "existing", "target_case_id": str(existing_case_id), "title": "Synthetic existing case", "digital_product": "Synthetic existing product", "fill_empty": ["contract_date"]},
            "NEW": {"mode": "create"},
            "TOTAL": {"mode": "create"},
        },
        "actors": {
            HISTORICAL_ACTOR: {"mode": "historical", "historical_name": HISTORICAL_ACTOR},
            CURRENT_ACTOR: {"mode": "user", "user_id": str(eligible_user_id)},
        },
        "row_decisions": {},
        "apply_current_assignments": True,
    }
