"""Data-only archive validation and skill-engine isolation, with no external services."""

from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
from io import BytesIO
import asyncio
import json
from pathlib import Path
import stat
import struct
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
import warnings
from zipfile import ZIP_DEFLATED, ZIP_STORED, ZipFile, ZipInfo
from zlib import crc32

from fastapi import HTTPException, UploadFile
from sqlalchemy import func, select, text
from sqlalchemy.dialects.sqlite.base import SQLiteTypeCompiler
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.schema import CreateTable

from app.api.routes.ai_provider import (
    _lock_skill_import,
    activate_audit_atomization_skill,
    import_audit_atomization_skill,
    list_audit_atomization_skills,
    retry_audit_atomization_skill_selftest,
)
from app.models.ai_provider import AIProviderEvent, AuditAtomizationSkill, AuditAtomizationSkillVersion
from app.models.audit_runtime import AuditTZRuntimeJob
from app.services import audit_skill_package as service


def skill_text(slug="sample-audit", *, version=None, description="Review bounded source requirements."):
    version_line = f"version: {version}\n" if version is not None else ""
    return (
        f"---\nname: {slug}\ndescription: {description}\n{version_line}---\n\n"
        "# Audit\nKeep each requirement independently verifiable and retain its source.\n"
    )


def archive_bytes(entries=None, *, root="sample-audit", compression=ZIP_STORED):
    if entries is None:
        entries = [("SKILL.md", skill_text())]
    output = BytesIO()
    with warnings.catch_warnings(), ZipFile(output, "w", compression=compression) as archive:
        warnings.simplefilter("ignore", UserWarning)
        for name, content in entries:
            if isinstance(name, str):
                name = f"{root}/{name}" if root else name
            archive.writestr(name, content)
    return output.getvalue()


def trusted_bytes():
    return archive_bytes([
        ("SKILL.md", skill_text("audit-tz")),
        ("scripts/audit_tz.py", "raise RuntimeError('must never execute')\n"),
        ("scripts/audit_tz_lib/__init__.py", 'SKILL_VERSION = "0.3.0"\nSCHEMA_VERSION = "1.0"\n'),
    ], root="audit-tz")


def forge_zip_member(data, name, *, size=None, crc=None, compressed_size=None, local_too=False):
    raw = bytearray(data)
    offset = raw.index(b"PK\x01\x02")
    while raw[offset:offset + 4] == b"PK\x01\x02":
        name_size, extra_size, comment_size = struct.unpack_from("<HHH", raw, offset + 28)
        filename = raw[offset + 46:offset + 46 + name_size].decode()
        if filename == name:
            local = struct.unpack_from("<I", raw, offset + 42)[0]
            for value, central_field, local_field in ((crc, 16, 14), (size, 24, 22), (compressed_size, 20, 18)):
                if value is not None:
                    struct.pack_into("<I", raw, offset + central_field, value)
                    if local_too:
                        struct.pack_into("<I", raw, local + local_field, value)
            return bytes(raw)
        offset += 46 + name_size + extra_size + comment_size
    raise AssertionError("Synthetic ZIP member not found")


