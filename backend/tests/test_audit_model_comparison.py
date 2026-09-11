"""Deterministic comparison and export tests for audit atom registries."""

from __future__ import annotations

from datetime import UTC, datetime
import io
from types import SimpleNamespace
import unittest
from uuid import uuid4
import zipfile

from pydantic import ValidationError

from app.schemas.audit_ai import AuditAIModelComparisonStart, AuditAIModelComparisonCommit
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
    def test_review_can_reject_all_proposals_and_exceed_old_600_limit(self):
        payload = dict(request_id=uuid4(), expected_config_version=1, drafts=[{
            "id": uuid4(), "title": f"Proposal {index}", "digital_product": "QA", "included": False,
        } for index in range(800)])
        review = AuditAIModelComparisonCommit(**payload)
        self.assertEqual(len(review.drafts), 800)
        self.assertFalse(any(item.included for item in review.drafts))
        payload["drafts"].append(payload["drafts"][0])
        with self.assertRaises(ValidationError):
            AuditAIModelComparisonCommit(**payload)

    def test_product_scope_and_case_sensitive_identifiers_are_not_merged(self):
        proposals = [_item(
            title=title, source_unit_id="U000001", locator="p1", excerpt="Names are case-sensitive.",
            sort_order=10, confidence=90,
        ) for title in ("Parameter A", "Parameter a", "Parameter A")]
        proposals[2].digital_product = "Another product"
        drafts = build_model_comparison([
            _registry(provider_name=str(index), model_name="model", items=[item], minute=index)
            for index, item in enumerate(proposals)
        ])
        self.assertEqual(len(drafts), 3)

    def test_large_comparison_keeps_all_independent_proposals(self):
        registries = [_registry(provider_name=str(number), model_name="model", minute=number, items=[
            _item(title=f"Proposal {number}:{index}", source_unit_id=f"U{index}", locator=f"p{index}",
                  excerpt=f"Requirement {number}:{index}", sort_order=index, confidence=90)
            for index in range(400)
        ]) for number in range(12)]
        self.assertEqual(len(build_model_comparison(registries)), 4800)

    def test_comparison_preserves_different_wording_as_separate_proposals(self):
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

        self.assertEqual(len(drafts), 3)
        self.assertTrue(all(draft.agreement_count == 1 for draft in drafts))
        self.assertEqual({draft.title for draft in drafts}, {
            shared_first.title, shared_second.title, unique_second.title,
        })
        self.assertTrue(all(len(draft.model_variants) == 1 for draft in drafts))

    def test_opposite_requirements_are_not_consensus_even_with_same_fingerprint(self):
        proposals = [_item(
            title=title, source_unit_id="U000001", locator="п. 1",
            excerpt="Правила экспорта определяются правами пользователя.", sort_order=10, confidence=90,
        ) for title in ("Экспорт разрешен", "Экспорт запрещен")]
        drafts = build_model_comparison([
            _registry(provider_name=str(index), model_name="model", items=[item], minute=index)
            for index, item in enumerate(proposals)
        ])
        self.assertEqual(len(drafts), 2)
        self.assertTrue(all(draft.agreement_count == 1 for draft in drafts))

    def test_exact_proposals_keep_both_sources_without_averaging_confidence(self):
        proposals = [_item(
            title="Экспорт разрешен", source_unit_id=unit, locator="п. 1",
            excerpt="Система позволяет выгрузить реестр.", sort_order=10, confidence=confidence,
        ) for unit, confidence in (("U000001", 80), ("p-3", 95))]
        drafts = build_model_comparison([
            _registry(provider_name=str(index), model_name="model", items=[item], minute=index)
            for index, item in enumerate(proposals)
        ])
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0].agreement_count, 2)
        self.assertEqual(len(drafts[0].model_variants), 2)
        self.assertIsNone(drafts[0].confidence_percent)

    def test_local_unit_ids_do_not_match_different_evidence(self):
        proposals = [_item(
            title="Экспорт", source_unit_id="U000001", locator=locator,
            excerpt=text, sort_order=10, confidence=90,
        ) for locator, text in (("п. 1", "Экспорт списка сотрудников"), ("п. 2", "Экспорт списка договоров"))]
        drafts = build_model_comparison([
            _registry(provider_name=str(index), model_name="model", items=[item], minute=index)
            for index, item in enumerate(proposals)
        ])
        self.assertEqual(len(drafts), 2)

    def test_different_conditions_in_notes_are_not_merged(self):
        proposals = [_item(
            title="Экспорт", source_unit_id="U000001", locator="п. 1",
            excerpt="Доступ к экспорту ограничен ролями.", sort_order=10, confidence=90,
        ) for _ in range(2)]
        proposals[0].notes = "Только администратор"
        proposals[1].notes = "Все сотрудники"
        drafts = build_model_comparison([
            _registry(provider_name=str(index), model_name="model", items=[item], minute=index)
            for index, item in enumerate(proposals)
        ])
        self.assertEqual(len(drafts), 2)

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
