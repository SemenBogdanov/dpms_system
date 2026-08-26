"""Audit registry and first-stage atomization API."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlsplit
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, Response
from sqlalchemy import and_, delete, func, or_, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.api.deps import get_db, require_audit_access
from app.models.ai_provider import (
    AIProviderConfig,
    AuditAtomizationSkill,
    AuditAtomizationSkillVersion,
)
from app.models.audit import (
    AuditAIAtomDraft,
    AuditAIAtomizationAttempt,
    AuditAssignment,
    AuditAtom,
    AuditCase,
    AuditDocument,
    AuditEvent,
    AuditTeamMember,
)
from app.models.audit_runtime import AuditTZRun, AuditTZRuntimeJob
from app.models.contact import Contact
from app.models.user import User, UserRole
from app.schemas.audit import (
    AuditAtomCreate,
    AuditAtomBulkStatusRead,
    AuditAtomBulkStatusUpdate,
    AuditAtomRead,
    AuditAtomUpdate,
    AuditAssignmentCellUpdate,
    AuditAssignmentListRead,
    AuditAssignmentRead,
    AuditCaseCreate,
    AuditCaseDeleteRequest,
    AuditCaseDeleteResponse,
    AuditCaseRead,
    AuditCaseUpdate,
    AuditContractReferenceRead,
    AuditDocumentBatchResponse,
    AuditDocumentRead,
    AuditDocumentUploadItem,
    AuditEventRead,
    AuditImportCommitResponse,
    AuditImportPreview,
    AuditResponsibleUpdate,
    AuditStatisticsRead,
    AuditTeamCandidateRead,
    AuditTeamMemberCreate,
    AuditTeamMemberRead,
    AuditTeamMemberUpdate,
)
from app.schemas.audit_ai import (
    AuditAIAtomDraftRead,
    AuditAIAtomizationAttemptRead,
    AuditAIAtomizationCommit,
    AuditAIAtomizationCommitRead,
    AuditAIPrivacyPreviewRead,
    AuditAIPrivacyPreviewRequest,
    AuditAIAtomizationStart,
    AuditAISourceRefRead,
    AuditAtomizationSkillList,
    AuditAtomizationSkillVersionRead,
)
from app.services.ai_provider import AIProviderError, get_ready_ai_provider
from app.services.audit_contract_reference import (
    AuditContractReferenceError,
    decrypt_contract_reference,
    encrypt_contract_reference,
)
from app.services.audit_ai_atomization import (
    AuditAIAtomizationError,
    complete_audit_atomization,
    create_audit_privacy_preview,
    verify_audit_privacy_preview,
)
from app.services.audit_documents import (
    MAX_AUDIT_BATCH_BYTES,
    MAX_AUDIT_DOCUMENTS_PER_BATCH,
    audit_document_path,
    discard_staged_audit_document,
    finalize_pending_audit_document,
    finalize_staged_audit_document,
    persist_audit_document_file,
    prepare_audit_document,
    remove_audit_case_files,
    stage_audit_document_file,
)
from app.services.audit_import import (
    build_audit_atom_export,
    build_audit_atom_template,
    build_contract_fields,
    commit_audit_import,
    generate_next_item_code,
    preview_audit_import,
    record_audit_event,
)
from app.services.audit_model_comparison import evidence_text
from app.services.audit_statistics import (
    AuditStatisticsAtomRecord,
    AuditStatisticsCaseRecord,
    AuditStatisticsStateEvent,
    build_audit_statistics,
    period_start_utc,
    statistics_period,
)
from app.services.activity import record_activity_event

router = APIRouter()
CASE_STATUSES = {"draft", "atomization", "ready", "archived"}
AUDIT_WORKFLOW_STAGES = {
    "unassigned",
    "atomization",
    "alpha_review",
    "commission_pending",
    "fixes_required",
    "fixing",
    "recommission_pending",
    "ready",
}
REQUIRED_CASE_FIELDS = {"title", "digital_product", "status", "workflow_stage"}
REQUIRED_ATOM_FIELDS = {"item_code", "title", "digital_product", "state", "sort_order"}
ATOM_SCOPE_FIELDS = {
    "item_code",
    "title",
    "digital_product",
    "work_type",
    "object_type",
    "source_clause",
    "state",
    "sort_order",
}
ALPHA_COMMENT_REQUIRED_RESULTS = {
    "not_present",
    "partial",
    "not_applicable",
    "needs_clarification",
}
SAFE_EVENT_PAYLOAD_FIELDS = {
    "case_number",
    "fields",
    "item_code",
    "title",
    "row_number",
    "sha256",
    "rows",
    "previous_responsible_user_id",
    "responsible_user_id",
    "document_id",
    "document_kind",
    "attempt_id",
    "skill_version_id",
    "model_name",
    "atom_count",
    "assignee_id",
    "scheduled_date",
    "previous_assignee_id",
    "previous_scheduled_date",
    "previous_assignment_id",
    "retained_assignment_id",
    "workflow_stage",
    "previous_workflow_stage",
    "status",
    "previous_status",
    "state",
    "previous_state",
    "alpha_result",
    "previous_alpha_result",
    "alpha_comment",
    "previous_alpha_comment",
    "alpha_date",
    "identifier_count",
    "replacement_count",
    "source_unit_count",
    "payload_sha256",
    "runtime_run_id",
    "block_code",
    "error_code",
}
AUDIT_DOCUMENT_KINDS = {"technical_spec", "atom_register", "audit_result", "protocol", "other"}
AUDIT_DOCUMENT_KIND_LABELS = {
    "technical_spec": "Техническое задание",
    "atom_register": "Реестр атомов",
    "audit_result": "Результат аудита",
    "protocol": "Протокол",
    "other": "Другой материал",
}


async def require_audit_workspace_member(
    user: User = Depends(require_audit_access),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Allow admins and explicit members of the audit team into shared audit data."""
    if user.role in (UserRole.admin, UserRole.teamlead):
        return user
    if not await _is_audit_team_member(user, db):
        raise HTTPException(status_code=403, detail="Пользователь не включен в команду аудита")
    return user


