"""Tests for bounded canonical audit atomization and source coverage."""

from hashlib import sha256
import json
from types import SimpleNamespace
import unittest
from uuid import uuid4

from fastapi import HTTPException
from pydantic import ValidationError

from app.api.routes.audit_runtime import (
    _create_atomization_consent_token,
    _verify_atomization_consent_token,
)
from app.schemas.audit_runtime import AuditTZAtomizationStart
from app.services.audit_tz_atomization import (
    CanonicalAtomizationError,
    assemble_atomization_result,
    build_batch_messages,
    build_source_batches,
    discover_contract_requisites,
    redact_contract_requisites,
    validate_batch_result,
)


def source_unit(number: int, text: str) -> dict:
    unit_id = f"U{number:06d}"
    text_hash = sha256(text.encode("utf-8")).hexdigest()
    return {
        "source_unit_id": unit_id,
        "source_locator": f"body:{number}",
        "source_kind": "paragraph",
        "text": text,
        "text_hash": text_hash,
        "source_sha256": "a" * 64,
        "run_id": "run-test",
        "raw_contract_id": "DPMS-DOC-1-TEST",
        "canonical_contract_id": "DPMS-DOC-1-TEST",
        "match_status": "SAME_TARGET",
        "block_id": f"B{number}",
        "lane": "source",
        "extractor_version": "1.0",
        "schema_version": "1.0",
        "gate_bundle_hash": "b" * 64,
        "order": number,
    }


def prompt_packet(units: list[dict]) -> dict:
    return {
        "gate_bundle_hash": "b" * 64,
        "source_sha256": "a" * 64,
        "prompt_packet_hash": "c" * 64,
        "source_units": units,
    }


