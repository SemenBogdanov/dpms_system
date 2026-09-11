"""Synthetic SQLite provenance tests; never use the configured database."""

from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import io
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4
import xml.etree.ElementTree as ET
import zipfile

from fastapi import HTTPException
from sqlalchemy import Column, DefaultClause, JSON, MetaData, String, Table, delete, event, func, select, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateIndex

from app.models.audit import (
    AuditAIAtomDraft, AuditAIAtomizationAttempt, AuditAIModelComparison,
    AuditAIModelComparisonDraft, AuditAIModelRegistry, AuditAIModelRegistryItem,
    AuditAtom, AuditCase, AuditDocument, AuditEvent, AuditImportBatch,
)
from app.models.audit_legacy import AuditLegacyImport
from app.models.audit_legacy_transfer import AuditLegacyProvenance, AuditLegacyTransfer, AuditLegacyTransferRow
from app.models.audit_runtime import AuditTZRun, AuditTZRuntimeJob
from app.models.user import UserRole
from app.schemas.audit import AuditAtomRead
from app.services import audit_atom_provenance as service
from app.services.audit_import import (
    EXPECTED_HEADERS, commit_audit_import, generate_next_item_code, parse_audit_xlsx_bytes,
)
from tests.test_audit_import import build_xlsx_bytes


class ProvenanceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")

        @event.listens_for(self.engine.sync_engine, "connect")
        def foreign_keys(connection, _):
            connection.isolation_level = None
            connection.execute("PRAGMA foreign_keys=ON")

        @event.listens_for(self.engine.sync_engine, "begin")
        def begin_transaction(connection):
            # SQLite must start the outer transaction before a nested savepoint.
            connection.exec_driver_sql("BEGIN")

        metadata = MetaData()
        for model in (
            AuditCase, AuditAtom, AuditDocument, AuditEvent, AuditImportBatch,
            AuditAIModelRegistry, AuditAIModelRegistryItem, AuditAIModelComparison,
            AuditAIModelComparisonDraft, AuditAIAtomizationAttempt, AuditAIAtomDraft,
            AuditLegacyImport, AuditLegacyTransfer, AuditLegacyProvenance, AuditLegacyTransferRow,
            AuditTZRun, AuditTZRuntimeJob,
        ):
            table = model.__table__.to_metadata(metadata)
            for column in table.c:
                if isinstance(column.type, postgresql.JSONB):
                    column.type = JSON()
        metadata.tables["audit_cases"].c.case_sequence.server_default = DefaultClause(text("1"))
        self.skills = Table("audit_atomization_skills", metadata,
            Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            Column("name", String), Column("slug", String),
        )
        self.versions = Table("audit_atomization_skill_versions", metadata,
            Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            Column("skill_id", postgresql.UUID(as_uuid=True)), Column("version_label", String),
        )
        for table in list(metadata.tables.values()):
            for foreign in table.foreign_keys:
                name = foreign.target_fullname.split(".")[0]
                if name not in metadata.tables:
                    Table(name, metadata, Column("id", postgresql.UUID(as_uuid=True), primary_key=True))
        self.metadata = metadata
        self.actor_id, self.run_id, self.provider_id, self.skill_id, self.version_id = [uuid4() for _ in range(5)]
        async with self.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            for name, identifier in (("users", self.actor_id), ("ai_provider_configs", self.provider_id)):
                await connection.execute(metadata.tables[name].insert().values(id=identifier))
            await connection.execute(self.skills.insert().values(id=self.skill_id, name="Synthetic skill", slug="synthetic"))
            await connection.execute(self.versions.insert().values(id=self.version_id, skill_id=self.skill_id, version_label="1.2"))
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False, autoflush=False)
        self.db = self.sessions()
        self.case = AuditCase(title="Synthetic audit", digital_product="TEST", workflow_stage="atomization")
        self.db.add(self.case)
        await self.db.flush()
        self.document = AuditDocument(
            case_id=self.case.id, kind="technical_spec", display_name="Source",
            original_filename="not-exported.xlsx", stored_filename="synthetic-only",
            content_type="application/octet-stream", size_bytes=1, sha256="d" * 64,
        )
        self.db.add(self.document)
        await self.db.flush()
        self.db.add(AuditTZRun(
            id=self.run_id, case_id=self.case.id, document_id=self.document.id,
            skill_version_id=self.version_id, run_key_hash="z" * 64, identifier_digest="i" * 64,
            source_sha256=self.document.sha256, skill_sha256="s" * 64,
        ))
        await self.db.flush()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def registry(self, *, provider_version=1, count=1):
        registry = AuditAIModelRegistry(
            case_id=self.case.id, canonical_run_id=self.run_id, document_id=self.document.id,
            skill_version_id=self.version_id, provider_config_id=self.provider_id,
            provider_config_version=provider_version, provider_name="Synthetic provider", model_name="test-model",
            document_sha256=self.document.sha256, skill_sha256="s" * 64,
            response_sha256="r" * 64, atom_count=count,
        )
        self.db.add(registry)
        await self.db.flush()
        for number in range(count):
            self.db.add(AuditAIModelRegistryItem(
                registry_id=registry.id, case_id=self.case.id, title="Same proposal",
                digital_product="TEST", source_clause="1", sort_order=number,
                source_fingerprint=f"same-source-{number}",
                source_refs_json=[{"source_unit_id": "p1", "locator": "1", "excerpt": "Evidence"}],
            ))
        await self.db.flush()
        return registry

    async def atom(self, **values):
        atom = AuditAtom(case_id=self.case.id, item_code="MANUAL-1", title="Same proposal", digital_product="TEST", **values)
        self.db.add(atom)
        await self.db.flush()
        return atom

    async def old_attempt(self):
        attempt = AuditAIAtomizationAttempt(
            case_id=self.case.id, document_id=self.document.id, skill_version_id=self.version_id,
            provider_config_id=self.provider_id, provider_config_version=4, model_name="old-model",
            document_sha256=self.document.sha256, skill_sha256="s" * 64, prompt_sha256="p" * 64,
            response_sha256="r" * 64, request_key_hash=uuid4().hex * 2, status="committed",
            consent_confirmed_at=datetime.now(timezone.utc),
        )
        self.db.add(attempt)
        await self.db.flush()
        draft = AuditAIAtomDraft(
            attempt_id=attempt.id, case_id=self.case.id, title="Original proposal", digital_product="TEST",
            source_clause="1", source_fingerprint="f" * 64, review_status="committed",
        )
        self.db.add(draft)
        await self.db.flush()
        return attempt, draft

    async def old_comparison_atom(self, registry, variants, *, case_id=None):
        case_id = case_id or self.case.id
        comparison = AuditAIModelComparison(
            case_id=case_id, canonical_run_id=self.run_id, document_id=self.document.id,
            skill_version_id=self.version_id, comparison_key_hash=uuid4().hex * 2,
            registry_ids_json=[str(registry.id)], status="committed",
        )
        self.db.add(comparison)
        await self.db.flush()
        draft = AuditAIModelComparisonDraft(
            comparison_id=comparison.id, case_id=case_id, title="Original comparison",
            digital_product="TEST", source_clause="1", source_fingerprint=uuid4().hex * 2,
            model_variants_json=variants, registry_count=1,
        )
        self.db.add(draft)
        await self.db.flush()
        atom = AuditAtom(
            case_id=case_id, item_code="OLD-" + uuid4().hex, title="Human corrected comparison",
            digital_product="Human product", ai_comparison_draft_id=draft.id,
            state="ready", alpha_result="present", alpha_comment="Keep decision",
            commission_result="confirmed",
        )
        self.db.add(atom)
        await self.db.flush()
        return atom

    async def test_partial_publication_reuses_old_comparison_by_exact_source_identity(self):
        registry = await self.registry(count=2)
        items = list(await self.db.scalars(select(AuditAIModelRegistryItem).where(
            AuditAIModelRegistryItem.registry_id == registry.id,
        ).order_by(AuditAIModelRegistryItem.sort_order)))
        old = await self.old_comparison_atom(registry, [
            {"registry_id": str(registry.id), "registry_item_id": str(items[0].id)},
        ])
        before = {column.name: deepcopy(getattr(old, column.name)) for column in AuditAtom.__table__.columns}
        result = await service.publish_model_registry_atoms(self.db, registry, self.actor_id)
        self.assertEqual((result.atoms_created, result.atoms_reused), (1, 1))
        self.assertEqual(result.atom_ids, [old.id, *result.created_atom_ids])
        new = await self.db.get(AuditAtom, result.created_atom_ids[0])
        self.assertEqual((new.ai_registry_item_id, new.state), (items[1].id, "draft"))
        self.assertEqual(new.title, items[1].title)
        retry = await service.publish_model_registry_atoms(self.db, registry, self.actor_id)
        self.assertEqual((retry.atoms_created, retry.atoms_reused), (0, 2))
        self.assertEqual(retry.atom_ids, result.atom_ids)
        await self.db.refresh(old)
        self.assertEqual({name: getattr(old, name) for name in before}, before)
        self.assertEqual(await self.db.scalar(select(func.count(AuditAtom.id))), 2)
        self.assertEqual(await self.db.scalar(select(func.count(AuditEvent.id))), 1)

    async def test_partial_publication_reuses_old_canonical_direct_atom(self):
        registry = await self.registry(provider_version=4, count=2)
        items = list(await self.db.scalars(select(AuditAIModelRegistryItem).where(
            AuditAIModelRegistryItem.registry_id == registry.id,
        ).order_by(AuditAIModelRegistryItem.sort_order)))
        attempt, draft = await self.old_attempt()
        attempt.canonical_run_id = self.run_id
        attempt.model_name = registry.model_name
        draft.source_fingerprint = items[0].source_fingerprint
        atom = await self.atom(
            ai_atomization_draft_id=draft.id, state="ready", alpha_result="present",
            alpha_comment="Human decision", commission_result="confirmed",
            provenance_json=[await service.attempt_origin_snapshot(self.db, attempt)],
        )
        atom.title = "Human corrected direct atom"
        atom.source_fingerprint = service.scoped_source_fingerprint("ai_attempt", attempt.id, draft.id)
        await self.db.flush()
        before = {column.name: deepcopy(getattr(atom, column.name)) for column in AuditAtom.__table__.columns}
        result = await service.publish_model_registry_atoms(self.db, registry, self.actor_id)
        self.assertEqual((result.atoms_created, result.atoms_reused), (1, 1))
        self.assertEqual(result.atom_ids, [atom.id, *result.created_atom_ids])
        created = await self.db.get(AuditAtom, result.created_atom_ids[0])
        self.assertEqual((created.ai_registry_item_id, created.state), (items[1].id, "draft"))
        retry = await service.publish_model_registry_atoms(self.db, registry, self.actor_id)
        self.assertEqual((retry.atoms_created, retry.atoms_reused), (0, 2))
        self.assertEqual(retry.atom_ids, result.atom_ids)
        await self.db.refresh(atom)
        self.assertEqual({name: getattr(atom, name) for name in before}, before)
        self.assertEqual(await self.db.scalar(select(func.count(AuditEvent.id))), 1)

    async def test_direct_atom_reuse_rejects_mismatched_attempt_context(self):
        registry = await self.registry(provider_version=4)
        item = await self.db.scalar(select(AuditAIModelRegistryItem).where(
            AuditAIModelRegistryItem.registry_id == registry.id,
        ))
        attempt, draft = await self.old_attempt()
        attempt.canonical_run_id = self.run_id
        attempt.model_name = registry.model_name
        draft.source_fingerprint = item.source_fingerprint
        atom = await self.atom(ai_atomization_draft_id=draft.id, state="ready")
        other_case = AuditCase(title="Other audit", digital_product="OTHER", case_sequence=2)
        self.db.add(other_case)
        await self.db.flush()
        atom_id = atom.id
        for target, field, value in (
            (attempt, "canonical_run_id", None),
            (attempt, "case_id", other_case.id),
            (attempt, "provider_config_version", 9),
            (attempt, "model_name", "different-model"),
            (attempt, "document_sha256", "x" * 64),
            (attempt, "skill_sha256", "x" * 64),
            (attempt, "response_sha256", None),
            (draft, "case_id", other_case.id),
            (draft, "source_fingerprint", "different-source"),
            (atom, "case_id", other_case.id),
        ):
            with self.subTest(model=type(target).__name__, field=field):
                transaction = await self.db.begin_nested()
                setattr(target, field, value)
                await self.db.flush()
                result = await service.publish_model_registry_atoms(self.db, registry, self.actor_id)
                self.assertEqual((result.atoms_created, result.atoms_reused), (1, 0))
                self.assertNotIn(atom_id, result.atom_ids)
                await service.freeze_attempt_atom_origins(self.db, attempt)
                await self.db.refresh(atom)
                self.assertIsNone(atom.ai_registry_item_id)
                await transaction.rollback()
                await self.db.refresh(target)

    async def test_freeze_links_registry_items_before_deleting_drafts_with_existing_snapshots(self):
        registry = await self.registry(provider_version=4, count=2)
        items = list(await self.db.scalars(select(AuditAIModelRegistryItem).where(
            AuditAIModelRegistryItem.registry_id == registry.id,
        ).order_by(AuditAIModelRegistryItem.sort_order)))
        attempt, first_draft = await self.old_attempt()
        attempt.canonical_run_id = self.run_id
        attempt.model_name = registry.model_name
        first_draft.source_fingerprint = items[0].source_fingerprint
        second_draft = AuditAIAtomDraft(
            attempt_id=attempt.id, case_id=self.case.id, title="Second source", digital_product="TEST",
            source_clause="2", source_fingerprint=items[1].source_fingerprint,
        )
        self.db.add(second_draft)
        await self.db.flush()
        stored = [await service.attempt_origin_snapshot(self.db, attempt)]
        first = await self.atom(
            ai_atomization_draft_id=first_draft.id, state="ready", alpha_comment="Keep first",
            provenance_json=deepcopy(stored),
        )
        second = AuditAtom(
            case_id=self.case.id, item_code="OLD-SECOND", title="Human edited second", digital_product="TEST",
            ai_atomization_draft_id=second_draft.id, state="ready", commission_result="confirmed",
        )
        self.db.add(second)
        await self.db.flush()
        excluded = {"provenance_json", "ai_atomization_draft_id", "ai_registry_item_id"}
        before = {atom.id: {column.name: deepcopy(getattr(atom, column.name))
                           for column in AuditAtom.__table__.columns if column.name not in excluded}
                  for atom in (first, second)}
        self.assertEqual(await service.freeze_attempt_atom_origins(self.db, attempt), 1)
        await self.db.refresh(first)
        await self.db.refresh(second)
        self.assertEqual([first.ai_registry_item_id, second.ai_registry_item_id], [item.id for item in items])
        self.assertEqual(first.provenance_json, stored)
        self.assertEqual(await service.freeze_attempt_atom_origins(self.db, attempt), 0)
        await self.db.execute(delete(AuditAIAtomDraft).where(AuditAIAtomDraft.attempt_id == attempt.id))
        attempt.provider_config_version = 99
        attempt.model_name = "Another model"
        attempt.document_sha256 = "n" * 64
        attempt.skill_sha256 = "n" * 64
        attempt.response_sha256 = None
        await self.db.commit()
        for atom in (first, second):
            await self.db.refresh(atom)
            self.assertIsNone(atom.ai_atomization_draft_id)
            self.assertEqual({name: getattr(atom, name) for name in before[atom.id]}, before[atom.id])
        self.assertEqual(first.provenance_json, stored)
        for _ in range(2):
            result = await service.publish_model_registry_atoms(self.db, registry, self.actor_id)
            self.assertEqual((result.atoms_created, result.atoms_reused), (0, 2))
            self.assertEqual(result.atom_ids, [first.id, second.id])
        self.assertEqual(await self.db.scalar(select(func.count(AuditAtom.id))), 2)
        self.assertEqual(await self.db.scalar(select(func.count(AuditEvent.id))), 0)

    async def test_freeze_registry_link_rejects_an_already_owned_item(self):
        registry = await self.registry(provider_version=4)
        item = await self.db.scalar(select(AuditAIModelRegistryItem).where(
            AuditAIModelRegistryItem.registry_id == registry.id,
        ))
        attempt, draft = await self.old_attempt()
        attempt.canonical_run_id = self.run_id
        attempt.model_name = registry.model_name
        draft.source_fingerprint = item.source_fingerprint
        old = await self.atom(ai_atomization_draft_id=draft.id, state="ready", alpha_comment="Keep")
        owner = AuditAtom(
            case_id=self.case.id, item_code="OWNER", title="Existing owner", digital_product="TEST",
            ai_registry_item_id=item.id, provenance_json=[service.origin_snapshot("ai")],
        )
        self.db.add(owner)
        await self.db.flush()
        with self.assertRaises(HTTPException) as raised:
            await service.freeze_attempt_atom_origins(self.db, attempt)
        self.assertEqual(raised.exception.status_code, 409)
        self.assertIsNone(old.ai_registry_item_id)
        self.assertEqual(old.provenance_json, [])
        self.assertEqual(old.ai_atomization_draft_id, draft.id)
        self.assertEqual(owner.ai_registry_item_id, item.id)

    async def test_freeze_registry_link_rolls_back_with_nonempty_snapshot(self):
        registry = await self.registry(provider_version=4)
        item = await self.db.scalar(select(AuditAIModelRegistryItem).where(
            AuditAIModelRegistryItem.registry_id == registry.id,
        ))
        attempt, draft = await self.old_attempt()
        attempt.canonical_run_id = self.run_id
        attempt.model_name = registry.model_name
        draft.source_fingerprint = item.source_fingerprint
        stored = [await service.attempt_origin_snapshot(self.db, attempt)]
        old = await self.atom(ai_atomization_draft_id=draft.id, provenance_json=deepcopy(stored))
        old_id, draft_id = old.id, draft.id
        await self.db.commit()
        self.assertEqual(await service.freeze_attempt_atom_origins(self.db, attempt), 0)
        await self.db.refresh(old)
        self.assertEqual(old.ai_registry_item_id, item.id)
        await self.db.rollback()
        persisted = await self.db.get(AuditAtom, old_id)
        self.assertIsNone(persisted.ai_registry_item_id)
        self.assertEqual(persisted.ai_atomization_draft_id, draft_id)
        self.assertEqual(persisted.provenance_json, stored)

    async def test_batched_publication_lookup_is_read_only_and_counts_source_items(self):
        direct = await self.registry(count=2)
        direct_result = await service.publish_model_registry_atoms(self.db, direct, self.actor_id)
        canonical = await self.registry(provider_version=4, count=2)
        canonical_items = list(await self.db.scalars(select(AuditAIModelRegistryItem).where(
            AuditAIModelRegistryItem.registry_id == canonical.id,
        ).order_by(AuditAIModelRegistryItem.sort_order)))
        attempt, draft = await self.old_attempt()
        attempt.canonical_run_id = self.run_id
        attempt.model_name = canonical.model_name
        draft.source_fingerprint = canonical_items[0].source_fingerprint
        canonical_atom = await self.atom(ai_atomization_draft_id=draft.id, state="ready")
        comparison = await self.registry(provider_version=3, count=2)
        comparison_items = list(await self.db.scalars(select(AuditAIModelRegistryItem).where(
            AuditAIModelRegistryItem.registry_id == comparison.id,
        )))
        old = await self.old_comparison_atom(comparison, [
            {"registry_id": str(comparison.id), "registry_item_id": str(item.id)} for item in comparison_items
        ])
        empty = await self.registry(provider_version=5)
        registries = [direct, canonical, comparison, empty]
        await self.db.flush()
        self.db.autoflush = True
        with patch.object(self.db, "execute", wraps=self.db.execute) as execute, patch.object(
            self.db, "flush", side_effect=AssertionError("Read-only lookup must not flush"),
        ), patch.object(
            self.db.sync_session, "flush", side_effect=AssertionError("Read-only lookup must not autoflush"),
        ):
            result = await service.lookup_published_registry_items_batch(self.db, registries)
        self.db.autoflush = False
        self.assertEqual(execute.await_count, 3)
        self.assertEqual([len(result[registry.id]) for registry in registries], [2, 1, 2, 0])
        self.assertEqual({atom_id for ids in result[direct.id].values() for atom_id in ids}, set(direct_result.atom_ids))
        self.assertEqual(result[canonical.id], {canonical_items[0].id: [canonical_atom.id]})
        self.assertEqual(result[comparison.id], {item.id: [old.id] for item in comparison_items})
        self.assertEqual(await service.lookup_published_registry_items(self.db, canonical), result[canonical.id])
        self.assertEqual(await service.lookup_published_registry_items_batch(self.db, []), {})
        self.assertEqual((old.provenance_json, canonical_atom.provenance_json), ([], []))
        self.assertFalse(self.db.dirty)

    async def test_publication_returns_unique_atom_ids_for_shared_comparison_origin(self):
        registry = await self.registry(count=2)
        items = list(await self.db.scalars(select(AuditAIModelRegistryItem).where(
            AuditAIModelRegistryItem.registry_id == registry.id,
        )))
        variants = [{"registry_id": str(registry.id), "registry_item_id": str(item.id)} for item in items]
        old = await self.old_comparison_atom(registry, [*variants, variants[0]])
        result = await service.publish_model_registry_atoms(self.db, registry, self.actor_id)
        self.assertEqual(result.atom_ids, [old.id])
        self.assertEqual(result.created_atom_ids, [])
        self.assertEqual((result.atoms_created, result.atoms_reused), (0, 1))
        self.assertEqual(await self.db.scalar(select(func.count(AuditEvent.id))), 0)

    async def test_old_comparison_reuse_requires_same_case_and_both_source_ids(self):
        registry = await self.registry()
        item = await self.db.scalar(select(AuditAIModelRegistryItem).where(
            AuditAIModelRegistryItem.registry_id == registry.id,
        ))
        other_case = AuditCase(title="Other audit", digital_product="OTHER", case_sequence=2)
        self.db.add(other_case)
        await self.db.flush()
        wrong_case = await self.old_comparison_atom(registry, [
            {"registry_id": str(registry.id), "registry_item_id": str(item.id)},
        ], case_id=other_case.id)
        wrong_identity = await self.old_comparison_atom(registry, [
            {"registry_id": str(uuid4()), "registry_item_id": str(item.id)},
            {"registry_id": str(registry.id), "registry_item_id": str(uuid4())},
            {"registry_id": str(registry.id), "registry_item_id": "invalid"},
            {"registry_id": str(registry.id)}, None, "invalid",
        ])
        wrong_identity.title = item.title
        wrong_identity.digital_product = item.digital_product
        await self.db.flush()
        result = await service.publish_model_registry_atoms(self.db, registry, self.actor_id)
        self.assertEqual((result.atoms_created, result.atoms_reused), (1, 0))
        self.assertNotIn(wrong_case.id, result.atom_ids)
        self.assertNotIn(wrong_identity.id, result.atom_ids)

    async def test_freeze_attempt_origin_survives_draft_deletion_and_context_reuse(self):
        attempt, draft = await self.old_attempt()
        _, other_draft = await self.old_attempt()
        atom = await self.atom(
            ai_atomization_draft_id=draft.id, state="ready", alpha_result="present",
            alpha_comment="Human decision", commission_result="confirmed", notes="Human correction",
        )
        stored = [service.origin_snapshot("ai", model_name="Already frozen model")]
        frozen_draft = AuditAIAtomDraft(
            attempt_id=attempt.id, case_id=self.case.id, title="Other proposal", digital_product="TEST",
            source_clause="2", source_fingerprint="g" * 64,
        )
        self.db.add(frozen_draft)
        await self.db.flush()
        untouched = [
            AuditAtom(case_id=self.case.id, item_code="FROZEN", title="Frozen", digital_product="TEST",
                      ai_atomization_draft_id=frozen_draft.id, provenance_json=stored),
            AuditAtom(case_id=self.case.id, item_code="OTHER", title="Other attempt", digital_product="TEST",
                      ai_atomization_draft_id=other_draft.id),
            AuditAtom(case_id=self.case.id, item_code="UNKNOWN", title="Unknown", digital_product="TEST"),
        ]
        self.db.add_all(untouched)
        await self.db.flush()
        human_fields = {column.name: deepcopy(getattr(atom, column.name)) for column in AuditAtom.__table__.columns
                        if column.name not in {"provenance_json", "ai_atomization_draft_id"}}
        untouched_origins = [deepcopy(row.provenance_json) for row in untouched]
        self.assertEqual(await service.freeze_attempt_atom_origins(self.db, attempt), 1)
        expected = deepcopy(atom.provenance_json)
        self.assertEqual(expected[0]["attempt_id"], str(attempt.id))
        self.assertEqual(expected[0]["provider_config_id"], str(self.provider_id))
        self.assertEqual(expected[0]["provider_config_version"], 4)
        self.assertEqual(expected[0]["model_name"], "old-model")
        self.assertEqual(expected[0]["document_id"], str(self.document.id))
        self.assertEqual(expected[0]["document_sha256"], "d" * 64)
        self.assertEqual(expected[0]["skill_version_id"], str(self.version_id))
        self.assertEqual(expected[0]["skill_sha256"], "s" * 64)
        self.assertEqual(expected[0]["skill_version"], "1.2")
        self.assertEqual(expected[0]["prompt_sha256"], "p" * 64)
        self.assertEqual(expected[0]["response_sha256"], "r" * 64)
        self.assertNotIn("provider_name", expected[0])
        self.assertEqual(await service.freeze_attempt_atom_origins(self.db, attempt), 0)
        await self.db.execute(delete(AuditAIAtomDraft).where(AuditAIAtomDraft.attempt_id == attempt.id))
        new_provider_id, new_version_id = uuid4(), uuid4()
        await self.db.execute(self.metadata.tables["ai_provider_configs"].insert().values(id=new_provider_id))
        await self.db.execute(self.versions.insert().values(
            id=new_version_id, skill_id=self.skill_id, version_label="2.0",
        ))
        attempt.provider_config_id = new_provider_id
        attempt.provider_config_version = 9
        attempt.model_name = "new-model"
        attempt.skill_version_id = new_version_id
        attempt.skill_sha256 = "n" * 64
        attempt.response_sha256 = None
        await self.db.commit()
        await self.db.refresh(atom)
        self.assertIsNone(atom.ai_atomization_draft_id)
        self.assertEqual(atom.provenance_json, expected)
        projected = (await service.read_audit_atoms(self.db, [atom]))[0]
        self.assertEqual(projected.provenance[0].model_name, "old-model")
        self.assertEqual(projected.provenance[0].skill_version, "1.2")
        self.assertEqual({name: getattr(atom, name) for name in human_fields}, human_fields)
        for row, origin in zip(untouched, untouched_origins):
            await self.db.refresh(row)
            self.assertEqual(row.provenance_json, origin)
        self.assertEqual(await service.freeze_attempt_atom_origins(self.db, attempt), 0)
        self.assertEqual(await self.db.scalar(select(func.count(AuditEvent.id))), 0)

    async def test_freeze_attempt_origin_rolls_back_with_caller_transaction(self):
        attempt, draft = await self.old_attempt()
        atom = await self.atom(ai_atomization_draft_id=draft.id, state="ready", alpha_comment="Keep")
        atom_id, draft_id = atom.id, draft.id
        await self.db.commit()
        self.assertEqual(await service.freeze_attempt_atom_origins(self.db, attempt), 1)
        await self.db.execute(delete(AuditAIAtomDraft).where(AuditAIAtomDraft.attempt_id == attempt.id))
        await self.db.rollback()
        persisted = await self.db.get(AuditAtom, atom_id)
        self.assertEqual(persisted.provenance_json, [])
        self.assertEqual(persisted.ai_atomization_draft_id, draft_id)
        self.assertEqual((persisted.state, persisted.alpha_comment), ("ready", "Keep"))

    async def test_legacy_attempt_list_endpoint_is_scoped_includes_committed_and_drafts(self):
        from fastapi import FastAPI
        from httpx import ASGITransport, AsyncClient
        from app.api.routes import audit as routes
        from app.schemas.audit_ai import AuditAIAtomDraftRead, AuditAIAtomizationAttemptRead

        committed, committed_draft = await self.old_attempt()
        ready, ready_draft = await self.old_attempt()
        ready.status = "draft_ready"
        canonical, _ = await self.old_attempt()
        canonical.canonical_run_id = self.run_id
        other_case = AuditCase(title="Other audit", digital_product="OTHER", case_sequence=2)
        self.db.add(other_case)
        await self.db.flush()
        other, other_draft = await self.old_attempt()
        other.case_id = other_case.id
        other_draft.case_id = other_case.id
        self.case.status = "archived"
        await self.db.flush()
        serialized = {}
        for attempt, draft in ((committed, committed_draft), (ready, ready_draft)):
            serialized[attempt.id] = AuditAIAtomizationAttemptRead(
                id=attempt.id, case_id=attempt.case_id, document_id=attempt.document_id,
                skill_version_id=attempt.skill_version_id, skill_name="Synthetic skill", skill_version="1.2",
                status=attempt.status, config_version=attempt.config_version,
                provider_config_id=attempt.provider_config_id, provider_name="Synthetic provider",
                model_name=attempt.model_name, document_sha256=attempt.document_sha256,
                skill_sha256=attempt.skill_sha256, created_at=attempt.created_at,
                drafts=[AuditAIAtomDraftRead(
                    id=draft.id, title=draft.title, digital_product=draft.digital_product,
                    source_clause=draft.source_clause, review_status=draft.review_status, sort_order=draft.sort_order,
                )],
            )

        async def serialize(db, attempt_id):
            self.assertIs(db, self.db)
            return serialized[attempt_id]

        async def db_dependency():
            yield self.db

        async def member():
            return SimpleNamespace(id=self.actor_id, role=UserRole.admin)

        async def denied():
            raise HTTPException(status_code=403, detail="Forbidden")

        app = FastAPI()
        app.include_router(routes.router, prefix="/api/audit")
        app.dependency_overrides[routes.get_db] = db_dependency
        app.dependency_overrides[routes.require_audit_workspace_member] = member
        with patch.object(routes, "_serialize_ai_attempt", side_effect=serialize) as serializer:
            async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                path = f"/api/audit/cases/{self.case.id}/ai-atomization/attempts"
                response = await client.get(path)
                self.assertEqual(response.status_code, 200)
                values = response.json()
                self.assertEqual([item["id"] for item in values], [str(ready.id), str(committed.id)])
                self.assertEqual({item["status"] for item in values}, {"draft_ready", "committed"})
                self.assertEqual(values[1]["drafts"][0]["id"], str(committed_draft.id))
                self.assertEqual(serializer.await_count, 2)
                self.assertEqual((await client.get(f"/api/audit/cases/{uuid4()}/ai-atomization/attempts")).status_code, 404)
                app.dependency_overrides[routes.require_audit_workspace_member] = denied
                self.assertEqual((await client.get(path)).status_code, 403)
                self.assertEqual(serializer.await_count, 2)
        self.assertFalse(self.db.dirty)

    async def test_publication_appends_drafts_and_retry_preserves_human_decisions(self):
        manual = await self.atom(state="ready", alpha_result="present", provenance_json=[service.origin_snapshot("manual")])
        registry = await self.registry(count=2)
        result = await service.publish_model_registry_atoms(self.db, registry, self.actor_id)
        self.assertEqual((result.atoms_created, result.atoms_reused), (2, 0))
        self.assertEqual(result.atom_ids, result.created_atom_ids)
        atoms = list((await self.db.scalars(select(AuditAtom).where(AuditAtom.id.in_(result.atom_ids)))).all())
        self.assertTrue(all(atom.state == "draft" and atom.alpha_result is None for atom in atoms))
        snapshot = deepcopy(atoms[0].provenance_json)
        atoms[0].title = "Human correction"
        atoms[0].state = "ready"
        atoms[0].alpha_result = "partial"
        atoms[0].alpha_comment = "Keep this decision"
        await self.db.flush()
        retried = await service.publish_model_registry_atoms(self.db, registry, self.actor_id)
        self.assertEqual((retried.atoms_created, retried.atoms_reused), (0, 2))
        self.assertEqual(retried.atom_ids, result.atom_ids)
        self.assertEqual(atoms[0].title, "Human correction")
        self.assertEqual(atoms[0].alpha_comment, "Keep this decision")
        self.assertEqual(atoms[0].provenance_json, snapshot)
        self.assertEqual(manual.alpha_result, "present")
        self.assertEqual(self.case.workflow_stage, "atomization")
        self.assertEqual(await self.db.scalar(select(func.count(AuditEvent.id))), 2)
        self.assertEqual(snapshot[0]["skill_version"], "1.2")
        self.assertEqual(snapshot[0]["provider_config_version"], 1)
        self.assertNotIn("filename", str(snapshot))

    async def test_identical_proposals_from_different_registries_coexist(self):
        first = await service.publish_model_registry_atoms(self.db, await self.registry(), self.actor_id)
        second = await service.publish_model_registry_atoms(self.db, await self.registry(provider_version=2), self.actor_id)
        self.assertNotEqual(first.atom_ids, second.atom_ids)
        fingerprints = (await self.db.scalars(select(AuditAtom.source_fingerprint))).all()
        self.assertEqual(len(set(fingerprints)), 2)

    async def test_late_stage_keeps_registry_without_publishing(self):
        registry = await self.registry()
        for stage in ("alpha_review", "commission_pending", "ready"):
            self.case.workflow_stage = stage
            await self.db.flush()
            with self.assertRaises(HTTPException) as raised:
                await service.publish_model_registry_atoms(self.db, registry, self.actor_id)
            self.assertEqual(raised.exception.status_code, 409)
            self.assertIn("Атомизация", raised.exception.detail)
        self.assertEqual(await self.db.scalar(select(func.count(AuditAtom.id))), 0)
        self.assertIsNotNone(await self.db.get(AuditAIModelRegistry, registry.id))

    async def test_allocator_uses_numeric_maximum_and_shared_case_lock(self):
        for index, code in enumerate(("ITEM-999", "ITEM-1000", "ITEM-junk", "OTHER-9999")):
            self.db.add(AuditAtom(case_id=self.case.id, item_code=code, title=str(index), digital_product="TEST"))
        await self.db.flush()
        statements = []
        original = self.db.execute

        async def capture(statement, *args, **kwargs):
            statements.append(str(statement.compile(dialect=postgresql.dialect())))
            return await original(statement, *args, **kwargs)

        with patch.object(self.db, "execute", side_effect=capture):
            self.assertEqual(await generate_next_item_code(self.db, self.case.id), "ITEM-1001")
        self.assertTrue(any("audit_cases" in query and "FOR UPDATE" in query for query in statements))
        result = await service.publish_model_registry_atoms(self.db, await self.registry(count=2), self.actor_id)
        codes = (await self.db.scalars(select(AuditAtom.item_code).where(AuditAtom.id.in_(result.atom_ids)))).all()
        self.assertEqual(set(codes), {"ITEM-1001", "ITEM-1002"})

    async def test_read_unknown_does_not_invent_manual_or_dirty_rows(self):
        atom = await self.atom()
        timestamp = atom.updated_at
        result = (await service.read_audit_atoms(self.db, [atom]))[0]
        self.assertEqual(result.provenance[0].kind, "unknown")
        self.assertEqual(atom.provenance_json, [])
        self.assertEqual(atom.updated_at, timestamp)
        self.assertFalse(self.db.dirty)

    async def test_legacy_reuse_is_reconstructed_and_redacted_without_writes(self):
        atom = await self.atom(provenance_json=[service.origin_snapshot("manual")])
        source = AuditLegacyImport(sha256="l" * 64, size_bytes=1, source_bytes=b"synthetic", inspection={})
        self.db.add(source)
        await self.db.flush()
        transfer = AuditLegacyTransfer(source_id=source.id, namespace="synthetic", config={}, status="committed")
        self.db.add(transfer)
        await self.db.flush()
        self.db.add(AuditLegacyProvenance(
            transfer_id=transfer.id, namespace="synthetic", kind="atoms",
            source_key="opaque", source_key_hash="h" * 64, content_hash="c" * 64,
            target_table="audit_atoms", target_id=atom.id,
        ))
        await self.db.flush()
        before = deepcopy(atom.provenance_json)
        public = (await service.read_audit_atoms(self.db, [atom]))[0]
        private = (await service.read_audit_atoms(self.db, [atom], include_private=True))[0]
        self.assertEqual({origin.kind for origin in public.provenance}, {"manual", "historical_import"})
        historical = next(origin for origin in public.provenance if origin.kind == "historical_import")
        self.assertIsNone(historical.source_register_id)
        self.assertIsNone(historical.source_sha256)
        self.assertEqual(private.provenance[-1].source_register_id, source.id)
        self.assertEqual(atom.provenance_json, before)
        self.assertFalse(self.db.dirty)

    async def test_original_comparison_provenance_and_human_atom_are_preserved(self):
        registries = [await self.registry(), await self.registry(provider_version=2)]
        items = list((await self.db.scalars(select(AuditAIModelRegistryItem))).all())
        comparison = AuditAIModelComparison(
            case_id=self.case.id, canonical_run_id=self.run_id, document_id=self.document.id,
            skill_version_id=self.version_id, comparison_key_hash="k" * 64,
            registry_ids_json=[str(registry.id) for registry in registries], status="committed",
        )
        self.db.add(comparison)
        await self.db.flush()
        draft = AuditAIModelComparisonDraft(
            comparison_id=comparison.id, case_id=self.case.id, title="Reviewed comparison",
            digital_product="TEST", source_clause="1", source_fingerprint="f" * 64,
            registry_count=2,
            model_variants_json=[{"registry_id": str(item.registry_id), "registry_item_id": str(item.id)} for item in items],
        )
        self.db.add(draft)
        await self.db.flush()
        atom = await self.atom(ai_comparison_draft_id=draft.id, state="ready", commission_result="confirmed")
        result = (await service.read_audit_atoms(self.db, [atom]))[0]
        self.assertEqual(len(result.provenance), 2)
        self.assertEqual({origin.source_register_id for origin in result.provenance}, {registry.id for registry in registries})
        self.assertEqual(atom.commission_result, "confirmed")
        self.assertEqual(await self.db.scalar(select(func.count(AuditAtom.id))), 1)

    async def test_manual_upload_snapshots_and_same_payload_in_other_upload(self):
        rows = [[], EXPECTED_HEADERS, [1, "TEST", "SYNTHETIC-1", None, None, None, "Same proposal", "1", None, None, None, None, None]]
        first = parse_audit_xlsx_bytes(build_xlsx_bytes(rows), "not-persisted.xlsx")
        second = parse_audit_xlsx_bytes(build_xlsx_bytes(rows, extra_members={"synthetic.txt": b"v2"}), "not-persisted.xlsx")
        self.assertNotEqual(first.rows[0].source_fingerprint, second.rows[0].source_fingerprint)
        for parsed in (first, second):
            with patch("app.services.audit_import.parse_audit_upload", return_value=parsed), patch(
                "app.services.audit_import.encrypt_contract_reference", return_value="synthetic-ciphertext",
            ):
                result = await commit_audit_import(self.db, None, SimpleNamespace(id=self.actor_id), parsed.sha256, target_case_id=self.case.id)
                self.assertEqual(result.created_atom_count, 1)
        atoms = list((await self.db.scalars(select(AuditAtom))).all())
        self.assertEqual(len(atoms), 2)
        self.assertNotEqual(atoms[0].import_batch_id, atoms[1].import_batch_id)
        self.assertTrue(all(atom.provenance_json[0]["kind"] == "manual_register" for atom in atoms))

    async def test_restrict_standalone_item_deletion_and_allow_archived_case_route(self):
        from app.api.routes import audit as routes
        from app.schemas.audit import AuditCaseDeleteRequest

        registry = await self.registry()
        result = await service.publish_model_registry_atoms(self.db, registry, self.actor_id)
        atom = await self.db.get(AuditAtom, result.atom_ids[0])
        item_id = atom.ai_registry_item_id
        with self.assertRaises(IntegrityError):
            async with self.db.begin_nested():
                await self.db.execute(delete(AuditAIModelRegistryItem).where(AuditAIModelRegistryItem.id == item_id))
        self.case.status = "archived"
        await self.db.flush()
        with patch.object(routes, "record_activity_event", new=AsyncMock()), patch.object(routes, "remove_audit_case_files") as remove:
            response = await routes.delete_audit_case(
                self.case.id, AuditCaseDeleteRequest(confirmation_code=self.case.case_number),
                manager=SimpleNamespace(id=self.actor_id, role=UserRole.admin), db=self.db,
            )
        self.assertEqual(response.deleted_atoms_count, 1)
        self.assertEqual(await self.db.scalar(select(func.count(AuditCase.id))), 0)
        self.assertEqual(await self.db.scalar(select(func.count(AuditAIModelRegistryItem.id))), 0)
        remove.assert_called_once()

    async def test_list_detail_source_filter_and_export_share_provenance(self):
        from app.api.routes import audit as routes

        await self.atom(provenance_json=[service.origin_snapshot("manual")])
        result = await service.publish_model_registry_atoms(self.db, await self.registry(), self.actor_id)
        user = SimpleNamespace(id=self.actor_id, role=UserRole.admin)
        listed = await routes.list_audit_atoms(self.case.id, source_kind="ai", user=user, db=self.db)
        detail = await routes.get_audit_atom(self.case.id, result.atom_ids[0], user=user, db=self.db)
        self.assertEqual([atom.id for atom in listed], result.atom_ids)
        self.assertEqual(listed[0].provenance, detail.provenance)
        exported = await routes.export_audit_atoms(self.case.id, source_kind="ai", user=user, db=self.db)
        with zipfile.ZipFile(io.BytesIO(exported.body)) as archive:
            main = archive.read("xl/worksheets/sheet1.xml").decode()
            self.assertIn("Synthetic provider", main)
            self.assertIn("Synthetic skill", main)
            self.assertIn("1.2", main)
            self.assertNotIn("MANUAL-1", main)

    async def test_older_attempt_commit_appends_without_overwriting_manual(self):
        from app.api.routes import audit as routes
        from app.schemas.audit_ai import AuditAIAtomizationCommit, AuditAIAtomDraftCommitItem

        manual = await self.atom(state="ready", alpha_result="present")
        attempt = AuditAIAtomizationAttempt(
            case_id=self.case.id, document_id=self.document.id, skill_version_id=self.version_id,
            provider_config_id=self.provider_id, provider_config_version=4, model_name="old-model",
            document_sha256=self.document.sha256, skill_sha256="s" * 64, prompt_sha256="p" * 64,
            request_key_hash="q" * 64, status="draft_ready", consent_confirmed_at=datetime.now(timezone.utc),
        )
        self.db.add(attempt)
        await self.db.flush()
        draft = AuditAIAtomDraft(
            attempt_id=attempt.id, case_id=self.case.id, title="Same proposal", digital_product="TEST",
            source_clause="1", source_fingerprint="f" * 64,
        )
        self.db.add(draft)
        await self.db.flush()
        body = AuditAIAtomizationCommit(
            request_id=uuid4(), expected_config_version=attempt.config_version,
            drafts=[AuditAIAtomDraftCommitItem(id=draft.id, title=draft.title, digital_product=draft.digital_product)],
        )
        user = SimpleNamespace(id=self.actor_id, role=UserRole.admin)
        result = await routes.commit_ai_atomization_attempt(self.case.id, attempt.id, body, user=user, db=self.db)
        atom = await self.db.get(AuditAtom, result.atom_ids[0])
        self.assertEqual(result.atoms_created, 1)
        self.assertEqual(atom.state, "draft")
        self.assertEqual(manual.alpha_result, "present")
        self.assertEqual(atom.provenance_json[0]["provider_config_version"], 4)
        retry = await routes.commit_ai_atomization_attempt(self.case.id, attempt.id, body, user=user, db=self.db)
        self.assertTrue(retry.already_committed)
        self.assertEqual(await self.db.scalar(select(func.count(AuditAtom.id))), 2)

    async def test_export_origins_are_typed_strings_and_exclude_private_extras(self):
        atom = await self.atom(provenance_json=[{
            **service.origin_snapshot("manual"), "filename": "DO-NOT-EXPORT", "provider_url": "DO-NOT-EXPORT",
        }])
        reads = await service.read_audit_atoms(self.db, [atom])
        content = service.build_atom_provenance_export(self.case, reads)
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            self.assertIsNone(archive.testzip())
            origins = archive.read("xl/worksheets/sheet2.xml")
            self.assertNotIn(b"DO-NOT-EXPORT", origins)
            self.assertIn(str(atom.id).encode(), origins)
            self.assertIn("Источники".encode(), archive.read("xl/workbook.xml"))
            root = ET.fromstring(origins)
            ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            self.assertTrue(all(cell.attrib["t"] == "inlineStr" for cell in root.findall(".//s:c", ns)))


