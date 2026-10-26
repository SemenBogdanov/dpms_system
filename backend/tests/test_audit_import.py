"""Unit tests for audit atomization parser."""
from __future__ import annotations

import io
import os
import unittest
import uuid
import zipfile
from datetime import date
from unittest.mock import AsyncMock
from xml.sax.saxutils import escape

from fastapi import HTTPException

from app.services.audit_import import (
    EXPECTED_HEADERS,
    _validate_target_case_import,
    build_audit_atom_template,
    build_contract_fields,
    parse_audit_xlsx_bytes,
)
from app.models.audit import AuditCase


def _cell_ref(column_index: int) -> str:
    letters = ""
    index = column_index
    while True:
        index, remainder = divmod(index, 26)
        letters = chr(ord("A") + remainder) + letters
        if index == 0:
            return letters
        index -= 1


def build_xlsx_bytes(
    rows: list[list[object | None]],
    *,
    with_formula: bool = False,
    invalid_shared_string_index: bool = False,
    extra_members: dict[str, bytes] | None = None,
) -> bytes:
    shared_strings: list[str] = []
    shared_index: dict[str, int] = {}

    def shared_id(value: str) -> int:
        if value not in shared_index:
            shared_index[value] = len(shared_strings)
            shared_strings.append(value)
        return shared_index[value]

    sheet_rows: list[str] = []
    for row_number, row_values in enumerate(rows, start=1):
        cells: list[str] = []
        for column_index, value in enumerate(row_values):
            if value is None:
                continue
            ref = f"{_cell_ref(column_index)}{row_number}"
            if with_formula and row_number == 3 and column_index == 6:
                cells.append(
                    f'<c r="{ref}"><f>1+1</f><v>2</v></c>'
                )
                continue
            if isinstance(value, (int, float)):
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
            else:
                idx = shared_id(str(value))
                if invalid_shared_string_index and row_number == 3 and column_index == 6:
                    idx = 999_999
                cells.append(f'<c r="{ref}" t="s"><v>{idx}</v></c>')
        sheet_rows.append(f'<row r="{row_number}">{"".join(cells)}</row>')

    shared_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        f'count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">'
        + "".join(f"<si><t>{escape(item)}</t></si>" for item in shared_strings)
        + "</sst>"
    )
    sheet_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        f"<sheetData>{''.join(sheet_rows)}</sheetData>"
        "</worksheet>"
    )
    workbook_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="5.1 Реестр технических объектов" sheetId="1" r:id="rId1"/></sheets>'
        "</workbook>"
    )
    workbook_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
        'Target="worksheets/sheet1.xml"/>'
        "</Relationships>"
    )
    root_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" '
        'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="xl/workbook.xml"/>'
        "</Relationships>"
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
        "</Types>"
    )

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("xl/workbook.xml", workbook_xml)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels)
        archive.writestr("xl/worksheets/sheet1.xml", sheet_xml)
        archive.writestr("xl/sharedStrings.xml", shared_xml)
        for name, payload in (extra_members or {}).items():
            archive.writestr(name, payload)
    return buffer.getvalue()


