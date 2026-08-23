"""Security and completeness tests for AI-assisted audit atomization."""

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import HTTPException

from app.config import settings
from app.services.audit_ai_atomization import (
    AuditAIAtomizationError,
    complete_audit_atomization,
    extract_audit_source_units,
    parse_audit_skill_package,
    prepare_audit_atomization,
)


WORD_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_docx(paragraphs: list[str], *, external_relation: bool = False) -> bytes:
    body = "".join(
        f'<w:p><w:r><w:t>{text}</w:t></w:r></w:p>'
        for text in paragraphs
    )
    document_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{WORD_NS}"><w:body>{body}</w:body></w:document>'
    )
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types />")
        archive.writestr("word/document.xml", document_xml)
        if external_relation:
            archive.writestr(
                "word/_rels/document.xml.rels",
                '<Relationships><Relationship TargetMode="External" Target="https://example.test" /></Relationships>',
            )
    return buffer.getvalue()


def document_for(path: Path, data: bytes):
    path.write_bytes(data)
    return SimpleNamespace(
        original_filename=path.name,
        stored_filename=path.name,
        sha256=sha256(data).hexdigest(),
    )


def skill_version():
    return SimpleNamespace(
        instructions_text="Выделяй одно независимо проверяемое требование в один атом и сохраняй связь с источником.",
        rules_json=["Не объединяй разные пользовательские результаты в один атом."],
    )


class AuditAIAtomizationTests(unittest.IsolatedAsyncioTestCase):
    def test_skill_package_is_declarative_and_strict(self):
        payload = {
            "schema_version": "1.0",
            "slug": "audit-tz",
            "name": "Атомизация ТЗ",
            "version": "1.0.0",
            "description": "Тестовая методика",
            "instructions": "Разделяй документ на независимо проверяемые атомы и всегда указывай исходный фрагмент.",
            "rules": ["Не придумывай отсутствующие требования."],
        }
        package, digest = parse_audit_skill_package(
            "audit-skill.json",
            json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        )
        self.assertEqual(package.slug, "audit-tz")
        self.assertEqual(len(digest), 64)

        payload["executable"] = "import os"
        with self.assertRaises(HTTPException) as context:
            parse_audit_skill_package(
                "audit-skill.json",
                json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )
        self.assertEqual(context.exception.status_code, 422)

    def test_docx_extraction_has_stable_source_units(self):
        data = make_docx(["Первое проверяемое требование.", "Второе проверяемое требование."])
        with TemporaryDirectory() as temp_dir, patch.object(settings, "UPLOAD_DIR", temp_dir):
            document = document_for(Path(temp_dir) / "technical-spec.docx", data)
            units = extract_audit_source_units(document)

        self.assertEqual([unit.source_unit_id for unit in units], ["U000001", "U000002"])
        self.assertEqual(units[0].locator, "DOCX, абзац 1")
        self.assertEqual(units[1].text, "Второе проверяемое требование.")

    def test_docx_with_external_relationship_is_rejected(self):
        data = make_docx(["Требование."], external_relation=True)
        with TemporaryDirectory() as temp_dir, patch.object(settings, "UPLOAD_DIR", temp_dir):
            document = document_for(Path(temp_dir) / "technical-spec.docx", data)
            with self.assertRaises(AuditAIAtomizationError) as context:
                extract_audit_source_units(document)
        self.assertEqual(context.exception.code, "external_office_relationship")

    def test_document_hash_change_blocks_atomization(self):
        data = make_docx(["Требование."])
        with TemporaryDirectory() as temp_dir, patch.object(settings, "UPLOAD_DIR", temp_dir):
            document = document_for(Path(temp_dir) / "technical-spec.docx", data)
            document.sha256 = "0" * 64
            with self.assertRaises(AuditAIAtomizationError) as context:
                extract_audit_source_units(document)
        self.assertEqual(context.exception.code, "document_hash_changed")

    async def test_valid_model_result_preserves_citations_and_coverage(self):
        data = make_docx(["Должен быть экран списка договоров.", "Пояснительный текст."])
        with TemporaryDirectory() as temp_dir, patch.object(settings, "UPLOAD_DIR", temp_dir):
            document = document_for(Path(temp_dir) / "technical-spec.docx", data)
            prepared = prepare_audit_atomization(
                audit_case=SimpleNamespace(digital_product="AUDIT"),
                document=document,
                skill_version=skill_version(),
            )
            response = json.dumps({
                "atoms": [{
                    "title": "Экран списка договоров доступен пользователю",
                    "work_type": "Разработка",
                    "object_type": "Экран",
                    "notes": None,
                    "source_unit_ids": ["U000001"],
                    "confidence": 0.91,
                }],
                "coverage": [
                    {"source_unit_id": "U000001", "disposition": "ATOMIZED", "reason": "Проверяемое требование"},
                    {"source_unit_id": "U000002", "disposition": "NON_REQUIREMENT", "reason": "Контекст"},
                ],
                "warnings": [],
            }, ensure_ascii=False)
            with patch(
                "app.services.audit_ai_atomization.generate_text",
                new=AsyncMock(return_value=response),
            ):
                result = await complete_audit_atomization(
                    provider=SimpleNamespace(),
                    prepared=prepared,
                    digital_product="AUDIT",
                )

        self.assertEqual(len(result.drafts), 1)
        self.assertEqual(result.drafts[0].source_refs[0]["source_unit_id"], "U000001")
        self.assertEqual(result.coverage_summary["ATOMIZED"], 1)
        self.assertEqual(result.coverage_summary["NON_REQUIREMENT"], 1)
        self.assertEqual(result.drafts[0].confidence_percent, 91)

    async def test_model_coverage_gap_rejects_entire_result(self):
        data = make_docx(["Первое требование.", "Второе требование."])
        with TemporaryDirectory() as temp_dir, patch.object(settings, "UPLOAD_DIR", temp_dir):
            document = document_for(Path(temp_dir) / "technical-spec.docx", data)
            prepared = prepare_audit_atomization(
                audit_case=SimpleNamespace(digital_product="AUDIT"),
                document=document,
                skill_version=skill_version(),
            )
            response = json.dumps({
                "atoms": [{
                    "title": "Первое требование",
                    "work_type": None,
                    "object_type": None,
                    "notes": None,
                    "source_unit_ids": ["U000001"],
                    "confidence": None,
                }],
                "coverage": [
                    {"source_unit_id": "U000001", "disposition": "ATOMIZED", "reason": "Требование"},
                ],
                "warnings": [],
            }, ensure_ascii=False)
            with patch(
                "app.services.audit_ai_atomization.generate_text",
                new=AsyncMock(return_value=response),
            ):
                with self.assertRaises(AuditAIAtomizationError) as context:
                    await complete_audit_atomization(
                        provider=SimpleNamespace(),
                        prepared=prepared,
                        digital_product="AUDIT",
                    )
        self.assertEqual(context.exception.code, "coverage_gap")


if __name__ == "__main__":
    unittest.main()