class DeclarativeArchiveTests(unittest.TestCase):
    def parse(self, data):
        return service.parse_audit_skill_upload("method.skill", data, trusted_hashes=set())

    def reject(self, data, *, status=422, detail=None):
        with self.assertRaises(HTTPException) as caught:
            self.parse(data)
        self.assertEqual(caught.exception.status_code, status)
        if detail:
            self.assertIn(detail, caught.exception.detail)

    def test_archive_keeps_complete_deterministic_text_and_provenance(self):
        entries = [
            ("SKILL.md", skill_text() + "[rules](references/rules.md)\n"),
            ("references/rules.md", "Use [template](../assets/rows.csv).\n"),
            ("assets/rows.csv", "requirement,source\n"),
            ("references/unlinked.txt", "Keep this complete too.\n"),
            ("references/schema.json", '{"type": "object"}\n'),
        ]
        data = archive_bytes(entries)
        parsed = self.parse(data)
        self.assertEqual(parsed.package_format, "declarative_archive")
        self.assertEqual(parsed.runtime_status, "ready")
        self.assertEqual(parsed.package_blob, data)
        self.assertEqual(parsed.content_sha256, sha256(data).hexdigest())
        self.assertEqual(parsed.version, f"sha256-{sha256(data).hexdigest()}")
        self.assertEqual(parsed.version, self.parse(data).version)
        self.assertEqual(parsed.rules, [])
        self.assertTrue(parsed.instructions.startswith(entries[0][1]))
        for name, content in entries:
            self.assertIn(content, parsed.instructions)
            manifest = next(item for item in parsed.package_manifest["files"] if item["path"] == name)
            self.assertEqual(manifest["size_bytes"], len(content.encode()))
            self.assertEqual(manifest["sha256"], sha256(content.encode()).hexdigest())
        self.assertEqual(parsed.package_manifest["file_count"], len(entries))
        self.assertEqual(parsed.package_manifest["instruction_bytes"], len(parsed.instructions.encode()))
        self.assertEqual(parsed.package_manifest["instructions_sha256"], sha256(parsed.instructions.encode()).hexdigest())
        self.assertEqual(parsed.instructions, self.parse(archive_bytes(list(reversed(entries)))).instructions)

    def test_provided_package_is_data_only_complete_and_versionless(self):
        source = Path("/Users/bogdanov/Code/audit-atomy/dist/audit-tz-atoms.skill")
        if not source.is_file():
            self.skipTest("Optional provided package is not present on this machine")
        self.assertFalse(source.is_symlink())
        data = source.read_bytes()
        parsed = self.parse(data)
        self.assertEqual(parsed.slug, "audit-tz-atoms")
        self.assertEqual(parsed.package_manifest["file_count"], 6)
        self.assertEqual(parsed.package_manifest["version_source"], "archive_sha256")
        self.assertGreater(len(parsed.instructions.encode()), 64 * 1024)
        self.assertLessEqual(len(parsed.instructions.encode()), 128 * 1024)
        with ZipFile(BytesIO(data)) as archive:
            for item in parsed.package_manifest["files"]:
                content = archive.read(f"audit-tz-atoms/{item['path']}")
                self.assertIn(content.decode(), parsed.instructions)
                self.assertEqual(sha256(content).hexdigest(), item["sha256"])

    def test_rootless_archive_and_explicit_version(self):
        parsed = self.parse(archive_bytes([("SKILL.md", skill_text(version="2.1-preview"))], root=""))
        self.assertEqual(parsed.version, "2.1-preview")
        self.assertEqual(parsed.package_manifest["root"], "")
        self.assertEqual(parsed.package_manifest["version_source"], "frontmatter")

    def test_utf8_budget_includes_reference_headers_and_rejects_not_truncates(self):
        limit = service.MAX_DECLARATIVE_INSTRUCTION_BYTES
        body = skill_text()
        header = "\n\n## Reference: references/data.txt\n\n"
        remaining = limit - len((body + header).encode())
        reference = "\u044f" * (remaining // 2) + "x" * (remaining % 2)
        entries = [("SKILL.md", body), ("references/data.txt", reference)]
        self.assertEqual(len(self.parse(archive_bytes(entries)).instructions.encode()), limit)
        entries[-1] = ("references/data.txt", reference + "x")
        self.reject(archive_bytes(entries), status=413)
        self.reject(archive_bytes([("SKILL.md", body + "x" * limit)]), status=413)

    def test_rejects_unsafe_paths_before_reading_members(self):
        for path in (
            "../escape.md", "/absolute.md", "x/../escape.md", "x//dup.md", "x/./dup.md",
            "C:/drive.md", "x\\escape.md", "x\x00hidden.md", ".env", "references/api-key.txt",
            "references/credentials.json", ".git/config.txt", "references/session.txt", "trailing.md ",
        ):
            with self.subTest(path=path), patch.object(service, "_read_archive_member", side_effect=AssertionError("must not read")):
                self.reject(archive_bytes([("SKILL.md", skill_text()), (path, "do not read")], root=""))

    def test_rejects_code_unknown_executable_and_special_files(self):
        for path in ("scripts/run.py", "run.sh", "run.exe", "binary", "nested/run.js", "a.md.py"):
            with self.subTest(path=path):
                self.reject(archive_bytes([("SKILL.md", skill_text()), (path, "unused")]), detail="SHA-256")
        for mode in (stat.S_IFLNK | 0o777, stat.S_IFIFO | 0o600, stat.S_IFREG | 0o755):
            item = ZipInfo("sample-audit/references/text.md")
            item.create_system = 3
            item.external_attr = mode << 16
            with self.subTest(mode=mode):
                self.reject(archive_bytes([("SKILL.md", skill_text()), (item, "unused")]))
        for content in (b"#! /bin/sh\necho no", b"text\x00binary", b"\xff\xfe", b"text\x1b[0m"):
            self.reject(archive_bytes([("SKILL.md", skill_text()), ("references/text.txt", content)]))

    def test_rejects_duplicates_multiple_roots_nested_skills_and_file_directory_collisions(self):
        for extras in (
            [("SKILL.md", "duplicate")], [("skill.MD", "case duplicate")],
            [("nested/SKILL.md", skill_text())], [("file.md", "x"), ("file.md/sub.txt", "y")],
        ):
            with self.subTest(extras=extras):
                self.reject(archive_bytes([("SKILL.md", skill_text()), *extras]))
        self.reject(archive_bytes([("one/SKILL.md", skill_text()), ("two/file.txt", "x")], root=""))

    def test_local_references_fail_closed_and_remote_includes_never_load(self):
        for content in (
            "[link](missing.md)", "[link](../../outside.md)", "[link](https://example.test/rules.md)",
            "[link](//example.test/rules.md)", "[link](file:///private/path)",
            "[link](%2e%2e/outside.md)", "[link](references/rules.md?load=1)",
            "[rules]: https://example.test/rules.md", "![include](https://example.test/a.md)",
            "!include: remote.md", "{% include 'remote.md' %}", "![[rules.md]]",
            "<!--#include file='outside.md' -->", ".. include:: outside.md",
            "<script>alert(1)</script>", "```python\nprint('no')\n```",
        ):
            with self.subTest(content=content):
                self.reject(archive_bytes([("SKILL.md", skill_text() + content)]))
        self.parse(archive_bytes([
            ("SKILL.md", skill_text() + "[rules][r]\n[r]: references/rules.md\n[anchor](#audit)"),
            ("references/rules.md", "```json\n{}\n```\nProse after a data fence.\n"),
        ]))

    def test_frontmatter_yaml_scalars_and_conservative_fallback(self):
        body = skill_text(description='"Quoted: description"', version='"2.0"')
        with patch.object(service, "yaml", None):
            self.assertEqual(self.parse(archive_bytes([("SKILL.md", body)])).description, "Quoted: description")
            self.reject(archive_bytes([("SKILL.md", skill_text(description="|\n  multiline"))]))
        if service.yaml is not None:
            parsed = self.parse(archive_bytes([("SKILL.md", skill_text(description=">-\n  folded\n  description"))]))
            self.assertEqual(parsed.description, "folded description")
        for frontmatter in (
            "name: sample-audit\nname: duplicate\ndescription: text",
            "name: sample-audit\ndescription: &ref text\nversion: *ref",
            "name: sample-audit\ndescription: !!python/object:object {}",
            "name: sample-audit\ndescription: {nested: text}",
            "name: sample-audit\ndescription: text\nexecutable: run.py",
            "name: Sample_Audit\ndescription: text", "name: sample-audit",
            "name: sample-audit\ndescription: text\nversion:",
        ):
            with self.subTest(frontmatter=frontmatter):
                self.reject(archive_bytes([("SKILL.md", f"---\n{frontmatter}\n---\nAudit source.\n")]))
        self.reject(archive_bytes([("SKILL.md", "No frontmatter")]))
        self.reject(archive_bytes([("SKILL.md", "---\nname: sample-audit\n---")]))

    def test_nested_yaml_rejected_before_compose_and_long_text_is_bounded(self):
        if service.yaml is not None:
            with patch.object(service.yaml, "compose", side_effect=AssertionError("must reject before compose")):
                nested = "[" * 2000 + "x" + "]" * 2000
                self.reject(archive_bytes([("SKILL.md", skill_text(description=nested))]))
        self.parse(archive_bytes([("SKILL.md", skill_text() + "a." * 20_000 + "\n" * 20_000)]))

    def test_frontmatter_rejects_decoded_surrogates_and_control_characters(self):
        for parser in (service.yaml, None):
            with patch.object(service, "yaml", parser):
                for description in ('"\\ud800"', '"\\u0000"', '"\\u001b"'):
                    with self.subTest(parser=parser is not None, description=description):
                        self.reject(archive_bytes([("SKILL.md", skill_text(description=description))]))

    def test_zip_size_count_ratio_corruption_and_encryption_limits(self):
        self.reject(b"", status=400)
        self.reject(b"not a zip", status=400)
        self.reject(b"x" * (service.MAX_SKILL_ARCHIVE_BYTES + 1), status=413)
        self.reject(archive_bytes([(f"{n}.txt", "x") for n in range(service.MAX_SKILL_ARCHIVE_FILES + 1)]), status=413)
        self.reject(archive_bytes([("SKILL.md", skill_text() + "x" * 100_000)], compression=ZIP_DEFLATED), status=413)
        data = bytearray(archive_bytes())
        central = data.index(b"PK\x01\x02")
        struct.pack_into("<H", data, central + 8, 1)
        self.reject(bytes(data))
        data = bytearray(archive_bytes())
        central = data.index(b"PK\x01\x02")
        struct.pack_into("<I", data, central + 16, 0)
        self.reject(bytes(data))
        data = bytearray(archive_bytes())
        central = data.index(b"PK\x01\x02")
        struct.pack_into("<H", data, central + 10, 99)
        self.reject(bytes(data))

    def test_forged_zip_sizes_never_truncate_required_references(self):
        prefix = b"Visible reference.\n"
        for compression in (ZIP_STORED, ZIP_DEFLATED):
            for repetitions in (1, 5000):
                for local_too in (False, True):
                    payload = prefix + b"Additional required reference text.\n" * repetitions
                    data = archive_bytes([
                        ("SKILL.md", skill_text()), ("references/rules.txt", payload),
                    ], compression=compression)
                    forged = forge_zip_member(data, "sample-audit/references/rules.txt", size=len(prefix), crc=crc32(prefix), local_too=local_too)
                    with self.subTest(compression=compression, repetitions=repetitions, local_too=local_too):
                        with self.assertRaises(HTTPException) as caught:
                            self.parse(forged)
                        self.assertIn(caught.exception.status_code, (400, 413, 422))

    def test_directory_payload_and_incomplete_deflate_stream_rejected(self):
        for compression in (ZIP_STORED, ZIP_DEFLATED):
            data = archive_bytes([
                ("SKILL.md", skill_text()), ("references/", b"Hidden reference payload"),
            ], compression=compression)
            forged = forge_zip_member(data, "sample-audit/references/", size=0, crc=0, local_too=True)
            with self.subTest(compression=compression), self.assertRaises(HTTPException):
                self.parse(forged)
        data = archive_bytes(compression=ZIP_DEFLATED)
        with ZipFile(BytesIO(data)) as archive:
            size = archive.getinfo("sample-audit/SKILL.md").compress_size
        self.reject(forge_zip_member(data, "sample-audit/SKILL.md", compressed_size=size - 1, local_too=True))

    def test_deflate_trailing_bytes_and_concatenated_streams_rejected(self):
        for suffix in (b"trailing payload", b"\x03\x00"):
            data = archive_bytes(compression=ZIP_DEFLATED)
            with ZipFile(BytesIO(data)) as archive:
                compressed_size = archive.getinfo("sample-audit/SKILL.md").compress_size
            central = data.index(b"PK\x01\x02")
            forged = bytearray(data[:central] + suffix + data[central:])
            end_record = forged.rindex(b"PK\x05\x06")
            struct.pack_into("<I", forged, end_record + 16, central + len(suffix))
            forged = forge_zip_member(forged, "sample-audit/SKILL.md", compressed_size=compressed_size + len(suffix), local_too=True)
            with self.subTest(suffix=suffix):
                self.reject(forged)

    def test_data_descriptors_are_validated_and_supported(self):
        class NonSeekableBuffer(BytesIO):
            def seek(self, *args):
                raise OSError("Non-seekable synthetic output")

        for compression in (ZIP_STORED, ZIP_DEFLATED):
            output = NonSeekableBuffer()
            with ZipFile(output, "w", compression=compression) as archive:
                archive.writestr("sample-audit/SKILL.md", skill_text())
            data = output.getvalue()
            parsed = self.parse(data)
            self.assertEqual(parsed.instructions, skill_text())
            descriptor = data.index(b"PK\x07\x08")
            corrupted = bytearray(data)
            struct.pack_into("<I", corrupted, descriptor + 4, 0)
            with self.subTest(compression=compression):
                self.reject(corrupted)

    def test_zip64_is_explicitly_rejected_for_data_only_archives(self):
        output = BytesIO()
        with ZipFile(output, "w") as archive:
            with archive.open("sample-audit/SKILL.md", "w", force_zip64=True) as member:
                member.write(skill_text().encode())
        self.reject(output.getvalue(), detail="ZIP64")

    def test_multiline_and_nested_markdown_links_cannot_escape_package(self):
        for target in ("../../outside.md", "//example.test/rules.md", "missing.md"):
            for label in ("rules", "rules\non two lines", "rules [nested label]"):
                for space in ("\n", " \r\n\t", " "):
                    with self.subTest(target=target, label=label, space=space):
                        self.reject(archive_bytes([("SKILL.md", skill_text() + f"[{label}]({space}{target}\n)")]))
        self.reject(archive_bytes([("SKILL.md", skill_text() + "[rules\non two lines]:\n  //example.test/rules.md")]))
        parsed = self.parse(archive_bytes([
            ("SKILL.md", skill_text() + "[rules [nested]](\nreferences/rules.md\n)\n[other\nlabel]:\nreferences/rules.md"),
            ("references/rules.md", "All local references remain available."),
        ]))
        self.assertIn("All local references remain available.", parsed.instructions)

    def test_trusted_allowlist_is_exact_and_never_falls_back(self):
        data = trusted_bytes()
        self.reject(data, detail="SHA-256")
        parsed = service.parse_audit_skill_upload("audit-tz.skill", data, trusted_hashes={sha256(data).hexdigest()})
        self.assertEqual(parsed.package_format, "trusted_skill_archive")
        self.assertEqual(parsed.runtime_status, "pending_worker")
        self.assertEqual(parsed.version, "0.3.0")
        self.assertEqual(parsed.package_blob, data)
        invalid_canonical = archive_bytes()
        with self.assertRaises(HTTPException):
            service.parse_audit_skill_upload("audit-tz.skill", invalid_canonical, trusted_hashes={sha256(invalid_canonical).hexdigest()})


class DeclarativeSkillRouteTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        tables = (AuditAtomizationSkill, AuditAtomizationSkillVersion, AIProviderEvent, AuditTZRuntimeJob)
        with patch.object(SQLiteTypeCompiler, "visit_JSONB", lambda self, type_, **kw: "JSON", create=True):
            async with self.engine.begin() as connection:
                for model in tables:
                    await connection.execute(CreateTable(model.__table__))
                await connection.execute(text(
                    "CREATE UNIQUE INDEX test_active_skill ON audit_atomization_skill_versions(skill_id) WHERE is_active"
                ))
        self.db = AsyncSession(self.engine, expire_on_commit=False)
        self.admin = SimpleNamespace(id=uuid4())

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def upload(self, data, *, filename="method.skill", trusted=False):
        allowed = {sha256(data).hexdigest()} if trusted else set()
        with patch.object(service, "_trusted_hashes", return_value=allowed):
            return await import_audit_atomization_skill(
                file=UploadFile(filename=filename, file=BytesIO(data)), admin=self.admin, db=self.db,
            )

    async def test_import_deduplicates_immutable_archives_and_never_queues_selftest(self):
        data = archive_bytes()
        first = await self.upload(data)
        second = await self.upload(data)
        self.assertEqual(first.id, second.id)
        self.assertTrue(first.is_active)
        self.assertTrue(first.runtime_ready)
        self.assertFalse(first.is_trusted_archive)
        self.assertEqual(first.runtime_selftest, {})
        self.assertEqual(first.package_format, "declarative_archive")
        version = await self.db.get(AuditAtomizationSkillVersion, first.id)
        self.assertEqual(version.package_blob, data)
        self.assertEqual(version.content_sha256, sha256(data).hexdigest())
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(AuditTZRuntimeJob)), 0)
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(AuditAtomizationSkillVersion)), 1)
        with self.assertRaises(HTTPException) as caught:
            await retry_audit_atomization_skill_selftest(first.id, admin=self.admin, db=self.db)
        self.assertEqual(caught.exception.status_code, 409)

    async def test_multiple_slugs_stay_active_and_explicit_activation_is_slug_scoped(self):
        first = await self.upload(archive_bytes())
        other = await self.upload(archive_bytes([("SKILL.md", skill_text("other-audit"))], root="other-audit"))
        updated_data = archive_bytes([("SKILL.md", skill_text(version="2.0"))])
        updated = await self.upload(updated_data)
        original = await self.db.get(AuditAtomizationSkillVersion, first.id)
        self.assertFalse(original.is_active)
        self.assertTrue((await self.db.get(AuditAtomizationSkillVersion, other.id)).is_active)
        await activate_audit_atomization_skill(first.id, admin=self.admin, db=self.db)
        self.assertTrue(original.is_active)
        self.assertFalse((await self.db.get(AuditAtomizationSkillVersion, updated.id)).is_active)
        result = await list_audit_atomization_skills(self.admin, self.db)
        self.assertEqual({item.slug for item in result.items if item.is_active}, {"sample-audit", "other-audit"})
        self.assertEqual((await self.db.get(AuditAtomizationSkillVersion, updated.id)).package_blob, updated_data)

    async def test_same_version_different_content_is_conflict_without_mutation(self):
        first = await self.upload(archive_bytes([("SKILL.md", skill_text(version="1.0"))]))
        with self.assertRaises(HTTPException) as caught:
            await self.upload(archive_bytes([("SKILL.md", skill_text(version="1.0") + "Changed.")]))
        self.assertEqual(caught.exception.status_code, 409)
        self.assertTrue((await self.db.get(AuditAtomizationSkillVersion, first.id)).is_active)

    async def test_json_and_archive_share_declarative_engine(self):
        first = await self.upload(archive_bytes())
        payload = dict(schema_version="1.0", slug="sample-audit", name="Sample audit", version="json-2", instructions="Preserve source references and split independently verifiable requirements.")
        second = await self.upload(json.dumps(payload).encode(), filename="method.json")
        self.assertEqual(first.skill_id, second.skill_id)
        self.assertTrue(second.is_active)
        self.assertFalse((await self.db.get(AuditAtomizationSkillVersion, first.id)).is_active)

    async def test_trusted_engine_cannot_be_replaced_by_json_or_data_archive(self):
        trusted = await self.upload(trusted_bytes(), trusted=True)
        version = await self.db.get(AuditAtomizationSkillVersion, trusted.id)
        self.assertFalse(version.is_active)
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(AuditTZRuntimeJob)), 1)
        version.runtime_status = "ready"
        await activate_audit_atomization_skill(version.id, admin=self.admin, db=self.db)
        payload = dict(schema_version="1.0", slug="audit-tz", name="Replacement", version="1.0", instructions="Preserve source references and split independently verifiable requirements.")
        for data, filename in (
            (json.dumps(payload).encode(), "method.json"),
            (archive_bytes([("SKILL.md", skill_text("audit-tz"))], root="audit-tz"), "method.skill"),
        ):
            with self.subTest(filename=filename), self.assertRaises(HTTPException) as caught:
                await self.upload(data, filename=filename)
            self.assertEqual(caught.exception.status_code, 409)
            self.assertIn("slug", caught.exception.detail)
            self.assertTrue(version.is_active)
            self.assertEqual((await self.db.get(AuditAtomizationSkill, version.skill_id)).name, trusted.name)
        other = await self.upload(archive_bytes())
        self.assertTrue(other.is_active)
        self.assertTrue(version.is_active)

    async def test_reverse_engine_collision_and_activation_of_legacy_mixed_slug(self):
        first = await self.upload(archive_bytes([("SKILL.md", skill_text("audit-tz"))]))
        with self.assertRaises(HTTPException) as caught:
            await self.upload(trusted_bytes(), trusted=True)
        self.assertEqual(caught.exception.status_code, 409)
        mixed = AuditAtomizationSkillVersion(
            skill_id=first.skill_id, version_label="old-trusted", schema_version="1.0",
            instructions_text="Existing legacy mixed-engine version", rules_json=[],
            content_sha256="a" * 64, source_filename="old.skill", package_format="trusted_skill_archive",
            package_blob=b"opaque", package_manifest_json={}, runtime_status="ready", is_active=False,
        )
        self.db.add(mixed)
        await self.db.flush()
        with self.assertRaises(HTTPException) as caught:
            await activate_audit_atomization_skill(mixed.id, admin=self.admin, db=self.db)
        self.assertEqual(caught.exception.status_code, 409)
        self.assertTrue((await self.db.get(AuditAtomizationSkillVersion, first.id)).is_active)

    async def test_legacy_inactive_json_does_not_block_existing_trusted_engine(self):
        imported = await self.upload(trusted_bytes(), trusted=True)
        trusted = await self.db.get(AuditAtomizationSkillVersion, imported.id)
        trusted.runtime_status = "ready"
        trusted.is_active = True
        old_json = AuditAtomizationSkillVersion(
            skill_id=trusted.skill_id, version_label="legacy-json", schema_version="1.0",
            instructions_text="Historical declarative methodology", rules_json=[], content_sha256="d" * 64,
            source_filename="old.json", package_format="declarative_json", package_blob=None,
            package_manifest_json={}, runtime_status="ready", is_active=False,
        )
        self.db.add(old_json)
        await self.db.flush()
        result = await activate_audit_atomization_skill(trusted.id, admin=self.admin, db=self.db)
        self.assertTrue(result.is_active)
        with self.assertRaises(HTTPException) as caught:
            await activate_audit_atomization_skill(old_json.id, admin=self.admin, db=self.db)
        self.assertEqual(caught.exception.status_code, 409)
        with ZipFile(BytesIO(trusted_bytes())) as archive:
            entries = [(item.filename.removeprefix("audit-tz/"), archive.read(item)) for item in archive.infolist()]
        updated = archive_bytes([
            (name, content.replace(b'"0.3.0"', b'"0.3.1"') if name.endswith("__init__.py") else content)
            for name, content in entries
        ], root="audit-tz")
        with self.assertRaises(HTTPException):
            await self.upload(updated, trusted=False)
        pending = await self.upload(updated, trusted=True)
        self.assertFalse(pending.is_active)
        self.assertEqual(pending.runtime_status, "pending_worker")
        for runtime_status in ("pending_worker", "runtime_failed"):
            version = await self.db.get(AuditAtomizationSkillVersion, pending.id)
            version.runtime_status = runtime_status
            with self.assertRaises(HTTPException) as caught:
                await activate_audit_atomization_skill(version.id, admin=self.admin, db=self.db)
            self.assertEqual(caught.exception.status_code, 409)
        version.runtime_status = "ready"
        result = await activate_audit_atomization_skill(version.id, admin=self.admin, db=self.db)
        self.assertTrue(result.is_trusted_archive)
        self.assertTrue(result.is_active)
        self.assertFalse(trusted.is_active)
        self.assertFalse(old_json.is_active)

    async def test_legacy_mixed_history_without_active_engine_stays_blocked(self):
        imported = await self.upload(trusted_bytes(), trusted=True)
        trusted = await self.db.get(AuditAtomizationSkillVersion, imported.id)
        trusted.runtime_status = "ready"
        old_json = AuditAtomizationSkillVersion(
            skill_id=trusted.skill_id, version_label="legacy-json", schema_version="1.0",
            instructions_text="Historical methodology", rules_json=[], content_sha256="e" * 64,
            source_filename="old.json", package_format="declarative_json", package_blob=None,
            package_manifest_json={}, runtime_status="ready", is_active=False,
        )
        self.db.add(old_json)
        await self.db.flush()
        for version in (trusted, old_json):
            with self.assertRaises(HTTPException) as caught:
                await activate_audit_atomization_skill(version.id, admin=self.admin, db=self.db)
            self.assertEqual(caught.exception.status_code, 409)
        old_json.is_active = True
        await self.db.flush()
        with self.assertRaises(HTTPException) as caught:
            await activate_audit_atomization_skill(trusted.id, admin=self.admin, db=self.db)
        self.assertEqual(caught.exception.status_code, 409)
        result = await activate_audit_atomization_skill(old_json.id, admin=self.admin, db=self.db)
        self.assertTrue(result.is_active)
        self.assertFalse(result.is_trusted_archive)

    async def test_database_format_and_blob_binding_checks(self):
        for format_, blob in (("declarative_archive", None), ("trusted_skill_archive", None), ("declarative_json", b"unexpected"), ("unknown", b"data")):
            with self.subTest(format=format_, blob=blob):
                with self.assertRaises(IntegrityError):
                    async with self.db.begin_nested():
                        self.db.add(AuditAtomizationSkillVersion(
                            skill_id=uuid4(), version_label="1.0", schema_version="1.0", instructions_text="test",
                            rules_json=[], content_sha256=uuid4().hex * 2, source_filename="test.skill",
                            package_format=format_, package_blob=blob, runtime_status="ready", is_active=False,
                        ))
                        await self.db.flush()

    async def test_concurrent_imports_serialize_before_duplicate_and_label_checks(self):
        locks = {}

        class AdvisorySession:
            """Simulate transaction-scoped PostgreSQL locks over the in-memory test DB."""

            def __init__(self, session):
                self.session = session
                self.held_lock = None

            def get_bind(self):
                return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

            def __getattr__(self, name):
                return getattr(self.session, name)

            async def execute(self, statement, params=None):
                if str(statement) == "SELECT pg_advisory_xact_lock(:lock_id)":
                    lock = locks.setdefault(params["lock_id"], asyncio.Lock())
                    await lock.acquire()
                    self.held_lock = lock
                    return None
                return await self.session.execute(statement, params)

        async def request(data):
            async with AsyncSession(self.engine, expire_on_commit=False) as session:
                db = AdvisorySession(session)
                try:
                    result = await import_audit_atomization_skill(
                        file=UploadFile(filename="method.skill", file=BytesIO(data)), admin=self.admin, db=db,
                    )
                    await session.commit()
                    return result
                except Exception:
                    await session.rollback()
                    raise
                finally:
                    if db.held_lock is not None:
                        db.held_lock.release()

        for index, (second_version, extra) in enumerate((("1.0", ""), ("2.0", ""), ("1.0", "Changed."))):
            slug = f"concurrent-{index}"
            first = archive_bytes([("SKILL.md", skill_text(slug, version="1.0"))])
            second = archive_bytes([("SKILL.md", skill_text(slug, version=second_version) + extra)])
            with patch.object(service, "_trusted_hashes", return_value=set()):
                results = await asyncio.gather(request(first), request(second), return_exceptions=True)
            if extra:
                failures = [result for result in results if isinstance(result, Exception)]
                self.assertEqual(len(failures), 1)
                self.assertIsInstance(failures[0], HTTPException)
                self.assertEqual(failures[0].status_code, 409)
            else:
                self.assertFalse(any(isinstance(result, Exception) for result in results), results)
                self.assertEqual(results[0].skill_id, results[1].skill_id)
                self.assertEqual(results[0].id == results[1].id, second_version == "1.0")
            active = await self.db.scalar(
                select(func.count()).select_from(AuditAtomizationSkillVersion)
                .join(AuditAtomizationSkill)
                .where(AuditAtomizationSkill.slug == slug, AuditAtomizationSkillVersion.is_active.is_(True))
            )
            self.assertEqual(active, 1)


