"""Route-level regressions for repeated canonical atomization."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.api.routes import audit_runtime
from app.schemas.audit_runtime import AuditTZAtomizationStart


class AuditRuntimeRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_committed_model_lane_can_be_reused_for_another_provider(self):
        case_id = uuid4()
        run_id = uuid4()
        previous_provider_id = uuid4()
        next_provider_id = uuid4()
        user = SimpleNamespace(id=uuid4())
        audit_case = SimpleNamespace(id=case_id, status="atomization")
        run = SimpleNamespace(
            id=run_id,
            case_id=case_id,
            status="committed",
            current_phase="general_registry_committed",
            source_unit_count=120,
            source_sha256="a" * 64,
            skill_sha256="b" * 64,
            skill_version_id=uuid4(),
            document_id=uuid4(),
            atom_count=40,
            completed_batch_count=4,
            total_batch_count=4,
            external_ai_called=True,
            error_code=None,
            finished_at=None,
        )
        attempt = SimpleNamespace(
            id=uuid4(),
            status="committed",
            provider_config_id=previous_provider_id,
            provider_config_version=1,
            model_name="first-model",
            config_version=3,
        )
        job = SimpleNamespace(
            status="done",
            attempt_count=1,
            available_at=None,
            lease_token=None,
            lease_expires_at=None,
            worker_id=None,
            error_code=None,
            finished_at=None,
        )
        provider = SimpleNamespace(
            id=next_provider_id,
            config_version=2,
            model_name="second-model",
            display_name="Second provider",
        )
        db = SimpleNamespace(
            scalar=AsyncMock(side_effect=[run, None, attempt, job, uuid4()]),
            execute=AsyncMock(),
            flush=AsyncMock(),
            add=MagicMock(),
        )
        body = AuditTZAtomizationStart(
            request_id=uuid4(),
            provider_id=next_provider_id,
            consent_token="x" * 40,
            data_transfer_confirmed=True,
        )
        serialized = SimpleNamespace(id=run_id, status="atomization_queued")

        with (
            patch.object(audit_runtime.settings, "AUDIT_TZ_WORKER_ENABLED", True),
            patch.object(audit_runtime.settings, "AUDIT_TZ_EXTERNAL_AI_ENABLED", True),
            patch.object(audit_runtime, "_get_case_or_404", AsyncMock(return_value=audit_case)),
            patch.object(audit_runtime, "_ensure_case_atom_editor", AsyncMock()),
            patch.object(audit_runtime, "get_ready_ai_provider", AsyncMock(return_value=provider)),
            patch.object(audit_runtime, "_verify_atomization_consent_token"),
            patch.object(audit_runtime, "_serialize_run", AsyncMock(return_value=serialized)),
        ):
            result = await audit_runtime.start_canonical_atomization(
                case_id=case_id,
                run_id=run_id,
                body=body,
                user=user,
                db=db,
            )

        self.assertIs(result, serialized)
        self.assertEqual(attempt.status, "running")
        self.assertEqual(attempt.provider_config_id, next_provider_id)
        self.assertEqual(attempt.model_name, "second-model")
        self.assertIsNone(attempt.commit_key_hash)
        self.assertEqual(run.status, "atomization_queued")
        self.assertEqual(job.status, "queued")
        db.execute.assert_awaited_once()
        self.assertEqual(db.scalar.await_count, 5)


if __name__ == "__main__":
    unittest.main()