class AuditImportParserTests(unittest.TestCase):
    def test_generated_template_is_accepted_and_empty(self):
        template = build_audit_atom_template()

        parsed = parse_audit_xlsx_bytes(template, "AUD-0001-atoms-template.xlsx")

        self.assertEqual(parsed.total_rows, 0)
        self.assertEqual(parsed.source_sheet, "5.1 Реестр технических объектов")

    def test_preview_masks_contract_and_url(self):
        rows = [
            [],
            EXPECTED_HEADERS,
            [
                1,
                "DPMS",
                "ДОГ-123/2026",
                46000,
                "Разработка",
                "экран",
                "Экран входа",
                "5.1",
                "https://example.test/objects/12345",
                1,
                0,
                46010,
                46020,
            ],
        ]
        parsed = parse_audit_xlsx_bytes(build_xlsx_bytes(rows), "audit_example.xlsx")
        preview = parsed.to_preview()

        self.assertEqual(preview.total_rows, 1)
        self.assertFalse(preview.has_errors)
        self.assertNotIn("ДОГ-123/2026", preview.model_dump_json())
        self.assertNotIn("https://example.test/objects/12345", preview.model_dump_json())
        self.assertEqual(preview.rows[0].contract_reference_mask, "ДО****26")
        self.assertEqual(preview.rows[0].system_url_mask, "https://example.test/ob***/12***")
        self.assertEqual(preview.rows[0].alpha_result, "present")
        self.assertEqual(preview.rows[0].commission_result, "not_confirmed")

    def test_formula_in_primary_table_becomes_row_issue(self):
        rows = [
            [],
            EXPECTED_HEADERS,
            [
                1,
                "DPMS",
                "ДОГ-321/2026",
                46000,
                "Разработка",
                "экран",
                "Экран оплаты",
                "7.2",
                "https://example.test/objects/77",
                1,
                1,
                46010,
                46020,
            ],
        ]
        parsed = parse_audit_xlsx_bytes(build_xlsx_bytes(rows, with_formula=True), "audit_example.xlsx")
        self.assertEqual(parsed.error_rows, 1)
        self.assertTrue(any(issue.field == "Название из договора" for issue in parsed.rows[0].issues))

    def test_contracts_with_same_mask_remain_separate_preview_groups(self):
        rows = [
            [],
            EXPECTED_HEADERS,
            [1, "DPMS", "AB-111-XY", 46000, "Разработка", "экран", "Экран 1", "1", None, None, None, None, None],
            [2, "DPMS", "AB-222-XY", 46000, "Разработка", "экран", "Экран 2", "2", None, None, None, None, None],
        ]
        preview = parse_audit_xlsx_bytes(build_xlsx_bytes(rows), "audit.xlsx").to_preview()

        self.assertEqual(len(preview.grouped_counts), 2)
        self.assertEqual({group.contract_reference_mask for group in preview.grouped_counts}, {"AB****XY"})
        self.assertEqual(len({group.group_id for group in preview.grouped_counts}), 2)

    def test_duplicate_atoms_are_reported_before_commit(self):
        atom = [1, "DPMS", "ДОГ-123", 46000, "Разработка", "экран", "Экран", "1", None, None, None, None, None]
        duplicate = atom.copy()
        duplicate[0] = 2
        parsed = parse_audit_xlsx_bytes(build_xlsx_bytes([[], EXPECTED_HEADERS, atom, duplicate]), "audit.xlsx")

        self.assertEqual(parsed.error_rows, 2)
        self.assertTrue(all(any("повторяется" in issue.message for issue in row.issues) for row in parsed.rows))

    def test_inconsistent_contract_dates_are_reported(self):
        rows = [
            [],
            EXPECTED_HEADERS,
            [1, "DPMS", "ДОГ-123", 46000, "Разработка", "экран", "Экран 1", "1", None, None, None, None, None],
            [2, "DPMS", "ДОГ-123", 46001, "Разработка", "экран", "Экран 2", "2", None, None, None, None, None],
        ]
        parsed = parse_audit_xlsx_bytes(build_xlsx_bytes(rows), "audit.xlsx")

        self.assertEqual(parsed.error_rows, 0)
        self.assertEqual(parsed.warning_rows, 1)
        self.assertTrue(
            any(issue.field == "Дата договора" and issue.severity == "warning" for issue in parsed.rows[1].issues)
        )

    def test_db_field_length_is_validated_in_preview(self):
        rows = [
            [],
            EXPECTED_HEADERS,
            [1, "DPMS", "ДОГ-123", 46000, "Разработка", "экран", "X" * 501, "1", None, None, None, None, None],
        ]
        parsed = parse_audit_xlsx_bytes(build_xlsx_bytes(rows), "audit.xlsx")

        self.assertEqual(parsed.error_rows, 1)
        self.assertTrue(any(issue.field == "Название из договора" and "500" in issue.message for issue in parsed.rows[0].issues))

    def test_invalid_shared_string_index_is_rejected_as_bad_request(self):
        rows = [
            [],
            EXPECTED_HEADERS,
            [1, "DPMS", "ДОГ-123", 46000, "Разработка", "экран", "Экран", "1", None, None, None, None, None],
        ]
        with self.assertRaises(HTTPException) as ctx:
            parse_audit_xlsx_bytes(
                build_xlsx_bytes(rows, invalid_shared_string_index=True),
                "audit.xlsx",
            )
        self.assertEqual(ctx.exception.status_code, 400)

    def test_disallowed_member_rejected(self):
        rows = [[], EXPECTED_HEADERS]
        data = build_xlsx_bytes(rows, extra_members={"xl/externalLinks/externalLink1.xml": b"<xml />"})
        with self.assertRaises(HTTPException) as ctx:
            parse_audit_xlsx_bytes(data, "audit_example.xlsx")
        self.assertIn("запрещенные", str(ctx.exception.detail))

    @unittest.skipUnless(os.path.exists("/Users/bogdanov/Downloads/audit_example.xlsx"), "sample workbook missing")
    def test_real_sample_row_count_if_file_exists(self):
        with open("/Users/bogdanov/Downloads/audit_example.xlsx", "rb") as fh:
            parsed = parse_audit_xlsx_bytes(fh.read(), "audit_example.xlsx")
        self.assertEqual(parsed.total_rows, 7)


class AuditTargetImportTests(unittest.IsolatedAsyncioTestCase):
    @staticmethod
    def _parsed_workbook(contract_reference: str):
        rows = [
            [],
            EXPECTED_HEADERS,
            [
                1,
                "DPMS",
                contract_reference,
                46000,
                "Разработка",
                "экран",
                "Экран аудита",
                "1.1",
                None,
                None,
                None,
                None,
                None,
            ],
        ]
        return parse_audit_xlsx_bytes(build_xlsx_bytes(rows), "audit.xlsx")

    async def test_target_case_rejects_another_contract(self):
        target_id = uuid.uuid4()
        target_fingerprint, target_mask = build_contract_fields("TARGET-2026")
        target = AuditCase(
            id=target_id,
            title="Целевой аудит",
            digital_product="DPMS",
            status="atomization",
            contract_reference_fingerprint=target_fingerprint,
            contract_reference_mask=target_mask,
            contract_date=date(2025, 12, 9),
        )
        db = AsyncMock()
        db.scalar.return_value = target

        with self.assertRaises(HTTPException) as ctx:
            await _validate_target_case_import(
                db,
                self._parsed_workbook("OTHER-2026"),
                target_id,
                lock=False,
            )

        self.assertEqual(ctx.exception.status_code, 409)
        self.assertIn("не совпадает", str(ctx.exception.detail))

    async def test_target_case_accepts_matching_contract_without_duplicate(self):
        target_id = uuid.uuid4()
        target_fingerprint, target_mask = build_contract_fields("TARGET-2026")
        target = AuditCase(
            id=target_id,
            title="Целевой аудит",
            digital_product="DPMS",
            status="atomization",
            contract_reference_fingerprint=target_fingerprint,
            contract_reference_mask=target_mask,
            contract_date=date(2025, 12, 9),
        )
        db = AsyncMock()
        db.scalar.side_effect = [target, None]

        result = await _validate_target_case_import(
            db,
            self._parsed_workbook("TARGET-2026"),
            target_id,
            lock=True,
        )

        self.assertIs(result, target)


if __name__ == "__main__":
    unittest.main()
