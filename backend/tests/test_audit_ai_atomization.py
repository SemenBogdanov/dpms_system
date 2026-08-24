"""Security and completeness tests for AI-assisted audit atomization."""

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import stat
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from fastapi import HTTPException

from app.config import settings
from app.core.security import decode_access_token
from app.services.audit_ai_atomization import (
    AuditAIAtomizationError,
    PreparedAuditAtomization,
    complete_audit_atomization,
    create_audit_privacy_preview,
    extract_audit_source_units,
    parse_audit_skill_package,
    prepare_privacy_safe_atomization,
    verify_audit_privacy_preview,
)
from app.services.audit_skill_package import parse_audit_skill_upload


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
        id=uuid4(),
    )


def skill_version():
    return SimpleNamespace(
        id=uuid4(),
        content_sha256="a" * 64,
        instructions_text="Выделяй одно независимо проверяемое требование в один атом и сохраняй связь с источником.",
        rules_json=["Не объединяй разные пользовательские результаты в один атом."],
    )


def make_skill_archive(*, extra_entries: list[tuple[ZipInfo | str, bytes]] | None = None) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "audit-tz/SKILL.md",
            """---
name: audit-tz
description: "Проверяемая атомизация технических заданий"
---

# Аудит ТЗ

Выполнять детерминированную проверку источника перед модельным анализом.
""",
        )
        archive.writestr(
            "audit-tz/scripts/audit_tz_lib/__init__.py",
            'SKILL_VERSION = "0.3.0"\nSCHEMA_VERSION = "1.0"\n',
        )
        archive.writestr(
            "audit-tz/scripts/audit_tz.py",
            'def main(argv=None):\n    return 0\n',
        )
        for name, content in extra_entries or []:
            archive.writestr(name, content)
    return buffer.getvalue()


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

    def test_trusted_skill_archive_is_verified_but_not_runtime_ready(self):
        data = make_skill_archive()
        digest = sha256(data).hexdigest()
        package = parse_audit_skill_upload("audit-tz.skill", data, trusted_hashes={digest})

        self.assertEqual(package.version, "0.3.0")
        self.assertEqual(package.package_format, "trusted_skill_archive")
        self.assertEqual(package.runtime_status, "pending_worker")
        self.assertEqual(package.package_blob, data)
        self.assertEqual(package.package_manifest["file_count"], 3)

        with self.assertRaises(HTTPException) as context:
            parse_audit_skill_upload("audit-tz.skill", data, trusted_hashes=set())
        self.assertEqual(context.exception.status_code, 422)

    def test_trusted_skill_archive_rejects_path_traversal_and_symlink(self):
        traversal = make_skill_archive(extra_entries=[("audit-tz/../outside.py", b"unsafe")])
        with self.assertRaises(HTTPException) as traversal_context:
            parse_audit_skill_upload(
                "audit-tz.skill",
                traversal,
                trusted_hashes={sha256(traversal).hexdigest()},
            )
        self.assertEqual(traversal_context.exception.status_code, 422)

        symlink = ZipInfo("audit-tz/scripts/link")
        symlink.create_system = 3
        symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
        linked = make_skill_archive(extra_entries=[(symlink, b"/tmp/target")])
        with self.assertRaises(HTTPException) as symlink_context:
            parse_audit_skill_upload(
                "audit-tz.skill",
                linked,
                trusted_hashes={sha256(linked).hexdigest()},
            )
        self.assertEqual(symlink_context.exception.status_code, 422)

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

    def test_privacy_preview_replaces_format_variants_and_fails_closed(self):
        raw_identifier = "19-АБ / 2026"
        data = make_docx([f"По договору 19 – АБ / 2026 должен быть создан экран реестра."])
        with TemporaryDirectory() as temp_dir, patch.object(settings, "UPLOAD_DIR", temp_dir):
            document = document_for(Path(temp_dir) / "contract-secret.docx", data)
            privacy = prepare_privacy_safe_atomization(
                audit_case=SimpleNamespace(digital_product=f"OPEC · {raw_identifier}"),
                document=document,
                skill_version=skill_version(),
                identifiers=[raw_identifier],
                pseudonym="[ДОГОВОР-A1B2C3D4]",
            )

        serialized = json.dumps(privacy.prepared.messages, ensure_ascii=False)
        self.assertNotIn("19-АБ", serialized)
        self.assertNotIn("19 – АБ", serialized)
        self.assertIn("[ДОГОВОР-A1B2C3D4]", serialized)
        self.assertGreaterEqual(privacy.replacement_count, 2)

        with TemporaryDirectory() as temp_dir, patch.object(settings, "UPLOAD_DIR", temp_dir):
            document = document_for(Path(temp_dir) / "contract-secret.docx", data)
            with self.assertRaises(AuditAIAtomizationError) as context:
                prepare_privacy_safe_atomization(
                    audit_case=SimpleNamespace(digital_product="OPEC"),
                    document=document,
                    skill_version=skill_version(),
                    identifiers=["ДРУГОЙ-НОМЕР"],
                )
        self.assertEqual(context.exception.code, "identifier_not_found")

    def test_privacy_token_is_bound_to_alias_document_skill_provider_and_user(self):
        data = make_docx(["Договор 77-AB-2026 предусматривает экран контроля."])
        user_id = uuid4()
        case_id = uuid4()
        provider = SimpleNamespace(
            id=uuid4(),
            config_version=3,
            model_name="test-model",
        )
        version = skill_version()
        with TemporaryDirectory() as temp_dir, patch.object(settings, "UPLOAD_DIR", temp_dir):
            document = document_for(Path(temp_dir) / "technical-spec.docx", data)
            audit_case = SimpleNamespace(digital_product="OPEC")
            preview = create_audit_privacy_preview(
                user_id=user_id,
                case_id=case_id,
                audit_case=audit_case,
                document=document,
                skill_version=version,
                provider=provider,
                identifiers=["77-AB-2026"],
            )
            claims = decode_access_token(preview.token)
            self.assertIsNotNone(claims)
            self.assertNotIn("sub", claims)
            self.assertEqual(claims["uid"], str(user_id))
            verified = verify_audit_privacy_preview(
                token=preview.token,
                user_id=user_id,
                case_id=case_id,
                audit_case=audit_case,
                document=document,
                skill_version=version,
                provider=provider,
                identifiers=["77-AB-2026"],
            )
            self.assertEqual(verified.payload_sha256, preview.payload_sha256)

            with self.assertRaises(AuditAIAtomizationError) as user_context:
                verify_audit_privacy_preview(
                    token=preview.token,
                    user_id=uuid4(),
                    case_id=case_id,
                    audit_case=audit_case,
                    document=document,
                    skill_version=version,
                    provider=provider,
                    identifiers=["77-AB-2026"],
                )
            self.assertEqual(user_context.exception.code, "privacy_context_changed")

            with self.assertRaises(AuditAIAtomizationError) as context:
                verify_audit_privacy_preview(
                    token=preview.token,
                    user_id=user_id,
                    case_id=case_id,
                    audit_case=audit_case,
                    document=document,
                    skill_version=version,
                    provider=provider,
                    identifiers=["77-AB-2027"],
                )
        self.assertEqual(context.exception.code, "identifier_not_found")

    def test_privacy_gate_blocks_identifier_inside_skill_instructions(self):
        identifier = "77-AB-2026"
        data = make_docx([f"Договор {identifier} предусматривает экран контроля."])
        leaking_skill = skill_version()
        leaking_skill.instructions_text += f" Внутренняя ссылка: {identifier}."
        with TemporaryDirectory() as temp_dir, patch.object(settings, "UPLOAD_DIR", temp_dir):
            document = document_for(Path(temp_dir) / "technical-spec.docx", data)
            with self.assertRaises(AuditAIAtomizationError) as context:
                prepare_privacy_safe_atomization(
                    audit_case=SimpleNamespace(digital_product="OPEC"),
                    document=document,
                    skill_version=leaking_skill,
                    identifiers=[identifier],
                )
        self.assertEqual(context.exception.code, "privacy_leak_detected")

    async def test_model_call_rejects_unverified_payload(self):
        prepared = PreparedAuditAtomization(
            messages=[{"role": "user", "content": "raw document"}],
            units=[],
            source_manifest=[],
            prompt_sha256="0" * 64,
            privacy_verified=False,
        )
        with patch(
            "app.services.audit_ai_atomization.generate_text",
            new=AsyncMock(),
        ) as generate:
            with self.assertRaises(AuditAIAtomizationError) as context:
                await complete_audit_atomization(
                    provider=SimpleNamespace(),
                    prepared=prepared,
                    digital_product="AUDIT",
                )
        self.assertEqual(context.exception.code, "privacy_verification_required")
        generate.assert_not_awaited()

    async def test_valid_model_result_preserves_citations_and_coverage(self):
        data = make_docx(["Должен быть экран списка договоров.", "Пояснительный текст."])
        with TemporaryDirectory() as temp_dir, patch.object(settings, "UPLOAD_DIR", temp_dir):
            document = document_for(Path(temp_dir) / "technical-spec.docx", data)
            prepared = prepare_privacy_safe_atomization(
                audit_case=SimpleNamespace(digital_product="AUDIT CONTRACT-TEST-001"),
                document=document,
                skill_version=skill_version(),
                identifiers=["CONTRACT-TEST-001"],
            ).prepared
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
            prepared = prepare_privacy_safe_atomization(
                audit_case=SimpleNamespace(digital_product="AUDIT CONTRACT-TEST-001"),
                document=document,
                skill_version=skill_version(),
                identifiers=["CONTRACT-TEST-001"],
            ).prepared
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
