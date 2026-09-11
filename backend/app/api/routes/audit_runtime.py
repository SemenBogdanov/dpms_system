"""API boundary for the isolated canonical audit-tz preflight worker."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db
from app.api.routes.audit import (
    _ensure_case_atom_editor,
    _get_case_or_404,
    _serialize_ai_attempt,
    require_audit_manager,
    require_audit_workspace_member,
)
from app.config import settings
from app.core.security import create_access_token, decode_access_token
from app.models.ai_provider import AIProviderConfig, AuditAtomizationSkill, AuditAtomizationSkillVersion
from app.models.audit import (
    AuditAIAtomDraft,
    AuditAIAtomizationAttempt,
    AuditAIModelComparison,
    AuditAIModelComparisonDraft,
    AuditAIModelRegistry,
    AuditAIModelRegistryItem,
    AuditAtom,
    AuditDocument,
    AuditEvent,
)
from app.models.audit_runtime import AuditTZArtifact, AuditTZRun, AuditTZRuntimeJob
from app.models.user import User
from app.schemas.audit_ai import (
    AuditAIAtomizationAttemptRead,
    AuditAIModelComparisonCommit,
    AuditAIModelComparisonCommitRead,
    AuditAIModelComparisonDraftRead,
    AuditAIModelComparisonRead,
    AuditAIModelComparisonStart,
    AuditAIModelRegistryItemRead,
    AuditAIModelRegistryList,
    AuditAIModelRegistryPublishRead,
    AuditAIModelRegistryRead,
    AuditAIModelVariantRead,
    AuditAIProviderOptionList,
    AuditAIProviderOptionRead,
    AuditAISourceRefRead,
)
from app.schemas.audit_runtime import (
    AuditTZArtifactRead,
    AuditTZAtomizationPreviewRead,
    AuditTZAtomizationStart,
    AuditTZRunList,
    AuditTZRunRead,
    AuditTZRunStart,
)
from app.services.ai_provider import AIProviderError, ai_provider_ready, get_ready_ai_provider
from app.services.audit_import import generate_next_item_code
from app.services.audit_atom_provenance import (
    freeze_attempt_atom_origins,
    lookup_published_registry_items_batch,
    publish_model_registry_atoms,
)
from app.services.audit_model_comparison import build_model_comparison, evidence_text
from app.services.audit_runtime_crypto import (
    AuditRuntimeCryptoError,
    build_run_key,
)
from app.services.audit_tz_runtime import (
    ATOMIZATION_MAX_JOB_ATTEMPTS,
    AuditTZRuntimeError,
    document_binding_digest,
)


router = APIRouter()
_ATOMIZATION_CONSENT_TYPE = "audit_tz_atomization_consent_v1"


def _create_atomization_consent_token(*, user: User, run: AuditTZRun, provider) -> str:
    return create_access_token(
        {
            "type": _ATOMIZATION_CONSENT_TYPE,
            "uid": str(user.id),
            "case_id": str(run.case_id),
            "run_id": str(run.id),
            "document_sha256": run.source_sha256,
            "skill_sha256": run.skill_sha256,
            "provider_id": str(provider.id),
            "provider_config_version": provider.config_version,
            "model_name": provider.model_name,
            "jti": str(uuid4()),
        },
        expires_delta=timedelta(minutes=15),
    )


def _verify_atomization_consent_token(
    token: str,
    *,
    user: User,
    run: AuditTZRun,
    provider,
) -> None:
    claims = decode_access_token(token)
    expected = {
        "type": _ATOMIZATION_CONSENT_TYPE,
        "uid": str(user.id),
        "case_id": str(run.case_id),
        "run_id": str(run.id),
        "document_sha256": run.source_sha256,
        "skill_sha256": run.skill_sha256,
        "provider_id": str(provider.id),
        "provider_config_version": provider.config_version,
        "model_name": provider.model_name,
    }
    if claims is None or any(claims.get(key) != value for key, value in expected.items()):
        raise HTTPException(
            status_code=409,
            detail="ИИ-провайдер, модель или документ изменились. Повторно откройте подтверждение передачи.",
        )


def _source_refs(raw_refs: list | None) -> list[AuditAISourceRefRead]:
    return [
        AuditAISourceRefRead(
            source_unit_id=str(ref.get("source_unit_id", ""))[:40],
            locator=str(ref.get("locator", ""))[:500],
            excerpt=str(ref.get("excerpt", ""))[:600],
        )
        for ref in (raw_refs or [])
        if isinstance(ref, dict) and ref.get("source_unit_id") and ref.get("locator")
    ]


def _registry_read(
    registry: AuditAIModelRegistry,
    *,
    skill: AuditAtomizationSkill | None = None,
    version: AuditAtomizationSkillVersion | None = None,
    document: AuditDocument | None = None,
    published_atom_count: int = 0,
) -> AuditAIModelRegistryRead:
    return AuditAIModelRegistryRead(
        id=registry.id,
        case_id=registry.case_id,
        canonical_run_id=registry.canonical_run_id,
        provider_config_id=registry.provider_config_id,
        provider_config_version=registry.provider_config_version,
        provider_name=registry.provider_name,
        model_name=registry.model_name,
        document_id=registry.document_id,
        document_sha256=registry.document_sha256,
        document_created_at=document.created_at if document else None,
        skill_version_id=registry.skill_version_id,
        skill_sha256=registry.skill_sha256,
        skill_name=skill.name if skill else None,
        skill_slug=skill.slug if skill else None,
        skill_version=version.version_label if version else None,
        published_atom_count=published_atom_count,
        atom_count=registry.atom_count,
        coverage_summary={
            str(key): int(value)
            for key, value in (registry.coverage_json or {}).items()
            if isinstance(value, int)
        },
        warnings=[str(item)[:500] for item in (registry.warnings_json or []) if isinstance(item, str)],
        items=[
            AuditAIModelRegistryItemRead(
                id=item.id,
                title=item.title,
                digital_product=item.digital_product,
                work_type=item.work_type,
                object_type=item.object_type,
                source_clause=item.source_clause,
                notes=item.notes,
                confidence_percent=item.confidence_percent,
                sort_order=item.sort_order,
                source_refs=_source_refs(item.source_refs_json),
            )
            for item in registry.items
        ],
        created_at=registry.created_at,
    )


def _comparison_read(comparison: AuditAIModelComparison) -> AuditAIModelComparisonRead:
    return AuditAIModelComparisonRead(
        id=comparison.id,
        case_id=comparison.case_id,
        canonical_run_id=comparison.canonical_run_id,
        status=comparison.status,
        config_version=comparison.config_version,
        registry_ids=[UUID(str(item)) for item in (comparison.registry_ids_json or [])],
        registry_snapshot=list(comparison.registry_snapshot_json or []),
        drafts=[
            AuditAIModelComparisonDraftRead(
                id=draft.id,
                title=draft.title,
                digital_product=draft.digital_product,
                work_type=draft.work_type,
                object_type=draft.object_type,
                source_clause=draft.source_clause,
                notes=draft.notes,
                confidence_percent=draft.confidence_percent,
                agreement_count=draft.agreement_count,
                registry_count=draft.registry_count,
                review_status=draft.review_status,
                sort_order=draft.sort_order,
                source_refs=_source_refs(draft.source_refs_json),
                model_variants=[AuditAIModelVariantRead(**variant) for variant in (draft.model_variants_json or [])],
            )
            for draft in comparison.drafts
        ],
        created_at=comparison.created_at,
        committed_at=comparison.committed_at,
        review_only=any(item.get("review_only") is True for item in (comparison.registry_snapshot_json or [])),
    )


async def _load_comparison(
    db: AsyncSession,
    comparison_id: UUID,
    case_id: UUID,
) -> AuditAIModelComparison | None:
    return await db.scalar(
        select(AuditAIModelComparison)
        .where(
            AuditAIModelComparison.id == comparison_id,
            AuditAIModelComparison.case_id == case_id,
        )
        .options(selectinload(AuditAIModelComparison.drafts))
    )


async def _serialize_run(db: AsyncSession, run_id: UUID) -> AuditTZRunRead:
    row = (
        await db.execute(
            select(AuditTZRun, AuditAtomizationSkill, AuditAtomizationSkillVersion)
            .join(
                AuditAtomizationSkillVersion,
                AuditAtomizationSkillVersion.id == AuditTZRun.skill_version_id,
            )
            .join(
                AuditAtomizationSkill,
                AuditAtomizationSkill.id == AuditAtomizationSkillVersion.skill_id,
            )
            .where(AuditTZRun.id == run_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Запуск canonical preflight не найден")
    run, skill, version = row
    attempt = await db.scalar(
        select(AuditAIAtomizationAttempt).where(AuditAIAtomizationAttempt.canonical_run_id == run.id)
    )
    atomization_job = await db.scalar(
        select(AuditTZRuntimeJob).where(
            AuditTZRuntimeJob.run_id == run.id,
            AuditTZRuntimeJob.kind == "atomization",
        )
    )
    artifacts = list(
        (
            await db.scalars(
                select(AuditTZArtifact)
                .where(AuditTZArtifact.run_id == run.id)
                .order_by(AuditTZArtifact.created_at.asc(), AuditTZArtifact.kind.asc())
            )
        ).all()
    )
    return AuditTZRunRead(
        id=run.id,
        case_id=run.case_id,
        document_id=run.document_id,
        skill_version_id=run.skill_version_id,
        skill_name=skill.name,
        skill_version=version.version_label,
        status=run.status,
        current_phase=run.current_phase,
        source_unit_count=run.source_unit_count,
        warning_count=run.warning_count,
        atom_count=run.atom_count,
        completed_batch_count=run.completed_batch_count,
        total_batch_count=run.total_batch_count,
        safe_summary=dict(run.safe_summary_json or {}),
        error_code=run.error_code,
        artifacts=[
            AuditTZArtifactRead(
                kind=item.kind,
                sha256=item.sha256,
                safe_summary=dict(item.safe_summary_json or {}),
            )
            for item in artifacts
            if item.visible_to_user
        ],
        external_ai_called=run.external_ai_called,
        ai_attempt_id=attempt.id if attempt is not None else None,
        pause_requested=bool(
            atomization_job is not None and atomization_job.pause_requested_at is not None
        ),
        priority=int(atomization_job.priority or 0) if atomization_job is not None else 0,
        paused_at=atomization_job.paused_at if atomization_job is not None else None,
        created_at=run.created_at,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


@router.post(
    "/cases/{case_id}/canonical-preflight/runs",
    response_model=AuditTZRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_canonical_preflight(
    case_id: UUID,
    body: AuditTZRunStart,
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    if not settings.AUDIT_TZ_WORKER_ENABLED:
        raise HTTPException(status_code=503, detail="Изолированный audit-tz runtime отключен")
    audit_case = await _get_case_or_404(db, case_id)
    await _ensure_case_atom_editor(audit_case, user, db)
    if audit_case.status == "archived":
        raise HTTPException(status_code=409, detail="Архивный аудит нельзя отправить на canonical preflight")
    document = await db.scalar(
        select(AuditDocument).where(
            AuditDocument.id == body.document_id,
            AuditDocument.case_id == case_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Исходный документ этого аудита не найден")
    document_suffix = Path(document.original_filename).suffix.lower()
    if document.kind != "technical_spec" or document_suffix not in {".docx", ".pdf"}:
        raise HTTPException(
            status_code=422,
            detail="Подготовка поддерживает неизменяемое ТЗ в DOCX или текстовом PDF",
        )
    skill_row = (
        await db.execute(
            select(AuditAtomizationSkill, AuditAtomizationSkillVersion)
            .join(
                AuditAtomizationSkillVersion,
                AuditAtomizationSkillVersion.skill_id == AuditAtomizationSkill.id,
            )
            .where(
                AuditAtomizationSkillVersion.id == body.skill_version_id,
                AuditAtomizationSkillVersion.package_format.in_(
                    ["trusted_skill_archive", "declarative_archive", "declarative_json"]
                ),
                AuditAtomizationSkillVersion.runtime_status == "ready",
                AuditAtomizationSkillVersion.is_active.is_(True),
                AuditAtomizationSkill.is_enabled.is_(True),
            )
        )
    ).one_or_none()
    if skill_row is None:
        raise HTTPException(status_code=409, detail="Выбранная активная методика не готова к запуску")
    _, skill_version = skill_row
    if document_suffix == ".pdf" and skill_version.package_format == "trusted_skill_archive":
        raise HTTPException(status_code=422, detail="Исполняемый audit-tz поддерживает только DOCX; для PDF выберите декларативную методику")
    try:
        digest = document_binding_digest(document.sha256)
        run_key = build_run_key(
            case_id=str(case_id),
            document_sha256=document.sha256,
            skill_sha256=skill_version.content_sha256,
            identifiers_digest=digest,
            mode="audit-only",
        )
    except (AuditRuntimeCryptoError, AuditTZRuntimeError) as error:
        raise HTTPException(status_code=503, detail={"code": error.code, "message": error.message})

    existing = await db.scalar(
        select(AuditTZRun)
        .where(AuditTZRun.run_key_hash == run_key)
        .with_for_update()
    )
    if existing is not None:
        if existing.case_id != case_id:
            raise HTTPException(status_code=409, detail="Ключ запуска уже использован в другом аудите")
        if existing.status in {"failed", "blocked"}:
            job = await db.scalar(
                select(AuditTZRuntimeJob)
                .where(
                    AuditTZRuntimeJob.run_id == existing.id,
                    AuditTZRuntimeJob.kind == "preflight",
                )
                .with_for_update()
            )
            if job is None or job.status == "running":
                raise HTTPException(status_code=409, detail="Не удалось безопасно повторить запуск")
            existing.identifier_ciphertext = None
            existing.identifiers_purged_at = datetime.now(timezone.utc)
            existing.status = "queued"
            existing.current_phase = "queued"
            existing.error_code = None
            existing.finished_at = None
            job.status = "queued"
            job.attempt_count = 0
            job.available_at = datetime.now(timezone.utc)
            job.lease_token = None
            job.lease_expires_at = None
            job.worker_id = None
            job.error_code = None
            job.finished_at = None
            db.add(
                AuditEvent(
                    case_id=case_id,
                    actor_id=user.id,
                    event_type="audit_tz_preflight_queued",
                    message="Документ повторно поставлен в очередь canonical runtime",
                    payload_json={"runtime_run_id": str(existing.id)},
                )
            )
            await db.flush()
        return await _serialize_run(db, existing.id)

    run = AuditTZRun(
        case_id=case_id,
        document_id=document.id,
        skill_version_id=skill_version.id,
        requested_by_id=user.id,
        mode="audit-only",
        source_binding="document_hash",
        run_key_hash=run_key,
        identifier_digest=digest,
        identifier_ciphertext=None,
        identifiers_purged_at=datetime.now(timezone.utc),
        source_sha256=document.sha256,
        skill_sha256=skill_version.content_sha256,
        status="queued",
        current_phase="queued",
    )
    db.add(run)
    try:
        await db.flush()
        db.add(
            AuditTZRuntimeJob(
                kind="preflight",
                skill_version_id=skill_version.id,
                run_id=run.id,
                status="queued",
                max_attempts=3,
            )
        )
        db.add(
            AuditEvent(
                case_id=case_id,
                actor_id=user.id,
                event_type="audit_tz_preflight_queued",
                message="Документ поставлен в очередь canonical runtime",
                payload_json={
                    "runtime_run_id": str(run.id),
                    "document_id": str(document.id),
                    "skill_version_id": str(skill_version.id),
                },
            )
        )
        await db.flush()
    except IntegrityError:
        await db.rollback()
        concurrent = await db.scalar(select(AuditTZRun).where(AuditTZRun.run_key_hash == run_key))
        if concurrent is None or concurrent.case_id != case_id:
            raise HTTPException(status_code=409, detail="Не удалось создать уникальный запуск preflight")
        return await _serialize_run(db, concurrent.id)
    return await _serialize_run(db, run.id)


@router.get(
    "/cases/{case_id}/canonical-preflight/runs/{run_id}/atomization-preview",
    response_model=AuditTZAtomizationPreviewRead,
)
async def preview_canonical_atomization(
    case_id: UUID,
    run_id: UUID,
    provider_id: UUID = Query(...),
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    audit_case = await _get_case_or_404(db, case_id)
    await _ensure_case_atom_editor(audit_case, user, db)
    run = await db.scalar(
        select(AuditTZRun).where(AuditTZRun.id == run_id, AuditTZRun.case_id == case_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Запуск canonical runtime не найден")
    atomization_retry = (
        run.status == "failed"
        and run.current_phase == "atomization_failed"
        and run.source_unit_count > 0
    )
    if run.status not in {
        "preflight_pass",
        "atomization_queued",
        "atomizing",
        "paused",
        "draft_ready",
        "committed",
    } and not atomization_retry:
        raise HTTPException(status_code=409, detail="Сначала подготовьте документ")
    try:
        provider = await get_ready_ai_provider(db, provider_id)
    except AIProviderError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        )
    existing_lane = await db.scalar(
        select(AuditAIModelRegistry.id).where(
            AuditAIModelRegistry.canonical_run_id == run.id,
            AuditAIModelRegistry.provider_config_id == provider.id,
            AuditAIModelRegistry.provider_config_version == provider.config_version,
            AuditAIModelRegistry.model_name == provider.model_name,
        )
    )
    if existing_lane is not None:
        raise HTTPException(
            status_code=409,
            detail="Реестр этой версии модели уже сформирован; выберите другое ИИ-подключение",
        )
    return AuditTZAtomizationPreviewRead(
        consent_token=_create_atomization_consent_token(user=user, run=run, provider=provider),
        provider_id=provider.id,
        provider_name=provider.display_name,
        model_name=provider.model_name,
        source_unit_count=run.source_unit_count,
        outbound_fields=[
            "обезличенный текст исходных фрагментов",
            "псевдонимные идентификаторы фрагментов",
            "правила атомизации и JSON-схема ответа",
        ],
        warnings=[
            "Номер договора не требуется и не используется для запуска.",
            "Реквизиты, похожие на номер договора, автоматически маскируются до отправки.",
            "Название файла, внутренние пути, SHA-256 и служебные ID модели не передаются.",
        ],
    )


@router.post(
    "/cases/{case_id}/canonical-preflight/runs/{run_id}/atomization",
    response_model=AuditTZRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def start_canonical_atomization(
    case_id: UUID,
    run_id: UUID,
    body: AuditTZAtomizationStart,
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    if not settings.AUDIT_TZ_WORKER_ENABLED:
        raise HTTPException(status_code=503, detail="Изолированный audit-tz runtime отключен")
    if not settings.AUDIT_TZ_EXTERNAL_AI_ENABLED:
        raise HTTPException(status_code=503, detail="Внешняя ИИ-атомизация отключена конфигурацией DPMS")
    audit_case = await _get_case_or_404(db, case_id, for_update=True)
    await _ensure_case_atom_editor(audit_case, user, db)
    if audit_case.status == "archived":
        raise HTTPException(status_code=409, detail="Архивный аудит нельзя атомизировать")
    run = await db.scalar(
        select(AuditTZRun)
        .where(AuditTZRun.id == run_id, AuditTZRun.case_id == case_id)
        .with_for_update()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Запуск canonical runtime не найден")
    atomization_retry = (
        run.status == "failed"
        and run.current_phase == "atomization_failed"
        and run.source_unit_count > 0
    )
    if run.status not in {
        "preflight_pass",
        "atomization_queued",
        "atomizing",
        "paused",
        "draft_ready",
        "committed",
    } and not atomization_retry:
        raise HTTPException(status_code=409, detail="Сначала успешно подготовьте документ")
    try:
        provider = await get_ready_ai_provider(db, body.provider_id)
    except AIProviderError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        )
    existing_lane = await db.scalar(
        select(AuditAIModelRegistry.id).where(
            AuditAIModelRegistry.canonical_run_id == run.id,
            AuditAIModelRegistry.provider_config_id == provider.id,
            AuditAIModelRegistry.provider_config_version == provider.config_version,
            AuditAIModelRegistry.model_name == provider.model_name,
        )
    )
    if existing_lane is not None:
        raise HTTPException(
            status_code=409,
            detail="Реестр этой версии модели уже сформирован; выберите другое ИИ-подключение",
        )
    _verify_atomization_consent_token(
        body.consent_token,
        user=user,
        run=run,
        provider=provider,
    )

    existing_attempt = await db.scalar(
        select(AuditAIAtomizationAttempt)
        .where(AuditAIAtomizationAttempt.canonical_run_id == run.id)
        .with_for_update()
    )
    if existing_attempt is not None:
        same_lane = (
            existing_attempt.provider_config_id == provider.id
            and existing_attempt.provider_config_version == provider.config_version
            and existing_attempt.model_name == provider.model_name
        )
        if existing_attempt.status == "running":
            if same_lane:
                return await _serialize_run(db, run.id)
            raise HTTPException(
                status_code=409,
                detail="Дождитесь завершения текущей модели перед запуском следующей",
            )
        if existing_attempt.status == "draft_ready" and same_lane:
            return await _serialize_run(db, run.id)
        job = await db.scalar(
            select(AuditTZRuntimeJob)
            .where(
                AuditTZRuntimeJob.run_id == run.id,
                AuditTZRuntimeJob.kind == "atomization",
            )
            .with_for_update()
        )
        if job is None or job.status == "running":
            raise HTTPException(status_code=409, detail="Не удалось безопасно повторить атомизацию")
        resume_checkpoint = bool(
            same_lane
            and existing_attempt.status == "failed"
            and existing_attempt.batch_results_json
        )
        if existing_attempt.status in {"draft_ready", "committed"}:
            saved_registry = await db.scalar(
                select(AuditAIModelRegistry.id).where(
                    AuditAIModelRegistry.canonical_run_id == run.id,
                    AuditAIModelRegistry.provider_config_id == existing_attempt.provider_config_id,
                    AuditAIModelRegistry.provider_config_version == existing_attempt.provider_config_version,
                    AuditAIModelRegistry.model_name == existing_attempt.model_name,
                )
            )
            if saved_registry is None:
                raise HTTPException(
                    status_code=409,
                    detail="Результат предыдущей модели еще не зафиксирован; обновите страницу",
                )
        await freeze_attempt_atom_origins(db, existing_attempt)
        await db.execute(
            delete(AuditAIAtomDraft).where(AuditAIAtomDraft.attempt_id == existing_attempt.id)
        )
        existing_attempt.request_key_hash = build_run_key(
            case_id=str(case_id),
            document_sha256=run.source_sha256,
            skill_sha256=run.skill_sha256,
            identifiers_digest=f"{body.request_id}:{provider.id}:{provider.config_version}",
            mode="canonical-atomization",
        )
        existing_attempt.status = "running"
        existing_attempt.error_code = None
        existing_attempt.provider_config_id = provider.id
        existing_attempt.provider_config_version = provider.config_version
        existing_attempt.model_name = provider.model_name
        existing_attempt.consent_confirmed_at = datetime.now(timezone.utc)
        existing_attempt.requested_by_id = user.id
        if not resume_checkpoint:
            existing_attempt.batch_results_json = []
        existing_attempt.source_manifest_json = []
        existing_attempt.coverage_json = {}
        existing_attempt.warnings_json = []
        existing_attempt.response_sha256 = None
        existing_attempt.commit_key_hash = None
        existing_attempt.committed_by_id = None
        existing_attempt.committed_at = None
        run.atom_count = 0
        run.completed_batch_count = (
            len(existing_attempt.batch_results_json or []) if resume_checkpoint else 0
        )
        if not resume_checkpoint:
            run.total_batch_count = 0
            run.external_ai_called = False
        run_summary = dict(getattr(run, "safe_summary_json", {}) or {})
        run_summary.pop("atomization_retry_at", None)
        run_summary.pop("atomization_retry_count", None)
        run_summary.pop("atomization_retry_error", None)
        run.safe_summary_json = run_summary
        existing_attempt.config_version += 1
        job.status = "queued"
        job.attempt_count = 0
        job.max_attempts = max(
            int(getattr(job, "max_attempts", 0) or 0),
            ATOMIZATION_MAX_JOB_ATTEMPTS,
        )
        job.available_at = datetime.now(timezone.utc)
        job.lease_token = None
        job.lease_expires_at = None
        job.worker_id = None
        job.pause_requested_at = None
        job.paused_at = None
        job.pause_requested_by_id = None
        job.priority = 0
        job.error_code = None
        job.finished_at = None
    else:
        request_key_hash = build_run_key(
            case_id=str(case_id),
            document_sha256=run.source_sha256,
            skill_sha256=run.skill_sha256,
            identifiers_digest=f"{body.request_id}:{provider.id}:{provider.config_version}",
            mode="canonical-atomization",
        )
        attempt = AuditAIAtomizationAttempt(
            case_id=case_id,
            canonical_run_id=run.id,
            document_id=run.document_id,
            skill_version_id=run.skill_version_id,
            provider_config_id=provider.id,
            provider_config_version=provider.config_version,
            model_name=provider.model_name,
            document_sha256=run.source_sha256,
            skill_sha256=run.skill_sha256,
            request_key_hash=request_key_hash,
            status="running",
            config_version=1,
            source_manifest_json=[],
            coverage_json={},
            warnings_json=[],
            batch_results_json=[],
            prompt_sha256="0" * 64,
            requested_by_id=user.id,
            consent_confirmed_at=datetime.now(timezone.utc),
        )
        db.add(attempt)
        await db.flush()
        db.add(
            AuditTZRuntimeJob(
                kind="atomization",
                skill_version_id=run.skill_version_id,
                run_id=run.id,
                status="queued",
                max_attempts=ATOMIZATION_MAX_JOB_ATTEMPTS,
            )
        )

    run.status = "atomization_queued"
    run.current_phase = "atomization_queued"
    run.error_code = None
    run.finished_at = None
    db.add(
        AuditEvent(
            case_id=case_id,
            actor_id=user.id,
            event_type="audit_tz_atomization_queued",
            message="ТЗ поставлено в очередь ИИ-атомизации",
            payload_json={
                "runtime_run_id": str(run.id),
                "source_unit_count": run.source_unit_count,
                "provider_id": str(provider.id),
                "provider_name": provider.display_name,
                "model_name": provider.model_name,
                "resumed_batch_count": run.completed_batch_count,
            },
        )
    )
    await db.flush()
    return await _serialize_run(db, run.id)


async def _locked_atomization_run_and_job(
    db: AsyncSession,
    *,
    case_id: UUID,
    run_id: UUID,
) -> tuple[AuditTZRun, AuditTZRuntimeJob]:
    job = await db.scalar(
        select(AuditTZRuntimeJob)
        .join(AuditTZRun, AuditTZRun.id == AuditTZRuntimeJob.run_id)
        .where(
            AuditTZRuntimeJob.run_id == run_id,
            AuditTZRuntimeJob.kind == "atomization",
            AuditTZRun.case_id == case_id,
        )
        .with_for_update(of=AuditTZRuntimeJob)
    )
    if job is None:
        run_exists = await db.scalar(
            select(AuditTZRun.id).where(AuditTZRun.id == run_id, AuditTZRun.case_id == case_id)
        )
        if run_exists is None:
            raise HTTPException(status_code=404, detail="Запуск canonical runtime не найден")
        raise HTTPException(status_code=409, detail="Задание ИИ-атомизации ещё не создано")
    run = await db.scalar(
        select(AuditTZRun)
        .where(AuditTZRun.id == run_id, AuditTZRun.case_id == case_id)
        .with_for_update()
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Запуск canonical runtime не найден")
    return run, job


@router.post(
    "/cases/{case_id}/canonical-preflight/runs/{run_id}/atomization/pause",
    response_model=AuditTZRunRead,
)
async def pause_canonical_atomization(
    case_id: UUID,
    run_id: UUID,
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    audit_case = await _get_case_or_404(db, case_id)
    await _ensure_case_atom_editor(audit_case, user, db)
    run, job = await _locked_atomization_run_and_job(db, case_id=case_id, run_id=run_id)
    if job.status == "paused":
        return await _serialize_run(db, run.id)
    if job.status not in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="Этот запуск уже нельзя приостановить")

    now = datetime.now(timezone.utc)
    if job.status == "queued":
        job.status = "paused"
        job.paused_at = now
        job.pause_requested_at = None
        run.status = "paused"
        run.current_phase = "atomization_paused"
        message = "ИИ-атомизация приостановлена до начала следующего пакета"
        event_type = "audit_tz_atomization_paused"
    else:
        job.pause_requested_at = now
        run.current_phase = "atomization_pause_requested"
        message = "Запрошена остановка ИИ-атомизации после текущего пакета"
        event_type = "audit_tz_atomization_pause_requested"
    job.pause_requested_by_id = user.id
    db.add(
        AuditEvent(
            case_id=case_id,
            actor_id=user.id,
            event_type=event_type,
            message=message,
            payload_json={
                "runtime_run_id": str(run.id),
                "completed_batch_count": run.completed_batch_count,
                "total_batch_count": run.total_batch_count,
            },
        )
    )
    await db.flush()
    return await _serialize_run(db, run.id)


@router.post(
    "/cases/{case_id}/canonical-preflight/runs/{run_id}/atomization/resume",
    response_model=AuditTZRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def resume_canonical_atomization(
    case_id: UUID,
    run_id: UUID,
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    audit_case = await _get_case_or_404(db, case_id)
    await _ensure_case_atom_editor(audit_case, user, db)
    run, job = await _locked_atomization_run_and_job(db, case_id=case_id, run_id=run_id)
    if job.status == "queued" and job.pause_requested_at is None:
        return await _serialize_run(db, run.id)
    if job.status == "running" and job.pause_requested_at is None:
        return await _serialize_run(db, run.id)
    if job.status not in {"paused", "running"}:
        raise HTTPException(status_code=409, detail="Этот запуск уже нельзя возобновить")

    now = datetime.now(timezone.utc)
    if job.status == "paused":
        job.status = "queued"
        job.available_at = now
        job.lease_token = None
        job.lease_expires_at = None
        job.worker_id = None
        job.finished_at = None
        run.status = "atomization_queued"
        run.current_phase = "atomization_queued"
    else:
        run.status = "atomizing"
        run.current_phase = "atomizing"
    job.pause_requested_at = None
    job.paused_at = None
    job.pause_requested_by_id = None
    run.error_code = None
    run.finished_at = None
    db.add(
        AuditEvent(
            case_id=case_id,
            actor_id=user.id,
            event_type="audit_tz_atomization_resumed",
            message="ИИ-атомизация возобновлена с сохранённого пакета",
            payload_json={
                "runtime_run_id": str(run.id),
                "completed_batch_count": run.completed_batch_count,
                "total_batch_count": run.total_batch_count,
            },
        )
    )
    await db.flush()
    return await _serialize_run(db, run.id)


@router.post(
    "/cases/{case_id}/canonical-preflight/runs/{run_id}/atomization/prioritize",
    response_model=AuditTZRunRead,
    status_code=status.HTTP_202_ACCEPTED,
)
async def prioritize_canonical_atomization(
    case_id: UUID,
    run_id: UUID,
    user: User = Depends(require_audit_manager),
    db: AsyncSession = Depends(get_db),
):
    await _get_case_or_404(db, case_id)
    run, job = await _locked_atomization_run_and_job(db, case_id=case_id, run_id=run_id)
    if job.status not in {"queued", "paused", "running"}:
        raise HTTPException(status_code=409, detail="Для завершённого запуска приоритет не применяется")

    await db.execute(
        update(AuditTZRuntimeJob)
        .where(
            AuditTZRuntimeJob.kind == "atomization",
            AuditTZRuntimeJob.status.in_(["queued", "paused", "running"]),
            AuditTZRuntimeJob.id != job.id,
        )
        .values(priority=0)
        .execution_options(synchronize_session=False)
    )
    job.priority = 100
    if job.status == "paused":
        job.status = "queued"
        job.available_at = datetime.now(timezone.utc)
        job.paused_at = None
        job.pause_requested_at = None
        job.pause_requested_by_id = None
        run.status = "atomization_queued"
        run.current_phase = "atomization_queued"
    db.add(
        AuditEvent(
            case_id=case_id,
            actor_id=user.id,
            event_type="audit_tz_atomization_prioritized",
            message="ИИ-атомизация выбрана следующей в очереди",
            payload_json={
                "runtime_run_id": str(run.id),
                "completed_batch_count": run.completed_batch_count,
                "total_batch_count": run.total_batch_count,
            },
        )
    )
    await db.flush()
    return await _serialize_run(db, run.id)


@router.get(
    "/cases/{case_id}/canonical-preflight/runs/{run_id}/attempt",
    response_model=AuditAIAtomizationAttemptRead,
)
async def get_canonical_atomization_attempt(
    case_id: UUID,
    run_id: UUID,
    _: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    await _get_case_or_404(db, case_id)
    attempt_id = await db.scalar(
        select(AuditAIAtomizationAttempt.id).where(
            AuditAIAtomizationAttempt.canonical_run_id == run_id,
            AuditAIAtomizationAttempt.case_id == case_id,
        )
    )
    if attempt_id is None:
        raise HTTPException(status_code=404, detail="Черновик canonical атомизации не найден")
    return await _serialize_ai_attempt(db, attempt_id)


@router.get("/ai-providers", response_model=AuditAIProviderOptionList)
async def list_ready_audit_ai_providers(
    _: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    providers = list(
        (
            await db.scalars(
                select(AIProviderConfig)
                .where(AIProviderConfig.provider_kind == "openai_compatible")
                .order_by(AIProviderConfig.display_name.asc(), AIProviderConfig.created_at.asc())
            )
        ).all()
    )
    return AuditAIProviderOptionList(
        items=[
            AuditAIProviderOptionRead(
                id=provider.id,
                display_name=provider.display_name,
                model_name=provider.model_name,
                config_version=provider.config_version,
            )
            for provider in providers
            if ai_provider_ready(provider)
        ]
    )


@router.get(
    "/cases/{case_id}/model-registries",
    response_model=AuditAIModelRegistryList,
)
async def list_audit_model_registries(
    case_id: UUID,
    run_id: UUID | None = Query(None),
    _: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    await _get_case_or_404(db, case_id)
    query = (
        select(AuditAIModelRegistry)
        .where(AuditAIModelRegistry.case_id == case_id)
        .options(selectinload(AuditAIModelRegistry.items))
        .order_by(AuditAIModelRegistry.created_at.asc(), AuditAIModelRegistry.id.asc())
    )
    if run_id is not None:
        query = query.where(AuditAIModelRegistry.canonical_run_id == run_id)
    registries = list((await db.scalars(query)).unique().all())
    if not registries:
        return AuditAIModelRegistryList(items=[])
    version_rows = (
        await db.execute(
            select(AuditAtomizationSkillVersion, AuditAtomizationSkill)
            .join(AuditAtomizationSkill, AuditAtomizationSkill.id == AuditAtomizationSkillVersion.skill_id)
            .where(AuditAtomizationSkillVersion.id.in_({row.skill_version_id for row in registries}))
        )
    ).all()
    versions = {version.id: (version, skill) for version, skill in version_rows}
    documents = {
        document.id: document
        for document in await db.scalars(
            select(AuditDocument).where(AuditDocument.id.in_({row.document_id for row in registries}))
        )
    }
    published = await lookup_published_registry_items_batch(db, registries)
    return AuditAIModelRegistryList(items=[
        _registry_read(
            registry,
            version=versions.get(registry.skill_version_id, (None, None))[0],
            skill=versions.get(registry.skill_version_id, (None, None))[1],
            document=documents.get(registry.document_id),
            published_atom_count=len(published.get(registry.id, {})),
        )
        for registry in registries
    ])


@router.post(
    "/cases/{case_id}/model-registries/{registry_id}/publish",
    response_model=AuditAIModelRegistryPublishRead,
)
async def publish_audit_model_registry(
    case_id: UUID,
    registry_id: UUID,
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    audit_case = await _get_case_or_404(db, case_id, for_update=True)
    await _ensure_case_atom_editor(audit_case, user, db)
    registry = await db.scalar(
        select(AuditAIModelRegistry)
        .where(AuditAIModelRegistry.id == registry_id, AuditAIModelRegistry.case_id == case_id)
        .options(selectinload(AuditAIModelRegistry.items))
    )
    if registry is None:
        raise HTTPException(status_code=404, detail="Модельный реестр не найден в этом договоре")
    result = await publish_model_registry_atoms(db, registry, user.id)
    await db.flush()
    return AuditAIModelRegistryPublishRead(
        registry_id=registry.id,
        atoms_created=result.atoms_created,
        atom_ids=result.atom_ids,
        already_published=result.atoms_created == 0,
    )


@router.get(
    "/cases/{case_id}/model-comparisons",
    response_model=list[AuditAIModelComparisonRead],
)
async def list_audit_model_comparisons(
    case_id: UUID,
    _: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    await _get_case_or_404(db, case_id)
    comparisons = list(
        (
            await db.scalars(
                select(AuditAIModelComparison)
                .where(AuditAIModelComparison.case_id == case_id)
                .options(selectinload(AuditAIModelComparison.drafts))
                .order_by(AuditAIModelComparison.created_at.desc())
            )
        ).unique().all()
    )
    return [_comparison_read(comparison) for comparison in comparisons]


@router.post(
    "/cases/{case_id}/model-comparisons",
    response_model=AuditAIModelComparisonRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_audit_model_comparison(
    case_id: UUID,
    body: AuditAIModelComparisonStart,
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    audit_case = await _get_case_or_404(db, case_id, for_update=True)
    await _ensure_case_atom_editor(audit_case, user, db)
    if audit_case.status == "archived":
        raise HTTPException(status_code=409, detail="Архивный аудит нельзя сравнивать")
    registries = list(
        (
            await db.scalars(
                select(AuditAIModelRegistry)
                .where(
                    AuditAIModelRegistry.case_id == case_id,
                    AuditAIModelRegistry.id.in_(body.registry_ids),
                )
                .options(selectinload(AuditAIModelRegistry.items))
            )
        ).unique().all()
    )
    if len(registries) != len(body.registry_ids):
        raise HTTPException(status_code=422, detail="Один из модельных реестров не найден")
    by_id = {registry.id: registry for registry in registries}
    registries = [by_id[registry_id] for registry_id in body.registry_ids]
    contexts = {
        (
            registry.document_id,
            registry.document_sha256,
        )
        for registry in registries
    }
    if len(contexts) != 1:
        raise HTTPException(
            status_code=422,
            detail="Сравнивать можно только результаты одной неизменяемой версии ТЗ; методики и модели могут отличаться",
        )
    lanes = {
        (
            registry.provider_config_id,
            registry.provider_config_version,
            registry.model_name,
            registry.skill_version_id,
            registry.skill_sha256,
        )
        for registry in registries
    }
    if len(lanes) != len(registries):
        raise HTTPException(status_code=422, detail="Для сравнения выбраны одинаковые модельные прогоны")
    skill_rows = (await db.execute(
        select(AuditAtomizationSkillVersion, AuditAtomizationSkill)
        .join(AuditAtomizationSkill, AuditAtomizationSkill.id == AuditAtomizationSkillVersion.skill_id)
        .where(AuditAtomizationSkillVersion.id.in_({row.skill_version_id for row in registries}))
    )).all()
    skill_metadata = {
        version.id: {"skill_name": skill.name, "skill_version": version.version_label}
        for version, skill in skill_rows
    }
    snapshots = [
        {
            "registry_id": str(registry.id),
            "provider_id": str(registry.provider_config_id),
            "provider_name": registry.provider_name,
            "provider_config_version": registry.provider_config_version,
            "model_name": registry.model_name,
            "document_id": str(registry.document_id),
            "document_sha256": registry.document_sha256,
            "skill_version_id": str(registry.skill_version_id),
            "skill_sha256": registry.skill_sha256,
            **skill_metadata.get(registry.skill_version_id, {}),
            "response_sha256": registry.response_sha256,
            "atom_count": registry.atom_count,
            "review_only": True,
        }
        for registry in registries
    ]
    comparison_key = sha256(
        json.dumps(
            {"algorithm": "exact-evidence-review-v2", "registries": sorted(
                ({key: value for key, value in item.items() if key not in {"provider_name", "skill_name", "skill_version"}}
                 for item in snapshots), key=lambda item: item["registry_id"],
            )},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    existing = await db.scalar(
        select(AuditAIModelComparison)
        .where(AuditAIModelComparison.comparison_key_hash == comparison_key)
        .options(selectinload(AuditAIModelComparison.drafts))
    )
    if existing is not None:
        return _comparison_read(existing)
    try:
        generated = build_model_comparison(registries)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))
    if not generated:
        raise HTTPException(status_code=422, detail="В выбранных модельных реестрах нет атомов")
    if len(generated) > 4800:
        raise HTTPException(status_code=422, detail="Сравнение превышает 4800 предложений; выберите меньше реестров")
    first = registries[0]
    comparison = AuditAIModelComparison(
        case_id=case_id,
        canonical_run_id=first.canonical_run_id,
        document_id=first.document_id,
        skill_version_id=first.skill_version_id,
        comparison_key_hash=comparison_key,
        registry_ids_json=[str(registry.id) for registry in registries],
        registry_snapshot_json=snapshots,
        status="draft_ready",
        config_version=1,
        requested_by_id=user.id,
    )
    db.add(comparison)
    await db.flush()
    for draft in generated:
        for variant in draft.model_variants:
            registry = by_id[UUID(variant["registry_id"])]
            variant.update({
                "skill_version_id": str(registry.skill_version_id),
                "skill_sha256": registry.skill_sha256,
                **skill_metadata.get(registry.skill_version_id, {}),
            })
        db.add(
            AuditAIModelComparisonDraft(
                comparison_id=comparison.id,
                case_id=case_id,
                title=draft.title,
                digital_product=draft.digital_product,
                work_type=draft.work_type,
                object_type=draft.object_type,
                source_clause=draft.source_clause,
                notes=draft.notes,
                source_refs_json=draft.source_refs,
                model_variants_json=draft.model_variants,
                source_fingerprint=draft.source_fingerprint,
                confidence_percent=draft.confidence_percent,
                agreement_count=draft.agreement_count,
                registry_count=draft.registry_count,
                review_status="pending",
                sort_order=draft.sort_order,
            )
        )
    db.add(
        AuditEvent(
            case_id=case_id,
            actor_id=user.id,
            event_type="ai_model_comparison_ready",
            message="Подготовлен сравнительный анализ модельных реестров без изменения рабочих атомов",
            payload_json={
                "comparison_id": str(comparison.id),
                "registry_ids": [str(registry.id) for registry in registries],
                "registry_count": len(registries),
                "draft_count": len(generated),
            },
        )
    )
    await db.flush()
    loaded = await _load_comparison(db, comparison.id, case_id)
    if loaded is None:
        raise HTTPException(status_code=500, detail="Не удалось сохранить сравнительный анализ")
    return _comparison_read(loaded)


@router.get(
    "/cases/{case_id}/model-comparisons/{comparison_id}",
    response_model=AuditAIModelComparisonRead,
)
async def get_audit_model_comparison(
    case_id: UUID,
    comparison_id: UUID,
    _: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    await _get_case_or_404(db, case_id)
    comparison = await _load_comparison(db, comparison_id, case_id)
    if comparison is None:
        raise HTTPException(status_code=404, detail="Сравнительный анализ не найден")
    return _comparison_read(comparison)


@router.post(
    "/cases/{case_id}/model-comparisons/{comparison_id}/commit",
    response_model=AuditAIModelComparisonCommitRead,
)
async def commit_audit_model_comparison(
    case_id: UUID,
    comparison_id: UUID,
    body: AuditAIModelComparisonCommit,
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    audit_case = await _get_case_or_404(db, case_id, for_update=True)
    await _ensure_case_atom_editor(audit_case, user, db)
    comparison = await db.scalar(
        select(AuditAIModelComparison)
        .where(AuditAIModelComparison.id == comparison_id, AuditAIModelComparison.case_id == case_id)
        .with_for_update()
    )
    if comparison is None:
        raise HTTPException(status_code=404, detail="Сравнительный анализ не найден")
    commit_key = sha256(f"audit-model-comparison:{user.id}:{body.request_id}".encode("utf-8")).hexdigest()
    review_payload_hash = sha256(json.dumps({
        "comparison_id": str(comparison.id), "expected_config_version": body.expected_config_version,
        "drafts": sorted((item.model_dump(mode="json") for item in body.drafts), key=lambda item: item["id"]),
    }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    drafts = list(await db.scalars(
        select(AuditAIModelComparisonDraft)
        .where(AuditAIModelComparisonDraft.comparison_id == comparison_id)
        .order_by(AuditAIModelComparisonDraft.sort_order, AuditAIModelComparisonDraft.id)
        .with_for_update()
    ))
    registry_ids = [UUID(str(value)) for value in comparison.registry_ids_json]
    if comparison.status == "committed":
        if comparison.commit_key_hash != commit_key:
            raise HTTPException(status_code=409, detail="Решения сравнения уже сохранены")
        saved_hashes = {item.get("review_payload_sha256") for item in comparison.registry_snapshot_json}
        if saved_hashes != {None} and saved_hashes != {review_payload_hash}:
            raise HTTPException(status_code=409, detail="Этот запрос уже сохранен с другими решениями сравнения")
        review_only = any(item.get("review_only") is True for item in comparison.registry_snapshot_json)
        query = select(AuditAtom.id).where(AuditAtom.case_id == case_id)
        if review_only:
            query = query.join(
                AuditAIModelRegistryItem, AuditAIModelRegistryItem.id == AuditAtom.ai_registry_item_id
            ).where(AuditAIModelRegistryItem.registry_id.in_(registry_ids))
        else:
            query = query.where(AuditAtom.ai_comparison_draft_id.in_([draft.id for draft in drafts]))
        atom_ids = list(await db.scalars(query))
        return AuditAIModelComparisonCommitRead(
            comparison_id=comparison.id, case_id=case_id, atoms_created=0 if review_only else len(atom_ids),
            atom_ids=atom_ids, already_committed=True, review_only=review_only,
        )
    if comparison.config_version != body.expected_config_version:
        raise HTTPException(status_code=409, detail="Сравнение изменилось; обновите его перед сохранением")
    registries = list((await db.scalars(
        select(AuditAIModelRegistry)
        .where(AuditAIModelRegistry.case_id == case_id, AuditAIModelRegistry.id.in_(registry_ids))
        .options(selectinload(AuditAIModelRegistry.items))
    )).unique().all())
    document = await db.get(AuditDocument, comparison.document_id)
    if (
        len(registries) != len(registry_ids)
        or document is None
        or document.case_id != case_id
        or any(row.document_id != document.id or row.document_sha256 != document.sha256 for row in registries)
    ):
        raise HTTPException(status_code=409, detail="Исходная версия документа или реестры изменились")
    submitted = {item.id: item for item in body.drafts}
    if set(submitted) != {draft.id for draft in drafts}:
        raise HTTPException(status_code=422, detail="Передайте решение по каждому предложению сравнения")

    # Keep source proposals and human audit results intact; a comparison is a separate review.
    for draft in drafts:
        item = submitted[draft.id]
        draft.title = item.title
        draft.digital_product = item.digital_product
        draft.work_type = item.work_type
        draft.object_type = item.object_type
        draft.notes = item.notes
        draft.review_status = "committed" if item.included else "rejected"
    atom_ids = list(await db.scalars(
        select(AuditAtom.id)
        .join(AuditAIModelRegistryItem, AuditAIModelRegistryItem.id == AuditAtom.ai_registry_item_id)
        .where(AuditAtom.case_id == case_id, AuditAIModelRegistryItem.registry_id.in_(registry_ids))
    ))
    comparison.registry_snapshot_json = [
        {**item, "review_only": True, "review_payload_sha256": review_payload_hash} for item in comparison.registry_snapshot_json
    ]
    comparison.status = "committed"
    comparison.commit_key_hash = commit_key
    comparison.committed_by_id = user.id
    comparison.committed_at = datetime.now(timezone.utc)
    comparison.config_version += 1
    db.add(AuditEvent(
        case_id=case_id, actor_id=user.id, event_type="ai_model_comparison_reviewed",
        message="Сохранены решения сравнения; исходные атомы и результаты проверок не изменены",
        payload_json={"comparison_id": str(comparison.id), "atom_count": len(atom_ids)},
    ))
    await db.flush()
    return AuditAIModelComparisonCommitRead(
        comparison_id=comparison.id, case_id=case_id, atoms_created=0,
        atom_ids=list(dict.fromkeys(atom_ids)), already_committed=False, review_only=True,
    )


@router.get(
    "/cases/{case_id}/canonical-preflight/runs/{run_id}",
    response_model=AuditTZRunRead,
)
async def get_canonical_preflight(
    case_id: UUID,
    run_id: UUID,
    _: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    await _get_case_or_404(db, case_id)
    run = await db.scalar(
        select(AuditTZRun).where(AuditTZRun.id == run_id, AuditTZRun.case_id == case_id)
    )
    if run is None:
        raise HTTPException(status_code=404, detail="Запуск canonical preflight не найден")
    return await _serialize_run(db, run.id)


@router.get(
    "/cases/{case_id}/canonical-preflight/runs",
    response_model=AuditTZRunList,
)
async def list_canonical_preflights(
    case_id: UUID,
    _: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    await _get_case_or_404(db, case_id)
    run_ids = list(
        await db.scalars(
            select(AuditTZRun.id)
            .where(AuditTZRun.case_id == case_id)
            .order_by(AuditTZRun.created_at.desc())
            .limit(20)
        )
    )
    return AuditTZRunList(items=[await _serialize_run(db, item) for item in run_ids])
