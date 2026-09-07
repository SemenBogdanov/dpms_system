"""Synthetic historical workbook fixtures; never reads user source files."""

from io import BytesIO
import unittest
from unittest.mock import patch
from xml.sax.saxutils import escape
from zipfile import ZipFile, ZIP_DEFLATED

from fastapi import HTTPException

from app.services.audit_legacy_workbook import inspect_legacy_workbook, preview_legacy_mapping


def workbook_bytes(sheets=None, *, formula=None, merge=None, date1904=False, extras=None):
    sheets = sheets or [("Реестр", [["Код договора", "Код атома", "Название атома"], ["PRIVATE-123456", "A-1", "Экран"]])]
    output = BytesIO()
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rel = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"/>')
        archive.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}" xmlns:r="{rel}"><workbookPr date1904="{int(date1904)}"/><sheets>' + "".join(f'<sheet name="{escape(name)}" sheetId="{i}" r:id="rId{i}"/>' for i, (name, _) in enumerate(sheets, 1)) + '</sheets></workbook>')
        archive.writestr("xl/_rels/workbook.xml.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' + "".join(f'<Relationship Id="rId{i}" Type="{rel}/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1, len(sheets) + 1)) + '</Relationships>')
        for index, (_, rows) in enumerate(sheets, 1):
            body = []
            for row_number, row in enumerate(rows, 1):
                cells = []
                for column_number, value in enumerate(row):
                    if value is None:
                        continue
                    ref = f"{chr(65 + column_number)}{row_number}"
                    if formula == (index, ref):
                        cells.append(f'<c r="{ref}"><f>1+1</f><v>2</v></c>')
                    else:
                        cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(str(value))}</t></is></c>')
                body.append(f'<row r="{row_number}">{"".join(cells)}</row>')
            merged = f'<mergeCells><mergeCell ref="{merge}"/></mergeCells>' if merge else ''
            archive.writestr(f"xl/worksheets/sheet{index}.xml", f'<worksheet xmlns="{ns}"><sheetData>{"".join(body)}</sheetData>{merged}</worksheet>')
        for name, value in (extras or {}).items():
            archive.writestr(name, value)
    return output.getvalue()


ATOM_MAPPING = {"sheet_id": "1", "header_row": 1, "kind": "atoms", "fields": {"case_key": "A", "atom_key": "B", "title": "C"}}


def replace_sheet(data: bytes, transform) -> bytes:
    result = BytesIO()
    with ZipFile(BytesIO(data)) as original, ZipFile(result, "w", ZIP_DEFLATED) as output:
        for part in original.infolist():
            body = original.read(part.filename)
            if part.filename == "xl/worksheets/sheet1.xml":
                body = transform(body.decode()).encode()
            output.writestr(part.filename, body)
    return result.getvalue()


