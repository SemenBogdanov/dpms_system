"""Route-level regressions for repeated canonical atomization."""

from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

from app.api.routes import audit_runtime
from app.schemas.audit_runtime import AuditTZAtomizationStart


class AuditRuntimeRouteTests(unittest.IsolatedAsyncioTestCase):
    async def test_running_atomization_requests_cooperative_pause(self):
        case_id = uuid4()
        run_id = uuid4()
        user = SimpleNamespace(id=uuid4())
        audit_case = SimpleNamespace(id=case_id)
        run = SimpleNamespace(
            id=run_id,
            completed_batch_count=3,
            total_batch_count=8,
            status="atomizing",
            current_phase="atomizing",
        )
        job = SimpleNamespace(
            status="running",
            pause_requested_at=None,
            pause_requested_by_id=None,
            paused_at=None,
        )
        db = SimpleNamespace(add=MagicMock(), flush=AsyncMock())
        serialized = SimpleNamespace(id=run_id, pause_requested=True)

        with (
            patch.object(audit_runtime, "_get_case_or_404", AsyncMock(return_value=audit_case)),
            patch.object(audit_runtime, "_ensure_case_atom_editor", AsyncMock()),
            patch.object(
                audit_runtime,
                "_locked_atomization_run_and_job",
                AsyncMock(return_value=(run, job)),
            ),
            patch.object(audit_runtime, "_serialize_run", AsyncMock(return_value=serialized)),
        ):
            result = await audit_runtime.pause_canonical_atomization(
                case_id=case_id,
                run_id=run_id,
                user=user,
                db=db,
            )

        self.assertIs(result, serialized)
        self.assertEqual(job.status, "running")
        self.assertIsNotNone(job.pause_requested_at)
        self.assertEqual(job.pause_requested_by_id, user.id)
        self.assertEqual(run.current_phase, "atomization_pause_requested")

    async def test_resume_keeps_saved_progress_and_requeues_paused_job(self):
        case_id = uuid4()
        run_id = uuid4()
        user = SimpleNamespace(id=uuid4())
        audit_case = SimpleNamespace(id=case_id)
        run = SimpleNamespace(
            id=run_id,
            completed_batch_count=5,
            total_batch_count=9,
            status="paused",
            current_phase="atomization_paused",
            error_code=None,
            finished_at=None,
        )
        job = SimpleNamespace(
            status="paused",
            pause_requested_at=None,
            pause_requested_by_id=user.id,
            paused_at=object(),
            available_at=None,
            lease_token=None,
            lease_expires_at=None,
            worker_id=None,
            finished_at=None,
        )
        db = SimpleNamespace(add=MagicMock(), flush=AsyncMock())
        serialized = SimpleNamespace(id=run_id, status="atomization_queued")

        with (
            patch.object(audit_runtime, "_get_case_or_404", AsyncMock(return_value=audit_case)),
            patch.object(audit_runtime, "_ensure_case_atom_editor", AsyncMock()),
            patch.object(
                audit_runtime,
                "_locked_atomization_run_and_job",
                AsyncMock(return_value=(run, job)),
            ),
            patch.object(audit_runtime, "_serialize_run", AsyncMock(return_value=serialized)),
        ):
            result = await audit_runtime.resume_canonical_atomization(
                case_id=case_id,
                run_id=run_id,
                user=user,
                db=db,
            )

        self.assertIs(result, serialized)
        self.assertEqual(job.status, "queued")
        self.assertEqual(run.status, "atomization_queued")
        self.assertEqual(run.completed_batch_count, 5)
        self.assertEqual(run.total_batch_count, 9)
        self.assertIsNone(job.pause_requested_by_id)

    async def test_prioritize_paused_atomization_makes_it_next(self):
        case_id = uuid4()
        run_id = uuid4()
        user = SimpleNamespace(id=uuid4())
        run = SimpleNamespace(
            id=run_id,
            completed_batch_count=2,
            total_batch_count=7,
            status="paused",
            current_phase="atomization_paused",
        )
        job = SimpleNamespace(
            id=uuid4(),
            status="paused",
            priority=0,
            available_at=None,
            paused_at=object(),
            pause_requested_at=None,
            pause_requested_by_id=user.id,
        )
        db = SimpleNamespace(execute=AsyncMock(), add=MagicMock(), flush=AsyncMock())
        serialized = SimpleNamespace(id=run_id, priority=100)

        with (
            patch.object(audit_runtime, "_get_case_or_404", AsyncMock()),
            patch.object(
                audit_runtime,
                "_locked_atomization_run_and_job",
                AsyncMock(return_value=(run, job)),
            ),
            patch.object(audit_runtime, "_serialize_run", AsyncMock(return_value=serialized)),
        ):
            result = await audit_runtime.prioritize_canonical_atomization(
                case_id=case_id,
                run_id=run_id,
                user=user,
                db=db,
            )

        self.assertIs(result, serialized)
        self.assertEqual(job.priority, 100)
        self.assertEqual(job.status, "queued")
        self.assertEqual(run.status, "atomization_queued")
        db.execute.assert_awaited_once()

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

    async def test_failed_same_model_resumes_saved_batches(self):
        case_id = uuid4()
        run_id = uuid4()
        provider_id = uuid4()
        user = SimpleNamespace(id=uuid4())
        saved_batches = [{"batch_index": index} for index in range(1, 9)]
        audit_case = SimpleNamespace(id=case_id, status="atomization")
        run = SimpleNamespace(
            id=run_id,
            case_id=case_id,
            status="failed",
            current_phase="atomization_failed",
            source_unit_count=360,
            source_sha256="a" * 64,
            skill_sha256="b" * 64,
            skill_version_id=uuid4(),
            document_id=uuid4(),
            atom_count=0,
            completed_batch_count=8,
            total_batch_count=12,
            external_ai_called=True,
            safe_summary_json={"atomization_batches_completed": 8},
            error_code="rate_limited",
            finished_at=None,
        )
        attempt = SimpleNamespace(
            id=uuid4(),
            status="failed",
            provider_config_id=provider_id,
            provider_config_version=3,
            model_name="same-model",
            batch_results_json=saved_batches.copy(),
            config_version=5,
        )
        job = SimpleNamespace(
            status="failed",
            attempt_count=1,
            max_attempts=3,
            available_at=None,
            lease_token=None,
            lease_expires_at=None,
            worker_id=None,
            error_code="rate_limited",
            finished_at=None,
        )
        provider = SimpleNamespace(
            id=provider_id,
            config_version=3,
            model_name="same-model",
            display_name="Same provider",
        )
        db = SimpleNamespace(
            scalar=AsyncMock(side_effect=[run, None, attempt, job]),
            execute=AsyncMock(),
            flush=AsyncMock(),
            add=MagicMock(),
        )
        body = AuditTZAtomizationStart(
            request_id=uuid4(),
            provider_id=provider_id,
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
        self.assertEqual(attempt.batch_results_json, saved_batches)
        self.assertEqual(run.completed_batch_count, 8)
        self.assertEqual(run.total_batch_count, 12)
        self.assertTrue(run.external_ai_called)
        self.assertEqual(job.status, "queued")
        self.assertEqual(job.attempt_count, 0)
        self.assertEqual(job.max_attempts, audit_runtime.ATOMIZATION_MAX_JOB_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
