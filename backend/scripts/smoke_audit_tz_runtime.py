#!/usr/bin/env python3
"""Local end-to-end smoke for the isolated canonical audit-tz preflight."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from unittest.mock import patch
from uuid import uuid4
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import HTTPException
from sqlalchemy import delete, select, update

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.api.routes.audit import commit_ai_atomization_attempt
from app.api.routes.audit_runtime import (
    preview_canonical_atomization,
    start_canonical_atomization,
    start_canonical_preflight,
)
from app.config import settings
from app.database import AsyncSessionLocal
from app.models.ai_provider import AuditAtomizationSkill, AuditAtomizationSkillVersion
from app.models.audit import (
    AuditAIAtomDraft,
    AuditAIAtomizationAttempt,
    AuditAtom,
    AuditCase,
    AuditDocument,
    AuditEvent,
)
from app.models.audit_runtime import AuditTZArtifact, AuditTZRun, AuditTZRuntimeJob
from app.models.user import User, UserRole
from app.schemas.audit_ai import AuditAIAtomDraftCommitItem, AuditAIAtomizationCommit
from app.schemas.audit_runtime import AuditTZAtomizationStart, AuditTZRunStart
from app.services.audit_documents import prepare_audit_document_bytes, persist_audit_document_file
from app.services.audit_tz_atomization import validate_batch_result
from app.services.audit_tz_runtime import process_atomization, process_preflight


def _require_local_compose() -> None:
    if os.getenv("AUDIT_TZ_SMOKE_ALLOW_COMPOSE_DB") != "1":
        raise RuntimeError("Set AUDIT_TZ_SMOKE_ALLOW_COMPOSE_DB=1 for the isolated local Compose database")
    database_url = settings.DATABASE_URL.lower()
    if "@db:5432/dpms" not in database_url or "prod" in database_url:
        raise RuntimeError("Canonical runtime smoke refuses a non-local database")


def _docx_fixture() -> bytes:
    paragraphs = [
        "Техническое задание на развитие цифрового продукта.",
        "Разработать экран Реестр заявок цифрового продукта.",
        "Система должна отображать номер, дату создания и статус каждой заявки.",
    ] + [f"Контекст реестра заявок, фрагмент {index}." for index in range(4, 36)]
    body = "".join(
        "<w:p><w:r><w:t>" + text + "</w:t></w:r></w:p>"
        for text in paragraphs
    )
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    relationships = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    document = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>{body}</w:body></w:document>"""
    output = BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/document.xml", document)
    return output.getvalue()


