"""Canonical transfer adapter contracts using synthetic workbooks only."""

import unittest

from fastapi import HTTPException

from app.services.audit_legacy_workbook import normalize_legacy_datasets
from tests.test_audit_legacy_workbook import ATOM_MAPPING, workbook_bytes


class LegacyNormalizationTests(unittest.TestCase):
    def normalize(self, rows, **overrides):
        return normalize_legacy_datasets(workbook_bytes([("Реестр", rows)]), [{**ATOM_MAPPING, **overrides}])

    def test_five_datasets_share_one_source_and_keep_actual_dates(self):
        data = workbook_bytes([
            ("Договоры", [["Код", "Продукт", "Дата"], ["CASE-1", "Экран", "01.08.2026"]]),
            ("Атомы", [["Код", "Атом", "Текст", "Статус", "Дата"], ["CASE-1", "A1", "Фильтр", "Принят", "02.08.2026"]]),
            ("Назначения", [["Код", "Email", "Когда", "Текущее"], ["CASE-1", "PERSON@EXAMPLE.TEST", "01.08.2026", "да"]]),
            ("События", [["Код", "Событие", "Тип", "Когда", "Атом", "До", "После"], ["CASE-1", "E1", "изменение статуса", "02.08.2026 10:00", "A1", "Черновик", "Принят"]]),
            ("Итоги", [["Код", "Дата", "Показатель", "Значение"], ["CASE-2", "03.08.2026", "Верифицировано", "7"]]),
        ])
        datasets = [
            {"sheet_id": "1", "header_row": 1, "kind": "cases", "fields": {"case_key": "A", "digital_product": "B", "contract_date": "C"}},
            {**ATOM_MAPPING, "sheet_id": "2", "fields": {**ATOM_MAPPING["fields"], "state": "D", "occurred_at": "E"}},
            {"sheet_id": "3", "header_row": 1, "kind": "assignments", "fields": {"case_key": "A", "assignee_email": "B", "assigned_at": "C", "is_current": "D"}},
            {"sheet_id": "4", "header_row": 1, "kind": "events", "fields": {"case_key": "A", "event_key": "B", "event_type": "C", "occurred_at": "D", "atom_key": "E", "previous_state": "F", "state": "G"}},
            {"sheet_id": "5", "header_row": 1, "kind": "daily_totals", "fields": {"case_key": "A", "metric_date": "B", "metric_type": "C", "value": "D"}},
        ]
        result = normalize_legacy_datasets(data, datasets)
        self.assertEqual(result["error_count"], 0, result["issues"])
        self.assertEqual(result["total_rows"], 5)
        self.assertEqual(result["records"][1]["values"]["occurred_at"], "2026-08-01T21:00:00+00:00")
        self.assertEqual(result["records"][2]["values"]["assignee_email"], "person@example.test")
        self.assertIs(result["records"][2]["values"]["is_current"], True)
        self.assertEqual(result["records"][3]["values"]["occurred_at"], "2026-08-02T07:00:00+00:00")
        self.assertEqual(result["records"][4]["values"]["value"], 7)

    def test_label_translation_is_explicit_and_unknown_value_blocks(self):
        rows = [["Код", "Атом", "Текст", "Статус"], ["C1", "A1", "Фильтр", "Обработан"]]
        fields = {**ATOM_MAPPING["fields"], "state": "D"}
        self.assertGreater(self.normalize(rows, fields=fields)["error_count"], 0)
        result = self.normalize(rows, fields=fields, value_maps={"state": {"Обработан": "ready"}})
        self.assertEqual(result["error_count"], 0)
        self.assertEqual(result["records"][0]["values"]["state"], "ready")
        self.assertEqual(result["warning_count"], 1)

    def test_unknown_dates_remain_unknown_and_defaults_are_declared(self):
        rows = [["Код", "Атом", "Текст"], ["C1", "A1", "Фильтр"]]
        result = self.normalize(rows, defaults={"state": "Принят"})
        self.assertNotIn("occurred_at", result["records"][0]["values"])
        self.assertEqual(result["error_count"], 0)
        self.assertIn("verification_date_unknown", {issue["code"] for issue in result["issues"]})

    def test_generated_atom_key_is_opt_in_and_order_independent(self):
        header = ["Код", "Текст", "Пункт"]
        rows = [header, ["C1", "Фильтр", "1"], ["C1", "Таблица", "2"]]
        fields = {"case_key": "A", "title": "B", "source_clause": "C"}
        self.assertGreater(self.normalize(rows, fields=fields)["error_count"], 0)
        a = self.normalize(rows, fields=fields, atom_key_mode="content")
        b = self.normalize([header, rows[2], rows[1]], fields=fields, atom_key_mode="content")
        self.assertEqual(a["error_count"], 0)
        self.assertEqual({r["values"]["atom_key"] for r in a["records"]}, {r["values"]["atom_key"] for r in b["records"]})

    def test_zero_metric_is_valid_and_invalid_numeric_values_rejected(self):
        mapping = {"sheet_id": "1", "header_row": 1, "kind": "daily_totals", "fields": {"case_key": "A", "metric_date": "B", "metric_type": "C", "value": "D"}}
        for value, valid in [("0", True), ("1.0", True), ("-1", False), ("1.5", False), ("NaN", False), ("Infinity", False), ("1000000001", False)]:
            with self.subTest(value=value):
                data = workbook_bytes([("Итоги", [["Код", "Дата", "Метрика", "Кол-во"], ["C1", "01.08.2026", "verified", value]])])
                result = normalize_legacy_datasets(data, [mapping])
                self.assertEqual(result["error_count"] == 0, valid)

    def test_formula_and_merges_cannot_be_replaced_with_defaults(self):
        result = normalize_legacy_datasets(workbook_bytes(formula=(1, "C2")), [{**ATOM_MAPPING, "defaults": {"title": "Подмена"}}])
        self.assertGreater(result["error_count"], 0)
        self.assertIsNone(result["records"][0]["values"]["title"])
        merged = normalize_legacy_datasets(workbook_bytes(merge="A2:A3"), [ATOM_MAPPING])
        self.assertIn("merged_value", {issue["code"] for issue in merged["issues"]})

    def test_historical_name_does_not_invent_email_or_current_assignment(self):
        data = workbook_bytes([("Назначения", [["Код", "Имя", "Когда", "До"], ["C1", "Исторический участник", "01.08.2026", "03.08.2026"]])])
        mapping = {"sheet_id": "1", "header_row": 1, "kind": "assignments", "fields": {"case_key": "A", "actor_name": "B", "assigned_at": "C", "ended_at": "D"}}
        result = normalize_legacy_datasets(data, [mapping])
        self.assertEqual(result["error_count"], 0)
        self.assertNotIn("assignee_email", result["records"][0]["values"])
        self.assertNotIn("is_current", result["records"][0]["values"])
        current = normalize_legacy_datasets(data, [{**mapping, "defaults": {"is_current": "true"}}])
        self.assertIn("ended_current_assignment", {issue["code"] for issue in current["issues"]})

    def test_error_count_includes_errors_beyond_bounded_issue_list(self):
        rows = [["Код", "Атом", "Текст"], *[["C1", f"A{i}", "Фильтр"] for i in range(510)], ["C1", "LAST", None]]
        result = self.normalize(rows, defaults={"state": "ready"})
        self.assertEqual(len(result["issues"]), 500)
        self.assertGreater(result["warning_count"], 500)
        self.assertEqual(result["error_count"], 1)
        self.assertEqual(result["issues"][0]["severity"], "error")
        self.assertEqual(result["issues"][0]["row"], 512)
        self.assertEqual(result["issues"][0]["field"], "title")

    def test_explicit_row_range_excludes_footer_without_row_number_identity(self):
        rows = [["Код", "Атом", "Текст"], ["C1", "A1", "Фильтр"], ["Итого", "1", None]]
        self.assertGreater(self.normalize(rows)["error_count"], 0)
        self.assertEqual(self.normalize(rows, row_from=2, row_to=2)["error_count"], 0)
        with self.assertRaises(HTTPException):
            self.normalize(rows, row_from=0)

    def test_conflicting_normalized_label_map_is_rejected(self):
        with self.assertRaises(HTTPException):
            self.normalize([["Код", "Атом", "Текст"], ["C1", "A1", "Фильтр"]], value_maps={"state": {"ОК": "ready", "ок": "draft"}})

    def test_event_does_not_synthesize_previous_state(self):
        mapping = {"sheet_id": "1", "header_row": 1, "kind": "events", "fields": {"case_key": "A", "event_key": "B", "atom_key": "C"}, "defaults": {"event_type": "atom_status_changed", "occurred_at": "01.08.2026", "state": "ready"}}
        result = normalize_legacy_datasets(workbook_bytes(), [mapping])
        self.assertIn("event_field_required", {issue["code"] for issue in result["issues"]})

    def test_links_with_credentials_block_and_safe_links_never_fetched(self):
        rows = [["Код", "Атом", "Текст"], ["C1", "A1", "Фильтр"]]
        self.assertEqual(self.normalize(rows, defaults={"system_url": "https://example.invalid/product"})["error_count"], 0)
        self.assertGreater(self.normalize(rows, defaults={"system_url": "https://user:password@example.invalid"})["error_count"], 0)

    def test_one_source_column_can_explicitly_supply_key_and_contract_reference(self):
        data = workbook_bytes([("Договоры", [["Номер", "Продукт"], ["TEST-001", "Экран"]])])
        result = normalize_legacy_datasets(data, [{
            "sheet_id": "1", "header_row": 1, "kind": "cases",
            "fields": {"case_key": "A", "contract_reference": "A", "digital_product": "B"},
        }])
        self.assertEqual(result["error_count"], 0)
        values = result["records"][0]["values"]
        self.assertEqual(values["case_key"], values["contract_reference"])


if __name__ == "__main__":
    unittest.main()