class SkillImportLockTests(unittest.IsolatedAsyncioTestCase):
    async def test_lock_uses_stable_signed_bigint_per_slug_and_transaction_scope(self):
        db = SimpleNamespace(
            get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
            execute=AsyncMock(),
        )
        await _lock_skill_import(db, "sample-audit")
        await _lock_skill_import(db, "sample-audit")
        await _lock_skill_import(db, "other-audit")
        calls = db.execute.await_args_list
        expected = int.from_bytes(sha256(b"dpms:audit-skill-import\0sample-audit").digest()[:8], "big", signed=True)
        self.assertEqual(str(calls[0].args[0]), "SELECT pg_advisory_xact_lock(:lock_id)")
        self.assertEqual(calls[0].args[1], {"lock_id": expected})
        self.assertEqual(calls[0].args[1], calls[1].args[1])
        self.assertNotEqual(calls[0].args[1], calls[2].args[1])
        self.assertTrue(-(2**63) <= expected < 2**63)

    async def test_sqlite_and_minimal_session_doubles_do_not_gain_sql_calls(self):
        for db in (
            SimpleNamespace(execute=AsyncMock()),
            SimpleNamespace(get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="sqlite")), execute=AsyncMock()),
        ):
            await _lock_skill_import(db, "sample-audit")
            db.execute.assert_not_awaited()

    async def test_duplicate_lookup_occurs_only_after_lock_completes(self):
        order = []

        async def execute(statement, params):
            self.assertEqual(str(statement), "SELECT pg_advisory_xact_lock(:lock_id)")
            order.append("lock")

        existing = SimpleNamespace(skill_id=uuid4())

        async def scalar(statement):
            self.assertEqual(order, ["lock"])
            self.assertIn("content_sha256", str(statement))
            order.append("lookup")
            return existing

        db = SimpleNamespace(
            get_bind=lambda: SimpleNamespace(dialect=SimpleNamespace(name="postgresql")),
            execute=AsyncMock(side_effect=execute), scalar=AsyncMock(side_effect=scalar),
            get=AsyncMock(return_value=SimpleNamespace()), add=MagicMock(),
        )
        marker = object()
        with patch("app.api.routes.ai_provider._skill_read", return_value=marker):
            result = await import_audit_atomization_skill(
                file=UploadFile(filename="method.skill", file=BytesIO(archive_bytes())),
                admin=SimpleNamespace(id=uuid4()), db=db,
            )
        self.assertIs(result, marker)
        self.assertEqual(order, ["lock", "lookup"])
        db.add.assert_not_called()


class DeclarativeSkillMigrationTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).parents[1] / "alembic/versions/084_audit_declarative_skills.py"
        spec = spec_from_file_location("declarative_skill_migration", path)
        self.migration = module_from_spec(spec)
        spec.loader.exec_module(self.migration)

    def test_upgrade_matches_model_constraints_and_installs_nothing(self):
        self.assertEqual(self.migration.down_revision, "083_audit_legacy_transfer")
        with patch.object(self.migration, "op") as op:
            self.migration.upgrade()
        constraints = {item.name: str(item.sqltext) for item in AuditAtomizationSkillVersion.__table__.constraints if hasattr(item, "sqltext")}
        self.assertEqual(op.create_check_constraint.call_count, 2)
        for call in op.create_check_constraint.call_args_list:
            name, table, expression = call.args
            self.assertEqual(table, "audit_atomization_skill_versions")
            self.assertEqual(expression, constraints[name])
        op.get_bind.assert_not_called()
        op.execute.assert_not_called()

    def test_downgrade_locks_before_guard_and_refuses_archive_data_loss(self):
        with patch.object(self.migration, "op") as op:
            bind = op.get_bind.return_value
            bind.execute.return_value.scalar_one.return_value = True
            with self.assertRaisesRegex(RuntimeError, "Preserve immutable"):
                self.migration.downgrade()
            self.assertIn("LOCK TABLE", str(bind.execute.call_args_list[0].args[0]))
            self.assertIn("declarative_archive", str(bind.execute.call_args_list[1].args[0]))
            op.drop_constraint.assert_not_called()
        with patch.object(self.migration, "op") as op:
            op.get_bind.return_value.execute.return_value.scalar_one.return_value = False
            self.migration.downgrade()
            self.assertEqual(op.create_check_constraint.call_count, 2)
            for call in op.create_check_constraint.call_args_list:
                self.assertNotIn("declarative_archive", call.args[2])


if __name__ == "__main__":
    unittest.main()