class AuditLegacyWorkbookTests(unittest.TestCase):
    def test_arbitrary_sheet_names_and_column_suggestions(self):
        data = workbook_bytes([("Любое название", [["Сводная таблица"], ["Код договора", "Код атома", "Название атома"], ["X", "1", "Работа"]]), ("Дневная статистика", [["Договор", "Дата", "Показатель", "Количество"], ["X", "01.08.2026", "ready", 4]])])
        result = inspect_legacy_workbook(data)
        self.assertEqual(result["parser_version"], "a19-xlsx-v1")
        self.assertEqual(len(result["sheets"]), 2)
        self.assertEqual(result["sheets"][0]["header_row"], 2)
        self.assertEqual(result["sheets"][0]["row_count"], 1)
        self.assertEqual(result["sheets"][1]["suggested_mapping"]["kind"], "daily_totals")

    def test_valid_mapping_is_only_staging_and_redacts_identifiers(self):
        result = preview_legacy_mapping(workbook_bytes(), ATOM_MAPPING)
        self.assertEqual(result["total_rows"], 1)
        self.assertEqual(result["valid_rows"], 1)
        self.assertEqual(result["error_rows"], 0)
        self.assertFalse(result["ready_for_import"])
        self.assertNotIn("PRIVATE-123456", str(result))

    def test_duplicates_both_rows_are_errors_and_order_independent(self):
        rows = [["Договор", "Код атома", "Атом"], ["X", "1", "Экран"], ["X", "1", "Другой текст"]]
        result = preview_legacy_mapping(workbook_bytes([("Лист", rows)]), ATOM_MAPPING)
        self.assertEqual(result["duplicate_rows"], 2)
        self.assertEqual(result["valid_rows"], 0)
        self.assertEqual(result["error_rows"], 2)

    def test_same_atom_key_different_cases_is_not_duplicate(self):
        rows = [["Договор", "Код атома", "Атом"], ["X", "1", "Экран"], ["Y", "1", "Экран"]]
        result = preview_legacy_mapping(workbook_bytes([("Лист", rows)]), ATOM_MAPPING)
        self.assertEqual(result["valid_rows"], 2)

    def test_formula_cached_result_is_not_a_fact(self):
        data = workbook_bytes(formula=(1, "C2"))
        self.assertEqual(inspect_legacy_workbook(data)["sheets"][0]["formula_count"], 1)
        result = preview_legacy_mapping(data, ATOM_MAPPING)
        self.assertEqual(result["error_rows"], 1)
        self.assertIn("formula_not_fact", {issue["code"] for issue in result["issues"]})

    def test_formula_on_unselected_analytics_sheet_does_not_block_inspection(self):
        data = workbook_bytes([("Атомы", [["Договор", "Код атома", "Атом"], ["X", "1", "Экран"]]), ("Расчеты", [["Итог"], [4]])], formula=(2, "A2"))
        self.assertEqual(preview_legacy_mapping(data, ATOM_MAPPING)["valid_rows"], 1)

    def test_missing_mapping_and_empty_rows(self):
        result = preview_legacy_mapping(workbook_bytes(), {**ATOM_MAPPING, "fields": {"case_key": "A"}})
        self.assertEqual(result["error_rows"], 1)
        self.assertEqual(result["valid_rows"], 0)
        self.assertIn("missing_mapping", {issue["code"] for issue in result["issues"]})

    def test_merged_source_values_are_not_forward_filled(self):
        result = preview_legacy_mapping(workbook_bytes(merge="A2:A3"), ATOM_MAPPING)
        self.assertIn("merged_value", {issue["code"] for issue in result["issues"]})

    def test_dates_statuses_and_unknown_verification_time(self):
        rows = [["Договор", "Код атома", "Атом", "Статус", "Дата альфа проверки"], ["X", "1", "Экран", "Принят", "не дата"], ["X", "2", "Отчет", "Непонятно", "2026-08-01"]]
        mapping = {**ATOM_MAPPING, "fields": {**ATOM_MAPPING["fields"], "state": "D", "alpha_date": "E"}}
        result = preview_legacy_mapping(workbook_bytes([("Лист", rows)]), mapping)
        self.assertEqual(result["error_rows"], 2)
        self.assertEqual(result["warning_rows"], 1)
        self.assertEqual({issue["code"] for issue in result["issues"]}, {"invalid_date", "unknown_value", "verification_date_unknown"})

    def test_assignment_does_not_infer_current_from_last_date_or_name(self):
        rows = [["Договор", "Email", "Дата назначения"], ["X", "person@example.test", "01.08.2026"], ["Y", "Иван Иванов", "2026-08-02"]]
        mapping = {"sheet_id": "1", "header_row": 1, "kind": "assignments", "fields": {"case_key": "A", "assignee_email": "B", "assigned_at": "C"}}
        result = preview_legacy_mapping(workbook_bytes([("Назначения", rows)]), mapping)
        self.assertEqual(result["error_rows"], 1)
        self.assertEqual(result["warning_rows"], 2)
        self.assertNotIn("person@example.test", str(result))

    def test_aggregate_is_not_synthetic_atom_history(self):
        rows = [["Договор", "Дата", "Метрика", "Количество"], ["X", "2026-08-01", "verified", 12], ["X", "2026-08-02", "verified", -1]]
        mapping = {"sheet_id": "1", "header_row": 1, "kind": "daily_totals", "fields": {"case_key": "A", "metric_date": "B", "metric_type": "C", "value": "D"}}
        result = preview_legacy_mapping(workbook_bytes([("Итоги", rows)]), mapping)
        self.assertEqual(result["valid_rows"], 1)
        self.assertEqual(result["error_rows"], 1)
        self.assertIn("aggregate_only", {issue["code"] for issue in result["issues"]})

    def test_date_only_and_excel_1904_are_accepted_without_rewriting_source(self):
        rows = [["Договор", "Цифровой продукт", "Дата договора"], ["X", "APP", "44900"]]
        mapping = {"sheet_id": "1", "header_row": 1, "kind": "cases", "fields": {"case_key": "A", "digital_product": "B", "contract_date": "C"}}
        result = preview_legacy_mapping(workbook_bytes([("Карточки", rows)], date1904=True), mapping)
        self.assertEqual(result["valid_rows"], 1)
        self.assertEqual(result["preview_rows"][0]["values"]["contract_date"], "44900")

    def test_invalid_mapping_rejected(self):
        variants = [
            {**ATOM_MAPPING, "sheet_id": "unknown"},
            {**ATOM_MAPPING, "header_row": 100},
            {**ATOM_MAPPING, "header_row": True},
            {**ATOM_MAPPING, "fields": {"case_key": "Z"}},
            {**ATOM_MAPPING, "fields": {"case_key": "A", "title": "A"}},
            {**ATOM_MAPPING, "fields": {"surprise": "A"}},
        ]
        for mapping in variants:
            with self.subTest(mapping=mapping), self.assertRaises(HTTPException):
                preview_legacy_mapping(workbook_bytes(), mapping)

    def test_empty_invalid_and_oversize_files_rejected(self):
        for data in (b"", b"not-xlsx", b"a" * (10 * 1024 * 1024 + 1)):
            with self.subTest(size=len(data)), self.assertRaises(HTTPException):
                inspect_legacy_workbook(data)

    def test_executable_external_and_traversal_archive_parts_rejected(self):
        for name in ("xl/vbaProject.bin", "xl/embeddings/object.bin", "xl/externalLinks/external.xml", "../outside.xml", "xl/../outside.xml"):
            with self.subTest(part=name), self.assertRaises(HTTPException):
                inspect_legacy_workbook(workbook_bytes(extras={name: b"<root/>"}))

    def test_entity_after_long_comment_is_rejected(self):
        xml = b'<!--' + b"padding " * 700 + b'--><!DOCTYPE x [<!ENTITY leak "value">]><x>&leak;</x>'
        with self.assertRaises(HTTPException):
            inspect_legacy_workbook(workbook_bytes(extras={"custom.xml": xml}))

    def test_external_data_relation_is_rejected_but_hyperlink_is_not_fetched(self):
        xml = '<Relationships><Relationship TargetMode="External" Target="https://example.test" Type="http://example.test/worksheet"/></Relationships>'
        with self.assertRaises(HTTPException):
            inspect_legacy_workbook(workbook_bytes(extras={"xl/_rels/custom.xml.rels": xml}))
        safe = xml.replace("/worksheet", "/hyperlink")
        self.assertEqual(len(inspect_legacy_workbook(workbook_bytes(extras={"xl/_rels/custom.xml.rels": safe}))["sheets"]), 1)

    def test_preview_is_bounded_and_error_total_is_exact(self):
        rows = [["Договор", "Код атома", "Атом"]] + [["X", "same-key", "Экран"] for _ in range(550)]
        result = preview_legacy_mapping(workbook_bytes([("Реестр", rows)]), ATOM_MAPPING)
        self.assertEqual(result["duplicate_rows"], 550)
        self.assertEqual(result["issue_count"], 550)
        self.assertEqual(len(result["issues"]), 500)
        self.assertEqual(len(result["preview_rows"]), 30)

    def test_array_formula_marks_cached_dependent_cells(self):
        data = replace_sheet(workbook_bytes(), lambda xml: xml.replace('<c r="B2" t="inlineStr">', '<c r="B2" t="inlineStr"><f t="array" ref="B2:C2">SOME_FORMULA()</f>'))
        mapping = {**ATOM_MAPPING, "kind": "cases", "fields": {"case_key": "A", "digital_product": "C"}}
        result = preview_legacy_mapping(data, mapping)
        self.assertEqual(result["error_rows"], 1)
        self.assertTrue(any(issue["column"] == "C" and issue["code"] == "formula_not_fact" for issue in result["issues"]))

    def test_merge_count_and_area_are_bounded_before_row_processing(self):
        for merges in ('<mergeCell ref="A2:A1048576"/>', '<mergeCell ref="Z100:Z101"/>' * 2001):
            data = replace_sheet(workbook_bytes(), lambda xml: xml.replace('</worksheet>', f'<mergeCells>{merges}</mergeCells></worksheet>'))
            with self.subTest(length=len(merges)), self.assertRaises(HTTPException):
                preview_legacy_mapping(data, ATOM_MAPPING)

    def test_unused_xml_node_and_depth_limits_are_checked_before_tree_allocation(self):
        for xml in ("<root>" + "<item/>" * 101 + "</root>", "<root>" * 81 + "</root>" * 81):
            with self.subTest(size=len(xml)), patch("app.services.audit_legacy_workbook.MAX_XML_NODES", 100), self.assertRaises(HTTPException) as error:
                inspect_legacy_workbook(workbook_bytes(extras={"unused.xml": xml}))
            self.assertIn("слишком сложен", error.exception.detail)

    def test_equivalent_daily_dates_are_duplicate_keys(self):
        from datetime import date
        serial = (date(2026, 8, 1) - date(1899, 12, 30)).days
        rows = [["Договор", "Дата", "Метрика", "Количество"], ["X", "2026-08-01", "verified", 12], ["X", "01.08.2026", "verified", 12], ["X", serial, "verified", 12]]
        mapping = {"sheet_id": "1", "header_row": 1, "kind": "daily_totals", "fields": {"case_key": "A", "metric_date": "B", "metric_type": "C", "value": "D"}}
        result = preview_legacy_mapping(workbook_bytes([("Итоги", rows)]), mapping)
        self.assertEqual(result["duplicate_rows"], 3)
        self.assertEqual(result["valid_rows"], 0)

    def test_equivalent_assignment_timestamps_are_duplicates(self):
        rows = [["Договор", "Email", "Дата назначения"], ["X", "person@example.test", "2026-08-01T10:00:00+03:00"], ["X", "person@example.test", "2026-08-01T07:00:00Z"]]
        mapping = {"sheet_id": "1", "header_row": 1, "kind": "assignments", "fields": {"case_key": "A", "assignee_email": "B", "assigned_at": "C"}}
        result = preview_legacy_mapping(workbook_bytes([("Назначения", rows)]), mapping)
        self.assertEqual(result["duplicate_rows"], 2)

    def test_invalid_header_invalidates_dataset_counts(self):
        result = preview_legacy_mapping(workbook_bytes(formula=(1, "C1")), ATOM_MAPPING)
        self.assertEqual(result["error_rows"], 1)
        self.assertEqual(result["valid_rows"], 0)
        self.assertIn("invalid_header", {issue["code"] for issue in result["issues"]})

    def test_coordinates_are_length_bounded_before_integer_conversion(self):
        from app.services.audit_legacy_workbook import _range_cells
        for value in ("A" * 250_000 + "1:B2", "A" + "9" * 250_000 + ":B2"):
            with self.subTest(length=len(value)), self.assertRaises(HTTPException):
                _range_cells(value)

    def test_merged_area_budget_is_workbook_wide(self):
        data = workbook_bytes([("One", [["x"]]), ("Two", [["y"]])], merge="B1:B12")
        with patch("app.services.audit_legacy_workbook.MAX_CELLS", 12), self.assertRaises(HTTPException) as error:
            inspect_legacy_workbook(data)
        self.assertIn("Суммарная область", error.exception.detail)

    def test_actor_spelling_does_not_split_daily_scope_when_email_known(self):
        rows = [["Договор", "Дата", "Метрика", "Количество", "Email", "ФИО"], ["X", "2026-08-01", "verified", 12, "person@example.test", "Иванов И.И."], ["X", "01.08.2026", "verified", 12, "person@example.test", "Иван Иванов"]]
        mapping = {"sheet_id": "1", "header_row": 1, "kind": "daily_totals", "fields": {"case_key": "A", "metric_date": "B", "metric_type": "C", "value": "D", "assignee_email": "E", "actor_name": "F"}}
        result = preview_legacy_mapping(workbook_bytes([("Итоги", rows)]), mapping)
        self.assertEqual(result["duplicate_rows"], 2)


if __name__ == "__main__":
    unittest.main()
