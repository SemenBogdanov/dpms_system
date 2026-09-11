"""Safe origin projections and append-only publication of immutable AI items."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import io
import json
from types import SimpleNamespace
from uuid import UUID, uuid4
import xml.etree.ElementTree as ET
import zipfile

from fastapi import HTTPException
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai_provider import AuditAtomizationSkill, AuditAtomizationSkillVersion
from app.models.audit import (
    AuditAIAtomDraft, AuditAIAtomizationAttempt, AuditAIModelComparison, AuditAIModelComparisonDraft,
    AuditAIModelRegistry, AuditAIModelRegistryItem, AuditAtom, AuditCase,
    AuditDocument, AuditEvent, AuditImportBatch,
)
from app.models.audit_legacy import AuditLegacyImport
from app.models.audit_legacy_transfer import AuditLegacyProvenance, AuditLegacyTransfer
from app.schemas.audit import AuditAtomOriginRead, AuditAtomRead
from app.services.audit_model_comparison import evidence_text


ORIGIN_LABELS = {
    "historical_import": "Исторический импорт",
    "manual_register": "Ручной реестр XLSX",
    "manual": "Добавлен вручную",
    "ai": "ИИ-реестр",
    "unknown": "Источник не установлен",
}
PRIVATE_LEGACY_FIELDS = {
    "source_register_id", "source_register_created_at", "source_sha256",
    "source_sheet", "source_row", "document_id", "document_sha256", "document_created_at",
}


@dataclass(frozen=True)
class PublishModelRegistryAtomsResult:
    atom_ids: list[UUID]
    created_atom_ids: list[UUID]
    atoms_created: int
    atoms_reused: int


def scoped_source_fingerprint(kind: str, register_id: object, item_id: object) -> str:
    """Identity of one source occurrence, never a semantic deduplication key."""
    return sha256(json.dumps(
        ["audit-origin-v1", kind, str(register_id), str(item_id)],
        ensure_ascii=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def origin_snapshot(kind: str, **fields) -> dict:
    return AuditAtomOriginRead(
        kind=kind, label=ORIGIN_LABELS[kind], **fields,
    ).model_dump(mode="json", exclude_none=True)


async def _skill_metadata(db: AsyncSession, identifiers: set[UUID]) -> dict[UUID, dict]:
    if not identifiers:
        return {}
    rows = (await db.execute(select(
        AuditAtomizationSkillVersion.id,
        AuditAtomizationSkillVersion.version_label,
        AuditAtomizationSkill.name,
        AuditAtomizationSkill.slug,
    ).join(
        AuditAtomizationSkill, AuditAtomizationSkill.id == AuditAtomizationSkillVersion.skill_id,
    ).where(AuditAtomizationSkillVersion.id.in_(identifiers)))).all()
    return {row.id: {"skill_name": row.name, "skill_slug": row.slug, "skill_version": row.version_label} for row in rows}


def _registry_origin(registry, *, item_id=None, skill=None, comparison_id=None, document_created_at=None) -> dict:
    return origin_snapshot(
        "ai", source_register_id=registry.id,
        source_register_created_at=registry.created_at,
        document_id=registry.document_id, document_sha256=registry.document_sha256,
        document_created_at=document_created_at,
        canonical_run_id=registry.canonical_run_id, registry_item_id=item_id,
        comparison_id=comparison_id, provider_config_id=registry.provider_config_id,
        provider_config_version=registry.provider_config_version,
        provider_name=registry.provider_name, model_name=registry.model_name,
        skill_version_id=registry.skill_version_id, skill_sha256=registry.skill_sha256,
        response_sha256=registry.response_sha256, **(skill or {}),
    )


async def attempt_origin_snapshot(db: AsyncSession, attempt: AuditAIAtomizationAttempt) -> dict:
    skills = await _skill_metadata(db, {attempt.skill_version_id})
    # A current provider display name is not evidence of its historical name.
    return origin_snapshot(
        "ai", source_register_id=attempt.id, source_register_created_at=attempt.created_at,
        document_id=attempt.document_id, document_sha256=attempt.document_sha256,
        canonical_run_id=attempt.canonical_run_id, attempt_id=attempt.id,
        provider_config_id=attempt.provider_config_id,
        provider_config_version=attempt.provider_config_version, model_name=attempt.model_name,
        skill_version_id=attempt.skill_version_id, skill_sha256=attempt.skill_sha256,
        prompt_sha256=attempt.prompt_sha256, response_sha256=attempt.response_sha256,
        **skills.get(attempt.skill_version_id, {}),
    )


def _canonical_item_atom_query():
    # Both rows copy the assembled fingerprint; context prevents cross-run reuse.
    return select(
        AuditAIModelRegistryItem.registry_id.label("registry_id"),
        AuditAIModelRegistryItem.id.label("item_id"), AuditAtom.id.label("atom_id"),
    ).select_from(AuditAIModelRegistryItem).join(
        AuditAIModelRegistry, AuditAIModelRegistry.id == AuditAIModelRegistryItem.registry_id,
    ).join(
        AuditAIAtomDraft, AuditAIAtomDraft.source_fingerprint == AuditAIModelRegistryItem.source_fingerprint,
    ).join(
        AuditAIAtomizationAttempt, AuditAIAtomizationAttempt.id == AuditAIAtomDraft.attempt_id,
    ).join(
        AuditAtom, AuditAtom.ai_atomization_draft_id == AuditAIAtomDraft.id,
    ).where(
        AuditAIModelRegistryItem.case_id == AuditAIModelRegistry.case_id,
        AuditAtom.case_id == AuditAIModelRegistry.case_id,
        AuditAIAtomDraft.case_id == AuditAIModelRegistry.case_id,
        AuditAIAtomizationAttempt.case_id == AuditAIModelRegistry.case_id,
        AuditAIAtomizationAttempt.canonical_run_id == AuditAIModelRegistry.canonical_run_id,
        AuditAIAtomizationAttempt.provider_config_id == AuditAIModelRegistry.provider_config_id,
        AuditAIAtomizationAttempt.provider_config_version == AuditAIModelRegistry.provider_config_version,
        AuditAIAtomizationAttempt.model_name == AuditAIModelRegistry.model_name,
        AuditAIAtomizationAttempt.document_id == AuditAIModelRegistry.document_id,
        AuditAIAtomizationAttempt.document_sha256 == AuditAIModelRegistry.document_sha256,
        AuditAIAtomizationAttempt.skill_version_id == AuditAIModelRegistry.skill_version_id,
        AuditAIAtomizationAttempt.skill_sha256 == AuditAIModelRegistry.skill_sha256,
        AuditAIAtomizationAttempt.response_sha256 == AuditAIModelRegistry.response_sha256,
        AuditAIAtomDraft.source_fingerprint != "",
    )


async def lookup_published_registry_items_batch(
    db: AsyncSession, registries: list[AuditAIModelRegistry],
) -> dict[UUID, dict[UUID, list[UUID]]]:
    """Three read-only queries; each registry maps covered item IDs to atom IDs.

    No flush, locks or ORM mutations. Count covered items with len(mapping),
    not the number of atoms: one old comparison atom can cover several items.
    """
    by_id = {registry.id: registry for registry in registries}
    result = {registry_id: {} for registry_id in by_id}
    if not by_id:
        return result
    rows = (await db.execute(select(
        AuditAIModelRegistryItem.id.label("item_id"), AuditAIModelRegistryItem.registry_id,
        AuditAIModelRegistryItem.case_id, AuditAtom.id.label("atom_id"),
        AuditAtom.case_id.label("atom_case_id"),
    ).outerjoin(
        AuditAtom, AuditAtom.ai_registry_item_id == AuditAIModelRegistryItem.id,
    ).where(AuditAIModelRegistryItem.registry_id.in_(by_id)).order_by(
        AuditAIModelRegistryItem.registry_id, AuditAIModelRegistryItem.sort_order, AuditAIModelRegistryItem.id,
    ).execution_options(autoflush=False))).all()
    item_registries = {}
    for row in rows:
        if row.case_id != by_id[row.registry_id].case_id:
            raise HTTPException(status_code=409, detail="Элемент ИИ-реестра принадлежит другому аудиту")
        item_registries[row.item_id] = row.registry_id
        if row.atom_id:
            if row.atom_case_id != row.case_id:
                raise HTTPException(status_code=409, detail="Опубликованный элемент ИИ-реестра принадлежит другому аудиту")
            result[row.registry_id][row.item_id] = [row.atom_id]
    attempt_rows = (await db.execute(_canonical_item_atom_query().where(
        AuditAIModelRegistry.id.in_(by_id),
    ).order_by(AuditAtom.created_at, AuditAtom.id).execution_options(autoflush=False))).all()
    for registry_id, item_id, atom_id in attempt_rows:
        result[registry_id].setdefault(item_id, []).append(atom_id)
    comparison_rows = (await db.execute(select(
        AuditAtom.id, AuditAtom.case_id, AuditAIModelComparisonDraft.model_variants_json,
    ).join(
        AuditAIModelComparisonDraft, AuditAIModelComparisonDraft.id == AuditAtom.ai_comparison_draft_id,
    ).join(
        AuditAIModelComparison, AuditAIModelComparison.id == AuditAIModelComparisonDraft.comparison_id,
    ).where(
        AuditAtom.case_id.in_({registry.case_id for registry in registries}),
        AuditAIModelComparisonDraft.case_id == AuditAtom.case_id,
        AuditAIModelComparison.case_id == AuditAtom.case_id,
    ).order_by(AuditAtom.created_at, AuditAtom.id).execution_options(autoflush=False))).all()
    for atom_id, case_id, variants in comparison_rows:
        for variant in variants or []:
            if not isinstance(variant, dict):
                continue
            try:
                registry_id = UUID(str(variant["registry_id"]))
                item_id = UUID(str(variant["registry_item_id"]))
            except (KeyError, ValueError, TypeError):
                continue
            if (registry_id in by_id and by_id[registry_id].case_id == case_id
                    and item_registries.get(item_id) == registry_id):
                result[registry_id].setdefault(item_id, []).append(atom_id)
    return {registry_id: {item_id: list(dict.fromkeys(atom_ids)) for item_id, atom_ids in covered.items()}
            for registry_id, covered in result.items()}


async def lookup_published_registry_items(
    db: AsyncSession, registry: AuditAIModelRegistry,
) -> dict[UUID, list[UUID]]:
    """Read-only source identity lookup shared by publication and API counts."""
    return (await lookup_published_registry_items_batch(db, [registry]))[registry.id]


async def _link_attempt_registry_items(db: AsyncSession, attempt: AuditAIAtomizationAttempt) -> int:
    if attempt.canonical_run_id is None or attempt.response_sha256 is None:
        return 0
    rows = (await db.execute(_canonical_item_atom_query().where(
        AuditAIAtomizationAttempt.id == attempt.id, AuditAtom.ai_registry_item_id.is_(None),
    ).order_by(AuditAtom.id).with_for_update(of=AuditAtom))).all()
    if not rows:
        return 0
    by_atom, by_item = {}, {}
    for _, item_id, atom_id in rows:
        by_atom.setdefault(atom_id, set()).add(item_id)
        by_item.setdefault(item_id, set()).add(atom_id)
    conflict = "Не удалось однозначно сохранить связь старого атома с модельным реестром"
    if any(len(values) != 1 for values in (*by_atom.values(), *by_item.values())):
        raise HTTPException(status_code=409, detail=conflict)
    occupied = list(await db.scalars(select(AuditAtom.id).where(
        AuditAtom.ai_registry_item_id.in_(by_item),
    ).with_for_update()))
    if occupied:
        raise HTTPException(status_code=409, detail=conflict)
    try:
        async with db.begin_nested():
            for atom_id, item_ids in by_atom.items():
                linked = (await db.scalars(update(AuditAtom).where(
                    AuditAtom.id == atom_id, AuditAtom.ai_registry_item_id.is_(None),
                ).values(
                    ai_registry_item_id=next(iter(item_ids)), updated_at=AuditAtom.updated_at,
                ).returning(AuditAtom.id).execution_options(synchronize_session="fetch"))).one_or_none()
                if linked is None:
                    raise HTTPException(status_code=409, detail=conflict)
    except IntegrityError as error:
        raise HTTPException(status_code=409, detail=conflict) from error
    return len(by_atom)


async def freeze_attempt_atom_origins(db: AsyncSession, attempt: AuditAIAtomizationAttempt) -> int:
    """Freeze old linked origins before deleting drafts or reusing an attempt.

    Caller holds the case/attempt locks and has not changed the attempt context.
    Flush only; exact item links and snapshots roll back with the caller.
    Return the number of new snapshots, excluding item-link backfills.
    """
    await db.flush()
    await _link_attempt_registry_items(db, attempt)
    atom_ids = list(await db.scalars(select(AuditAtom.id).join(
        AuditAIAtomDraft, AuditAIAtomDraft.id == AuditAtom.ai_atomization_draft_id,
    ).where(
        AuditAIAtomDraft.attempt_id == attempt.id,
        AuditAIAtomDraft.case_id == attempt.case_id,
        AuditAtom.case_id == attempt.case_id,
        AuditAtom.provenance_json == [],
    ).with_for_update(of=AuditAtom)))
    if not atom_ids:
        return 0
    snapshot = await attempt_origin_snapshot(db, attempt)
    # Provenance preservation is not a human edit, including its edit timestamp.
    frozen_ids = list(await db.scalars(update(AuditAtom).where(
        AuditAtom.id.in_(atom_ids), AuditAtom.provenance_json == [],
    ).values(
        provenance_json=[snapshot], updated_at=AuditAtom.updated_at,
    ).returning(AuditAtom.id).execution_options(synchronize_session="fetch")))
    await db.flush()
    return len(frozen_ids)


async def next_atom_number(db: AsyncSession, case_id: UUID) -> int:
    """Caller holds the case lock; numeric ordering also works beyond ITEM-999."""
    codes = (await db.scalars(select(AuditAtom.item_code).where(AuditAtom.case_id == case_id))).all()
    numbers = [int(code[5:]) for code in codes if code.startswith("ITEM-") and code[5:].isascii() and code[5:].isdigit()]
    return max(numbers, default=0) + 1


async def publish_model_registry_atoms(
    db: AsyncSession, registry: AuditAIModelRegistry, actor_id: UUID | None,
) -> PublishModelRegistryAtomsResult:
    """Flush draft atoms in the caller's transaction; never change live decisions.

    The caller authorizes the action and commits/rolls back. Registry and items
    must be complete, immutable and added to the same session before this call.
    """
    audit_case = await db.scalar(select(AuditCase).where(
        AuditCase.id == registry.case_id,
    ).with_for_update().execution_options(populate_existing=True))
    if audit_case is None:
        raise HTTPException(status_code=404, detail="Аудит не найден")
    if audit_case.status == "archived":
        raise HTTPException(status_code=409, detail="Архивный аудит доступен только для чтения")
    if audit_case.workflow_stage not in {"unassigned", "atomization"}:
        raise HTTPException(status_code=409, detail="Верните договор на этап Атомизация перед добавлением ИИ-атомов")
    await db.flush()
    items = list((await db.scalars(select(AuditAIModelRegistryItem).where(
        AuditAIModelRegistryItem.registry_id == registry.id,
    ).order_by(AuditAIModelRegistryItem.sort_order, AuditAIModelRegistryItem.id))).all())
    if any(item.case_id != registry.case_id for item in items):
        raise HTTPException(status_code=409, detail="Элемент ИИ-реестра принадлежит другому аудиту")
    if len(items) != registry.atom_count:
        raise HTTPException(status_code=409, detail="Формирование модельного реестра не завершено")
    if not items:
        return PublishModelRegistryAtomsResult([], [], 0, 0)
    existing = await lookup_published_registry_items(db, registry)
    skills = await _skill_metadata(db, {registry.skill_version_id}) if len(existing) < len(items) else {}
    document_created_at = await db.scalar(select(AuditDocument.created_at).where(
        AuditDocument.id == registry.document_id, AuditDocument.case_id == registry.case_id,
        AuditDocument.sha256 == registry.document_sha256,
    ))
    if document_created_at is None:
        raise HTTPException(status_code=409, detail="Исходный документ модельного реестра изменился")
    number = await next_atom_number(db, registry.case_id)
    atom_ids, created_ids = [], []
    for item in items:
        if item.id in existing:
            atom_ids.extend(existing[item.id])
            continue
        atom = AuditAtom(
            id=uuid4(), case_id=registry.case_id, item_code=f"ITEM-{number:03d}",
            title=item.title, digital_product=item.digital_product,
            work_type=item.work_type, object_type=item.object_type,
            source_clause=item.source_clause, notes=item.notes,
            source_refs_json=deepcopy(item.source_refs_json or []),
            source_evidence_text=evidence_text(item.source_refs_json or []),
            source_sheet=ORIGIN_LABELS["ai"], state="draft", sort_order=number * 10,
            ai_registry_item_id=item.id,
            source_fingerprint=scoped_source_fingerprint("ai", registry.id, item.id),
            provenance_json=[_registry_origin(registry, item_id=item.id,
                skill=skills.get(registry.skill_version_id), document_created_at=document_created_at)],
        )
        db.add(atom)
        atom_ids.append(atom.id)
        created_ids.append(atom.id)
        number += 1
    await db.flush()
    # Generation is not a human acceptance or a historical state transition.
    for atom_id in created_ids:
        db.add(AuditEvent(
            case_id=registry.case_id, atom_id=atom_id, actor_id=actor_id,
            event_type="ai_atom_generated", message="ИИ-предложение добавлено в реестр как черновик",
            payload_json={"registry_id": str(registry.id)},
        ))
    await db.flush()
    return PublishModelRegistryAtomsResult(
        list(dict.fromkeys(atom_ids)), created_ids, len(created_ids),
        len({atom_id for linked_ids in existing.values() for atom_id in linked_ids}),
    )


async def load_atom_provenance(
    db: AsyncSession, atoms: list[AuditAtom], *, include_private: bool = False,
) -> dict[UUID, list[AuditAtomOriginRead]]:
    """Batch reconstruction without writes, source bytes, filenames or configs.

    Legacy reuse can add an origin to a pre-existing manual/AI atom, so inverse
    provenance joins are performed even when an immutable snapshot exists.
    """
    if not atoms:
        return {}
    by_id = {atom.id: atom for atom in atoms}
    origins = {atom.id: deepcopy(getattr(atom, "provenance_json", None) or []) for atom in atoms}
    missing = [atom for atom in atoms if not origins[atom.id]]

    imported = [atom for atom in atoms if atom.import_batch_id]
    if imported:
        rows = (await db.execute(select(
            AuditAtom.id.label("atom_id"), AuditImportBatch.id.label("batch_id"),
            AuditImportBatch.sha256, AuditImportBatch.created_at,
            AuditDocument.id.label("document_id"),
            AuditDocument.created_at.label("document_created_at"),
        ).join(AuditImportBatch, AuditImportBatch.id == AuditAtom.import_batch_id).outerjoin(
            AuditDocument, (AuditDocument.case_id == AuditAtom.case_id) & (AuditDocument.sha256 == AuditImportBatch.sha256),
        ).where(AuditAtom.id.in_([atom.id for atom in imported])))).all()
        for row in rows:
            atom = by_id[row.atom_id]
            stored = next((origin for origin in origins[atom.id] if origin.get("kind") == "manual_register"
                           and origin.get("source_register_id") == str(row.batch_id)), None)
            if stored is not None:
                # The document attachment is created after the import snapshot;
                # resolve that link on read without changing the stored snapshot.
                if row.document_id and not stored.get("document_id"):
                    stored.update(document_id=str(row.document_id), document_sha256=row.sha256,
                                  document_created_at=row.document_created_at.isoformat())
                continue
            origins[atom.id].append(origin_snapshot(
                "manual_register", source_register_id=row.batch_id,
                source_register_created_at=row.created_at, source_sha256=row.sha256,
                document_id=row.document_id, document_sha256=row.sha256 if row.document_id else None,
                document_created_at=row.document_created_at,
                source_sheet=atom.source_sheet, source_row=atom.source_row,
            ))

    direct_items = {atom.ai_registry_item_id: atom.id for atom in missing if atom.ai_registry_item_id}
    comparison_drafts = {atom.ai_comparison_draft_id: atom.id for atom in missing if atom.ai_comparison_draft_id}
    registry_links = []
    if direct_items:
        rows = (await db.execute(select(AuditAIModelRegistryItem.id, AuditAIModelRegistryItem.registry_id).where(
            AuditAIModelRegistryItem.id.in_(direct_items),
            AuditAIModelRegistryItem.case_id.in_({atom.case_id for atom in atoms}),
        ))).all()
        registry_links.extend((direct_items[row.id], row.registry_id, row.id, None) for row in rows)
    if comparison_drafts:
        drafts = (await db.scalars(select(AuditAIModelComparisonDraft).where(
            AuditAIModelComparisonDraft.id.in_(comparison_drafts),
        ))).all()
        for draft in drafts:
            for variant in draft.model_variants_json or []:
                try:
                    registry_id = UUID(str(variant["registry_id"]))
                    item_id = UUID(str(variant["registry_item_id"]))
                except (KeyError, ValueError, TypeError):
                    continue
                registry_links.append((comparison_drafts[draft.id], registry_id, item_id, draft.comparison_id))
    if registry_links:
        registries = {registry.id: registry for registry in (await db.scalars(select(AuditAIModelRegistry).where(
            AuditAIModelRegistry.id.in_({link[1] for link in registry_links}),
        ))).all()}
        skills = await _skill_metadata(db, {registry.skill_version_id for registry in registries.values()})
        for atom_id, registry_id, item_id, comparison_id in registry_links:
            registry = registries.get(registry_id)
            if registry and registry.case_id == by_id[atom_id].case_id:
                origins[atom_id].append(_registry_origin(
                    registry, item_id=item_id, comparison_id=comparison_id, skill=skills.get(registry.skill_version_id),
                ))

    attempt_atoms = {atom.ai_atomization_draft_id: atom.id for atom in missing if atom.ai_atomization_draft_id}
    if attempt_atoms:
        rows = (await db.execute(select(AuditAIAtomDraft.id, AuditAIAtomizationAttempt).join(
            AuditAIAtomizationAttempt, AuditAIAtomizationAttempt.id == AuditAIAtomDraft.attempt_id,
        ).where(AuditAIAtomDraft.id.in_(attempt_atoms)))).all()
        skills = await _skill_metadata(db, {attempt.skill_version_id for _, attempt in rows})
        for draft_id, attempt in rows:
            atom_id = attempt_atoms[draft_id]
            if attempt.case_id != by_id[atom_id].case_id:
                continue
            origins[atom_id].append(origin_snapshot(
                "ai", source_register_id=attempt.id, source_register_created_at=attempt.created_at,
                document_id=attempt.document_id, document_sha256=attempt.document_sha256,
                canonical_run_id=attempt.canonical_run_id, attempt_id=attempt.id,
                provider_config_id=attempt.provider_config_id,
                provider_config_version=attempt.provider_config_version, model_name=attempt.model_name,
                skill_version_id=attempt.skill_version_id, skill_sha256=attempt.skill_sha256,
                prompt_sha256=attempt.prompt_sha256, response_sha256=attempt.response_sha256,
                **skills.get(attempt.skill_version_id, {}),
            ))

    legacy_links = (await db.execute(select(
        AuditLegacyProvenance.target_id, AuditLegacyProvenance.transfer_id,
    ).where(
        AuditLegacyProvenance.target_table == "audit_atoms", AuditLegacyProvenance.kind == "atoms",
        AuditLegacyProvenance.active.is_(True), AuditLegacyProvenance.target_id.in_(by_id),
    ))).all()
    legacy_ids = {(atom_id, transfer_id) for atom_id, transfer_id in legacy_links}
    legacy_ids.update((atom.id, atom.legacy_transfer_id) for atom in atoms if atom.legacy_transfer_id)
    if legacy_ids:
        rows = (await db.execute(select(
            AuditLegacyTransfer.id, AuditLegacyTransfer.source_id,
            AuditLegacyImport.sha256, AuditLegacyImport.created_at,
        ).join(AuditLegacyImport, AuditLegacyImport.id == AuditLegacyTransfer.source_id).where(
            AuditLegacyTransfer.id.in_({link[1] for link in legacy_ids}),
            AuditLegacyTransfer.status == "committed",
        ))).all()
        transfers = {row.id: row for row in rows}
        for atom_id, transfer_id in sorted(legacy_ids, key=lambda pair: (str(pair[0]), str(pair[1]))):
            transfer = transfers.get(transfer_id)
            if transfer:
                origins[atom_id].append(origin_snapshot(
                    "historical_import", legacy_transfer_id=transfer_id,
                    historical_effective_at=by_id[atom_id].legacy_effective_at,
                    source_register_id=transfer.source_id, source_sha256=transfer.sha256,
                    source_register_created_at=transfer.created_at,
                ))

    result = {}
    for atom in atoms:
        values, seen = [], set()
        for raw in origins[atom.id] or [origin_snapshot("unknown")]:
            # Explicit allowlist: filenames, provider endpoints and legacy keys
            # cannot leak even if an old snapshot contains additional fields.
            origin = AuditAtomOriginRead.model_validate(raw)
            origin.label = ORIGIN_LABELS[origin.kind]
            if origin.kind == "historical_import" and not include_private:
                origin = origin.model_copy(update={field: None for field in PRIVATE_LEGACY_FIELDS})
            key = origin.model_dump_json()
            if key not in seen:
                values.append(origin)
                seen.add(key)
        result[atom.id] = values
    return result


async def read_audit_atoms(db: AsyncSession, atoms: list[AuditAtom], *, include_private=False) -> list[AuditAtomRead]:
    origins = await load_atom_provenance(db, atoms, include_private=include_private)
    return [AuditAtomRead.model_validate(atom).model_copy(update={"provenance": origins[atom.id]}) for atom in atoms]


def build_atom_provenance_export(audit_case, atoms: list[AuditAtomRead]) -> bytes:
    """Use the existing registry layout plus a normalized, safe origins sheet."""
    from app.services.audit_import import build_audit_atom_export

    def label(origin):
        parts = [origin.label]
        if origin.kind == "ai":
            parts.extend(value for value in (origin.provider_name, origin.model_name) if value)
            if origin.provider_config_version is not None:
                parts.append(f"конфигурация v{origin.provider_config_version}")
            if origin.skill_name or origin.skill_slug:
                parts.append(f"методика {origin.skill_name or origin.skill_slug}")
            if origin.skill_version:
                parts.append(f"версия {origin.skill_version}")
        return ", ".join(parts)

    export_atoms = [SimpleNamespace(**{
        **atom.model_dump(),
        "source_sheet": "; ".join(dict.fromkeys(label(origin) for origin in atom.provenance)),
    }) for atom in atoms]
    base = build_audit_atom_export(audit_case, export_atoms)
    spreadsheet = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    relationships = "http://schemas.openxmlformats.org/package/2006/relationships"
    office_relationships = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    content_types = "http://schemas.openxmlformats.org/package/2006/content-types"
    fields = list(AuditAtomOriginRead.model_fields)
    sheet = ET.Element(f"{{{spreadsheet}}}worksheet")
    sheet_data = ET.SubElement(sheet, f"{{{spreadsheet}}}sheetData")
    rows = [["atom_id", "item_code", *fields]]
    rows.extend(
        [str(atom.id), atom.item_code, *[origin.model_dump(mode="json").get(field) for field in fields]]
        for atom in atoms for origin in atom.provenance
    )
    for number, values in enumerate(rows, 1):
        row = ET.SubElement(sheet_data, f"{{{spreadsheet}}}row", r=str(number))
        for value in values:
            cell = ET.SubElement(row, f"{{{spreadsheet}}}c", t="inlineStr")
            inline = ET.SubElement(cell, f"{{{spreadsheet}}}is")
            text = ET.SubElement(inline, f"{{{spreadsheet}}}t")
            text.text = "".join(char for char in str(value if value is not None else "")
                                if char in "\t\n\r" or ord(char) >= 32)[:32767]
    output = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(base)) as source, zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as target:
        workbook = ET.fromstring(source.read("xl/workbook.xml"))
        rels = ET.fromstring(source.read("xl/_rels/workbook.xml.rels"))
        types = ET.fromstring(source.read("[Content_Types].xml"))
        sheets = workbook.find(f"{{{spreadsheet}}}sheets")
        relationship_id = "rIdAtomOrigins"
        ET.SubElement(sheets, f"{{{spreadsheet}}}sheet", {
            "name": "Источники", "sheetId": "2", f"{{{office_relationships}}}id": relationship_id,
        })
        ET.SubElement(rels, f"{{{relationships}}}Relationship", {
            "Id": relationship_id, "Type": f"{office_relationships}/worksheet", "Target": "worksheets/sheet2.xml",
        })
        ET.SubElement(types, f"{{{content_types}}}Override", {
            "PartName": "/xl/worksheets/sheet2.xml",
            "ContentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml",
        })
        replacements = {"xl/workbook.xml": workbook, "xl/_rels/workbook.xml.rels": rels,
                        "[Content_Types].xml": types, "xl/worksheets/sheet2.xml": sheet}
        for name in source.namelist():
            if name not in replacements:
                target.writestr(name, source.read(name))
        for name, root in replacements.items():
            target.writestr(name, ET.tostring(root, encoding="utf-8", xml_declaration=True))
    return output.getvalue()