class CanonicalAuditAtomizationTests(unittest.TestCase):
    def test_external_transfer_requires_explicit_confirmation(self):
        with self.assertRaises(ValidationError):
            AuditTZAtomizationStart(
                request_id="172bbb71-2c2c-4d3a-906d-c0dffeab90c3",
                consent_token="x" * 40,
                data_transfer_confirmed=False,
            )

    def test_consent_is_bound_to_provider_model_and_version(self):
        user = SimpleNamespace(id=uuid4())
        run = SimpleNamespace(
            id=uuid4(),
            case_id=uuid4(),
            source_sha256="a" * 64,
            skill_sha256="b" * 64,
        )
        provider = SimpleNamespace(id=uuid4(), config_version=7, model_name="model-a")
        token = _create_atomization_consent_token(user=user, run=run, provider=provider)

        _verify_atomization_consent_token(token, user=user, run=run, provider=provider)
        changed = SimpleNamespace(id=provider.id, config_version=8, model_name="model-b")
        with self.assertRaises(HTTPException) as raised:
            _verify_atomization_consent_token(token, user=user, run=run, provider=changed)

        self.assertEqual(raised.exception.status_code, 409)

    def test_contract_requisites_are_masked_without_user_identifier(self):
        text = "Договор № 1909-02-0111 и контракт N ABC-2026-991 используются как реквизиты."

        sanitized, count = redact_contract_requisites(text)

        self.assertEqual(count, 2)
        self.assertNotIn("1909-02-0111", sanitized)
        self.assertNotIn("ABC-2026-991", sanitized)
        self.assertEqual(sanitized.count("[РЕКВИЗИТ-СКРЫТ]"), 2)

    def test_contract_requisites_with_spaces_and_date_are_masked(self):
        examples = [
            "Договор № 12 АБ/2026 заключен сторонами.",
            "Договор от 01.02.2026 № 77-ФЗ применяется к ТЗ.",
            "Контракт № ЦП 15/26 содержит приложение.",
        ]

        for text in examples:
            with self.subTest(text=text):
                sanitized, count = redact_contract_requisites(text)
                self.assertGreaterEqual(count, 1)
                self.assertIn("[РЕКВИЗИТ-СКРЫТ]", sanitized)
                self.assertNotRegex(sanitized, r"(?:12\s+АБ/2026|77-ФЗ|ЦП\s+15/26)")

    def test_unknown_contract_requisite_format_blocks_transfer(self):
        with self.assertRaises(CanonicalAtomizationError) as raised:
            redact_contract_requisites("Договор № @@@ содержит техническое задание")

        self.assertEqual(raised.exception.code, "privacy_requisite_unrecognized")

    def test_discovered_contract_requisite_is_masked_in_later_fragments(self):
        units = [
            source_unit(1, "Техническое задание к договору № ABC-2026-991"),
            source_unit(2, "Материалы ABC-2026-991 используются при приемке продукта"),
        ]

        identifiers = discover_contract_requisites(units)
        batches = build_source_batches(prompt_packet(units))
        outbound_text = "\n".join(
            item["text"]
            for batch in batches
            for item in batch.outbound_units
        )

        self.assertIn("ABC-2026-991", identifiers)
        self.assertNotIn("ABC-2026-991", outbound_text)

    def test_634_units_are_batched_without_loss(self):
        units = [source_unit(index, f"Фрагмент {index}: описание элемента цифрового продукта") for index in range(1, 635)]

        batches = build_source_batches(prompt_packet(units))

        self.assertGreater(len(batches), 1)
        self.assertEqual(sum(len(batch.units) for batch in batches), 634)
        self.assertEqual(
            [item["source_unit_id"] for batch in batches for item in batch.units],
            [item["source_unit_id"] for item in units],
        )
        self.assertTrue(all(len(batch.units) <= 32 for batch in batches))
        self.assertTrue(all("locator" not in item for batch in batches for item in batch.outbound_units))

    def test_schema_retry_prompt_contains_only_safe_correction_code(self):
        batch = build_source_batches(
            prompt_packet([source_unit(1, "Экран содержит реестр обращений.")])
        )[0]

        messages = build_batch_messages(batch, 1, correction_code="coverage_gap")
        payload = json.loads(messages[1]["content"])

        self.assertEqual(payload["correction"]["previous_response_rejected"], "coverage_gap")
        self.assertIn("каждого", payload["correction"]["required_fix"])
        self.assertNotIn("previous_response", payload["correction"])

    def test_atom_can_reference_every_unit_in_full_batch(self):
        units = [
            source_unit(index, f"Фрагмент {index}: часть одного проверяемого элемента")
            for index in range(1, 33)
        ]
        batch = build_source_batches(prompt_packet(units))[0]
        unit_ids = [item["source_unit_id"] for item in units]

        messages = build_batch_messages(batch, 1)
        prompt_payload = json.loads(messages[1]["content"])
        result = validate_batch_result(
            {
                "atoms": [
                    {
                        "local_id": "A1",
                        "title": "Составной проверяемый элемент",
                        "object_type": "Другое",
                        "work_type": None,
                        "notes": None,
                        "source_unit_ids": unit_ids,
                        "anchor_source_unit_id": unit_ids[0],
                        "confidence": 0.9,
                    }
                ],
                "coverage": [
                    {
                        "source_unit_id": unit_id,
                        "disposition": "ATOMIZED" if index == 0 else "DUPLICATE",
                        "reason": "Опорный фрагмент" if index == 0 else "Дополняет тот же элемент",
                    }
                    for index, unit_id in enumerate(unit_ids)
                ],
                "warnings": [],
            },
            batch,
        )

        self.assertEqual(len(result.atoms[0]["source_unit_ids"]), 32)
        self.assertEqual(
            prompt_payload["output_constraints"]["max_source_unit_ids_per_atom"],
            32,
        )

    def test_validated_batches_create_semantic_drafts_not_one_atom_per_fragment(self):
        units = [
            source_unit(1, "Экран содержит реестр обращений."),
            source_unit(2, "В реестре доступны фильтры по периоду и статусу."),
            source_unit(3, "Раздел 4. Общие положения."),
            source_unit(4, "Пользователь может выгрузить отчет в XLSX."),
        ]
        packet = prompt_packet(units)
        batch = build_source_batches(packet)[0]
        result = validate_batch_result(
            {
                "atoms": [
                    {
                        "local_id": "A1",
                        "title": "Реестр обращений с фильтрами",
                        "object_type": "Реестр",
                        "work_type": "Проверка интерфейса",
                        "notes": None,
                        "source_unit_ids": ["U000001", "U000002"],
                        "anchor_source_unit_id": "U000001",
                        "confidence": 0.96,
                    },
                    {
                        "local_id": "A2",
                        "title": "Выгрузка отчета в XLSX",
                        "object_type": "Действие",
                        "work_type": None,
                        "notes": None,
                        "source_unit_ids": ["U000004"],
                        "anchor_source_unit_id": "U000004",
                        "confidence": 0.9,
                    },
                ],
                "coverage": [
                    {"source_unit_id": "U000001", "disposition": "ATOMIZED", "reason": "Опорное требование"},
                    {"source_unit_id": "U000002", "disposition": "DUPLICATE", "reason": "Детализирует атом A1"},
                    {"source_unit_id": "U000003", "disposition": "NON_REQUIREMENT", "reason": "Заголовок"},
                    {"source_unit_id": "U000004", "disposition": "ATOMIZED", "reason": "Отдельное действие"},
                ],
                "warnings": [],
            },
            batch,
        )

        assembled = assemble_atomization_result(packet, [result], model_name="test-model")

        self.assertEqual(len(assembled.drafts), 2)
        self.assertEqual(len(assembled.package["atoms"]), 2)
        self.assertEqual(len(assembled.package["coverage"]), 4)
        self.assertEqual(len(assembled.drafts[0].source_refs), 2)
        self.assertEqual(assembled.coverage_summary["ATOMIZED"], 2)

    def test_duplicate_atoms_from_different_batches_are_consolidated(self):
        units = [source_unit(index, f"Служебный фрагмент {index}") for index in range(1, 34)]
        units[0] = source_unit(1, "Реестр обращений доступен пользователю.")
        units[32] = source_unit(33, "Экран реестра обращений доступен пользователю.")
        packet = prompt_packet(units)
        first, second = build_source_batches(packet)
        first_result = validate_batch_result(
            {
                "atoms": [{
                    "local_id": "A1",
                    "title": "Реестр обращений",
                    "object_type": "Реестр",
                    "work_type": None,
                    "notes": None,
                    "source_unit_ids": ["U000001"],
                    "anchor_source_unit_id": "U000001",
                    "confidence": 0.9,
                }],
                "coverage": [
                    {
                        "source_unit_id": item["source_unit_id"],
                        "disposition": "ATOMIZED" if item["source_unit_id"] == "U000001" else "NON_REQUIREMENT",
                        "reason": "Требование" if item["source_unit_id"] == "U000001" else "Служебный текст",
                    }
                    for item in first.units
                ],
                "warnings": [],
            },
            first,
        )
        second_result = validate_batch_result(
            {
                "atoms": [{
                    "local_id": "A1",
                    "title": "Экран реестра обращений",
                    "object_type": "Реестр",
                    "work_type": None,
                    "notes": None,
                    "source_unit_ids": ["U000033"],
                    "anchor_source_unit_id": "U000033",
                    "confidence": 0.95,
                }],
                "coverage": [{
                    "source_unit_id": "U000033",
                    "disposition": "ATOMIZED",
                    "reason": "Требование",
                }],
                "warnings": [],
            },
            second,
        )

        assembled = assemble_atomization_result(
            packet,
            [first_result, second_result],
            model_name="test-model",
        )

        self.assertEqual(len(assembled.drafts), 1)
        self.assertEqual(len(assembled.drafts[0].source_refs), 2)
        self.assertEqual(assembled.coverage_summary["ATOMIZED"], 1)
        self.assertEqual(assembled.coverage_summary["DUPLICATE"], 1)

    def test_duplicate_atoms_with_same_anchor_keep_atomized_coverage(self):
        packet = prompt_packet([source_unit(1, "Экран содержит реестр обращений и список обращений.")])
        batch = build_source_batches(packet)[0]
        result = validate_batch_result(
            {
                "atoms": [
                    {
                        "local_id": "A1",
                        "title": "Реестр обращений",
                        "object_type": "Реестр",
                        "work_type": None,
                        "notes": None,
                        "source_unit_ids": ["U000001"],
                        "anchor_source_unit_id": "U000001",
                        "confidence": 0.91,
                    },
                    {
                        "local_id": "A2",
                        "title": "Экран реестра обращений",
                        "object_type": "Реестр",
                        "work_type": None,
                        "notes": None,
                        "source_unit_ids": ["U000001"],
                        "anchor_source_unit_id": "U000001",
                        "confidence": 0.94,
                    },
                ],
                "coverage": [
                    {
                        "source_unit_id": "U000001",
                        "disposition": "ATOMIZED",
                        "reason": "Опорное требование",
                    }
                ],
                "warnings": [],
            },
            batch,
        )

        assembled = assemble_atomization_result(packet, [result], model_name="test-model")

        self.assertEqual(len(assembled.package["atoms"]), 1)
        self.assertEqual(assembled.package["coverage"][0]["disposition"], "ATOMIZED")
        self.assertEqual(assembled.coverage_summary["ATOMIZED"], 1)
        self.assertEqual(assembled.coverage_summary["DUPLICATE"], 0)

    def test_coverage_gap_blocks_draft(self):
        packet = prompt_packet([source_unit(1, "Экран"), source_unit(2, "Фильтр")])
        batch = build_source_batches(packet)[0]

        with self.assertRaises(CanonicalAtomizationError) as raised:
            validate_batch_result(
                {
                    "atoms": [],
                    "coverage": [
                        {"source_unit_id": "U000001", "disposition": "NON_REQUIREMENT", "reason": "Нет"}
                    ],
                    "warnings": [],
                },
                batch,
            )

        self.assertEqual(raised.exception.code, "coverage_gap")


if __name__ == "__main__":
    unittest.main()