async def require_audit_manager(
    user: User = Depends(require_audit_access),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Allow system managers and audit leaders to change audit workspace data."""
    if not await _is_audit_manager(user, db):
        raise HTTPException(status_code=403, detail="Недостаточно прав руководителя аудита")
    return user


async def _is_audit_manager(user: User, db: AsyncSession) -> bool:
    if user.role in (UserRole.admin, UserRole.teamlead):
        return True
    membership = await db.scalar(
        select(AuditTeamMember.id).where(
            AuditTeamMember.user_id == user.id,
            AuditTeamMember.role == "leader",
        )
    )
    return membership is not None


async def _is_audit_team_member(user: User, db: AsyncSession) -> bool:
    membership = await db.scalar(
        select(AuditTeamMember.id).where(AuditTeamMember.user_id == user.id)
    )
    return membership is not None


def _activate_case_for_assignment(
    db: AsyncSession,
    audit_case: AuditCase,
    actor_id: UUID,
) -> None:
    """Keep the public workflow and internal lifecycle consistent on assignment."""
    previous_stage = audit_case.workflow_stage
    previous_status = audit_case.status
    if audit_case.workflow_stage == "unassigned":
        audit_case.workflow_stage = "atomization"
    if audit_case.status == "draft":
        audit_case.status = "atomization"
    if audit_case.workflow_stage != previous_stage:
        record_audit_event(
            db,
            case_id=audit_case.id,
            actor_id=actor_id,
            event_type="workflow_stage_changed",
            message="Этап аудита: атомизация",
            payload_json={
                "previous_workflow_stage": previous_stage,
                "workflow_stage": audit_case.workflow_stage,
                "previous_status": previous_status,
                "status": audit_case.status,
            },
        )


async def _ensure_case_atom_editor(
    audit_case: AuditCase,
    user: User,
    db: AsyncSession,
) -> None:
    if audit_case.status == "archived":
        raise HTTPException(status_code=409, detail="Архивный аудит доступен только для чтения")
    if await _is_audit_manager(user, db):
        return
    if audit_case.responsible_user_id == user.id:
        return
    raise HTTPException(
        status_code=403,
        detail="Атомизацию может выполнять назначенный ответственный или руководитель аудита",
    )


def _validated_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlsplit(value)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(status_code=422, detail="Ссылка на объект должна начинаться с http:// или https://")
    return value


async def _get_case_or_404(
    db: AsyncSession,
    case_id: UUID,
    *,
    for_update: bool = False,
) -> AuditCase:
    query = select(AuditCase).where(AuditCase.id == case_id)
    if for_update:
        query = query.with_for_update()
    result = await db.execute(query)
    audit_case = result.scalar_one_or_none()
    if audit_case is None:
        raise HTTPException(status_code=404, detail="Аудит не найден")
    return audit_case


def _utc_timestamp(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _ensure_atom_version(atom: AuditAtom, expected_updated_at: datetime) -> None:
    if _utc_timestamp(expected_updated_at) != _utc_timestamp(atom.updated_at):
        raise HTTPException(
            status_code=409,
            detail=(
                f"Атом {atom.item_code} уже изменен другим пользователем. "
                "Обновите данные и повторите решение."
            ),
        )


def _return_case_to_atomization(
    db: AsyncSession,
    audit_case: AuditCase,
    actor_id: UUID,
    *,
    reason: str,
) -> None:
    if audit_case.workflow_stage in {"unassigned", "atomization"}:
        if audit_case.status == "ready":
            audit_case.status = "atomization"
        return
    previous_stage = audit_case.workflow_stage
    previous_status = audit_case.status
    audit_case.workflow_stage = "atomization"
    audit_case.status = "atomization"
    record_audit_event(
        db,
        case_id=audit_case.id,
        actor_id=actor_id,
        event_type="workflow_stage_changed",
        message="Этап аудита возвращен к атомизации",
        payload_json={
            "previous_workflow_stage": previous_stage,
            "workflow_stage": audit_case.workflow_stage,
            "previous_status": previous_status,
            "status": audit_case.status,
            "fields": [reason],
        },
    )


async def _get_atom_or_404(db: AsyncSession, case_id: UUID, atom_id: UUID) -> AuditAtom:
    result = await db.execute(
        select(AuditAtom)
        .where(AuditAtom.id == atom_id, AuditAtom.case_id == case_id)
        .with_for_update()
    )
    atom = result.scalar_one_or_none()
    if atom is None:
        raise HTTPException(status_code=404, detail="Атом аудита не найден")
    return atom


async def _load_atoms(db: AsyncSession, case_id: UUID) -> list[AuditAtom]:
    result = await db.execute(
        select(AuditAtom)
        .where(AuditAtom.case_id == case_id)
        .order_by(AuditAtom.sort_order.asc(), AuditAtom.item_code.asc())
    )
    return list(result.scalars().all())


async def _serialize_case(
    db: AsyncSession,
    audit_case: AuditCase,
    include_atoms: bool,
    counts: tuple[int, int, int, int, int, int, int] | None = None,
    responsible: tuple[str | None, str | None] | None = None,
    can_view_contract_reference: bool = False,
) -> AuditCaseRead:
    atoms = await _load_atoms(db, audit_case.id) if include_atoms else []
    if counts is None:
        counts = (
            len(atoms),
            sum(atom.state == "ready" for atom in atoms),
            sum(atom.state == "draft" for atom in atoms),
            sum(atom.state == "excluded" for atom in atoms),
            sum(atom.alpha_result == "present" for atom in atoms),
            sum(atom.commission_result == "confirmed" for atom in atoms),
            int(await db.scalar(select(func.count(AuditDocument.id)).where(AuditDocument.case_id == audit_case.id)) or 0),
        )
    atoms_count, ready_atoms_count, draft_atoms_count, excluded_atoms_count, alpha_passed_count, commission_passed_count, documents_count = counts
    if responsible is None and audit_case.responsible_user_id is not None:
        responsible = (
            await db.execute(
                select(User.full_name, User.email).where(User.id == audit_case.responsible_user_id)
            )
        ).one_or_none()
    responsible_name, responsible_email = responsible or (None, None)
    return AuditCaseRead(
        id=audit_case.id,
        case_number=audit_case.case_number,
        code=audit_case.code,
        created_by_id=audit_case.created_by_id,
        responsible_user_id=audit_case.responsible_user_id,
        responsible_name=responsible_name,
        responsible_email=responsible_email,
        title=audit_case.title,
        digital_product=audit_case.digital_product,
        contract_reference_mask=(
            audit_case.contract_reference_mask if can_view_contract_reference else None
        ),
        contract_reference_revealable=bool(
            can_view_contract_reference and audit_case.contract_reference_ciphertext
        ),
        contract_date=audit_case.contract_date,
        status=audit_case.status,
        workflow_stage=audit_case.workflow_stage,
        notes=audit_case.notes,
        atoms_count=atoms_count,
        ready_atoms_count=ready_atoms_count,
        draft_atoms_count=draft_atoms_count,
        excluded_atoms_count=excluded_atoms_count,
        alpha_passed_count=alpha_passed_count,
        commission_passed_count=commission_passed_count,
        documents_count=documents_count,
        atoms=[AuditAtomRead.model_validate(atom) for atom in atoms] if include_atoms else [],
        created_at=audit_case.created_at,
        updated_at=audit_case.updated_at,
    )


@router.get("/statistics", response_model=AuditStatisticsRead)
async def get_audit_statistics(
    days: int = Query(30, ge=7, le=366),
    _: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    date_from, date_to = statistics_period(days)
    case_rows = (
        await db.execute(
            select(AuditCase.id, AuditCase.status, AuditCase.workflow_stage)
        )
    ).all()
    atom_rows = (
        await db.execute(
            select(
                AuditAtom.id,
                AuditAtom.case_id,
                AuditAtom.state,
                AuditAtom.alpha_result,
                AuditAtom.commission_result,
                AuditAtom.created_at,
            )
        )
    ).all()
    event_rows = (
        await db.execute(
            select(AuditEvent.atom_id, AuditEvent.created_at, AuditEvent.payload_json)
            .where(
                AuditEvent.event_type == "atom_status_changed",
                AuditEvent.atom_id.is_not(None),
                AuditEvent.created_at >= period_start_utc(date_from),
            )
            .order_by(AuditEvent.created_at.asc(), AuditEvent.id.asc())
        )
    ).all()
    state_events = []
    for atom_id, created_at, payload in event_rows:
        previous_state = (payload or {}).get("previous_state")
        next_state = (payload or {}).get("state")
        if atom_id is None or previous_state not in {"draft", "ready", "excluded"}:
            continue
        if next_state not in {"draft", "ready", "excluded"}:
            continue
        state_events.append(
            AuditStatisticsStateEvent(
                atom_id=atom_id,
                created_at=created_at,
                previous_state=previous_state,
                state=next_state,
            )
        )
    return AuditStatisticsRead.model_validate(
        build_audit_statistics(
            [
                AuditStatisticsCaseRecord(
                    id=row.id,
                    status=row.status,
                    workflow_stage=row.workflow_stage,
                )
                for row in case_rows
            ],
            [
                AuditStatisticsAtomRecord(
                    id=row.id,
                    case_id=row.case_id,
                    state=row.state,
                    alpha_result=row.alpha_result,
                    commission_result=row.commission_result,
                    created_at=row.created_at,
                )
                for row in atom_rows
            ],
            state_events,
            period_start=date_from,
            period_end=date_to,
        )
    )


@router.get("/cases", response_model=list[AuditCaseRead])
async def list_audit_cases(
    status_filter: str = Query("all", alias="status"),
    search: str | None = Query(None, max_length=120),
    limit: int = Query(100, ge=1, le=300),
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    """Shared register visible to every user with audit access."""
    can_view_contract_reference = await _is_audit_team_member(user, db)
    atom_counts = (
        select(
            AuditAtom.case_id.label("case_id"),
            func.count(AuditAtom.id).label("atoms_count"),
            func.count(AuditAtom.id).filter(AuditAtom.state == "ready").label("ready_atoms_count"),
            func.count(AuditAtom.id).filter(AuditAtom.state == "draft").label("draft_atoms_count"),
            func.count(AuditAtom.id).filter(AuditAtom.state == "excluded").label("excluded_atoms_count"),
            func.count(AuditAtom.id).filter(AuditAtom.alpha_result == "present").label("alpha_passed_count"),
            func.count(AuditAtom.id).filter(AuditAtom.commission_result == "confirmed").label("commission_passed_count"),
        )
        .group_by(AuditAtom.case_id)
        .subquery()
    )
    document_counts = (
        select(
            AuditDocument.case_id.label("case_id"),
            func.count(AuditDocument.id).label("documents_count"),
        )
        .group_by(AuditDocument.case_id)
        .subquery()
    )
    responsible_user = aliased(User)
    query = select(
        AuditCase,
        func.coalesce(atom_counts.c.atoms_count, 0),
        func.coalesce(atom_counts.c.ready_atoms_count, 0),
        func.coalesce(atom_counts.c.draft_atoms_count, 0),
        func.coalesce(atom_counts.c.excluded_atoms_count, 0),
        func.coalesce(atom_counts.c.alpha_passed_count, 0),
        func.coalesce(atom_counts.c.commission_passed_count, 0),
        func.coalesce(document_counts.c.documents_count, 0),
        responsible_user.full_name,
        responsible_user.email,
    ).outerjoin(atom_counts, atom_counts.c.case_id == AuditCase.id).outerjoin(
        document_counts, document_counts.c.case_id == AuditCase.id
    ).outerjoin(responsible_user, responsible_user.id == AuditCase.responsible_user_id)
    if status_filter != "all":
        if status_filter not in CASE_STATUSES:
            raise HTTPException(status_code=400, detail="Некорректный статус аудита")
        query = query.where(AuditCase.status == status_filter)
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        search_fields = [
            AuditCase.title.ilike(pattern),
            AuditCase.digital_product.ilike(pattern),
        ]
        if can_view_contract_reference:
            search_fields.append(AuditCase.contract_reference_mask.ilike(pattern))
        query = query.where(or_(*search_fields))
    result = await db.execute(query.order_by(AuditCase.updated_at.desc()).limit(limit))
    return [
        await _serialize_case(
            db,
            audit_case,
            include_atoms=False,
            counts=(int(total), int(ready), int(draft), int(excluded), int(alpha), int(commission), int(documents)),
            responsible=(responsible_name, responsible_email),
            can_view_contract_reference=can_view_contract_reference,
        )
        for audit_case, total, ready, draft, excluded, alpha, commission, documents, responsible_name, responsible_email in result.all()
    ]


@router.post("/cases", response_model=AuditCaseRead, status_code=status.HTTP_201_CREATED)
async def create_audit_case(
    body: AuditCaseCreate,
    user: User = Depends(require_audit_manager),
    db: AsyncSession = Depends(get_db),
):
    if body.status == "ready":
        raise HTTPException(status_code=422, detail="Новый аудит нельзя создать сразу в статусе «Готово»")
    if body.workflow_stage != "unassigned":
        raise HTTPException(
            status_code=422,
            detail="Новый договор сначала создается без назначения",
        )
    can_view_contract_reference = await _is_audit_team_member(user, db)
    if body.contract_reference and not can_view_contract_reference:
        raise HTTPException(
            status_code=403,
            detail="Номер договора доступен только участникам команды аудита",
        )
    fingerprint, mask = build_contract_fields(body.contract_reference)
    contract_reference_ciphertext = None
    if body.contract_reference:
        try:
            contract_reference_ciphertext = encrypt_contract_reference(body.contract_reference)
        except AuditContractReferenceError as exc:
            raise HTTPException(status_code=503, detail=exc.message) from exc
    if fingerprint:
        existing = await db.execute(
            select(AuditCase.id).where(AuditCase.contract_reference_fingerprint == fingerprint)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="Для этого договора аудит уже существует")
    audit_case = AuditCase(
        created_by_id=user.id,
        title=body.title,
        digital_product=body.digital_product,
        contract_reference_fingerprint=fingerprint,
        contract_reference_mask=mask,
        contract_reference_ciphertext=contract_reference_ciphertext,
        contract_date=body.contract_date,
        status=body.status,
        workflow_stage=body.workflow_stage,
        notes=body.notes,
    )
    db.add(audit_case)
    await db.flush()
    await db.refresh(audit_case)
    record_audit_event(
        db,
        case_id=audit_case.id,
        actor_id=user.id,
        event_type="case_created",
        message="Создана карточка аудита",
        payload_json={"case_number": audit_case.case_number},
    )
    return await _serialize_case(
        db,
        audit_case,
        include_atoms=True,
        can_view_contract_reference=can_view_contract_reference,
    )


@router.get("/cases/{case_id}", response_model=AuditCaseRead)
async def get_audit_case(
    case_id: UUID,
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    return await _serialize_case(
        db,
        await _get_case_or_404(db, case_id),
        include_atoms=True,
        can_view_contract_reference=await _is_audit_team_member(user, db),
    )


@router.post(
    "/cases/{case_id}/contract-reference/reveal",
    response_model=AuditContractReferenceRead,
)
async def reveal_audit_contract_reference(
    case_id: UUID,
    response: Response,
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    if not await _is_audit_team_member(user, db):
        raise HTTPException(
            status_code=403,
            detail="Полный номер договора доступен только участникам команды аудита",
        )
    audit_case = await _get_case_or_404(db, case_id)
    try:
        contract_reference = decrypt_contract_reference(
            audit_case.contract_reference_ciphertext
        )
    except AuditContractReferenceError as exc:
        status_code = 503 if exc.code == "encryption_key_not_configured" else 409
        raise HTTPException(status_code=status_code, detail=exc.message) from exc
    record_audit_event(
        db,
        case_id=audit_case.id,
        actor_id=user.id,
        event_type="contract_reference_revealed",
        message="Просмотрен полный номер договора",
    )
    response.headers["Cache-Control"] = "no-store"
    return AuditContractReferenceRead(contract_reference=contract_reference)


@router.patch("/cases/{case_id}", response_model=AuditCaseRead)
async def update_audit_case(
    case_id: UUID,
    body: AuditCaseUpdate,
    user: User = Depends(require_audit_manager),
    db: AsyncSession = Depends(get_db),
):
    audit_case = await _get_case_or_404(db, case_id)
    changes = body.model_dump(exclude_unset=True)
    contract_reference_requested = "contract_reference" in changes
    contract_reference = changes.pop("contract_reference", None)
    can_view_contract_reference = await _is_audit_team_member(user, db)
    if contract_reference_requested and not can_view_contract_reference:
        raise HTTPException(
            status_code=403,
            detail="Номер договора доступен только участникам команды аудита",
        )
    previous_workflow_stage = audit_case.workflow_stage
    invalid_fields = sorted(field for field in REQUIRED_CASE_FIELDS if field in changes and changes[field] is None)
    if invalid_fields:
        raise HTTPException(
            status_code=422,
            detail=f"Обязательные поля нельзя очистить: {', '.join(invalid_fields)}",
        )
    workflow_stage_is_explicit = "workflow_stage" in changes
    if changes.get("status") == "ready" and not workflow_stage_is_explicit:
        changes["workflow_stage"] = "ready"
    target_workflow_stage = changes.get("workflow_stage", audit_case.workflow_stage)
    if target_workflow_stage not in AUDIT_WORKFLOW_STAGES:
        raise HTTPException(status_code=422, detail="Некорректный этап аудита")
    if target_workflow_stage != audit_case.workflow_stage:
        has_assignment = await db.scalar(
            select(AuditAssignment.id).where(AuditAssignment.case_id == case_id).limit(1)
        )
        if target_workflow_stage == "unassigned" and has_assignment is not None:
            raise HTTPException(
                status_code=409,
                detail="Сначала снимите назначение договора в календаре",
            )
        if target_workflow_stage != "unassigned" and has_assignment is None:
            raise HTTPException(
                status_code=422,
                detail="Сначала назначьте договор сотруднику и укажите дату",
            )
    if target_workflow_stage == "ready":
        atom_counts = (
            await db.execute(
                select(
                    func.count(AuditAtom.id),
                    func.count(AuditAtom.id).filter(
                        AuditAtom.state.notin_(["ready", "excluded"])
                    ),
                ).where(AuditAtom.case_id == case_id)
            )
        ).one()
        if int(atom_counts[0]) == 0 or int(atom_counts[1]) > 0:
            raise HTTPException(
                status_code=422,
                detail="Аудит можно отметить готовым только после разметки всех атомов",
            )
        if changes.get("status") != "archived":
            changes["status"] = "ready"
    elif changes.get("status") == "ready" or (
        audit_case.status == "ready" and changes.get("status") != "archived"
    ):
        changes["status"] = "atomization"
    changed_fields = list(changes)
    if contract_reference:
        fingerprint, mask = build_contract_fields(contract_reference)
        duplicate = await db.execute(
            select(AuditCase.id).where(
                AuditCase.contract_reference_fingerprint == fingerprint,
                AuditCase.id != audit_case.id,
            )
        )
        if duplicate.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="Для этого договора аудит уже существует")
        audit_case.contract_reference_fingerprint = fingerprint
        audit_case.contract_reference_mask = mask
        try:
            audit_case.contract_reference_ciphertext = encrypt_contract_reference(
                contract_reference
            )
        except AuditContractReferenceError as exc:
            raise HTTPException(status_code=503, detail=exc.message) from exc
        changed_fields.append("contract_reference")
    for field, value in changes.items():
        setattr(audit_case, field, value)
    await db.flush()
    await db.refresh(audit_case)
    if changed_fields:
        record_audit_event(
            db,
            case_id=audit_case.id,
            actor_id=user.id,
            event_type="case_updated",
            message="Параметры аудита изменены",
            payload_json={"fields": changed_fields},
        )
    if audit_case.workflow_stage != previous_workflow_stage:
        record_audit_event(
            db,
            case_id=audit_case.id,
            actor_id=user.id,
            event_type="workflow_stage_changed",
            message=f"Этап аудита: {audit_case.workflow_stage}",
            payload_json={
                "previous_workflow_stage": previous_workflow_stage,
                "workflow_stage": audit_case.workflow_stage,
            },
        )
    return await _serialize_case(
        db,
        audit_case,
        include_atoms=True,
        can_view_contract_reference=can_view_contract_reference,
    )


@router.delete("/cases/{case_id}", response_model=AuditCaseDeleteResponse)
async def delete_audit_case(
    case_id: UUID,
    body: AuditCaseDeleteRequest,
    manager: User = Depends(require_audit_manager),
    db: AsyncSession = Depends(get_db),
):
    audit_case = await db.scalar(
        select(AuditCase).where(AuditCase.id == case_id).with_for_update()
    )
    if audit_case is None:
        raise HTTPException(status_code=404, detail="Аудит не найден")
    if audit_case.status != "archived":
        raise HTTPException(
            status_code=409,
            detail="Сначала перенесите договор в архив. Рабочий договор удалить нельзя.",
        )
    if body.confirmation_code != audit_case.case_number.upper():
        raise HTTPException(
            status_code=422,
            detail=f"Для подтверждения введите код {audit_case.case_number}",
        )

    active_runtime_job = await db.scalar(
        select(AuditTZRuntimeJob.id)
        .join(AuditTZRun, AuditTZRuntimeJob.run_id == AuditTZRun.id)
        .where(
            AuditTZRun.case_id == case_id,
            AuditTZRuntimeJob.status.in_(["queued", "running"]),
        )
        .with_for_update()
        .limit(1)
    )
    active_ai_attempt = await db.scalar(
        select(AuditAIAtomizationAttempt.id)
        .where(
            AuditAIAtomizationAttempt.case_id == case_id,
            AuditAIAtomizationAttempt.status == "running",
        )
        .with_for_update()
        .limit(1)
    )
    if active_runtime_job is not None or active_ai_attempt is not None:
        raise HTTPException(
            status_code=409,
            detail="Дождитесь завершения текущей проверки или атомизации, затем повторите удаление.",
        )

    documents = list(
        await db.scalars(select(AuditDocument).where(AuditDocument.case_id == case_id))
    )
    atoms_count = int(
        await db.scalar(select(func.count(AuditAtom.id)).where(AuditAtom.case_id == case_id)) or 0
    )
    case_number = audit_case.case_number
    await record_activity_event(
        db,
        manager.id,
        "audit_case_deleted",
        metadata={
            "audit_case_id": str(case_id),
            "case_number": case_number,
            "documents_count": len(documents),
            "atoms_count": atoms_count,
            "reason": body.reason,
        },
    )
    await db.execute(delete(AuditCase).where(AuditCase.id == case_id))
    await db.commit()

    remove_audit_case_files(case_id, [document.stored_filename for document in documents])
    return AuditCaseDeleteResponse(
        id=case_id,
        case_number=case_number,
        deleted_documents_count=len(documents),
        deleted_atoms_count=atoms_count,
    )


@router.post("/cases/{case_id}/atoms", response_model=AuditAtomRead, status_code=status.HTTP_201_CREATED)
async def create_audit_atom(
    case_id: UUID,
    body: AuditAtomCreate,
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    audit_case = await _get_case_or_404(db, case_id, for_update=True)
    await _ensure_case_atom_editor(audit_case, user, db)
    if body.alpha_result is not None or body.alpha_date is not None or body.alpha_comment is not None:
        raise HTTPException(
            status_code=422,
            detail="Сначала добавьте и примите атом, затем зафиксируйте результат альфа-проверки",
        )
    item_code = body.item_code or await generate_next_item_code(db, case_id)
    duplicate = await db.execute(
        select(AuditAtom.id).where(AuditAtom.case_id == case_id, AuditAtom.item_code == item_code)
    )
    if duplicate.scalar_one_or_none() is not None:
        raise HTTPException(status_code=409, detail="Код атома уже используется в этом аудите")
    atom_data = body.model_dump(exclude={"item_code"})
    atom_data["system_url"] = _validated_url(atom_data.get("system_url"))
    atom = AuditAtom(case_id=case_id, item_code=item_code, **atom_data)
    db.add(atom)
    if audit_case.status in {"draft", "ready"}:
        audit_case.status = "atomization"
    _return_case_to_atomization(db, audit_case, user.id, reason="atom_created")
    await db.flush()
    await db.refresh(atom)
    record_audit_event(
        db,
        case_id=case_id,
        atom_id=atom.id,
        actor_id=user.id,
        event_type="atom_created",
        message=f"Добавлен атом {atom.item_code}",
        payload_json={"item_code": atom.item_code, "title": atom.title},
    )
    return AuditAtomRead.model_validate(atom)


@router.patch(
    "/cases/{case_id}/atoms/bulk-status",
    response_model=AuditAtomBulkStatusRead,
)
async def bulk_update_audit_atom_status(
    case_id: UUID,
    body: AuditAtomBulkStatusUpdate,
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    audit_case = await _get_case_or_404(db, case_id, for_update=True)
    await _ensure_case_atom_editor(audit_case, user, db)
    atoms = list(
        (
            await db.scalars(
                select(AuditAtom)
                .where(
                    AuditAtom.case_id == case_id,
                    AuditAtom.id.in_(body.atom_ids),
                )
                .with_for_update()
            )
        ).all()
    )
    if len(atoms) != len(body.atom_ids):
        raise HTTPException(status_code=422, detail="Один из выбранных атомов не найден в этом аудите")
    for atom in atoms:
        _ensure_atom_version(atom, body.expected_updated_at_by_atom[atom.id])
    changed_atoms = [atom for atom in atoms if atom.state != body.state]
    for atom in changed_atoms:
        previous_state = atom.state
        atom.state = body.state
        if body.state != "ready":
            atom.alpha_result = None
            atom.alpha_comment = None
            atom.alpha_date = None
            atom.commission_result = None
            atom.commission_date = None
        record_audit_event(
            db,
            case_id=case_id,
            atom_id=atom.id,
            actor_id=user.id,
            event_type="atom_status_changed",
            message=f"Статус атома {atom.item_code}: {previous_state} -> {body.state}",
            payload_json={
                "item_code": atom.item_code,
                "fields": ["state"],
                "previous_state": previous_state,
                "state": body.state,
            },
        )
    if changed_atoms:
        _return_case_to_atomization(db, audit_case, user.id, reason="atom_bulk_state_changed")
    record_audit_event(
        db,
        case_id=case_id,
        actor_id=user.id,
        event_type="atoms_bulk_status_changed",
        message=f"Для {len(changed_atoms)} атомов установлен статус {body.state}",
        payload_json={"atom_count": len(changed_atoms), "fields": ["state"]},
    )
    await db.flush()
    return AuditAtomBulkStatusRead(
        case_id=case_id,
        state=body.state,
        updated_count=len(changed_atoms),
        atom_ids=[atom.id for atom in changed_atoms],
    )


@router.get("/cases/{case_id}/atoms/export")
async def export_audit_atoms(
    case_id: UUID,
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    if user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Экспорт генерального реестра доступен только администратору")
    audit_case = await _get_case_or_404(db, case_id)
    atoms = list(
        (
            await db.scalars(
                select(AuditAtom)
                .where(AuditAtom.case_id == case_id)
                .order_by(AuditAtom.sort_order.asc(), AuditAtom.item_code.asc())
            )
        ).all()
    )
    if not atoms:
        raise HTTPException(status_code=409, detail="В этом аудите еще нет атомов для экспорта")
    content = build_audit_atom_export(audit_case, atoms)
    record_audit_event(
        db,
        case_id=case_id,
        actor_id=user.id,
        event_type="atoms_exported",
        message="Администратор выгрузил генеральный реестр атомов",
        payload_json={"atom_count": len(atoms)},
    )
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{audit_case.case_number}-general-atoms.xlsx"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/cases/{case_id}/alpha-review/start", response_model=AuditCaseRead)
async def start_audit_alpha_review(
    case_id: UUID,
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    audit_case = await db.scalar(
        select(AuditCase).where(AuditCase.id == case_id).with_for_update()
    )
    if audit_case is None:
        raise HTTPException(status_code=404, detail="Аудит не найден")
    await _ensure_case_atom_editor(audit_case, user, db)
    if audit_case.responsible_user_id is None:
        raise HTTPException(
            status_code=409,
            detail="Сначала назначьте ответственного за аудит",
        )
    if audit_case.workflow_stage == "alpha_review":
        return await _serialize_case(
            db,
            audit_case,
            include_atoms=True,
            can_view_contract_reference=await _is_audit_team_member(user, db),
        )
    if audit_case.workflow_stage != "atomization":
        raise HTTPException(
            status_code=409,
            detail="Альфа-проверку можно начать только после этапа атомизации",
        )
    total_atoms, draft_atoms, ready_atoms = (
        await db.execute(
            select(
                func.count(AuditAtom.id),
                func.count(AuditAtom.id).filter(AuditAtom.state == "draft"),
                func.count(AuditAtom.id).filter(AuditAtom.state == "ready"),
            ).where(AuditAtom.case_id == case_id)
        )
    ).one()
    if int(total_atoms) == 0:
        raise HTTPException(status_code=409, detail="Сначала сформируйте реестр атомов")
    if int(draft_atoms) > 0:
        raise HTTPException(
            status_code=409,
            detail=f"Сначала проверьте все черновики атомов: осталось {int(draft_atoms)}",
        )
    if int(ready_atoms) == 0:
        raise HTTPException(
            status_code=409,
            detail="Для альфа-проверки нужен хотя бы один принятый атом",
        )
    previous_stage = audit_case.workflow_stage
    audit_case.workflow_stage = "alpha_review"
    audit_case.status = "atomization"
    record_audit_event(
        db,
        case_id=case_id,
        actor_id=user.id,
        event_type="alpha_review_started",
        message="Начата альфа-проверка атомов",
        payload_json={
            "previous_workflow_stage": previous_stage,
            "workflow_stage": audit_case.workflow_stage,
            "atom_count": int(ready_atoms),
        },
    )
    await db.flush()
    return await _serialize_case(
        db,
        audit_case,
        include_atoms=True,
        can_view_contract_reference=await _is_audit_team_member(user, db),
    )


@router.patch("/cases/{case_id}/atoms/{atom_id}", response_model=AuditAtomRead)
async def update_audit_atom(
    case_id: UUID,
    atom_id: UUID,
    body: AuditAtomUpdate,
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    audit_case = await _get_case_or_404(db, case_id, for_update=True)
    await _ensure_case_atom_editor(audit_case, user, db)
    atom = await _get_atom_or_404(db, case_id, atom_id)
    changes = body.model_dump(exclude_unset=True)
    expected_updated_at = changes.pop("expected_updated_at")
    _ensure_atom_version(atom, expected_updated_at)
    invalid_fields = sorted(field for field in REQUIRED_ATOM_FIELDS if field in changes and changes[field] is None)
    if invalid_fields:
        raise HTTPException(
            status_code=422,
            detail=f"Обязательные поля нельзя очистить: {', '.join(invalid_fields)}",
        )
    if "system_url" in changes:
        changes["system_url"] = _validated_url(changes["system_url"])
    if changes.get("item_code") and changes["item_code"] != atom.item_code:
        duplicate = await db.execute(
            select(AuditAtom.id).where(
                AuditAtom.case_id == case_id,
                AuditAtom.item_code == changes["item_code"],
                AuditAtom.id != atom.id,
            )
        )
        if duplicate.scalar_one_or_none() is not None:
            raise HTTPException(status_code=409, detail="Код атома уже используется в этом аудите")
    changes = {
        field: value
        for field, value in changes.items()
        if getattr(atom, field) != value
    }
    scope_changed = bool(ATOM_SCOPE_FIELDS.intersection(changes))
    alpha_fields_changed = bool({"alpha_result", "alpha_comment", "alpha_date"}.intersection(changes))
    if scope_changed and changes.get("alpha_result") is not None:
        raise HTTPException(
            status_code=422,
            detail="Сначала сохраните изменение атома и повторно пройдите его проверку",
        )
    if scope_changed:
        for field in (
            "alpha_result",
            "alpha_comment",
            "alpha_date",
            "commission_result",
            "commission_date",
        ):
            if getattr(atom, field) is not None:
                changes[field] = None
        _return_case_to_atomization(db, audit_case, user.id, reason="atom_scope_changed")

    if alpha_fields_changed:
        next_result = changes.get("alpha_result", atom.alpha_result)
        next_comment = changes.get("alpha_comment", atom.alpha_comment)
        next_date = changes.get("alpha_date", atom.alpha_date)
        next_state = changes.get("state", atom.state)
        if next_result is None:
            changes["alpha_comment"] = None
            changes["alpha_date"] = None
        else:
            if audit_case.workflow_stage != "alpha_review":
                raise HTTPException(
                    status_code=409,
                    detail="Результат можно фиксировать только после запуска альфа-проверки",
                )
            if next_state != "ready":
                raise HTTPException(
                    status_code=422,
                    detail="Альфа-проверка доступна только для принятых атомов",
                )
            if next_date is None:
                raise HTTPException(status_code=422, detail="Укажите дату альфа-проверки")
            if next_result in ALPHA_COMMENT_REQUIRED_RESULTS and not next_comment:
                raise HTTPException(
                    status_code=422,
                    detail="Для этого результата обязателен комментарий",
                )
    previous_state = atom.state
    previous_alpha_result = atom.alpha_result
    previous_alpha_comment = atom.alpha_comment
    for field, value in changes.items():
        setattr(atom, field, value)
    await db.flush()
    await db.refresh(atom)
    if changes:
        if atom.state != previous_state:
            event_type = "atom_status_changed"
            message = f"Статус атома {atom.item_code}: {previous_state} -> {atom.state}"
        elif atom.alpha_result != previous_alpha_result:
            event_type = "atom_alpha_decision_changed"
            message = f"Результат альфа-проверки атома {atom.item_code}: {atom.alpha_result or 'не задан'}"
        else:
            event_type = "atom_updated"
            message = f"Изменен атом {atom.item_code}"
        record_audit_event(
            db,
            case_id=case_id,
            atom_id=atom.id,
            actor_id=user.id,
            event_type=event_type,
            message=message,
            payload_json={
                "item_code": atom.item_code,
                "fields": list(changes),
                "previous_state": previous_state,
                "state": atom.state,
                "previous_alpha_result": previous_alpha_result,
                "alpha_result": atom.alpha_result,
                "previous_alpha_comment": previous_alpha_comment,
                "alpha_comment": atom.alpha_comment,
                "alpha_date": atom.alpha_date.isoformat() if atom.alpha_date else None,
            },
        )
    return AuditAtomRead.model_validate(atom)


@router.get("/cases/{case_id}/events", response_model=list[AuditEventRead])
async def list_audit_events(
    case_id: UUID,
    _: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    await _get_case_or_404(db, case_id)
    result = await db.execute(
        select(AuditEvent, User.full_name)
        .outerjoin(User, User.id == AuditEvent.actor_id)
        .where(AuditEvent.case_id == case_id)
        .order_by(AuditEvent.created_at.desc())
        .limit(500)
    )
    return [
        AuditEventRead(
            id=event.id,
            case_id=event.case_id,
            atom_id=event.atom_id,
            import_batch_id=event.import_batch_id,
            actor_id=event.actor_id,
            actor_name=actor_name,
            event_type=event.event_type,
            message=event.message,
            payload_json={
                key: value
                for key, value in (event.payload_json or {}).items()
                if key in SAFE_EVENT_PAYLOAD_FIELDS
            } or None,
            created_at=event.created_at,
        )
        for event, actor_name in result.all()
    ]


def _team_member_read(member: AuditTeamMember, user: User) -> AuditTeamMemberRead:
    return AuditTeamMemberRead(
        id=member.id,
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        role=member.role,
        is_active=user.is_active,
        audit_enabled=user.audit_enabled or user.role == UserRole.admin,
        added_by_id=member.added_by_id,
        created_at=member.created_at,
    )


def _document_read(document: AuditDocument, uploaded_by_name: str | None = None) -> AuditDocumentRead:
    return AuditDocumentRead(
        id=document.id,
        case_id=document.case_id,
        uploaded_by_id=document.uploaded_by_id,
        uploaded_by_name=uploaded_by_name,
        kind=document.kind,
        display_name=document.display_name,
        original_filename=document.original_filename,
        content_type=document.content_type,
        size_bytes=document.size_bytes,
        sha256=document.sha256,
        created_at=document.created_at,
    )


def _ai_request_hash(namespace: str, user_id: UUID, request_id: UUID) -> str:
    return sha256(f"{namespace}:{user_id}:{request_id}".encode("utf-8")).hexdigest()


def _active_skill_read(
    skill: AuditAtomizationSkill,
    version: AuditAtomizationSkillVersion,
) -> AuditAtomizationSkillVersionRead:
    return AuditAtomizationSkillVersionRead(
        id=version.id,
        skill_id=skill.id,
        slug=skill.slug,
        name=skill.name,
        description=skill.description,
        version=version.version_label,
        schema_version=version.schema_version,
        content_sha256=version.content_sha256,
        source_filename=version.source_filename,
        package_format=version.package_format,
        package_manifest=dict(version.package_manifest_json or {}),
        runtime_status=version.runtime_status,
        runtime_ready=version.runtime_status == "ready",
        runtime_checked_at=version.runtime_checked_at,
        runtime_error_code=version.runtime_error_code,
        runtime_selftest=dict(version.runtime_selftest_json or {}),
        is_trusted_archive=version.package_format == "trusted_skill_archive",
        is_enabled=skill.is_enabled,
        is_active=version.is_active,
        created_at=version.created_at,
        activated_at=version.activated_at,
    )


def _assignment_read(
    assignment: AuditAssignment,
    audit_case: AuditCase,
    assignee: User,
    atoms_count: int = 0,
) -> AuditAssignmentRead:
    return AuditAssignmentRead(
        id=assignment.id,
        case_id=audit_case.id,
        case_number=audit_case.case_number,
        case_title=audit_case.title,
        digital_product=audit_case.digital_product,
        case_status=audit_case.status,
        workflow_stage=audit_case.workflow_stage,
        atoms_count=atoms_count,
        assignee_id=assignee.id,
        assignee_name=assignee.full_name,
        scheduled_date=assignment.scheduled_date,
        assigned_by_id=assignment.assigned_by_id,
        created_at=assignment.created_at,
        updated_at=assignment.updated_at,
    )


def _assignment_query():
    atom_counts = (
        select(
            AuditAtom.case_id.label("case_id"),
            func.count(AuditAtom.id).label("atoms_count"),
        )
        .group_by(AuditAtom.case_id)
        .subquery()
    )
    return (
        select(
            AuditAssignment,
            AuditCase,
            User,
            func.coalesce(atom_counts.c.atoms_count, 0),
        )
        .join(AuditCase, AuditCase.id == AuditAssignment.case_id)
        .join(User, User.id == AuditAssignment.assignee_id)
        .outerjoin(atom_counts, atom_counts.c.case_id == AuditAssignment.case_id)
    )


async def _serialize_ai_attempt(
    db: AsyncSession,
    attempt_id: UUID,
) -> AuditAIAtomizationAttemptRead:
    row = (
        await db.execute(
            select(
                AuditAIAtomizationAttempt,
                AuditAtomizationSkill,
                AuditAtomizationSkillVersion,
                AIProviderConfig,
            )
            .join(
                AuditAtomizationSkillVersion,
                AuditAtomizationSkillVersion.id == AuditAIAtomizationAttempt.skill_version_id,
            )
            .join(
                AuditAtomizationSkill,
                AuditAtomizationSkill.id == AuditAtomizationSkillVersion.skill_id,
            )
            .join(
                AIProviderConfig,
                AIProviderConfig.id == AuditAIAtomizationAttempt.provider_config_id,
            )
            .where(AuditAIAtomizationAttempt.id == attempt_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Черновик ИИ-атомизации не найден")
    attempt, skill, version, provider = row
    drafts = list(
        (
            await db.scalars(
                select(AuditAIAtomDraft)
                .where(AuditAIAtomDraft.attempt_id == attempt.id)
                .order_by(AuditAIAtomDraft.sort_order.asc(), AuditAIAtomDraft.id.asc())
            )
        ).all()
    )
    return AuditAIAtomizationAttemptRead(
        id=attempt.id,
        case_id=attempt.case_id,
        document_id=attempt.document_id,
        skill_version_id=attempt.skill_version_id,
        skill_name=skill.name,
        skill_version=version.version_label,
        status=attempt.status,
        config_version=attempt.config_version,
        provider_config_id=attempt.provider_config_id,
        provider_name=provider.display_name,
        model_name=attempt.model_name,
        document_sha256=attempt.document_sha256,
        skill_sha256=attempt.skill_sha256,
        coverage_summary={
            str(key): int(value)
            for key, value in (attempt.coverage_json or {}).items()
            if isinstance(value, int)
        },
        warnings=[str(item)[:500] for item in (attempt.warnings_json or []) if isinstance(item, str)],
        error_code=attempt.error_code,
        drafts=[
            AuditAIAtomDraftRead(
                id=draft.id,
                title=draft.title,
                digital_product=draft.digital_product,
                work_type=draft.work_type,
                object_type=draft.object_type,
                source_clause=draft.source_clause,
                notes=draft.notes,
                confidence_percent=draft.confidence_percent,
                review_status=draft.review_status,
                sort_order=draft.sort_order,
                source_refs=[
                    AuditAISourceRefRead(
                        source_unit_id=str(ref.get("source_unit_id", ""))[:40],
                        locator=str(ref.get("locator", ""))[:500],
                        excerpt=str(ref.get("excerpt", ""))[:600],
                    )
                    for ref in (draft.source_refs_json or [])
                    if isinstance(ref, dict)
                    and ref.get("source_unit_id")
                    and ref.get("locator")
                ],
            )
            for draft in drafts
        ],
        created_at=attempt.created_at,
        committed_at=attempt.committed_at,
    )


@router.get("/ai-atomization/skills", response_model=AuditAtomizationSkillList)
async def list_active_audit_atomization_skills(
    _: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(AuditAtomizationSkill, AuditAtomizationSkillVersion)
            .join(
                AuditAtomizationSkillVersion,
                AuditAtomizationSkillVersion.skill_id == AuditAtomizationSkill.id,
            )
            .where(
                AuditAtomizationSkill.is_enabled.is_(True),
                AuditAtomizationSkillVersion.is_active.is_(True),
                AuditAtomizationSkillVersion.runtime_status == "ready",
            )
            .order_by(AuditAtomizationSkill.name.asc())
        )
    ).all()
    return AuditAtomizationSkillList(items=[_active_skill_read(skill, version) for skill, version in rows])


@router.get("/assignments", response_model=AuditAssignmentListRead)
async def list_audit_assignments(
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    _: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    range_start = date_from or date.today()
    range_end = date_to or (range_start + timedelta(days=13))
    if range_end < range_start:
        raise HTTPException(status_code=422, detail="Дата окончания периода раньше даты начала")
    if (range_end - range_start).days > 91:
        raise HTTPException(status_code=422, detail="За один запрос доступно не более 92 дней")
    rows = (
        await db.execute(
            _assignment_query()
            .where(
                AuditAssignment.scheduled_date >= range_start,
                AuditAssignment.scheduled_date <= range_end,
            )
            .order_by(
                AuditAssignment.scheduled_date.asc(),
                User.full_name.asc(),
                AuditCase.case_sequence.asc(),
            )
        )
    ).all()
    return AuditAssignmentListRead(
        date_from=range_start,
        date_to=range_end,
        items=[
            _assignment_read(assignment, audit_case, assignee, int(atoms_count))
            for assignment, audit_case, assignee, atoms_count in rows
        ],
    )


@router.get("/assignments/index", response_model=list[AuditAssignmentRead])
async def list_audit_assignment_index(
    _: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    """Return the single active assignment for every contract."""
    rows = (
        await db.execute(
            _assignment_query().order_by(AuditCase.case_sequence.asc())
        )
    ).all()
    return [
        _assignment_read(assignment, audit_case, assignee, int(atoms_count))
        for assignment, audit_case, assignee, atoms_count in rows
    ]


@router.put("/assignments/cell", response_model=AuditAssignmentListRead)
async def replace_audit_assignment_cell(
    body: AuditAssignmentCellUpdate,
    manager: User = Depends(require_audit_manager),
    db: AsyncSession = Depends(get_db),
):
    assignee_row = (
        await db.execute(
            select(AuditTeamMember, User)
            .join(User, User.id == AuditTeamMember.user_id)
            .where(
                AuditTeamMember.user_id == body.assignee_id,
                User.is_active.is_(True),
            )
        )
    ).one_or_none()
    if assignee_row is None:
        raise HTTPException(status_code=422, detail="Исполнитель не входит в активную команду аудита")
    _, assignee = assignee_row

    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
        {
            "scope": (
                f"audit-assignment-cell:{body.scheduled_date.isoformat()}:"
                f"{body.assignee_id}"
            )
        },
    )

    current = list(
        (
            await db.scalars(
                select(AuditAssignment)
                .where(
                    AuditAssignment.assignee_id == body.assignee_id,
                    AuditAssignment.scheduled_date == body.scheduled_date,
                )
                .order_by(AuditAssignment.case_id.asc())
                .with_for_update()
            )
        ).all()
    )
    current_ids = {assignment.case_id for assignment in current}
    if current_ids != set(body.expected_case_ids):
        raise HTTPException(
            status_code=409,
            detail="Назначения в этой ячейке уже изменились; обновите матрицу",
        )

    requested_ids = set(body.case_ids)
    transfer_ids = set(body.transfer_case_ids)
    scoped_ids = requested_ids | current_ids
    cases_by_id: dict[UUID, AuditCase] = {}
    if scoped_ids:
        scoped_cases = list(
            (
                await db.scalars(
                    select(AuditCase)
                    .where(AuditCase.id.in_(scoped_ids))
                    .order_by(AuditCase.id.asc())
                    .with_for_update()
                )
            ).all()
        )
        cases_by_id = {audit_case.id: audit_case for audit_case in scoped_cases}
        if set(cases_by_id) != scoped_ids:
            raise HTTPException(status_code=422, detail="Один или несколько договоров не найдены")
        if any(cases_by_id[case_id].status == "archived" for case_id in requested_ids):
            raise HTTPException(status_code=422, detail="Архивный договор нельзя добавить в новое назначение")

    existing_assignments = list(
        (
            await db.scalars(
                select(AuditAssignment)
                .where(AuditAssignment.case_id.in_(scoped_ids))
                .order_by(AuditAssignment.case_id.asc())
                .with_for_update()
            )
        ).all()
    ) if scoped_ids else []
    existing_by_case = {assignment.case_id: assignment for assignment in existing_assignments}
    assigned_elsewhere_ids = {
        case_id
        for case_id in requested_ids
        if (assignment := existing_by_case.get(case_id)) is not None
        and (
            assignment.assignee_id != body.assignee_id
            or assignment.scheduled_date != body.scheduled_date
        )
    }
    unconfirmed_transfers = assigned_elsewhere_ids - transfer_ids
    if unconfirmed_transfers:
        case_number = cases_by_id[next(iter(unconfirmed_transfers))].case_number
        raise HTTPException(
            status_code=409,
            detail=f"{case_number} уже назначен. Подтвердите передачу договора в выбранную ячейку",
        )
    stale_transfers = transfer_ids - assigned_elsewhere_ids
    if stale_transfers:
        raise HTTPException(
            status_code=409,
            detail="Назначение передаваемого договора уже изменилось; обновите матрицу",
        )

    current_by_case = {assignment.case_id: assignment for assignment in current}
    removed_ids = current_ids - requested_ids
    added_ids = requested_ids - current_ids
    for case_id in removed_ids:
        assignment = current_by_case[case_id]
        audit_case = cases_by_id[case_id]
        await db.delete(assignment)
        record_audit_event(
            db,
            case_id=case_id,
            actor_id=manager.id,
            event_type="assignment_removed",
            message=f"Снято назначение на {body.scheduled_date.strftime('%d.%m.%Y')}",
            payload_json={
                "assignee_id": str(body.assignee_id),
                "scheduled_date": body.scheduled_date.isoformat(),
            },
        )
        if audit_case.workflow_stage not in {"ready"}:
            previous_stage = audit_case.workflow_stage
            audit_case.workflow_stage = "unassigned"
            if previous_stage != audit_case.workflow_stage:
                record_audit_event(
                    db,
                    case_id=case_id,
                    actor_id=manager.id,
                    event_type="workflow_stage_changed",
                    message="Этап аудита: договор не назначен",
                    payload_json={
                        "previous_workflow_stage": previous_stage,
                        "workflow_stage": audit_case.workflow_stage,
                    },
                )
        if audit_case.responsible_user_id == body.assignee_id:
            audit_case.responsible_user_id = None
            record_audit_event(
                db,
                case_id=case_id,
                actor_id=manager.id,
                event_type="responsible_changed",
                message="Ответственный снят вместе с календарным назначением",
                payload_json={
                    "previous_responsible_user_id": str(body.assignee_id),
                    "responsible_user_id": None,
                    "scheduled_date": body.scheduled_date.isoformat(),
                },
            )
    for case_id in added_ids:
        audit_case = cases_by_id[case_id]
        existing_assignment = existing_by_case.get(case_id)
        if existing_assignment is not None:
            previous_assignee_id = existing_assignment.assignee_id
            previous_scheduled_date = existing_assignment.scheduled_date
            existing_assignment.assignee_id = body.assignee_id
            existing_assignment.scheduled_date = body.scheduled_date
            existing_assignment.assigned_by_id = manager.id
            assignment_event_type = "assignment_transferred"
            assignment_message = (
                f"Договор передан {assignee.full_name} "
                f"на {body.scheduled_date.strftime('%d.%m.%Y')}"
            )
            assignment_payload = {
                "previous_assignee_id": str(previous_assignee_id),
                "previous_scheduled_date": previous_scheduled_date.isoformat(),
                "assignee_id": str(body.assignee_id),
                "scheduled_date": body.scheduled_date.isoformat(),
            }
        else:
            db.add(AuditAssignment(
                case_id=case_id,
                assignee_id=body.assignee_id,
                scheduled_date=body.scheduled_date,
                assigned_by_id=manager.id,
            ))
            assignment_event_type = "assignment_created"
            assignment_message = (
                f"Назначено {assignee.full_name} "
                f"на {body.scheduled_date.strftime('%d.%m.%Y')}"
            )
            assignment_payload = {
                "assignee_id": str(body.assignee_id),
                "scheduled_date": body.scheduled_date.isoformat(),
            }
        record_audit_event(
            db,
            case_id=case_id,
            actor_id=manager.id,
            event_type=assignment_event_type,
            message=assignment_message,
            payload_json=assignment_payload,
        )
        _activate_case_for_assignment(db, audit_case, manager.id)
        previous_user_id = audit_case.responsible_user_id
        if previous_user_id != body.assignee_id:
            audit_case.responsible_user_id = body.assignee_id
            record_audit_event(
                db,
                case_id=case_id,
                actor_id=manager.id,
                event_type="responsible_changed",
                message=(
                    f"Ответственный: {assignee.full_name} "
                    f"(назначение на {body.scheduled_date.strftime('%d.%m.%Y')})"
                ),
                payload_json={
                    "previous_responsible_user_id": str(previous_user_id) if previous_user_id else None,
                    "responsible_user_id": str(body.assignee_id),
                    "assignee_id": str(body.assignee_id),
                    "scheduled_date": body.scheduled_date.isoformat(),
                },
            )
    try:
        await db.flush()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(
            status_code=409,
            detail="Договор уже назначен другому сотруднику; обновите матрицу",
        ) from error

    rows = (
        await db.execute(
            _assignment_query()
            .where(
                AuditAssignment.assignee_id == body.assignee_id,
                AuditAssignment.scheduled_date == body.scheduled_date,
            )
            .order_by(AuditCase.case_sequence.asc())
        )
    ).all()
    return AuditAssignmentListRead(
        date_from=body.scheduled_date,
        date_to=body.scheduled_date,
        items=[
            _assignment_read(assignment, audit_case, user, int(atoms_count))
            for assignment, audit_case, user, atoms_count in rows
        ],
    )


@router.get("/team", response_model=list[AuditTeamMemberRead])
async def list_audit_team(
    _: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(AuditTeamMember, User)
        .join(User, User.id == AuditTeamMember.user_id)
        .order_by(AuditTeamMember.role.asc(), User.full_name.asc())
    )
    return [_team_member_read(member, user) for member, user in result.all()]


@router.get("/team/candidates", response_model=list[AuditTeamCandidateRead])
async def list_audit_team_candidates(
    manager: User = Depends(require_audit_manager),
    db: AsyncSession = Depends(get_db),
):
    contact_rows = await db.execute(
        select(Contact.requester_id, Contact.recipient_id).where(
            Contact.status == "accepted",
            or_(Contact.requester_id == manager.id, Contact.recipient_id == manager.id),
        )
    )
    candidate_ids = {manager.id}
    for requester_id, recipient_id in contact_rows.all():
        candidate_ids.add(recipient_id if requester_id == manager.id else requester_id)
    existing_ids = set(
        (await db.scalars(select(AuditTeamMember.user_id))).all()
    )
    candidate_ids.difference_update(existing_ids)
    if not candidate_ids:
        return []
    users = (
        await db.scalars(
            select(User)
            .where(User.id.in_(candidate_ids), User.is_active.is_(True))
            .order_by(User.full_name.asc())
        )
    ).all()
    return [
        AuditTeamCandidateRead(
            user_id=user.id,
            full_name=user.full_name,
            email=user.email,
            is_active=user.is_active,
            audit_enabled=user.audit_enabled or user.role == UserRole.admin,
        )
        for user in users
        if user.audit_enabled or user.role == UserRole.admin
    ]


@router.post("/team", response_model=AuditTeamMemberRead, status_code=status.HTTP_201_CREATED)
async def add_audit_team_member(
    body: AuditTeamMemberCreate,
    manager: User = Depends(require_audit_manager),
    db: AsyncSession = Depends(get_db),
):
    target = await db.scalar(select(User).where(User.id == body.user_id))
    if target is None or not target.is_active:
        raise HTTPException(status_code=404, detail="Сотрудник не найден или деактивирован")
    if not target.audit_enabled and target.role != UserRole.admin:
        raise HTTPException(status_code=422, detail="Сначала откройте сотруднику доступ к разделу «Аудит»")
    if target.id != manager.id:
        accepted_contact = await db.scalar(
            select(Contact.id).where(
                Contact.status == "accepted",
                or_(
                    and_(Contact.requester_id == manager.id, Contact.recipient_id == target.id),
                    and_(Contact.requester_id == target.id, Contact.recipient_id == manager.id),
                ),
            )
        )
        if accepted_contact is None:
            raise HTTPException(status_code=422, detail="Сотрудник должен быть в принятых контактах")
    if await db.scalar(select(AuditTeamMember.id).where(AuditTeamMember.user_id == target.id)):
        raise HTTPException(status_code=409, detail="Сотрудник уже состоит в команде аудита")
    member = AuditTeamMember(
        user_id=target.id,
        role=body.role,
        added_by_id=manager.id,
    )
    db.add(member)
    await db.flush()
    await db.refresh(member)
    return _team_member_read(member, target)


@router.patch("/team/{member_id}", response_model=AuditTeamMemberRead)
async def update_audit_team_member(
    member_id: UUID,
    body: AuditTeamMemberUpdate,
    _: User = Depends(require_audit_manager),
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(AuditTeamMember, User)
            .join(User, User.id == AuditTeamMember.user_id)
            .where(AuditTeamMember.id == member_id)
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Участник команды не найден")
    member, target = row
    member.role = body.role
    await db.flush()
    await db.refresh(member)
    return _team_member_read(member, target)


@router.delete("/team/{member_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_audit_team_member(
    member_id: UUID,
    _: User = Depends(require_audit_manager),
    db: AsyncSession = Depends(get_db),
):
    member = await db.scalar(select(AuditTeamMember).where(AuditTeamMember.id == member_id))
    if member is None:
        raise HTTPException(status_code=404, detail="Участник команды не найден")
    assigned_case = await db.scalar(
        select(AuditCase.id).where(
            AuditCase.responsible_user_id == member.user_id,
            AuditCase.status != "archived",
        ).limit(1)
    )
    if assigned_case is not None:
        raise HTTPException(
            status_code=409,
            detail="Сначала переназначьте активные аудиты этого сотрудника",
        )
    await db.delete(member)


@router.patch("/cases/{case_id}/responsible", response_model=AuditCaseRead)
async def assign_audit_responsible(
    case_id: UUID,
    body: AuditResponsibleUpdate,
    manager: User = Depends(require_audit_manager),
    db: AsyncSession = Depends(get_db),
):
    audit_case = await _get_case_or_404(db, case_id)
    active_assignment = await db.scalar(
        select(AuditAssignment)
        .where(AuditAssignment.case_id == audit_case.id)
        .with_for_update()
    )
    if active_assignment is not None and body.user_id != active_assignment.assignee_id:
        raise HTTPException(
            status_code=409,
            detail=(
                "У договора уже есть календарное назначение. "
                "Передайте его другому сотруднику в разделе «Назначения»"
            ),
        )
    if audit_case.status == "archived" and body.user_id is not None:
        raise HTTPException(status_code=409, detail="Архивный договор нельзя назначить")
    previous_user_id = audit_case.responsible_user_id
    responsible_name = None
    responsible_email = None
    if body.user_id is not None:
        row = (
            await db.execute(
                select(AuditTeamMember, User)
                .join(User, User.id == AuditTeamMember.user_id)
                .where(AuditTeamMember.user_id == body.user_id, User.is_active.is_(True))
            )
        ).one_or_none()
        if row is None:
            raise HTTPException(status_code=422, detail="Ответственного сначала нужно добавить в команду аудита")
        _, responsible = row
        responsible_name = responsible.full_name
        responsible_email = responsible.email
    audit_case.responsible_user_id = body.user_id
    if body.user_id is not None:
        _activate_case_for_assignment(db, audit_case, manager.id)
    elif audit_case.workflow_stage != "ready":
        previous_stage = audit_case.workflow_stage
        audit_case.workflow_stage = "unassigned"
        if previous_stage != audit_case.workflow_stage:
            record_audit_event(
                db,
                case_id=audit_case.id,
                actor_id=manager.id,
                event_type="workflow_stage_changed",
                message="Этап аудита: договор не назначен",
                payload_json={
                    "previous_workflow_stage": previous_stage,
                    "workflow_stage": audit_case.workflow_stage,
                },
            )
    await db.flush()
    await db.refresh(audit_case)
    record_audit_event(
        db,
        case_id=audit_case.id,
        actor_id=manager.id,
        event_type="responsible_changed",
        message=f"Ответственный: {responsible_name or 'не назначен'}",
        payload_json={
            "previous_responsible_user_id": str(previous_user_id) if previous_user_id else None,
            "responsible_user_id": str(body.user_id) if body.user_id else None,
        },
    )
    return await _serialize_case(
        db,
        audit_case,
        include_atoms=True,
        responsible=(responsible_name, responsible_email),
        can_view_contract_reference=await _is_audit_team_member(manager, db),
    )


@router.post("/documents", response_model=AuditDocumentBatchResponse, status_code=status.HTTP_201_CREATED)
async def upload_new_audit_documents(
    files: list[UploadFile] = File(...),
    digital_product: str | None = Form(None, max_length=255),
    manager: User = Depends(require_audit_manager),
    db: AsyncSession = Depends(get_db),
):
    if not files or len(files) > MAX_AUDIT_DOCUMENTS_PER_BATCH:
        raise HTTPException(
            status_code=400,
            detail=f"За один раз можно загрузить от 1 до {MAX_AUDIT_DOCUMENTS_PER_BATCH} документов",
        )
    prepared_documents = [await prepare_audit_document(upload) for upload in files]
    if sum(document.size_bytes for document in prepared_documents) > MAX_AUDIT_BATCH_BYTES:
        raise HTTPException(status_code=400, detail="Общий размер пакета больше 100 МБ")
    hashes = [document.sha256 for document in prepared_documents]
    if len(set(hashes)) != len(hashes):
        raise HTTPException(status_code=409, detail="В пакете есть одинаковые файлы")
    existing_hash = await db.scalar(
        select(AuditDocument.sha256).where(AuditDocument.sha256.in_(hashes)).limit(1)
    )
    if existing_hash is not None:
        raise HTTPException(status_code=409, detail="Один из документов уже загружен в аудит")

    product = (digital_product or "").strip() or "Требует заполнения"
    written_paths: list[Path] = []
    response_items: list[AuditDocumentUploadItem] = []
    try:
        for index, prepared in enumerate(prepared_documents, start=1):
            display_name = "Техническое задание" if len(prepared_documents) == 1 else f"Техническое задание {index}"
            audit_case = AuditCase(
                created_by_id=manager.id,
                title=f"Аудит: {product}" if len(prepared_documents) == 1 else f"Аудит документа {index}: {product}",
                digital_product=product,
                status="draft",
            )
            db.add(audit_case)
            await db.flush()
            stored_filename, file_path = persist_audit_document_file(audit_case.id, prepared)
            written_paths.append(file_path)
            document = AuditDocument(
                case_id=audit_case.id,
                uploaded_by_id=manager.id,
                kind="technical_spec",
                display_name=display_name,
                original_filename=prepared.original_filename,
                stored_filename=stored_filename,
                content_type=prepared.content_type,
                size_bytes=prepared.size_bytes,
                sha256=prepared.sha256,
            )
            db.add(document)
            await db.flush()
            await db.refresh(audit_case)
            await db.refresh(document)
            record_audit_event(
                db,
                case_id=audit_case.id,
                actor_id=manager.id,
                event_type="document_uploaded",
                message=f"Загружен документ «{display_name}»",
                payload_json={
                    "document_id": str(document.id),
                    "document_kind": document.kind,
                    "sha256": document.sha256,
                },
            )
            response_items.append(
                AuditDocumentUploadItem(
                    case=await _serialize_case(
                        db,
                        audit_case,
                        include_atoms=True,
                        can_view_contract_reference=await _is_audit_team_member(manager, db),
                    ),
                    document=_document_read(document, manager.full_name),
                )
            )
    except Exception:
        for file_path in written_paths:
            file_path.unlink(missing_ok=True)
        raise
    return AuditDocumentBatchResponse(items=response_items)


@router.get("/cases/{case_id}/documents", response_model=list[AuditDocumentRead])
async def list_audit_documents(
    case_id: UUID,
    _: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    await _get_case_or_404(db, case_id)
    uploader = aliased(User)
    result = await db.execute(
        select(AuditDocument, uploader.full_name)
        .outerjoin(uploader, uploader.id == AuditDocument.uploaded_by_id)
        .where(AuditDocument.case_id == case_id)
        .order_by(AuditDocument.created_at.desc())
    )
    return [_document_read(document, uploader_name) for document, uploader_name in result.all()]


@router.post(
    "/cases/{case_id}/documents",
    response_model=list[AuditDocumentRead],
    status_code=status.HTTP_201_CREATED,
)
async def upload_audit_case_documents(
    case_id: UUID,
    files: list[UploadFile] = File(...),
    kind: str = Form("other", max_length=30),
    display_name: str | None = Form(None, max_length=255),
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    audit_case = await db.scalar(
        select(AuditCase).where(AuditCase.id == case_id).with_for_update()
    )
    if audit_case is None:
        raise HTTPException(status_code=404, detail="Аудит не найден")
    await _ensure_case_atom_editor(audit_case, user, db)
    if kind not in AUDIT_DOCUMENT_KINDS:
        raise HTTPException(status_code=422, detail="Некорректная категория материала")
    if not files or len(files) > MAX_AUDIT_DOCUMENTS_PER_BATCH:
        raise HTTPException(
            status_code=400,
            detail=f"За один раз можно загрузить от 1 до {MAX_AUDIT_DOCUMENTS_PER_BATCH} документов",
        )
    requested_name = (display_name or "").strip()
    if requested_name and len(files) != 1:
        raise HTTPException(
            status_code=422,
            detail="Собственное название можно указать только при загрузке одного файла",
        )

    prepared_documents = [await prepare_audit_document(upload) for upload in files]
    if sum(document.size_bytes for document in prepared_documents) > MAX_AUDIT_BATCH_BYTES:
        raise HTTPException(status_code=400, detail="Общий размер пакета больше 100 МБ")
    hashes = [document.sha256 for document in prepared_documents]
    if len(set(hashes)) != len(hashes):
        raise HTTPException(status_code=409, detail="В пакете есть одинаковые файлы")
    existing_hash = await db.scalar(
        select(AuditDocument.sha256)
        .where(
            AuditDocument.case_id == case_id,
            AuditDocument.sha256.in_(hashes),
        )
        .limit(1)
    )
    if existing_hash is not None:
        raise HTTPException(status_code=409, detail="Этот файл уже прикреплен к договору")

    staged_documents = []
    created_documents: list[AuditDocument] = []
    category_label = AUDIT_DOCUMENT_KIND_LABELS[kind]
    try:
        for prepared in prepared_documents:
            staged = stage_audit_document_file(case_id, prepared)
            staged_documents.append(staged)
            material_name = requested_name or (
                category_label
                if len(prepared_documents) == 1
                else f"{category_label}: {Path(prepared.original_filename).stem[:180]}"
            )
            document = AuditDocument(
                case_id=case_id,
                uploaded_by_id=user.id,
                kind=kind,
                display_name=material_name,
                original_filename=prepared.original_filename,
                stored_filename=staged.stored_filename,
                content_type=prepared.content_type,
                size_bytes=prepared.size_bytes,
                sha256=prepared.sha256,
            )
            db.add(document)
            created_documents.append(document)
        await db.flush()
        for document in created_documents:
            record_audit_event(
                db,
                case_id=case_id,
                actor_id=user.id,
                event_type="document_uploaded",
                message=f"Загружен материал «{document.display_name}»",
                payload_json={
                    "document_id": str(document.id),
                    "document_kind": document.kind,
                    "sha256": document.sha256,
                },
            )
        await db.commit()
    except Exception:
        for staged in staged_documents:
            discard_staged_audit_document(staged)
        raise

    for staged in staged_documents:
        try:
            finalize_staged_audit_document(staged)
        except OSError:
            # Reconciliation and download can finalize a committed pending file.
            pass
    return [_document_read(document, user.full_name) for document in created_documents]


@router.get("/documents/{document_id}/content")
async def download_audit_document(
    document_id: UUID,
    _: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    document = await db.scalar(select(AuditDocument).where(AuditDocument.id == document_id))
    if document is None:
        raise HTTPException(status_code=404, detail="Документ не найден")
    file_path = audit_document_path(document)
    if not file_path.is_file():
        finalize_pending_audit_document(document.stored_filename)
    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Файл документа отсутствует в хранилище")
    return FileResponse(
        str(file_path),
        media_type=document.content_type,
        filename=document.original_filename,
        content_disposition_type="attachment",
    )


@router.post(
    "/cases/{case_id}/ai-atomization/privacy-preview",
    response_model=AuditAIPrivacyPreviewRead,
)
async def preview_ai_atomization_privacy(
    case_id: UUID,
    body: AuditAIPrivacyPreviewRequest,
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    audit_case = await _get_case_or_404(db, case_id)
    await _ensure_case_atom_editor(audit_case, user, db)
    atoms_count = int(
        await db.scalar(select(func.count(AuditAtom.id)).where(AuditAtom.case_id == case_id)) or 0
    )
    if atoms_count:
        raise HTTPException(
            status_code=409,
            detail="ИИ-черновик первого slice создается только до появления атомов в реестре",
        )
    document = await db.scalar(
        select(AuditDocument).where(
            AuditDocument.id == body.document_id,
            AuditDocument.case_id == case_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Исходный документ этого аудита не найден")
    if document.kind != "technical_spec":
        raise HTTPException(status_code=422, detail="Для ИИ-атомизации выберите исходное техническое задание")
    skill_row = (
        await db.execute(
            select(AuditAtomizationSkill, AuditAtomizationSkillVersion)
            .join(
                AuditAtomizationSkillVersion,
                AuditAtomizationSkillVersion.skill_id == AuditAtomizationSkill.id,
            )
            .where(
                AuditAtomizationSkillVersion.id == body.skill_version_id,
                AuditAtomizationSkillVersion.package_format == "declarative_json",
                AuditAtomizationSkillVersion.is_active.is_(True),
                AuditAtomizationSkillVersion.runtime_status == "ready",
                AuditAtomizationSkill.is_enabled.is_(True),
            )
        )
    ).one_or_none()
    if skill_row is None:
        raise HTTPException(status_code=409, detail="Выбранная версия skill не готова к запуску")
    _, skill_version = skill_row
    try:
        provider = await get_ready_ai_provider(db)
        identifiers = [item.get_secret_value() for item in body.contract_identifiers]
        body.contract_identifiers.clear()
        preview = create_audit_privacy_preview(
            user_id=user.id,
            case_id=case_id,
            audit_case=audit_case,
            document=document,
            skill_version=skill_version,
            provider=provider,
            identifiers=identifiers,
        )
        identifiers = []
    except (AIProviderError, AuditAIAtomizationError) as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        )
    record_audit_event(
        db,
        case_id=case_id,
        actor_id=user.id,
        event_type="ai_atomization_privacy_previewed",
        message="Проверено обезличивание запроса к ИИ",
        payload_json={
            "identifier_count": preview.identifier_count,
            "replacement_count": preview.replacement_count,
            "source_unit_count": preview.source_unit_count,
            "payload_sha256": preview.payload_sha256,
            "document_id": str(document.id),
            "skill_version_id": str(skill_version.id),
            "model_name": provider.model_name,
        },
    )
    await db.commit()
    return AuditAIPrivacyPreviewRead(
        privacy_token=preview.token,
        expires_at=preview.expires_at,
        provider_name=provider.display_name,
        model_name=provider.model_name,
        pseudonym=preview.pseudonym,
        identifier_count=preview.identifier_count,
        replacement_count=preview.replacement_count,
        source_unit_count=preview.source_unit_count,
        character_count=preview.character_count,
        outbound_fields=[
            "протокол атомизации",
            "обезличенный цифровой продукт",
            "правила активного skill",
            "локаторы и обезличенный текст фрагментов",
        ],
        samples=preview.samples,
        payload_sha256=preview.payload_sha256,
        warnings=["Гарантия распространяется на указанный номер и перечисленные точные варианты написания."],
    )


@router.post(
    "/cases/{case_id}/ai-atomization/attempts",
    response_model=AuditAIAtomizationAttemptRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_ai_atomization_attempt(
    case_id: UUID,
    body: AuditAIAtomizationStart,
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    user_id = user.id
    request_key_hash = _ai_request_hash("audit-ai-start", user_id, body.request_id)
    existing = await db.scalar(
        select(AuditAIAtomizationAttempt).where(
            AuditAIAtomizationAttempt.request_key_hash == request_key_hash
        )
    )
    if existing is not None:
        if existing.case_id != case_id or existing.requested_by_id != user_id:
            raise HTTPException(status_code=409, detail="request_id уже использован для другой операции")
        return await _serialize_ai_attempt(db, existing.id)

    audit_case = await _get_case_or_404(db, case_id)
    await _ensure_case_atom_editor(audit_case, user, db)
    atoms_count = int(
        await db.scalar(select(func.count(AuditAtom.id)).where(AuditAtom.case_id == case_id)) or 0
    )
    if atoms_count:
        raise HTTPException(
            status_code=409,
            detail="ИИ-черновик первого slice создается только до появления атомов в реестре",
        )
    document = await db.scalar(
        select(AuditDocument).where(
            AuditDocument.id == body.document_id,
            AuditDocument.case_id == case_id,
        )
    )
    if document is None:
        raise HTTPException(status_code=404, detail="Исходный документ этого аудита не найден")
    if document.kind != "technical_spec":
        raise HTTPException(status_code=422, detail="Для ИИ-атомизации выберите исходное техническое задание")
    skill_row = (
        await db.execute(
            select(AuditAtomizationSkill, AuditAtomizationSkillVersion)
            .join(
                AuditAtomizationSkillVersion,
                AuditAtomizationSkillVersion.skill_id == AuditAtomizationSkill.id,
            )
            .where(
                AuditAtomizationSkillVersion.id == body.skill_version_id,
                AuditAtomizationSkillVersion.package_format == "declarative_json",
                AuditAtomizationSkillVersion.is_active.is_(True),
                AuditAtomizationSkillVersion.runtime_status == "ready",
                AuditAtomizationSkill.is_enabled.is_(True),
            )
        )
    ).one_or_none()
    if skill_row is None:
        raise HTTPException(status_code=409, detail="Выбранная версия skill не готова к запуску")
    skill, skill_version = skill_row
    try:
        provider = await get_ready_ai_provider(db)
    except AIProviderError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        )

    case_snapshot = SimpleNamespace(
        id=audit_case.id,
        digital_product=audit_case.digital_product,
        status=audit_case.status,
    )
    document_snapshot = SimpleNamespace(
        id=document.id,
        case_id=document.case_id,
        kind=document.kind,
        original_filename=document.original_filename,
        stored_filename=document.stored_filename,
        sha256=document.sha256,
    )
    skill_snapshot = SimpleNamespace(
        id=skill_version.id,
        skill_id=skill.id,
        version_label=skill_version.version_label,
        instructions_text=skill_version.instructions_text,
        rules_json=list(skill_version.rules_json or []),
        content_sha256=skill_version.content_sha256,
    )
    provider_snapshot = SimpleNamespace(
        id=provider.id,
        enabled=provider.enabled,
        base_url=provider.base_url,
        model_name=provider.model_name,
        api_key_ciphertext=provider.api_key_ciphertext,
        config_version=provider.config_version,
        last_test_status=provider.last_test_status,
        last_verified_config_version=provider.last_verified_config_version,
    )
    try:
        identifiers = [item.get_secret_value() for item in body.contract_identifiers]
        body.contract_identifiers.clear()
        privacy = verify_audit_privacy_preview(
            token=body.privacy_token,
            user_id=user_id,
            case_id=case_id,
            audit_case=case_snapshot,
            document=document_snapshot,
            skill_version=skill_snapshot,
            provider=provider_snapshot,
            identifiers=identifiers,
        )
        identifiers = []
        prepared = privacy.prepared
    except AuditAIAtomizationError as error:
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        )

    now = datetime.now(timezone.utc)
    attempt = AuditAIAtomizationAttempt(
        case_id=case_id,
        document_id=document_snapshot.id,
        skill_version_id=skill_snapshot.id,
        provider_config_id=provider_snapshot.id,
        provider_config_version=provider_snapshot.config_version,
        model_name=provider_snapshot.model_name,
        document_sha256=document_snapshot.sha256,
        skill_sha256=skill_snapshot.content_sha256,
        request_key_hash=request_key_hash,
        status="running",
        config_version=1,
        source_manifest_json=prepared.source_manifest,
        coverage_json={},
        warnings_json=[],
        prompt_sha256=prepared.prompt_sha256,
        requested_by_id=user_id,
        consent_confirmed_at=now,
    )
    db.add(attempt)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        concurrent = await db.scalar(
            select(AuditAIAtomizationAttempt).where(
                AuditAIAtomizationAttempt.request_key_hash == request_key_hash
            )
        )
        if concurrent is not None and concurrent.case_id == case_id and concurrent.requested_by_id == user_id:
            return await _serialize_ai_attempt(db, concurrent.id)
        raise HTTPException(status_code=409, detail="request_id уже использован для другой операции")
    attempt_id = attempt.id
    record_audit_event(
        db,
        case_id=case_id,
        actor_id=user_id,
        event_type="ai_atomization_started",
        message="Запущено формирование ИИ-черновика атомов",
        payload_json={
            "attempt_id": str(attempt_id),
            "document_id": str(document_snapshot.id),
            "skill_version_id": str(skill_snapshot.id),
            "model_name": provider_snapshot.model_name,
            "identifier_count": privacy.identifier_count,
            "replacement_count": privacy.replacement_count,
            "source_unit_count": privacy.source_unit_count,
            "payload_sha256": privacy.payload_sha256,
        },
    )
    await db.commit()

    try:
        generated = await complete_audit_atomization(
            provider=provider_snapshot,
            prepared=prepared,
            digital_product=case_snapshot.digital_product,
        )
    except (AIProviderError, AuditAIAtomizationError) as error:
        failed = await db.get(AuditAIAtomizationAttempt, attempt_id)
        if failed is not None and failed.status == "running":
            failed.status = "failed"
            failed.error_code = error.code[:80]
            failed.config_version += 1
            record_audit_event(
                db,
                case_id=case_id,
                actor_id=user_id,
                event_type="ai_atomization_failed",
                message="ИИ-черновик атомов не сформирован",
                payload_json={"attempt_id": str(attempt_id)},
            )
            await db.commit()
        raise HTTPException(
            status_code=error.status_code,
            detail={"code": error.code, "message": error.message},
        )
    except Exception:
        failed = await db.get(AuditAIAtomizationAttempt, attempt_id)
        if failed is not None and failed.status == "running":
            failed.status = "failed"
            failed.error_code = "internal_generation_error"
            failed.config_version += 1
            record_audit_event(
                db,
                case_id=case_id,
                actor_id=user_id,
                event_type="ai_atomization_failed",
                message="ИИ-черновик атомов не сформирован из-за внутренней ошибки",
                payload_json={"attempt_id": str(attempt_id)},
            )
            await db.commit()
        raise HTTPException(status_code=500, detail="Не удалось сформировать ИИ-черновик")

    locked_attempt = await db.scalar(
        select(AuditAIAtomizationAttempt)
        .where(AuditAIAtomizationAttempt.id == attempt_id)
        .with_for_update()
    )
    current_case = await db.scalar(
        select(AuditCase).where(AuditCase.id == case_id).with_for_update()
    )
    current_document = await db.get(AuditDocument, document_snapshot.id)
    current_skill = await db.get(AuditAtomizationSkillVersion, skill_snapshot.id)
    current_skill_definition = (
        await db.get(AuditAtomizationSkill, current_skill.skill_id)
        if current_skill is not None
        else None
    )
    current_provider = await db.get(AIProviderConfig, provider_snapshot.id)
    context_valid = bool(
        locked_attempt is not None
        and locked_attempt.status == "running"
        and current_case is not None
        and current_case.status != "archived"
        and current_document is not None
        and current_document.case_id == case_id
        and current_document.sha256 == document_snapshot.sha256
        and current_skill is not None
        and current_skill.content_sha256 == skill_snapshot.content_sha256
        and current_skill.is_active
        and current_skill.runtime_status == "ready"
        and current_skill_definition is not None
        and current_skill_definition.is_enabled
        and current_provider is not None
        and current_provider.enabled
        and current_provider.last_test_status == "ok"
        and current_provider.config_version == provider_snapshot.config_version
        and current_provider.last_verified_config_version == current_provider.config_version
    )
    current_atoms_count = int(
        await db.scalar(select(func.count(AuditAtom.id)).where(AuditAtom.case_id == case_id)) or 0
    )
    if not context_valid or current_atoms_count:
        if locked_attempt is not None and locked_attempt.status == "running":
            locked_attempt.status = "failed"
            locked_attempt.error_code = "context_changed"
            locked_attempt.config_version += 1
            await db.commit()
        raise HTTPException(
            status_code=409,
            detail="Документ, skill, ИИ-профиль или реестр изменились во время обработки; запустите заново",
        )
    for draft in generated.drafts:
        db.add(
            AuditAIAtomDraft(
                attempt_id=attempt_id,
                case_id=case_id,
                title=draft.title,
                digital_product=draft.digital_product,
                work_type=draft.work_type,
                object_type=draft.object_type,
                source_clause=draft.source_clause,
                notes=draft.notes,
                source_refs_json=draft.source_refs,
                model_payload_json=draft.model_payload,
                source_fingerprint=draft.source_fingerprint,
                confidence_percent=draft.confidence_percent,
                review_status="pending",
                sort_order=draft.sort_order,
            )
        )
    locked_attempt.status = "draft_ready"
    locked_attempt.coverage_json = generated.coverage_summary
    locked_attempt.warnings_json = generated.warnings
    locked_attempt.response_sha256 = generated.response_sha256
    locked_attempt.config_version += 1
    record_audit_event(
        db,
        case_id=case_id,
        actor_id=user_id,
        event_type="ai_atomization_ready",
        message="Сформирован ИИ-черновик атомов для проверки",
        payload_json={
            "attempt_id": str(attempt_id),
            "atom_count": len(generated.drafts),
        },
    )
    await db.commit()
    return await _serialize_ai_attempt(db, attempt_id)


@router.post(
    "/cases/{case_id}/ai-atomization/attempts/{attempt_id}/commit",
    response_model=AuditAIAtomizationCommitRead,
)
async def commit_ai_atomization_attempt(
    case_id: UUID,
    attempt_id: UUID,
    body: AuditAIAtomizationCommit,
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    user_id = user.id
    commit_key_hash = _ai_request_hash("audit-ai-commit", user_id, body.request_id)
    audit_case = await _get_case_or_404(db, case_id)
    await _ensure_case_atom_editor(audit_case, user, db)
    attempt = await db.scalar(
        select(AuditAIAtomizationAttempt)
        .where(
            AuditAIAtomizationAttempt.id == attempt_id,
            AuditAIAtomizationAttempt.case_id == case_id,
        )
        .with_for_update()
    )
    if attempt is None:
        raise HTTPException(status_code=404, detail="Черновик ИИ-атомизации не найден")
    drafts = list(
        (
            await db.scalars(
                select(AuditAIAtomDraft)
                .where(AuditAIAtomDraft.attempt_id == attempt_id)
                .order_by(AuditAIAtomDraft.sort_order.asc(), AuditAIAtomDraft.id.asc())
                .with_for_update()
            )
        ).all()
    )
    if attempt.status == "committed":
        if attempt.commit_key_hash != commit_key_hash:
            raise HTTPException(status_code=409, detail="Этот ИИ-черновик уже зафиксирован")
        atom_ids = list(
            (
                await db.scalars(
                    select(AuditAtom.id).where(
                        AuditAtom.ai_atomization_draft_id.in_([draft.id for draft in drafts])
                    )
                )
            ).all()
        )
        return AuditAIAtomizationCommitRead(
            attempt_id=attempt_id,
            case_id=case_id,
            atoms_created=len(atom_ids),
            atom_ids=atom_ids,
            already_committed=True,
        )
    if attempt.status != "draft_ready":
        raise HTTPException(status_code=409, detail="ИИ-черновик еще не готов к фиксации")
    if attempt.config_version != body.expected_config_version:
        raise HTTPException(status_code=409, detail="ИИ-черновик изменился; обновите его перед фиксацией")
    current_document = await db.get(AuditDocument, attempt.document_id)
    if (
        current_document is None
        or current_document.case_id != case_id
        or current_document.sha256 != attempt.document_sha256
    ):
        raise HTTPException(status_code=409, detail="Исходный документ изменился; запустите атомизацию заново")
    existing_atoms = int(
        await db.scalar(select(func.count(AuditAtom.id)).where(AuditAtom.case_id == case_id)) or 0
    )
    if existing_atoms:
        raise HTTPException(
            status_code=409,
            detail="В реестре уже появились атомы; объединение с ИИ-черновиком требует отдельного review",
        )
    submitted_by_id = {item.id: item for item in body.drafts}
    if set(submitted_by_id) != {draft.id for draft in drafts}:
        raise HTTPException(status_code=422, detail="Передайте решение по каждому атому ИИ-черновика")

    first_item_code = await generate_next_item_code(db, case_id)
    try:
        next_number = int(first_item_code.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        next_number = 1
    created_atoms: list[AuditAtom] = []
    for draft in drafts:
        submitted = submitted_by_id[draft.id]
        draft.title = submitted.title
        draft.digital_product = submitted.digital_product
        draft.work_type = submitted.work_type
        draft.object_type = submitted.object_type
        draft.notes = submitted.notes
        if not submitted.included:
            draft.review_status = "rejected"
            continue
        atom = AuditAtom(
            case_id=case_id,
            item_code=f"ITEM-{next_number:03d}",
            title=draft.title,
            digital_product=draft.digital_product,
            work_type=draft.work_type,
            object_type=draft.object_type,
            source_clause=draft.source_clause,
            source_evidence_text=evidence_text(draft.source_refs_json or []),
            source_refs_json=list(draft.source_refs_json or []),
            notes=draft.notes,
            state="draft",
            source_sheet="ИИ-черновик",
            source_fingerprint=draft.source_fingerprint,
            sort_order=next_number * 10,
            ai_atomization_draft_id=draft.id,
        )
        next_number += 1
        db.add(atom)
        created_atoms.append(atom)
        draft.review_status = "committed"
    await db.flush()
    for atom in created_atoms:
        record_audit_event(
            db,
            case_id=case_id,
            atom_id=atom.id,
            actor_id=user_id,
            event_type="atom_created",
            message=f"Из ИИ-черновика создан атом {atom.item_code}",
            payload_json={"item_code": atom.item_code, "title": atom.title},
        )
    attempt.status = "committed"
    attempt.commit_key_hash = commit_key_hash
    attempt.committed_by_id = user_id
    attempt.committed_at = datetime.now(timezone.utc)
    attempt.config_version += 1
    if attempt.canonical_run_id is not None:
        canonical_run = await db.get(AuditTZRun, attempt.canonical_run_id)
        if canonical_run is not None:
            canonical_run.status = "committed"
            canonical_run.current_phase = "registry_committed"
            canonical_run.atom_count = len(created_atoms)
            canonical_run.finished_at = datetime.now(timezone.utc)
    audit_case.status = "atomization"
    if audit_case.workflow_stage != "unassigned":
        audit_case.workflow_stage = "atomization"
    record_audit_event(
        db,
        case_id=case_id,
        actor_id=user_id,
        event_type="ai_atomization_committed",
        message="ИИ-черновик проверен и зафиксирован в реестре атомов",
        payload_json={
            "attempt_id": str(attempt_id),
            "atom_count": len(created_atoms),
        },
    )
    created_atom_ids = [atom.id for atom in created_atoms]
    await db.commit()
    return AuditAIAtomizationCommitRead(
        attempt_id=attempt_id,
        case_id=case_id,
        atoms_created=len(created_atoms),
        atom_ids=created_atom_ids,
        already_committed=False,
    )


async def _persist_import_registers(
    db: AsyncSession,
    result: AuditImportCommitResponse,
    prepared,
    user: User,
) -> None:
    written_paths: list[Path] = []
    try:
        for committed_case in result.cases:
            existing = await db.scalar(
                select(AuditDocument.id).where(
                    AuditDocument.case_id == committed_case.case_id,
                    AuditDocument.sha256 == prepared.sha256,
                )
            )
            if existing is not None:
                continue
            stored_filename, file_path = persist_audit_document_file(
                committed_case.case_id,
                prepared,
            )
            written_paths.append(file_path)
            document = AuditDocument(
                case_id=committed_case.case_id,
                uploaded_by_id=user.id,
                kind="atom_register",
                display_name="Реестр атомов",
                original_filename=prepared.original_filename,
                stored_filename=stored_filename,
                content_type=prepared.content_type,
                size_bytes=prepared.size_bytes,
                sha256=prepared.sha256,
            )
            db.add(document)
            await db.flush()
            await db.refresh(document)
            record_audit_event(
                db,
                case_id=committed_case.case_id,
                actor_id=user.id,
                event_type="document_uploaded",
                message="Сохранен исходный реестр атомов",
                payload_json={
                    "document_id": str(document.id),
                    "document_kind": document.kind,
                    "sha256": document.sha256,
                },
            )
    except Exception:
        for file_path in written_paths:
            file_path.unlink(missing_ok=True)
        raise


@router.get("/cases/{case_id}/atom-template")
async def download_atom_template(
    case_id: UUID,
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    audit_case = await _get_case_or_404(db, case_id)
    await _ensure_case_atom_editor(audit_case, user, db)
    return Response(
        content=build_audit_atom_template(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f'attachment; filename="{audit_case.case_number}-atoms-template.xlsx"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/cases/{case_id}/imports/preview", response_model=AuditImportPreview)
async def preview_case_import(
    case_id: UUID,
    file: UploadFile = File(...),
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    audit_case = await _get_case_or_404(db, case_id)
    await _ensure_case_atom_editor(audit_case, user, db)
    return await preview_audit_import(db, file, user, target_case_id=case_id)


@router.post("/cases/{case_id}/imports/commit", response_model=AuditImportCommitResponse)
async def commit_case_import(
    case_id: UUID,
    file: UploadFile = File(...),
    expected_sha256: str = Form(..., min_length=64, max_length=64),
    user: User = Depends(require_audit_workspace_member),
    db: AsyncSession = Depends(get_db),
):
    audit_case = await _get_case_or_404(db, case_id)
    await _ensure_case_atom_editor(audit_case, user, db)
    prepared = await prepare_audit_document(file)
    await file.seek(0)
    result = await commit_audit_import(
        db,
        file,
        user,
        expected_sha256,
        target_case_id=case_id,
    )
    await _persist_import_registers(db, result, prepared, user)
    return result


@router.post("/imports/preview", response_model=AuditImportPreview)
async def preview_import(
    file: UploadFile = File(...),
    user: User = Depends(require_audit_manager),
    db: AsyncSession = Depends(get_db),
):
    return await preview_audit_import(db, file, user)


@router.post("/imports/commit", response_model=AuditImportCommitResponse)
async def commit_import(
    file: UploadFile = File(...),
    expected_sha256: str = Form(..., min_length=64, max_length=64),
    user: User = Depends(require_audit_manager),
    db: AsyncSession = Depends(get_db),
):
    prepared = await prepare_audit_document(file)
    await file.seek(0)
    result = await commit_audit_import(db, file, user, expected_sha256)
    await _persist_import_registers(db, result, prepared, user)
    return result
