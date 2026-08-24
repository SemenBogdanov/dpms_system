"""Deterministic comparison and export tests for audit atom registries."""

from __future__ import annotations

from datetime import UTC, datetime
import io
from types import SimpleNamespace
import unittest
from uuid import uuid4
import zipfile

from pydantic import ValidationError

from app.schemas.audit_ai import AuditAIModelComparisonStart
from app.services.audit_import import build_audit_atom_export
from app.services.audit_model_comparison import build_model_comparison


def _item(
    *,
    title: str,
    source_unit_id: str,
    locator: str,
    excerpt: str,
    sort_order: int,
    confidence: int,
):
    return SimpleNamespace(
        id=uuid4(),
        title=title,
        digital_product="OPEC",
        work_type="Разработка",
        object_type="Экран",
        source_clause=locator,
        notes=None,
        source_fingerprint=f"fingerprint-{source_unit_id}-{sort_order}",
        source_refs_json=[
            {
                "source_unit_id": source_unit_id,
                "locator": locator,
                "excerpt": excerpt,
            }
        ],
        confidence_percent=confidence,
        sort_order=sort_order,
    )


def _registry(*, provider_name: str, model_name: str, items: list[object], minute: int):
    return SimpleNamespace(
        id=uuid4(),
        provider_name=provider_name,
        model_name=model_name,
        created_at=datetime(2026, 8, 24, 10, minute, tzinfo=UTC),
        items=items,
    )


class AuditModelComparisonTests(unittest.TestCase):
    def test_comparison_preserves_consensus_and_unique_model_variants(self):
        shared_first = _item(
            title="Экран списка договоров",
            source_unit_id="p-12",
            locator="п. 12",
            excerpt="Система отображает реестр договоров.",
            sort_order=10,
            confidence=91,
        )
        shared_second = _item(
            title="Реестр договоров",
            source_unit_id="p-12",
            locator="пункт 12",
            excerpt="Должен быть доступен список договоров.",
            sort_order=10,
            confidence=84,
        )
        unique_second = _item(
            title="Экспорт результата проверки",
            source_unit_id="p-19",
            locator="п. 19",
            excerpt="Результат проверки выгружается в файл.",
            sort_order=20,
            confidence=78,
        )
        registries = [
            _registry(provider_name="Локальная", model_name="model-local", items=[shared_first], minute=1),
            _registry(
                provider_name="Облачная",
                model_name="model-cloud",
                items=[shared_second, unique_second],
                minute=2,
            ),
        ]

        drafts = build_model_comparison(registries)

        self.assertEqual(len(drafts), 2)
        shared = next(draft for draft in drafts if draft.agreement_count == 2)
        unique = next(draft for draft in drafts if draft.agreement_count == 1)
        self.assertEqual(shared.registry_count, 2)
        self.assertEqual(len(shared.model_variants), 2)
        self.assertIn("Система отображает реестр договоров", " ".join(ref["excerpt"] for ref in shared.source_refs))
        self.assertEqual(unique.title, "Экспорт результата проверки")
        self.assertEqual(len(unique.model_variants), 1)

    def test_single_registry_builds_reviewable_working_draft(self):
        item = _item(
            title="Карточка договора",
            source_unit_id="p-7",
            locator="п. 7",
            excerpt="Система отображает карточку договора.",
            sort_order=10,
            confidence=89,
        )
        registry = _registry(provider_name="Одна", model_name="single", items=[item], minute=1)

        drafts = build_model_comparison([registry])

        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].registry_count, 1)
        self.assertEqual(drafts[0].agreement_count, 1)
        self.assertEqual(len(drafts[0].model_variants), 1)
        self.assertEqual(drafts[0].source_refs[0]["excerpt"], "Система отображает карточку договора.")

    def test_comparison_request_accepts_one_registry_and_rejects_empty_selection(self):
        registry_id = uuid4()

        request = AuditAIModelComparisonStart(registry_ids=[registry_id])

        self.assertEqual(request.registry_ids, [registry_id])
        with self.assertRaises(ValidationError):
            AuditAIModelComparisonStart(registry_ids=[])

    def test_export_contains_general_registry_and_textual_evidence(self):
        audit_case = SimpleNamespace(case_number="AUD-0042")
        atom = SimpleNamespace(
            item_code="ATM-0001",
            digital_product="OPEC",
            title="Экран договоров & фильтр",
            work_type="Разработка",
            object_type="Экран",
            source_clause="п. 12",
            source_evidence_text="Система должна отображать <договоры>.",
            state="ready",
            system_url=None,
            alpha_result_raw=None,
            alpha_result=None,
            alpha_date=None,
            commission_result_raw=None,
            commission_result=None,
            commission_date=None,
            notes="Проверено",
            source_sheet="AI comparison",
        )

        content = build_audit_atom_export(audit_case, [atom])

        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertEqual(archive.testzip(), None)
            sheet = archive.read("xl/worksheets/sheet1.xml").decode("utf-8")
            workbook = archive.read("xl/workbook.xml").decode("utf-8")
        self.assertIn("Генеральный реестр", workbook)
        self.assertIn("Текстовое основание", sheet)
        self.assertIn("Система должна отображать &lt;договоры&gt;.", sheet)
        self.assertIn("Экран договоров &amp; фильтр", sheet)


if __name__ == "__main__":
    unittest.main()