class ProvenanceMigrationTests(unittest.TestCase):
    def test_publication_has_unique_fk_and_read_only_api_snapshot(self):
        foreign = next(iter(AuditAtom.__table__.c.ai_registry_item_id.foreign_keys))
        self.assertEqual(foreign.ondelete, "RESTRICT")
        index = next(index for index in AuditAtom.__table__.indexes if index.name == "uq_audit_atoms_ai_registry_item_id")
        sql = str(CreateIndex(index).compile(dialect=postgresql.dialect()))
        self.assertIn("UNIQUE", sql)
        self.assertIn("IS NOT NULL", sql)
        self.assertIn("provenance", AuditAtomRead.model_fields)

    def test_migration_normalizes_legacy_receipts_without_publishing(self):
        path = Path(__file__).parents[1] / "alembic/versions/085_audit_atom_provenance.py"
        spec = importlib.util.spec_from_file_location("provenance_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        with patch.object(migration, "op") as op:
            migration.upgrade()
        statements = "\n".join(str(call.args[0]) for call in op.execute.call_args_list)
        self.assertIn("UPDATE audit_legacy_transfer_rows", statements)
        self.assertIn("CREATE TRIGGER", statements)
        self.assertNotIn("INSERT INTO audit_atoms", statements)
        self.assertNotIn("UPDATE audit_atoms", statements)
        self.assertEqual(migration.down_revision, "084_audit_declarative_skills")


if __name__ == "__main__":
    unittest.main()
