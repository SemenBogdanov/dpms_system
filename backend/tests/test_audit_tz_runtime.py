"""Security and adapter tests for the isolated canonical audit-tz runtime."""

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from app.config import settings
from app.models.ai_provider import AuditAtomizationSkill, AuditAtomizationSkillVersion
from app.models.audit import AuditAIAtomizationAttempt, AuditCase, AuditDocument
from app.models.audit_runtime import AuditTZRun, AuditTZRuntimeJob
from app.schemas.audit_runtime import AuditTZRunStart
from app.services.audit_runtime_crypto import (
    build_run_key,
    decrypt_identifiers,
    encrypt_identifiers,
    identifier_digest,
)
from app.services.audit_skill_package import extract_trusted_skill_archive
from app.services.audit_tz_runtime import (
    AuditTZRuntimeError,
    _read_json_file,
    _recover_stale_jobs,
    _run_cli,
    _safe_identity_summary,
    document_binding_digest,
    document_binding_id,
    process_preflight,
    reconcile_orphan_audit_tz_run_files,
)


def make_runtime_archive() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "audit-tz/SKILL.md",
            """---
name: audit-tz
description: "Canonical audit runtime test package"
---

# Audit runtime
""",
        )
        archive.writestr(
            "audit-tz/scripts/audit_tz_lib/__init__.py",
            'SKILL_VERSION = "0.3.0"\nSCHEMA_VERSION = "1.0"\n',
        )
        archive.writestr(
            "audit-tz/scripts/audit_tz.py",
            """import json

def main(argv=None):
    print(json.dumps({"status": "PASS", "passed": True, "args_count": len(argv or [])}))
    return 0
""",
        )
    return buffer.getvalue()


class AuditTZRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def test_start_request_needs_only_document_and_skill(self):
        request = AuditTZRunStart(
            request_id=uuid4(),
            document_id=uuid4(),
            skill_version_id=uuid4(),
        )

        self.assertNotIn("contract_identifiers", request.model_dump())

    def test_document_binding_is_deterministic_and_not_a_contract_number(self):
        source_hash = "ab12" * 16

        binding_id = document_binding_id(source_hash)
        binding_digest = document_binding_digest(source_hash)

        self.assertEqual(
            binding_id,
            "DPMS-DOC-1-AB12AB12AB12AB12AB12AB12AB12AB12-AB12AB12AB12AB12AB12AB12AB12AB12",
        )
        self.assertEqual(len(binding_digest), 64)
        self.assertEqual(binding_digest, document_binding_digest(source_hash.upper()))

    def test_document_binding_rejects_invalid_hash(self):
        with self.assertRaises(AuditTZRuntimeError) as raised:
            document_binding_id("not-a-sha256")

        self.assertEqual(raised.exception.code, "document_hash_invalid")

    async def test_worker_reconciles_only_orphan_run_directories(self):
        existing_run_id = uuid4()
        orphan_run_id = uuid4()

        class FakeDB:
            async def scalars(self, _query):
                return [existing_run_id]

        with TemporaryDirectory() as temp_dir, patch.object(settings, "AUDIT_TZ_RUNTIME_DIR", temp_dir):
            root = Path(temp_dir)
            for scope in ("inputs", "runs"):
                (root / scope / str(existing_run_id)).mkdir(parents=True)
                orphan = root / scope / str(orphan_run_id)
                orphan.mkdir(parents=True)
                (orphan / "artifact.json").write_text("{}", encoding="utf-8")

            removed = await reconcile_orphan_audit_tz_run_files(FakeDB())

            self.assertEqual(removed, 2)
            self.assertTrue((root / "inputs" / str(existing_run_id)).is_dir())
            self.assertTrue((root / "runs" / str(existing_run_id)).is_dir())
            self.assertFalse((root / "inputs" / str(orphan_run_id)).exists())
            self.assertFalse((root / "runs" / str(orphan_run_id)).exists())

    def test_runtime_identifiers_are_encrypted_and_keyed(self):
        identifiers = ["TEST-2026-001", "TEST / 2026 / 001"]
        with patch.object(settings, "INTEGRATION_SECRET_KEY", "x" * 48):
            ciphertext = encrypt_identifiers(identifiers)
            digest = identifier_digest(identifiers)
            run_key = build_run_key(
                case_id="case-id",
                document_sha256="a" * 64,
                skill_sha256="b" * 64,
                identifiers_digest=digest,
                mode="audit-only",
            )

        self.assertNotIn(identifiers[0], ciphertext)
        self.assertEqual(decrypt_with_key(ciphertext), identifiers)
        self.assertEqual(len(digest), 64)
        self.assertEqual(len(run_key), 64)

    def test_identity_summary_never_exposes_contract_or_path(self):
        report = {
            "decision": "PASS",
            "target_contract_id": "SECRET-2026-001",
            "accepted_contract_ids": ["SECRET-2026-001"],
            "source": {
                "kind": "docx",
                "path": "/private/SECRET-2026-001.docx",
                "unit_count": 7,
                "content_contract_ids": ["SECRET-2026-001"],
                "external_relationship_count": 0,
            },
            "warnings": [],
        }
        summary = _safe_identity_summary(report, {"source_unit_count": 7})
        serialized = json.dumps(summary, ensure_ascii=False)

        self.assertEqual(summary["decision"], "PASS")
        self.assertEqual(summary["source_unit_count"], 7)
        self.assertNotIn("SECRET", serialized)
        self.assertNotIn("/private", serialized)

    def test_archive_is_revalidated_and_materialized_read_only(self):
        data = make_runtime_archive()
        digest = sha256(data).hexdigest()
        with TemporaryDirectory() as temp_dir, patch.object(
            settings,
            "AUDIT_TRUSTED_SKILL_SHA256",
            digest,
        ):
            root = extract_trusted_skill_archive(
                data,
                Path(temp_dir) / digest,
                expected_sha256=digest,
            )
            self.assertTrue((root / "scripts" / "audit_tz.py").is_file())
            self.assertEqual(
                extract_trusted_skill_archive(
                    data,
                    Path(temp_dir) / digest,
                    expected_sha256=digest,
                ),
                root,
            )

    async def test_child_adapter_executes_with_isolated_json_request(self):
        with TemporaryDirectory() as temp_dir, patch.object(settings, "AUDIT_TZ_RUNTIME_DIR", temp_dir):
            skill_root = Path(temp_dir) / "skills" / "test" / "audit-tz"
            scripts = skill_root / "scripts"
            scripts.mkdir(parents=True)
            (scripts / "audit_tz.py").write_text(
                "import json\n"
                "def main(argv=None):\n"
                "    print(json.dumps({'status':'PASS','passed':True,'args_count':len(argv or [])}))\n"
                "    return 0\n",
                encoding="utf-8",
            )
            result = await _run_cli(skill_root, "selftest", [], allowed_exit_codes={0})

        self.assertEqual(result.exit_code, 0)
        self.assertTrue(result.payload["passed"])
        self.assertEqual(result.payload["args_count"], 1)

    async def test_preflight_adapter_cannot_spawn_child_processes(self):
        with TemporaryDirectory() as temp_dir, patch.object(settings, "AUDIT_TZ_RUNTIME_DIR", temp_dir):
            skill_root = Path(temp_dir) / "skills" / "test" / "audit-tz"
            scripts = skill_root / "scripts"
            scripts.mkdir(parents=True)
            (scripts / "audit_tz.py").write_text(
                "import json\n"
                "import subprocess\n"
                "import sys\n"
                "def main(argv=None):\n"
                "    subprocess.run([sys.executable, '-c', 'print(1)'], check=True)\n"
                "    print(json.dumps({'status':'PASS'}))\n"
                "    return 0\n",
                encoding="utf-8",
            )
            with self.assertRaises(AuditTZRuntimeError) as raised:
                await _run_cli(skill_root, "preflight", [], allowed_exit_codes={0})

        self.assertEqual(raised.exception.code, "runtime_protocol_error")

    async def test_preflight_runtime_error_finishes_job_without_secondary_exception(self):
        run_id = uuid4()
        job = SimpleNamespace(id=uuid4(), run_id=run_id, kind="preflight")
        run = SimpleNamespace(
            id=run_id,
            document_id=uuid4(),
            skill_version_id=uuid4(),
            case_id=uuid4(),
            requested_by_id=uuid4(),
            source_sha256="a" * 64,
            skill_sha256="b" * 64,
            source_binding="document_hash",
            status="running",
            current_phase="preflight",
            identifier_ciphertext=None,
            identifiers_purged_at=None,
            error_code=None,
            finished_at=None,
        )
        document = SimpleNamespace(id=run.document_id, sha256=run.source_sha256, case_id=run.case_id)
        version = SimpleNamespace(
            id=run.skill_version_id,
            skill_id=uuid4(),
            content_sha256=run.skill_sha256,
            runtime_status="ready",
            is_active=True,
        )
        skill = SimpleNamespace(id=version.skill_id, is_enabled=True)
        audit_case = SimpleNamespace(id=run.case_id)
        added: list[object] = []

        class FakeSession:
            async def get(self, model, key):
                return {
                    AuditTZRuntimeJob: job,
                    AuditTZRun: run,
                    AuditDocument: document,
                    AuditAtomizationSkillVersion: version,
                    AuditAtomizationSkill: skill,
                    AuditCase: audit_case,
                }.get(model)

            def add(self, value):
                added.append(value)

            async def commit(self):
                return None

        @asynccontextmanager
        async def db_factory():
            yield FakeSession()

        with patch(
            "app.services.audit_tz_runtime._skill_directory",
            side_effect=AuditTZRuntimeError("synthetic_preflight_failure", "test"),
        ), patch(
            "app.services.audit_tz_runtime._complete_job",
            new=AsyncMock(return_value=job),
        ):
            await process_preflight(job.id, "lease", db_factory)

        self.assertEqual(run.status, "failed")
        self.assertEqual(run.error_code, "synthetic_preflight_failure")
        self.assertEqual(len(added), 1)

    async def test_exhausted_atomization_lease_marks_attempt_retryable(self):
        now = datetime.now(timezone.utc)
        run_id = uuid4()
        job = SimpleNamespace(
            id=uuid4(),
            kind="atomization",
            run_id=run_id,
            skill_version_id=uuid4(),
            status="running",
            attempt_count=3,
            max_attempts=3,
            lease_token="lease",
            lease_expires_at=now - timedelta(seconds=1),
            worker_id="worker",
            error_code=None,
            finished_at=None,
        )
        run = SimpleNamespace(
            id=run_id,
            status="atomizing",
            current_phase="atomizing",
            error_code=None,
            finished_at=None,
            identifier_ciphertext=None,
            identifiers_purged_at=None,
        )
        attempt = SimpleNamespace(status="running", error_code=None, config_version=1)

        class ScalarRows:
            def all(self):
                return [job]

        class FakeSession:
            async def scalars(self, _query):
                return ScalarRows()

            async def get(self, model, key):
                return run if model is AuditTZRun and key == run_id else None

            async def scalar(self, _query):
                return attempt

        await _recover_stale_jobs(FakeSession(), now)

        self.assertEqual(job.status, "failed")
        self.assertEqual(run.current_phase, "atomization_failed")
        self.assertEqual(attempt.status, "failed")
        self.assertEqual(attempt.error_code, "worker_lease_expired")

    def test_runtime_artifact_symlink_is_rejected(self):
        with TemporaryDirectory() as temp_dir, patch.object(settings, "AUDIT_TZ_RUNTIME_DIR", temp_dir):
            root = Path(temp_dir)
            target = root / "target.json"
            target.write_text('{"decision":"PASS"}', encoding="utf-8")
            link = root / "identity_report.json"
            link.symlink_to(target)

            with self.assertRaises(AuditTZRuntimeError) as raised:
                _read_json_file(link)

        self.assertEqual(raised.exception.code, "runtime_path_invalid")


def decrypt_with_key(ciphertext: str) -> list[str]:
    with patch.object(settings, "INTEGRATION_SECRET_KEY", "x" * 48):
        return decrypt_identifiers(ciphertext)


if __name__ == "__main__":
    unittest.main()