async def run() -> None:
    _require_local_compose()
    source_path: Path | None = None
    case_id = None
    previous_active_ids: list = []
    skill_id = None
    try:
        async with AsyncSessionLocal() as db:
            admin = await db.scalar(
                select(User)
                .where(User.role == UserRole.admin, User.is_active.is_(True))
                .order_by(User.created_at.asc())
                .limit(1)
            )
            if admin is None:
                raise AssertionError("Local database has no active administrator")
            row = (
                await db.execute(
                    select(AuditAtomizationSkill, AuditAtomizationSkillVersion)
                    .join(
                        AuditAtomizationSkillVersion,
                        AuditAtomizationSkillVersion.skill_id == AuditAtomizationSkill.id,
                    )
                    .where(
                        AuditAtomizationSkillVersion.package_format == "trusted_skill_archive",
                        AuditAtomizationSkillVersion.runtime_status == "ready",
                    )
                    .order_by(AuditAtomizationSkillVersion.created_at.desc())
                    .limit(1)
                )
            ).one_or_none()
            if row is None:
                raise AssertionError("No runtime-ready trusted audit-tz version is installed")
            skill, version = row
            skill_id = skill.id
            previous_active_ids = list(
                await db.scalars(
                    select(AuditAtomizationSkillVersion.id).where(
                        AuditAtomizationSkillVersion.skill_id == skill.id,
                        AuditAtomizationSkillVersion.is_active.is_(True),
                    )
                )
            )
            await db.execute(
                update(AuditAtomizationSkillVersion)
                .where(AuditAtomizationSkillVersion.skill_id == skill.id)
                .values(is_active=False)
            )
            version.is_active = True
            skill.is_enabled = True

            audit_case = AuditCase(
                created_by_id=admin.id,
                responsible_user_id=admin.id,
                title="SMOKE: canonical audit-tz preflight",
                digital_product="SMOKE",
                status="atomization",
                workflow_stage="atomization",
            )
            db.add(audit_case)
            await db.flush()
            case_id = audit_case.id

            prepared = prepare_audit_document_bytes("smoke-technical-spec.docx", _docx_fixture())
            stored_filename, source_path = persist_audit_document_file(audit_case.id, prepared)
            document = AuditDocument(
                case_id=audit_case.id,
                uploaded_by_id=admin.id,
                kind="technical_spec",
                display_name="SMOKE: неизменяемое ТЗ",
                original_filename=prepared.original_filename,
                stored_filename=stored_filename,
                content_type=prepared.content_type,
                size_bytes=prepared.size_bytes,
                sha256=prepared.sha256,
            )
            db.add(document)
            await db.flush()
            response = await start_canonical_preflight(
                audit_case.id,
                AuditTZRunStart(
                    request_id=uuid4(),
                    document_id=document.id,
                    skill_version_id=version.id,
                ),
                admin,
                db,
            )
            run_id = response.id
            await db.commit()

        async with AsyncSessionLocal() as db:
            runtime_job = await db.scalar(
                select(AuditTZRuntimeJob).where(
                    AuditTZRuntimeJob.run_id == run_id,
                    AuditTZRuntimeJob.kind == "preflight",
                )
            )
            preflight_lease_token = str(uuid4())
            runtime_job.status = "running"
            runtime_job.attempt_count = 1
            runtime_job.lease_token = preflight_lease_token
            runtime_job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
            runtime_job.worker_id = "canonical-preflight-smoke"
            runtime_job.started_at = datetime.now(timezone.utc)
            await db.commit()
            preflight_job_id = runtime_job.id

        await process_preflight(
            preflight_job_id,
            preflight_lease_token,
            AsyncSessionLocal,
        )
        async with AsyncSessionLocal() as db:
            completed = await db.get(AuditTZRun, run_id)
        assert completed.status == "preflight_pass", completed.error_code
        assert completed.source_unit_count > 0
        assert completed.identifier_ciphertext is None
        assert completed.identifiers_purged_at is not None
        assert completed.source_binding == "document_hash"
        assert completed.safe_summary_json.get("source_binding") == "document_hash"

        async with AsyncSessionLocal() as db:
            artifact_count = len(
                list(
                    await db.scalars(
                        select(AuditTZArtifact.id).where(AuditTZArtifact.run_id == run_id)
                    )
                )
            )
            event_types = set(
                await db.scalars(
                    select(AuditEvent.event_type).where(AuditEvent.case_id == case_id)
                )
            )
        assert artifact_count == 3
        assert {"audit_tz_preflight_queued", "audit_tz_preflight_pass"}.issubset(event_types)

        async with AsyncSessionLocal() as db:
            preview = await preview_canonical_atomization(
                case_id,
                run_id,
                admin,
                db,
            )
            try:
                await start_canonical_atomization(
                    case_id,
                    run_id,
                    AuditTZAtomizationStart(
                        request_id=uuid4(),
                        consent_token="x" * 40,
                        data_transfer_confirmed=True,
                    ),
                    admin,
                    db,
                )
            except HTTPException as error:
                assert error.status_code == 409
            else:
                raise AssertionError("Atomization started without a valid provider-bound consent token")
            assert not list(
                await db.scalars(
                    select(AuditAIAtomizationAttempt.id).where(
                        AuditAIAtomizationAttempt.canonical_run_id == run_id
                    )
                )
            )
            await start_canonical_atomization(
                case_id,
                run_id,
                AuditTZAtomizationStart(
                    request_id=uuid4(),
                    consent_token=preview.consent_token,
                    data_transfer_confirmed=True,
                ),
                admin,
                db,
            )
            await db.commit()

        async with AsyncSessionLocal() as db:
            lease_token = str(uuid4())
            run_row = await db.get(AuditTZRun, run_id)
            attempt = await db.scalar(
                select(AuditAIAtomizationAttempt).where(
                    AuditAIAtomizationAttempt.canonical_run_id == run_id
                )
            )
            runtime_job = await db.scalar(
                select(AuditTZRuntimeJob).where(
                    AuditTZRuntimeJob.run_id == run_id,
                    AuditTZRuntimeJob.kind == "atomization",
                )
            )
            if attempt is None or runtime_job is None:
                raise AssertionError("Atomization endpoint did not create attempt and job")
            run_row.status = "atomizing"
            run_row.current_phase = "atomizing"
            runtime_job.status = "running"
            runtime_job.attempt_count = 1
            runtime_job.lease_token = lease_token
            runtime_job.lease_expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
            runtime_job.worker_id = "canonical-atomization-smoke"
            runtime_job.started_at = datetime.now(timezone.utc)
            await db.commit()
            atomization_job_id = runtime_job.id
            attempt_id = attempt.id

        async def fake_model_result(_provider, batch, _total_batches):
            anchor_id = str(batch.units[0]["source_unit_id"])
            payload = {
                "atoms": [
                    {
                        "local_id": "A1",
                        "title": "Реестр заявок цифрового продукта",
                        "object_type": "Экран",
                        "work_type": "Разработка",
                        "notes": "Синтетический smoke-черновик",
                        "source_unit_ids": [anchor_id],
                        "anchor_source_unit_id": anchor_id,
                        "confidence": 0.9,
                    }
                ],
                "coverage": [
                    {
                        "source_unit_id": str(unit["source_unit_id"]),
                        "disposition": "ATOMIZED" if str(unit["source_unit_id"]) == anchor_id else "NON_REQUIREMENT",
                        "reason": "Опорное требование" if str(unit["source_unit_id"]) == anchor_id else "Контекст или описание",
                    }
                    for unit in batch.units
                ],
                "warnings": [],
            }
            return validate_batch_result(payload, batch)

        with patch(
            "app.services.audit_tz_runtime.generate_batch_result",
            new=fake_model_result,
        ):
            await process_atomization(
                atomization_job_id,
                lease_token,
                AsyncSessionLocal,
            )

        async with AsyncSessionLocal() as db:
            attempt = await db.get(AuditAIAtomizationAttempt, attempt_id)
            atomization_run = await db.get(AuditTZRun, run_id)
            drafts = list(
                await db.scalars(
                    select(AuditAIAtomDraft)
                    .where(AuditAIAtomDraft.attempt_id == attempt_id)
                    .order_by(AuditAIAtomDraft.sort_order.asc())
                )
            )
            assert attempt.status == "draft_ready", (
                f"attempt={attempt.status}:{attempt.error_code}; "
                f"run={atomization_run.status}:{atomization_run.error_code}"
            )
            assert drafts
            assert not list(await db.scalars(select(AuditAtom.id).where(AuditAtom.case_id == case_id)))
            commit_body = AuditAIAtomizationCommit(
                request_id=uuid4(),
                expected_config_version=attempt.config_version,
                drafts=[
                    AuditAIAtomDraftCommitItem(
                        id=draft.id,
                        included=True,
                        title=draft.title,
                        digital_product=draft.digital_product,
                        work_type=draft.work_type,
                        object_type=draft.object_type,
                        notes=draft.notes,
                    )
                    for draft in drafts
                ],
            )
            committed = await commit_ai_atomization_attempt(
                case_id,
                attempt_id,
                commit_body,
                admin,
                db,
            )
            draft_count = len(drafts)

        async with AsyncSessionLocal() as db:
            committed_run = await db.get(AuditTZRun, run_id)
            registry_count = len(
                list(await db.scalars(select(AuditAtom.id).where(AuditAtom.case_id == case_id)))
            )
            assert committed_run.status == "committed"
            assert registry_count == draft_count == committed.atoms_created
            assert draft_count == 1, "Cross-batch duplicate candidates were not consolidated"
        print(
            json.dumps(
                {
                    "status": "PASS",
                    "runtime_status": committed_run.status,
                    "source_unit_count": completed.source_unit_count,
                    "draft_atom_count": draft_count,
                    "registry_atom_count": registry_count,
                    "artifact_count": artifact_count,
                    "document_hash_bound": True,
                    "external_ai_called": True,
                    "external_model_was_mocked": True,
                },
                ensure_ascii=False,
            )
        )
    finally:
        if case_id is not None:
            async with AsyncSessionLocal() as db:
                await db.execute(delete(AuditCase).where(AuditCase.id == case_id))
                if skill_id is not None:
                    await db.execute(
                        update(AuditAtomizationSkillVersion)
                        .where(AuditAtomizationSkillVersion.skill_id == skill_id)
                        .values(is_active=False)
                    )
                    if previous_active_ids:
                        await db.execute(
                            update(AuditAtomizationSkillVersion)
                            .where(AuditAtomizationSkillVersion.id.in_(previous_active_ids))
                            .values(is_active=True)
                        )
                await db.commit()
        if source_path is not None:
            source_path.unlink(missing_ok=True)


if __name__ == "__main__":
    asyncio.run(run())
