"""Disposable PostgreSQL + in-process ASGI multisource integration acceptance.

Run against an isolated local PostgreSQL, not the shared application database:
  DPMS_MIGRATION_SMOKE_ALLOW_CREATE_DATABASE=1 PYTHONDONTWRITEBYTECODE=1 \
    python -B -m scripts.smoke_audit_multisource --allow-create-database

The default (also --synthetic-skill) generates a synthetic data-only archive in
memory, without host files. To test the actual supplied six-file package, add
--archive /mounted/audit-tz-atoms.skill. An explicit missing/invalid archive never
falls back to the synthetic fixture. Output identifies the source in both modes.

DATABASE_URL must be supplied through the process environment. Dotenv files are
not loaded. The script creates, migrates, fences all application sessions into,
and finally drops its own database. No lifespan, real users, worker daemon,
external AI, archive extraction, or application implementation writes.
Historical/XLSX origins and immutable AI responses are synthetic DB fixtures;
manual creation, publication, comparison, review and archive import use ASGI.
"""

import argparse
import asyncio
from contextlib import ExitStack
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from io import BytesIO
import json
import logging
import os
from pathlib import Path
import re
import sys
import traceback
from unittest.mock import patch
from uuid import UUID, uuid4
from zipfile import ZipFile, ZipInfo


OPT_IN_ENV = "DPMS_MIGRATION_SMOKE_ALLOW_CREATE_DATABASE"
TEMP_NAME = re.compile(r"^dpms_multisource_[0-9a-f]{12}$")
ROOT = Path(__file__).resolve().parents[1]
AUDIT = "/api/audit/cases"
SKILLS = "/api/admin/integrations/ai/skills"
SCENARIOS = (
    "four_source_coexistence", "cross_method_comparison", "concurrent_comparison_creation", "document_binding_guards",
    "publish_retry_preserves_ready", "legacy_partial_comparison_publication", "legacy_canonical_draft_reuse",
    "allocation_beyond_999", "concurrent_publication",
    "publication_rollback", "role_crosscase_stage_guards", "comparison_review_isolation",
    "comparison_review_all_rejected", "comparison_review_without_publication",
    "legacy_attempt_origin_freeze", "worker_publication_eligibility",
    "skill_archive_data_only", "migration_084_downgrade_guard",
    "migration_085_downgrade_guard", "migration_085_legacy_rollback", "case_delete_cascade",
)
SNAPSHOT_TABLES = (
    "audit_cases", "audit_atoms", "audit_tz_runs", "audit_ai_model_registries",
    "audit_ai_model_registry_items",
)


class Blocked(Exception):
    """Only hardcoded safe blocker identifiers may be attached."""


class CheckFailed(Exception):
    """Only hardcoded safe assertion identifiers may be attached."""


class Results:
    def __init__(self):
        self.checks = 0
        self.passed, self.failed, self.blocked = [], [], []

    def check(self, condition, identifier):
        self.checks += 1
        if not condition:
            raise CheckFailed(identifier)

    async def scenario(self, name, function):
        try:
            await function()
        except Blocked as error:
            self.blocked.append(name)
            print(f"BLOCKED {name} blocker={error}", flush=True)
        except CheckFailed as error:
            self.failed.append(name)
            print(f"FAIL {name} check={error}", flush=True)
        except Exception as error:
            self.failed.append(name)
            print(f"FAIL {name} exception_type={type(error).__name__} locations={safe_location(error)}", flush=True)
        else:
            self.passed.append(name)
            print(f"PASS {name}", flush=True)


def safe_location(error):
    return ",".join(f"{Path(frame.filename).name}:{frame.lineno}"
                    for frame in traceback.extract_tb(error.__traceback__)[-3:])


def digest(value):
    return sha256(str(value).encode()).hexdigest()


@dataclass(frozen=True)
class SkillArchiveFixture:
    source: str
    filename: str
    data: bytes
    expected_slug: str
    expected_file_count: int


def skill_archive_fixture(archive_path, max_bytes):
    if archive_path is not None:
        source = Path(archive_path)
        if not source.is_file():
            raise Blocked("supplied_archive_missing")
        if source.is_symlink() or source.suffix != ".skill":
            raise CheckFailed("supplied_archive_regular_skill_file")
        if source.stat().st_size > max_bytes:
            raise CheckFailed("supplied_archive_size_bound")
        with source.open("rb") as stream:
            data = stream.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise CheckFailed("supplied_archive_size_bound")
        return SkillArchiveFixture("supplied", source.name, data, "audit-tz-atoms", 6)

    slug = "synthetic-multisource-audit"
    entries = {
        "SKILL.md": (
            f"---\nname: {slug}\ndescription: Synthetic multisource QA methodology.\n---\n\n"
            "# Synthetic audit fixture\n"
            "Apply [rules](references/rules.md) and retain [sources](references/sources.md).\n"
        ),
        "references/rules.md": (
            "# Synthetic rules\nUse [decisions](decisions.txt), [rows](../assets/atoms.csv), "
            "and [schema](output.json).\n"
            + "Retain each proposal and its source evidence.\n" * 1600
        ),
        "references/sources.md": "# Synthetic evidence\nRequire a document hash, locator and literal excerpt.\n",
        "references/decisions.txt": "Proposals are drafts. A human decides acceptance.\n",
        "assets/atoms.csv": "title,locator,excerpt\nSynthetic report,paragraph 1,Display the report\n",
        "references/output.json": '{"type":"object","required":["atoms","coverage"]}\n',
    }
    output = BytesIO()
    with ZipFile(output, "w") as archive:
        for name, content in entries.items():
            archive.writestr(ZipInfo(f"{slug}/{name}", date_time=(2026, 1, 1, 0, 0, 0)), content)
    data = output.getvalue()
    if len(data) > max_bytes:
        raise CheckFailed("synthetic_archive_size_bound")
    return SkillArchiveFixture("synthetic", f"{slug}.skill", data, slug, len(entries))


def ensure_safe_target(url, allow_create):
    if not allow_create or os.environ.get(OPT_IN_ENV) != "1":
        raise Blocked("explicit_local_create_flag_and_env_required")
    if url.get_backend_name() != "postgresql":
        raise Blocked("postgresql_required")
    allowed = {"localhost", "127.0.0.1", "::1"}
    if Path("/.dockerenv").is_file():
        allowed.add("db")
    if (url.host or "") not in allowed or url.query:
        raise Blocked("local_only_host_without_connection_query_required")


async def database_lifecycle(url, name, *, drop=False):
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    if not TEMP_NAME.fullmatch(name):
        raise Blocked("unexpected_disposable_database_name")
    engine = create_async_engine(url, isolation_level="AUTOCOMMIT", echo=False,
                                 hide_parameters=True, connect_args={"timeout": 10})
    try:
        async with engine.connect() as connection:
            if drop:
                await connection.execute(text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ), {"name": name})
                await connection.execute(text(f'DROP DATABASE IF EXISTS "{name}"'))
            else:
                await connection.execute(text(f'CREATE DATABASE "{name}"'))
    finally:
        await engine.dispose()


async def migrate(engine, results):
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import text

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    heads = scripts.get_heads()
    if len(heads) != 1 or "086_audit_skills_registry_guide" not in {
        revision.revision for revision in scripts.walk_revisions()
    }:
        raise Blocked("migration_086_single_head_not_ready")
    config.config_file_name = None
    async with engine.connect() as connection:
        def upgrade(sync_connection, revision):
            config.attributes["connection"] = sync_connection
            command.upgrade(config, revision)
        await connection.run_sync(upgrade, "084_audit_declarative_skills")
        legacy = await seed_pre085_rollback(connection)
        await connection.commit()
        await connection.run_sync(upgrade, "head")
        results.check(await connection.scalar(text("SELECT version_num FROM alembic_version")) == heads[0],
                      "migration_revision")
        columns = set((await connection.execute(text(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = 'audit_atoms'"
        ))).scalars())
        results.check({"provenance_json", "ai_registry_item_id"} <= columns, "migration_provenance_columns")
        results.check(await connection.scalar(text("SELECT count(*) FROM audit_atoms")) == 2,
                      "migration_did_not_autopublish_or_remove_atoms")
        results.check(await connection.scalar(text("""
            SELECT count(*) FROM knowledge_articles WHERE status = 'published' AND slug IN (
                'soobshcheniya-perenos-menyu-i-chtenie-bazy-znanij',
                'trekery-gruppy-povtoreniya-napominaniya',
                'lichnye-gruppy-zametok-i-kontekst', 'lichnaya-zadacha-bystroe-sozdanie',
                'audit-proverka-istoricheskogo-xlsx', 'audit-metodiki-i-istochniki-atomov')
        """)) == 6, "release_six_published_articles")
    print(f"PASS migration revision={heads[0]}", flush=True)
    return legacy


async def seed_pre085_rollback(connection):
    """Persist old-schema owned/fill-empty journals before running the real 085."""
    from sqlalchemy import text
    from app.services.audit_legacy_transfer import json_value

    ids = {name: uuid4() for name in ("case", "source", "transfer", "owned", "filled")}
    await connection.execute(text("""
        INSERT INTO audit_cases (id, title, digital_product)
        VALUES (:case, 'Synthetic pre-085 case', 'Synthetic product')
    """), ids)
    await connection.execute(text("""
        INSERT INTO audit_legacy_imports (id, sha256, size_bytes, source_bytes, inspection)
        VALUES (:source, :sha, 1, :data, '{}'::jsonb)
    """), {**ids, "sha": digest(ids["source"]), "data": b"x"})
    await connection.execute(text("""
        INSERT INTO audit_legacy_transfers (id, source_id, namespace, status, config)
        VALUES (:transfer, :source, 'synthetic-pre085', 'committed', '{}'::jsonb)
    """), ids)
    for name in ("owned", "filled"):
        await connection.execute(text("""
            INSERT INTO audit_atoms (id, case_id, item_code, title, digital_product, notes)
            VALUES (:atom, :case, :code, 'Synthetic pre-085 atom', 'Synthetic product', NULL)
        """), {**ids, "atom": ids[name], "code": "ITEM-001" if name == "owned" else "ITEM-002"})
        query = text("SELECT * FROM audit_atoms WHERE id = :id")
        before = json_value(dict((await connection.execute(query, {"id": ids[name]})).mappings().one()))
        if name == "filled":
            await connection.execute(text("UPDATE audit_atoms SET notes = 'Historical fill' WHERE id = :id"),
                                     {"id": ids[name]})
        after = json_value(dict((await connection.execute(query, {"id": ids[name]})).mappings().one()))
        await connection.execute(text("""
            INSERT INTO audit_legacy_transfer_rows
                (id, transfer_id, row_key, target_table, target_id, outcome, owned, "before", "after")
            VALUES (:id, :transfer, :name, 'audit_atoms', :atom, :outcome, :owned,
                    CAST(:before AS jsonb), CAST(:after AS jsonb))
        """), {"id": uuid4(), "transfer": ids["transfer"], "name": name, "atom": ids[name],
                 "outcome": "create" if name == "owned" else "fill_empty", "owned": name == "owned",
                 "before": None if name == "owned" else json.dumps(before), "after": json.dumps(after)})
    return ids


@dataclass
class Fixture:
    case_id: UUID
    document_id: UUID
    document_sha256: str
    registries: list


class Acceptance:
    def __init__(self, sessions, app, results, archive, legacy):
        self.sessions, self.app, self.results, self.archive = sessions, app, results, archive
        self.users, self.versions = {}, []
        self.client = None
        self.legacy = legacy
        self.imported_archive_id = None

    def check(self, condition, identifier):
        self.results.check(condition, identifier)

    async def seed(self):
        from app.models.ai_provider import AIProviderConfig, AuditAtomizationSkill, AuditAtomizationSkillVersion
        from app.models.audit import AuditTeamMember
        from app.models.user import League, User, UserRole

        async with self.sessions() as db:
            for label in ("admin", "editor", "other", "outsider"):
                user = User(full_name=f"Synthetic {label}", email=f"multisource-{label}@example.invalid",
                            role=UserRole.admin if label == "admin" else UserRole.executor,
                            league=League.A, is_active=True, audit_enabled=True)
                db.add(user)
                await db.flush()
                self.users[label] = user
                if label in {"editor", "other"}:
                    db.add(AuditTeamMember(user_id=user.id, role="member", added_by_id=self.users["admin"].id))
            provider = AIProviderConfig(display_name="Synthetic provider", base_url="https://example.invalid/v1",
                                        model_name="synthetic-model", api_key_ciphertext="synthetic-unused",
                                        enabled=False, config_version=1)
            db.add(provider)
            await db.flush()
            self.provider = provider
            for index in range(3):
                skill = AuditAtomizationSkill(slug=f"multisource-method-{index}", name=f"Synthetic method {index}")
                db.add(skill)
                await db.flush()
                version = AuditAtomizationSkillVersion(
                    skill_id=skill.id, version_label="1.0", instructions_text=f"Synthetic methodology {index}",
                    rules_json=[], content_sha256=digest(f"skill-{index}"), source_filename="synthetic.json",
                    package_format="declarative_json", runtime_status="ready", is_active=True,
                )
                db.add(version)
                await db.flush()
                self.versions.append(version)
            await db.commit()

    async def fixture(self, *, count=2):
        from app.models.audit import AuditCase, AuditDocument

        async with self.sessions() as db:
            case = AuditCase(title="Synthetic multisource", digital_product="Synthetic product",
                             status="atomization", workflow_stage="atomization",
                             responsible_user_id=self.users["editor"].id, created_by_id=self.users["admin"].id)
            db.add(case)
            await db.flush()
            document = AuditDocument(case_id=case.id, kind="technical_spec", display_name="Synthetic DOC",
                                     original_filename="synthetic.docx", stored_filename=f"{uuid4()}.docx",
                                     content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                                     size_bytes=1, sha256=digest(case.id))
            db.add(document)
            await db.commit()
        fixture = Fixture(case.id, document.id, document.sha256, [])
        for index in range(count):
            fixture.registries.append(await self.registry(fixture, index))
        return fixture

    async def registry(self, fixture, method, *, source_hash=None, item_case=None, title="Display report"):
        from app.models.audit import AuditAIModelRegistry, AuditAIModelRegistryItem
        from app.models.audit_runtime import AuditTZRun

        version = self.versions[method]
        async with self.sessions() as db:
            run = AuditTZRun(case_id=fixture.case_id, document_id=fixture.document_id,
                             skill_version_id=version.id, requested_by_id=self.users["editor"].id,
                             run_key_hash=digest(uuid4()), identifier_digest=digest("synthetic-binding"),
                             source_sha256=source_hash or fixture.document_sha256,
                             skill_sha256=version.content_sha256, status="draft_ready", atom_count=1)
            db.add(run)
            await db.flush()
            registry = AuditAIModelRegistry(
                case_id=fixture.case_id, canonical_run_id=run.id, document_id=fixture.document_id,
                skill_version_id=version.id, provider_config_id=self.provider.id,
                provider_config_version=1, provider_name=self.provider.display_name,
                model_name=self.provider.model_name, document_sha256=run.source_sha256,
                skill_sha256=version.content_sha256, response_sha256=digest(uuid4()), atom_count=1,
            )
            db.add(registry)
            await db.flush()
            db.add(AuditAIModelRegistryItem(
                registry_id=registry.id, case_id=item_case or fixture.case_id,
                title=title, digital_product="Synthetic product", work_type="Development",
                object_type="Report", source_clause="paragraph 1", notes="Synthetic scope",
                source_fingerprint=digest("same-semantic-proposal"), confidence_percent=90 - method * 10,
                source_refs_json=[{"source_unit_id": f"method-{method}-unit-1", "locator": "paragraph 1",
                                   "excerpt": "The system must display the report."}], sort_order=10,
            ))
            await db.commit()
        return registry

    async def request(self, method, path, *, expected=200, actor="admin", **kwargs):
        response = await asyncio.wait_for(self.client.request(
            method, path, headers={"x-smoke-actor": actor}, **kwargs), timeout=30)
        self.check(response.status_code == expected, f"http_expected_{expected}_actual_{response.status_code}")
        return response.json() if response.status_code != 204 else None

    async def atoms(self, fixture, *, actor="admin"):
        return (await self.request("GET", f"{AUDIT}/{fixture.case_id}", actor=actor))["atoms"]

    async def publish(self, fixture, index=0, **kwargs):
        return await self.request("POST", f"{AUDIT}/{fixture.case_id}/model-registries/{fixture.registries[index].id}/publish",
                                  **kwargs)

    async def compare(self, fixture, *, registries=None, **kwargs):
        return await self.request("POST", f"{AUDIT}/{fixture.case_id}/model-comparisons", expected=201,
                                  json={"registry_ids": [str(row.id) for row in registries or fixture.registries]}, **kwargs)

    async def snapshot(self, fixture, *, events=False, reviews=False):
        from sqlalchemy import text

        tables = (*SNAPSHOT_TABLES, "audit_events") if events else SNAPSHOT_TABLES
        if reviews:
            tables = (*tables, "audit_ai_model_comparisons", "audit_ai_comparison_drafts")
        async with self.sessions() as db:
            snapshot = {}
            for table in tables:
                column = "id" if table == "audit_cases" else "case_id"
                rows = await db.execute(text(f'SELECT * FROM "{table}" WHERE {column} = :id ORDER BY id'),
                                        {"id": fixture.case_id})
                snapshot[table] = deepcopy([dict(row) for row in rows.mappings()])
            return snapshot

    async def set_stage(self, fixture, stage, *, archived=False):
        from app.models.audit import AuditCase

        async with self.sessions() as db:
            case = await db.get(AuditCase, fixture.case_id)
            case.status = "archived" if archived else "atomization"
            case.workflow_stage = stage
            await db.commit()

    def review_body(self, comparison):
        return {"request_id": str(uuid4()), "expected_config_version": comparison["config_version"],
                "drafts": [{"id": row["id"], "included": True, "title": "Review-only changed title",
                            "digital_product": row["digital_product"], "work_type": row["work_type"],
                            "object_type": row["object_type"], "notes": "Review-only changed notes"}
                           for row in comparison["drafts"]]}

    async def four_source_coexistence(self):
        from app.models.audit import AuditAtom, AuditImportBatch
        from app.models.audit_legacy import AuditLegacyImport
        from app.models.audit_legacy_transfer import AuditLegacyTransfer
        from app.services.audit_atom_provenance import publish_model_registry_atoms

        fixture = await self.fixture()
        async with self.sessions() as db:
            source = AuditLegacyImport(sha256=digest(uuid4()), size_bytes=1, source_bytes=b"x", inspection={})
            batch = AuditImportBatch(sha256=digest(uuid4()), source_filename="synthetic.xlsx", source_sheet="Synthetic")
            db.add_all([source, batch])
            await db.flush()
            transfer = AuditLegacyTransfer(source_id=source.id, namespace=f"synthetic-{uuid4().hex}",
                                           status="committed", config={})
            db.add(transfer)
            await db.flush()
            db.add_all([
                AuditAtom(case_id=fixture.case_id, item_code="ITEM-001", title="Historical proposal",
                          digital_product="Synthetic product", state="ready", legacy_transfer_id=transfer.id,
                          legacy_effective_at=datetime(2025, 1, 1)),
                AuditAtom(case_id=fixture.case_id, item_code="ITEM-002", title="XLSX proposal",
                          digital_product="Synthetic product", state="draft", import_batch_id=batch.id,
                          source_sheet="Synthetic", source_row=2),
            ])
            await db.commit()
        await self.request("POST", f"{AUDIT}/{fixture.case_id}/atoms", expected=201,
                           json={"title": "Manual proposal", "digital_product": "Synthetic product"})
        before = await self.snapshot(fixture)
        # Exercise the same atomic append service used by worker finalization.
        for registry in fixture.registries:
            async with self.sessions() as db:
                result = await publish_model_registry_atoms(db, registry, self.users["admin"].id)
                self.check(result.atoms_created == 1, "new_registry_appends_one_draft")
                await db.commit()
        atoms = await self.atoms(fixture)
        self.check(len(atoms) == 5, "all_four_sources_and_two_ai_items_coexist")
        self.check({origin["kind"] for atom in atoms for origin in atom["provenance"]} ==
                   {"historical_import", "manual_register", "manual", "ai"}, "explicit_four_source_kinds")
        ai = [atom for atom in atoms if atom["ai_registry_item_id"]]
        self.check(len(ai) == 2 and all(atom["state"] == "draft" for atom in ai), "ai_never_autoaccepted")
        self.check(len({atom["source_fingerprint"] for atom in ai}) == 2, "same_text_distinct_source_identity")
        self.check({atom["provenance"][0]["skill_sha256"] for atom in ai} ==
                   {row.skill_sha256 for row in fixture.registries}, "ai_skill_snapshots")
        after = await self.snapshot(fixture)
        original = {row["id"]: row for row in before["audit_atoms"]}
        self.check(all(row == original[row["id"]] for row in after["audit_atoms"] if row["id"] in original),
                   "preexisting_sources_unchanged")
        self.check(after["audit_cases"] == before["audit_cases"], "append_does_not_rewrite_case")
        listed = await self.request("GET", f"{AUDIT}/{fixture.case_id}/model-registries")
        self.check(all(row["published_atom_count"] == 1 for row in listed["items"]), "published_counts")

    async def cross_method_comparison(self):
        from app.models.ai_provider import AIProviderConfig, AuditAtomizationSkill, AuditAtomizationSkillVersion

        fixture = await self.fixture()
        comparison = await self.compare(fixture)
        self.check(len(comparison["drafts"]) == 1, "exact_evidence_cross_method_match")
        draft = comparison["drafts"][0]
        self.check(draft["confidence_percent"] is None, "no_averaged_confidence")
        self.check(len(draft["model_variants"]) == 2, "both_original_variants")
        self.check({item["skill_sha256"] for item in comparison["registry_snapshot"]} ==
                   {row.skill_sha256 for row in fixture.registries}, "comparison_per_method_snapshots")
        self.check(not await self.atoms(fixture), "comparison_creation_never_publishes")
        before = await self.snapshot(fixture, events=True, reviews=True)
        labels = []
        try:
            async with self.sessions() as db:
                provider = await db.get(AIProviderConfig, self.provider.id)
                labels.append((AIProviderConfig, provider.id, "display_name", provider.display_name))
                provider.display_name = "Renamed synthetic provider"
                for index, registry in enumerate(fixture.registries):
                    version = await db.get(AuditAtomizationSkillVersion, registry.skill_version_id)
                    skill = await db.get(AuditAtomizationSkill, version.skill_id)
                    labels.extend([
                        (AuditAtomizationSkill, skill.id, "name", skill.name),
                        (AuditAtomizationSkillVersion, version.id, "version_label", version.version_label),
                    ])
                    skill.name, version.version_label = f"Renamed synthetic method {index}", "renamed-1.0"
                await db.commit()
            retry = await self.compare(fixture, registries=list(reversed(fixture.registries)))
            self.check(retry["id"] == comparison["id"], "comparison_key_ignores_mutable_display_labels")
            self.check(retry["registry_snapshot"] == comparison["registry_snapshot"],
                       "comparison_retry_keeps_original_display_snapshots")
            self.check(await self.snapshot(fixture, events=True, reviews=True) == before,
                       "display_rename_does_not_duplicate_or_rewrite_comparison")
        finally:
            async with self.sessions() as db:
                for model, row_id, field, value in labels:
                    setattr(await db.get(model, row_id), field, value)
                await db.commit()

    async def concurrent_comparison_creation(self):
        from sqlalchemy import func, select
        from app.models.audit import AuditAIModelComparison, AuditAIModelComparisonDraft, AuditEvent

        fixture = await self.fixture()
        before = await self.snapshot(fixture)
        # Wait for both requests even if one fails, so no request leaks into the next scenario.
        responses = await asyncio.gather(self.compare(fixture), self.compare(fixture), return_exceptions=True)
        self.check(all(isinstance(response, dict) for response in responses),
                   "concurrent_comparison_create_both_requests_succeed")
        first, second = responses
        self.check(first["id"] == second["id"], "concurrent_comparison_create_same_id")
        self.check([row["id"] for row in first["drafts"]] == [row["id"] for row in second["drafts"]],
                   "concurrent_comparison_create_same_drafts")
        retry = await self.compare(fixture, registries=list(reversed(fixture.registries)))
        self.check(retry["id"] == first["id"], "comparison_create_reordered_key_retry")
        async with self.sessions() as db:
            self.check(await db.scalar(select(func.count(AuditAIModelComparison.id)).where(
                AuditAIModelComparison.case_id == fixture.case_id)) == 1, "concurrent_comparison_one_row")
            self.check(await db.scalar(select(func.count(AuditAIModelComparisonDraft.id)).where(
                AuditAIModelComparisonDraft.case_id == fixture.case_id)) == len(first["drafts"]),
                       "concurrent_comparison_no_duplicate_drafts")
            self.check(await db.scalar(select(func.count(AuditEvent.id)).where(
                AuditEvent.case_id == fixture.case_id, AuditEvent.event_type == "ai_model_comparison_ready")) == 1,
                       "concurrent_comparison_one_creation_event")
        self.check(await self.snapshot(fixture) == before, "concurrent_comparison_no_live_mutation")

    async def document_binding_guards(self):
        fixture = await self.fixture(count=1)
        different_hash = await self.registry(fixture, 1, source_hash=digest("wrong-version"))
        baseline = await self.snapshot(fixture)
        await self.request("POST", f"{AUDIT}/{fixture.case_id}/model-comparisons", expected=422,
                           json={"registry_ids": [str(fixture.registries[0].id), str(different_hash.id)]})
        self.check(await self.snapshot(fixture) == baseline, "hash_mismatch_no_changes")
        other = await self.fixture(count=1)
        await self.request("POST", f"{AUDIT}/{fixture.case_id}/model-comparisons", expected=422,
                           json={"registry_ids": [str(fixture.registries[0].id), str(other.registries[0].id)]})

    async def publish_retry_preserves_ready(self):
        from app.models.audit import AuditAtom

        fixture = await self.fixture(count=1)
        first = await self.publish(fixture)
        self.check(first["atoms_created"] == 1 and not first["already_published"], "first_publish")
        atom = (await self.atoms(fixture))[0]
        await self.request("PATCH", f"{AUDIT}/{fixture.case_id}/atoms/{atom['id']}", json={
            "expected_updated_at": atom["updated_at"], "title": "Human-edited proposal", "state": "ready",
        })
        async with self.sessions() as db:
            row = await db.get(AuditAtom, UUID(atom["id"]))
            row.alpha_result, row.alpha_date, row.alpha_comment = "present", date(2026, 1, 1), "Human finding"
            row.commission_result, row.commission_date = "confirmed", date(2026, 1, 2)
            await db.commit()
        baseline = await self.snapshot(fixture, events=True)
        for _ in range(2):
            retry = await self.publish(fixture)
            self.check(retry["atoms_created"] == 0 and retry["already_published"], "retry_no_append")
            self.check(retry["atom_ids"] == first["atom_ids"], "retry_stable_atom_identity")
        self.check(await self.snapshot(fixture, events=True) == baseline, "retry_preserves_every_live_field_and_event")

    async def legacy_partial_comparison_publication(self):
        from sqlalchemy import select
        from app.models.audit import (
            AuditAIModelComparison, AuditAIModelComparisonDraft, AuditAIModelRegistry,
            AuditAIModelRegistryItem, AuditAtom,
        )
        from app.services.audit_atom_provenance import publish_model_registry_atoms

        fixture = await self.fixture(count=1)
        edited_title = "Human-edited legacy report"
        async with self.sessions() as db:
            registry = await db.get(AuditAIModelRegistry, fixture.registries[0].id)
            original = await db.scalar(select(AuditAIModelRegistryItem).where(
                AuditAIModelRegistryItem.registry_id == registry.id))
            items = [original]
            for index, title in enumerate((edited_title,), 2):
                item = AuditAIModelRegistryItem(
                    registry_id=registry.id, case_id=fixture.case_id, title=title,
                    digital_product="Synthetic product", work_type="Development", object_type="Report",
                    source_clause=f"paragraph {index}", source_fingerprint=digest(uuid4()), sort_order=index * 10,
                    source_refs_json=[{"source_unit_id": f"legacy-unit-{index}", "locator": f"paragraph {index}",
                                       "excerpt": f"Synthetic requirement {index}."}],
                )
                db.add(item)
                items.append(item)
            registry.atom_count = len(items)
            comparison = AuditAIModelComparison(
                case_id=fixture.case_id, canonical_run_id=registry.canonical_run_id,
                document_id=registry.document_id, skill_version_id=registry.skill_version_id,
                comparison_key_hash=digest(uuid4()), commit_key_hash=digest(uuid4()),
                registry_ids_json=[str(registry.id)], registry_snapshot_json=[{"registry_id": str(registry.id)}],
                status="committed", config_version=2, committed_by_id=self.users["admin"].id,
                committed_at=datetime(2026, 1, 1),
            )
            db.add(comparison)
            await db.flush()
            accepted_draft = None
            for index, item in enumerate(items):
                draft = AuditAIModelComparisonDraft(
                    comparison_id=comparison.id, case_id=fixture.case_id, title=item.title,
                    digital_product=item.digital_product, source_clause=item.source_clause,
                    source_refs_json=deepcopy(item.source_refs_json), source_fingerprint=digest(uuid4()),
                    model_variants_json=[{
                        "registry_id": str(registry.id), "registry_item_id": str(item.id), "title": item.title,
                        "provider_name": registry.provider_name, "model_name": registry.model_name,
                    }],
                    agreement_count=1, registry_count=1,
                    review_status="committed" if index == 0 else "rejected", sort_order=(index + 1) * 10,
                )
                db.add(draft)
                if index == 0:
                    accepted_draft = draft
            await db.flush()
            accepted = AuditAtom(
                case_id=fixture.case_id, item_code="ITEM-001", title=edited_title,
                digital_product="Synthetic product", ai_comparison_draft_id=accepted_draft.id,
                source_fingerprint=accepted_draft.source_fingerprint, state="ready", notes="Human correction",
                alpha_result="present", alpha_comment="Human finding", alpha_date=date(2026, 1, 1),
                commission_result="confirmed", commission_date=date(2026, 1, 2),
            )
            db.add(accepted)
            await db.commit()
            accepted_id = accepted.id
            remaining_item_ids = {str(item.id) for item in items[1:]}
        before = await self.snapshot(fixture, events=True, reviews=True)
        listed = await self.request("GET", f"{AUDIT}/{fixture.case_id}/model-registries")
        self.check(listed["items"][0]["published_atom_count"] == 1,
                   "legacy_comparison_count_before_partial_publish")
        async with self.sessions() as db:
            registry = await db.get(AuditAIModelRegistry, fixture.registries[0].id)
            published = await publish_model_registry_atoms(db, registry, self.users["admin"].id)
            self.check((published.atoms_created, published.atoms_reused) == (1, 1),
                       "legacy_partial_publish_created_one_reused_one")
            await db.commit()
        published_ids = {str(atom_id) for atom_id in published.atom_ids}
        self.check(str(accepted_id) in published_ids and len(published_ids) == 2,
                   "legacy_partial_publish_reuses_exact_accepted_identity")
        atoms = await self.atoms(fixture)
        self.check(len(atoms) == 2, "legacy_partial_publish_no_accepted_duplicate")
        new = [atom for atom in atoms if atom["id"] != str(accepted_id)]
        self.check({atom["ai_registry_item_id"] for atom in new} == remaining_item_ids,
                   "legacy_partial_publish_keeps_same_title_different_identity")
        self.check(all(atom["state"] == "draft" and atom["alpha_result"] is None and
                       atom["commission_result"] is None for atom in new), "legacy_partial_publish_new_items_draft_only")
        after = await self.snapshot(fixture, events=True, reviews=True)
        old_row = before["audit_atoms"][0]
        reused_row = next(row for row in after["audit_atoms"] if row["id"] == accepted_id)
        self.check(reused_row == old_row, "legacy_partial_publish_preserves_entire_accepted_row")
        self.check(all(after[table] == before[table] for table in before if table not in {"audit_atoms", "audit_events"}),
                   "legacy_partial_publish_preserves_source_comparison_and_run")
        self.check(len(after["audit_events"]) == 1 and all(row["atom_id"] != accepted_id for row in after["audit_events"]),
                   "legacy_partial_publish_events_only_for_new_atoms")
        async with self.sessions() as db:
            registry = await db.get(AuditAIModelRegistry, fixture.registries[0].id)
            retry = await publish_model_registry_atoms(db, registry, self.users["admin"].id)
            self.check((retry.atoms_created, retry.atoms_reused) == (0, 2),
                       "legacy_partial_publish_retry_created_zero_reused_two")
            self.check({str(atom_id) for atom_id in retry.atom_ids} == published_ids,
                       "legacy_partial_publish_retry_reuses_both_identities")
            await db.commit()
        for _ in range(2):
            retry = await self.publish(fixture)
            self.check(retry["atoms_created"] == 0 and retry["already_published"] and
                       set(retry["atom_ids"]) == published_ids, "legacy_partial_publish_retry_idempotent")
        self.check(await self.snapshot(fixture, events=True, reviews=True) == after,
                   "legacy_partial_publish_retries_change_nothing")
        listed = await self.request("GET", f"{AUDIT}/{fixture.case_id}/model-registries")
        self.check(listed["items"][0]["published_atom_count"] == 2,
                   "legacy_comparison_count_after_partial_publish")

    async def legacy_canonical_draft_reuse(self):
        from sqlalchemy import select
        from app.models.audit import AuditAIAtomDraft, AuditAIAtomizationAttempt, AuditAIModelRegistryItem, AuditAtom
        from app.services.audit_atom_provenance import (
            freeze_attempt_atom_origins, publish_model_registry_atoms, scoped_source_fingerprint,
        )

        fixture = await self.fixture(count=1)
        registry = fixture.registries[0]
        async with self.sessions() as db:
            item = await db.scalar(select(AuditAIModelRegistryItem).where(
                AuditAIModelRegistryItem.registry_id == registry.id))
            attempt = AuditAIAtomizationAttempt(
                case_id=fixture.case_id, canonical_run_id=registry.canonical_run_id,
                document_id=registry.document_id, document_sha256=registry.document_sha256,
                skill_version_id=registry.skill_version_id, skill_sha256=registry.skill_sha256,
                provider_config_id=registry.provider_config_id, provider_config_version=registry.provider_config_version,
                model_name=registry.model_name, response_sha256=registry.response_sha256,
                prompt_sha256=digest("legacy-canonical-prompt"), request_key_hash=digest(uuid4()),
                status="committed", consent_confirmed_at=datetime(2026, 1, 1),
            )
            db.add(attempt)
            await db.flush()
            draft = AuditAIAtomDraft(
                attempt_id=attempt.id, case_id=fixture.case_id, title=item.title,
                digital_product=item.digital_product, source_clause=item.source_clause,
                source_refs_json=deepcopy(item.source_refs_json), source_fingerprint=item.source_fingerprint,
                review_status="committed",
            )
            db.add(draft)
            await db.flush()
            atom = AuditAtom(
                case_id=fixture.case_id, item_code="ITEM-001", title="Human-edited canonical proposal",
                digital_product="Human product", ai_atomization_draft_id=draft.id,
                source_fingerprint=scoped_source_fingerprint("ai_attempt", attempt.id, draft.id),
                state="ready", notes="Human correction", alpha_result="present", alpha_comment="Human finding",
                alpha_date=date(2026, 1, 1), commission_result="confirmed", commission_date=date(2026, 1, 2),
            )
            db.add(atom)
            await db.commit()
            atom_id = atom.id

        async def source_rows():
            async with self.sessions() as db:
                return [deepcopy(dict((await db.execute(select(model.__table__).where(
                    model.id == row_id))).mappings().one())) for model, row_id in (
                        (AuditAIAtomizationAttempt, attempt.id), (AuditAIAtomDraft, draft.id))]

        before = await self.snapshot(fixture, events=True)
        sources_before = await source_rows()
        for _ in range(2):
            async with self.sessions() as db:
                result = await publish_model_registry_atoms(db, registry, self.users["admin"].id)
                self.check((result.atoms_created, result.atoms_reused) == (0, 1),
                           "legacy_canonical_publish_created_zero_reused_one")
                self.check(result.atom_ids == [atom_id], "legacy_canonical_publish_reuses_exact_atom")
                await db.commit()
            retry = await self.publish(fixture)
            self.check(retry["atoms_created"] == 0 and retry["already_published"] and
                       retry["atom_ids"] == [str(atom_id)], "legacy_canonical_asgi_retry_idempotent")
        self.check(await self.snapshot(fixture, events=True) == before,
                   "legacy_canonical_publish_preserves_every_live_row_and_event")
        self.check(await source_rows() == sources_before, "legacy_canonical_publish_preserves_attempt_and_draft")
        listed = await self.request("GET", f"{AUDIT}/{fixture.case_id}/model-registries")
        self.check(listed["items"][0]["published_atom_count"] == 1,
                   "legacy_canonical_count_preserves_published_identity")
        async with self.sessions() as db:
            current_attempt = await db.get(AuditAIAtomizationAttempt, attempt.id)
            await freeze_attempt_atom_origins(db, current_attempt)
            await db.delete(await db.get(AuditAIAtomDraft, draft.id))
            current_attempt.response_sha256 = digest("new-model-response")
            await db.commit()
        after_freeze = await self.snapshot(fixture, events=True)
        frozen_atom = after_freeze["audit_atoms"][0]
        self.check(frozen_atom["ai_registry_item_id"] == item.id and
                   frozen_atom["ai_atomization_draft_id"] is None,
                   "legacy_canonical_freeze_keeps_durable_item_link")
        self.check(all(value == before["audit_atoms"][0][key] for key, value in frozen_atom.items()
                       if key not in {"ai_registry_item_id", "ai_atomization_draft_id", "provenance_json"}),
                   "legacy_canonical_freeze_preserves_human_fields_and_timestamp")
        retry = await self.publish(fixture)
        self.check(retry["atoms_created"] == 0 and retry["atom_ids"] == [str(atom_id)],
                   "legacy_canonical_publish_after_draft_deletion_reuses_identity")
        self.check(await self.snapshot(fixture, events=True) == after_freeze,
                   "legacy_canonical_publish_after_freeze_changes_nothing")

    async def allocation_beyond_999(self):
        from app.models.audit import AuditAtom

        fixture = await self.fixture()
        async with self.sessions() as db:
            for number in (9, 99, 998, 999):
                db.add(AuditAtom(case_id=fixture.case_id, item_code=f"ITEM-{number:03d}",
                                 title="Synthetic existing", digital_product="Synthetic product"))
            await db.commit()
        await self.publish(fixture, 0)
        await self.publish(fixture, 1)
        manual = await self.request("POST", f"{AUDIT}/{fixture.case_id}/atoms", expected=201,
                                    json={"title": "After 1000", "digital_product": "Synthetic product"})
        self.check(manual["item_code"] == "ITEM-1002", "manual_allocator_after_multiple_ai_publications")
        self.check({atom["item_code"] for atom in await self.atoms(fixture)} ==
                   {"ITEM-009", "ITEM-099", "ITEM-998", "ITEM-999", "ITEM-1000", "ITEM-1001", "ITEM-1002"},
                   "numeric_allocator_boundaries")

    async def concurrent_publication(self):
        fixture = await self.fixture()
        responses = await asyncio.gather(self.publish(fixture, 0), self.publish(fixture, 0))
        self.check(sorted(row["atoms_created"] for row in responses) == [0, 1], "concurrent_same_registry_once")
        self.check(responses[0]["atom_ids"] == responses[1]["atom_ids"], "concurrent_same_registry_identity")
        await asyncio.gather(
            self.publish(fixture, 1),
            self.request("POST", f"{AUDIT}/{fixture.case_id}/atoms", expected=201,
                         json={"title": "Concurrent manual", "digital_product": "Synthetic product"}),
        )
        atoms = await self.atoms(fixture)
        self.check(len(atoms) == len({row["item_code"] for row in atoms}) == 3, "concurrent_distinct_writers")

    async def publication_rollback(self):
        from app.services.audit_atom_provenance import publish_model_registry_atoms

        fixture = await self.fixture(count=1)
        before = await self.snapshot(fixture, events=True)
        async with self.sessions() as db:
            result = await publish_model_registry_atoms(db, fixture.registries[0], self.users["admin"].id)
            self.check(result.atoms_created == 1, "append_flushed_inside_transaction")
            await db.rollback()
        self.check(await self.snapshot(fixture, events=True) == before, "rollback_removes_atoms_and_events")
        result = await self.publish(fixture)
        self.check(result["atoms_created"] == 1, "retry_after_rollback")

    async def role_crosscase_stage_guards(self):
        fixture, other = await self.fixture(count=1), await self.fixture(count=1)
        before = await self.snapshot(fixture, events=True)
        for actor in ("other", "outsider"):
            await self.publish(fixture, actor=actor, expected=403)
        await self.request("POST", f"{AUDIT}/{other.case_id}/model-registries/{fixture.registries[0].id}/publish",
                           expected=404)
        self.check(await self.snapshot(fixture, events=True) == before, "denied_publish_no_changes")
        for stage, archived in (("alpha_review", False), ("ready", False), ("atomization", True)):
            await self.set_stage(fixture, stage, archived=archived)
            before = await self.snapshot(fixture, events=True)
            await self.publish(fixture, expected=409)
            self.check(await self.snapshot(fixture, events=True) == before, "stage_guard_no_changes")
        await self.set_stage(fixture, "atomization")
        self.check((await self.publish(fixture, actor="editor"))["atoms_created"] == 1, "assigned_editor_can_publish")
        malformed = await self.registry(fixture, 1, item_case=other.case_id)
        before = await self.snapshot(fixture, events=True)
        await self.request("POST", f"{AUDIT}/{fixture.case_id}/model-registries/{malformed.id}/publish", expected=409)
        self.check(await self.snapshot(fixture, events=True) == before, "crosscase_item_guard")

    async def comparison_review_isolation(self):
        fixture = await self.fixture(count=0)
        fixture.registries = [
            await self.registry(fixture, 0),
            await self.registry(fixture, 1, title="Export report"),
        ]
        for index in range(2):
            await self.publish(fixture, index)
        atom = (await self.atoms(fixture))[0]
        await self.request("PATCH", f"{AUDIT}/{fixture.case_id}/atoms/{atom['id']}", json={
            "expected_updated_at": atom["updated_at"], "title": "Already reviewed", "state": "ready",
        })
        comparison = await self.compare(fixture)
        body = self.review_body(comparison)
        self.check(len(body["drafts"]) == 2, "review_retry_has_two_distinct_drafts")
        path = f"{AUDIT}/{fixture.case_id}/model-comparisons/{comparison['id']}/commit"
        before = await self.snapshot(fixture)
        await self.request("POST", path, expected=409, json={**body, "expected_config_version": 999})
        for actor in ("other", "outsider"):
            await self.request("POST", path, expected=403, actor=actor, json=body)
        other = await self.fixture(count=1)
        await self.request("POST", f"{AUDIT}/{other.case_id}/model-comparisons/{comparison['id']}/commit",
                           expected=404, json=body)
        saved = await self.request("POST", path, json=body)
        self.check(saved["review_only"] and saved["atoms_created"] == 0, "save_is_review_only")
        self.check(set(saved["atom_ids"]) == {row["id"] for row in await self.atoms(fixture)}, "save_reads_general_ids")
        committed = await self.snapshot(fixture, events=True, reviews=True)
        stored_hashes = {item.get("review_payload_sha256")
                         for item in committed["audit_ai_model_comparisons"][0]["registry_snapshot_json"]}
        self.check(len(stored_hashes) == 1 and all(isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value)
                                                  for value in stored_hashes), "review_payload_hash_persisted")
        retry = await self.request("POST", path, json=body)
        self.check(retry["already_committed"] and retry["atoms_created"] == 0, "review_retry")
        reordered = deepcopy(body)
        reordered["drafts"].reverse()
        for draft in reordered["drafts"]:
            for field in ("title", "digital_product", "work_type", "object_type", "notes"):
                draft[field] = f" \t{draft[field]}\n "
        retry = await self.request("POST", path, json=reordered)
        self.check(retry["already_committed"] and retry["atoms_created"] == 0,
                   "review_reordered_normalized_retry_accepted")
        self.check(set(retry["atom_ids"]) == set(saved["atom_ids"]), "review_reordered_retry_same_atom_ids")
        for field, value in (
            ("title", "Changed retry title"), ("digital_product", "Changed retry product"),
            ("work_type", "Changed retry work"), ("object_type", "Changed retry object"),
            ("notes", "Changed retry notes"), ("included", False),
        ):
            changed = deepcopy(body)
            changed["drafts"][0][field] = value
            await self.request("POST", path, expected=409, json=changed)
        await self.request("POST", path, expected=409,
                           json={**body, "expected_config_version": body["expected_config_version"] + 1})
        await self.request("POST", path, expected=409, json={**body, "request_id": str(uuid4())})
        self.check(await self.snapshot(fixture, events=True, reviews=True) == committed,
                   "review_retries_do_not_change_comparison_drafts_events_or_live_rows")
        self.check(await self.snapshot(fixture) == before, "review_preserves_atoms_registries_runs_case")

    async def comparison_review_without_publication(self):
        fixture = await self.fixture()
        comparison = await self.compare(fixture)
        body = self.review_body(comparison)
        path = f"{AUDIT}/{fixture.case_id}/model-comparisons/{comparison['id']}/commit"
        before = await self.snapshot(fixture)
        saved = await self.request("POST", path, json=body)
        self.check(saved["atom_ids"] == [] and saved["atoms_created"] == 0, "review_does_not_publish_old_registry")
        self.check(await self.snapshot(fixture) == before, "unpublished_review_no_live_changes")

    async def comparison_review_all_rejected(self):
        fixture = await self.fixture()
        for index in range(2):
            await self.publish(fixture, index)
        atoms = await self.atoms(fixture)
        await self.request("PATCH", f"{AUDIT}/{fixture.case_id}/atoms/{atoms[0]['id']}", json={
            "expected_updated_at": atoms[0]["updated_at"], "state": "ready",
        })
        comparison = await self.compare(fixture)
        body = self.review_body(comparison)
        for draft in body["drafts"]:
            draft["included"] = False
        path = f"{AUDIT}/{fixture.case_id}/model-comparisons/{comparison['id']}"
        before = await self.snapshot(fixture)
        saved = await self.request("POST", f"{path}/commit", json=body)
        self.check(saved["review_only"] and saved["atoms_created"] == 0, "all_rejected_review_only_save")
        self.check(set(saved["atom_ids"]) == {atom["id"] for atom in atoms}, "all_rejected_retains_general_atoms")
        persisted = await self.request("GET", path)
        self.check(len(persisted["drafts"]) == len(body["drafts"]) and
                   all(draft["review_status"] == "rejected" for draft in persisted["drafts"]),
                   "all_rejected_decisions_persisted")
        self.check(persisted["config_version"] == body["expected_config_version"] + 1,
                   "all_rejected_increments_review_version")
        retry = await self.request("POST", f"{path}/commit", json=body)
        self.check(retry["already_committed"] and retry["atoms_created"] == 0, "all_rejected_retry_idempotent")
        self.check(await self.snapshot(fixture) == before, "all_rejected_preserves_every_live_row")

    async def legacy_attempt_origin_freeze(self):
        from sqlalchemy import delete, select
        from app.models.audit import AuditAIAtomDraft, AuditAIAtomizationAttempt, AuditAtom, AuditCase
        from app.services.audit_atom_provenance import freeze_attempt_atom_origins

        fixture = await self.fixture(count=0)
        async with self.sessions() as db:
            attempt = AuditAIAtomizationAttempt(
                case_id=fixture.case_id, document_id=fixture.document_id,
                skill_version_id=self.versions[0].id, provider_config_id=self.provider.id,
                provider_config_version=1, model_name="original-synthetic-model",
                document_sha256=fixture.document_sha256, skill_sha256=self.versions[0].content_sha256,
                prompt_sha256=digest("original-prompt"), response_sha256=digest("original-response"),
                request_key_hash=digest(uuid4()), status="committed", consent_confirmed_at=datetime(2026, 1, 1),
            )
            db.add(attempt)
            await db.flush()
            draft = AuditAIAtomDraft(
                attempt_id=attempt.id, case_id=fixture.case_id, title="Original proposal",
                digital_product="Synthetic product", source_clause="paragraph 1",
                source_fingerprint=digest(uuid4()), review_status="committed",
            )
            db.add(draft)
            await db.flush()
            atom = AuditAtom(
                case_id=fixture.case_id, item_code="ITEM-001", title="Human-edited original proposal",
                digital_product="Synthetic product", ai_atomization_draft_id=draft.id, state="ready",
                notes="Human correction", alpha_result="present", alpha_comment="Human finding",
                alpha_date=date(2026, 1, 1), commission_result="confirmed", commission_date=date(2026, 1, 2),
            )
            db.add(atom)
            await db.commit()
            attempt_id, draft_id, atom_id = attempt.id, draft.id, atom.id
        before = await self.snapshot(fixture, events=True)

        async def freeze_and_reuse(db):
            await db.scalar(select(AuditCase).where(AuditCase.id == fixture.case_id).with_for_update())
            old = await db.scalar(select(AuditAIAtomizationAttempt).where(
                AuditAIAtomizationAttempt.id == attempt_id).with_for_update())
            self.check(await freeze_attempt_atom_origins(db, old) == 1, "legacy_origin_frozen_once")
            self.check(await freeze_attempt_atom_origins(db, old) == 0, "legacy_origin_freeze_idempotent")
            await db.execute(delete(AuditAIAtomDraft).where(AuditAIAtomDraft.attempt_id == attempt_id))
            old.model_name, old.provider_config_version = "replacement-synthetic-model", 2
            old.skill_version_id, old.skill_sha256 = self.versions[1].id, self.versions[1].content_sha256
            old.prompt_sha256, old.response_sha256 = digest("replacement-prompt"), None
            await db.flush()

        async with self.sessions() as db:
            await freeze_and_reuse(db)
            await db.rollback()
        self.check(await self.snapshot(fixture, events=True) == before, "legacy_freeze_rollback_restores_atom_and_link")
        async with self.sessions() as db:
            old = await db.get(AuditAIAtomizationAttempt, attempt_id)
            self.check(old.model_name == "original-synthetic-model" and await db.get(AuditAIAtomDraft, draft_id) is not None,
                       "legacy_freeze_rollback_restores_attempt_and_draft")
        async with self.sessions() as db:
            await freeze_and_reuse(db)
            await db.commit()
        after = await self.snapshot(fixture, events=True)
        original_row, frozen_row = before["audit_atoms"][0], after["audit_atoms"][0]
        mutable_fields = {"provenance_json", "ai_atomization_draft_id"}
        self.check({name: value for name, value in frozen_row.items() if name not in mutable_fields} ==
                   {name: value for name, value in original_row.items() if name not in mutable_fields},
                   "legacy_freeze_preserves_human_fields_and_updated_at")
        self.check(frozen_row["ai_atomization_draft_id"] is None, "legacy_draft_delete_real_fk_set_null")
        origin = frozen_row["provenance_json"][0]
        expected = {"attempt_id": str(attempt_id), "provider_config_id": str(self.provider.id),
                    "provider_config_version": 1, "model_name": "original-synthetic-model",
                    "document_id": str(fixture.document_id), "document_sha256": fixture.document_sha256,
                    "skill_version_id": str(self.versions[0].id), "skill_sha256": self.versions[0].content_sha256,
                    "prompt_sha256": digest("original-prompt"), "response_sha256": digest("original-response")}
        self.check(all(origin.get(name) == value for name, value in expected.items()), "legacy_origin_keeps_original_context")
        projected = next(row for row in await self.atoms(fixture) if row["id"] == str(atom_id))
        self.check(all(projected["provenance"][0].get(name) == value for name, value in expected.items()),
                   "legacy_origin_survives_public_projection")
        self.check(after["audit_events"] == before["audit_events"] and after["audit_cases"] == before["audit_cases"],
                   "legacy_freeze_no_human_events_or_case_change")

    async def worker_publication_eligibility(self):
        from app.models.audit import AuditCase, AuditTeamMember
        from app.models.user import User
        from app.services.audit_tz_runtime import _registry_autoappend_blocker
        from sqlalchemy import delete

        fixture = await self.fixture(count=1)
        async with self.sessions() as db:
            case = await db.get(AuditCase, fixture.case_id)
            editor = await db.get(User, self.users["editor"].id)
            self.check(await _registry_autoappend_blocker(db, case, editor.id) is None, "worker_editor_allowed")
            self.check(await _registry_autoappend_blocker(db, case, self.users["other"].id) ==
                       "atom_editor_permission_revoked", "worker_reassigned_guard")
            editor.is_active = False
            await db.flush()
            self.check(await _registry_autoappend_blocker(db, case, editor.id) == "initiator_inactive", "worker_inactive_guard")
            editor.is_active, editor.audit_enabled = True, False
            await db.flush()
            self.check(await _registry_autoappend_blocker(db, case, editor.id) == "audit_access_revoked", "worker_access_guard")
            editor.audit_enabled = True
            await db.flush()
            await db.execute(delete(AuditTeamMember).where(AuditTeamMember.user_id == editor.id))
            self.check(await _registry_autoappend_blocker(db, case, editor.id) == "audit_membership_revoked", "worker_membership_guard")
            case.status = "archived"
            self.check(await _registry_autoappend_blocker(db, case, editor.id) == "case_archived", "worker_archive_guard")
            case.status, case.workflow_stage = "atomization", "alpha_review"
            self.check(await _registry_autoappend_blocker(db, case, editor.id) == "case_stage_changed", "worker_stage_guard")
            await db.rollback()

    async def skill_archive_data_only(self):
        from sqlalchemy import func, select
        from app.models.ai_provider import AuditAtomizationSkillVersion
        from app.models.audit_runtime import AuditTZRuntimeJob
        from app.services.audit_skill_package import MAX_SKILL_UPLOAD_BYTES, parse_audit_skill_upload
        from app.services.audit_declarative_runtime import build_methodology_snapshot, build_native_preflight, validate_native_prompt

        fixture = skill_archive_fixture(self.archive, MAX_SKILL_UPLOAD_BYTES)
        data = fixture.data
        with ExitStack() as stack:
            for target in ("subprocess.Popen", "os.system", "zipfile.ZipFile.extract", "zipfile.ZipFile.extractall"):
                stack.enter_context(patch(target, side_effect=CheckFailed("archive_attempted_execution_or_extraction")))
            parsed = parse_audit_skill_upload(fixture.filename, data, trusted_hashes=set())
            self.check(parsed.slug == fixture.expected_slug and parsed.package_format == "declarative_archive",
                       "archive_declarative_not_trusted")
            self.check(parsed.content_sha256 == sha256(data).hexdigest(), "archive_hash")
            self.check(parsed.runtime_status == "ready" and
                       parsed.package_manifest["file_count"] == fixture.expected_file_count,
                       "archive_complete_manifest")
            self.check(64 * 1024 < len(parsed.instructions.encode()) <= 128 * 1024,
                       "archive_full_instruction_budget")
            with ZipFile(BytesIO(data)) as archive:
                for entry in parsed.package_manifest["files"]:
                    content = archive.read(f"{parsed.package_manifest['root']}/{entry['path']}")
                    self.check(content.decode() in parsed.instructions, "archive_reference_retained")
                    self.check(sha256(content).hexdigest() == entry["sha256"], "archive_reference_hash")
            uploaded = await self.request("POST", f"{SKILLS}/import", expected=201,
                                          files={"file": (fixture.filename, data, "application/octet-stream")})
            async with self.sessions() as db:
                version = await db.get(AuditAtomizationSkillVersion, UUID(uploaded["id"]))
                self.check(version.package_format == "declarative_archive", "archive_import_persisted_as_data")
                self.imported_archive_id = version.id
                self.check(await db.scalar(select(func.count(AuditTZRuntimeJob.id)).where(
                    AuditTZRuntimeJob.skill_version_id == version.id)) == 0, "data_import_no_executable_job")
                methodology = build_methodology_snapshot(version)
            output = BytesIO()
            with ZipFile(output, "w") as document:
                document.writestr("word/document.xml", (
                    '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
                    '<w:body><w:p><w:r><w:t>The system must display the report.</w:t></w:r></w:p>'
                    '</w:body></w:document>'
                ))
            document_data, run_id = output.getvalue(), str(uuid4())
            source_hash = sha256(document_data).hexdigest()
            preflight = build_native_preflight(document_data, run_id=run_id, source_sha256=source_hash,
                                               binding_id="synthetic-document", methodology=methodology)
            validate_native_prompt(preflight.prompt_packet, run_id=run_id, source_sha256=source_hash,
                                   methodology=methodology)
            self.check(bool(preflight.prompt_packet["source_units"]), "native_preflight_nonempty")
            self.check(preflight.prompt_packet["methodology"]["skill_sha256"] == parsed.content_sha256,
                       "native_preflight_pins_selected_archive")

    async def assert_locked_downgrade_guard(self, revision, tables):
        from alembic.migration import MigrationContext
        from alembic.operations import Operations
        from importlib.util import module_from_spec, spec_from_file_location
        from sqlalchemy import text
        from sqlalchemy.exc import DBAPIError

        spec = spec_from_file_location(f"smoke_{revision}", ROOT / "alembic" / "versions" / f"{revision}.py")
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        async with self.sessions() as db:
            connection = await db.connection()
            head_before = await db.scalar(text("SELECT version_num FROM alembic_version"))

            def guarded_downgrade(sync_connection):
                with Operations.context(MigrationContext.configure(sync_connection)):
                    module.downgrade()

            try:
                await connection.run_sync(guarded_downgrade)
            except RuntimeError:
                pass
            else:
                raise CheckFailed("nonempty_downgrade_must_refuse")
            locks = set((await db.execute(text("""
                SELECT c.relname FROM pg_locks l JOIN pg_class c ON c.oid = l.relation
                WHERE l.pid = pg_backend_pid() AND l.granted AND l.mode = 'AccessExclusiveLock'
            """))).scalars())
            self.check(set(tables) <= locks, "downgrade_holds_exclusive_locks_through_guard")
            async with self.sessions() as contender:
                await contender.execute(text("SET LOCAL lock_timeout = '100ms'"))
                try:
                    await contender.execute(text(f'SELECT 1 FROM "{tables[0]}" LIMIT 1'))
                except DBAPIError as error:
                    self.check(getattr(error.orig, "sqlstate", None) == "55P03", "downgrade_fences_concurrent_access")
                else:
                    raise CheckFailed("downgrade_lock_did_not_block_contender")
                await contender.rollback()
            self.check(await db.scalar(text("SELECT version_num FROM alembic_version")) == head_before,
                       "guard_preserves_revision")
            await db.rollback()

    async def migration_084_downgrade_guard(self):
        if self.imported_archive_id is None:
            raise Blocked("declarative_archive_fixture_not_imported")
        await self.assert_locked_downgrade_guard("084_audit_declarative_skills", ("audit_atomization_skill_versions",))

    async def migration_085_downgrade_guard(self):
        fixture = await self.fixture(count=1)
        await self.publish(fixture)
        before = await self.snapshot(fixture, events=True)
        await self.assert_locked_downgrade_guard("085_audit_atom_provenance", ("audit_atoms", "audit_legacy_transfer_rows"))
        self.check(await self.snapshot(fixture, events=True) == before, "downgrade_preserves_protected_origins")

    async def migration_085_legacy_rollback(self):
        from sqlalchemy import select
        from app.models.audit import AuditAtom
        from app.models.audit_legacy_transfer import AuditLegacyTransferRow
        from app.schemas.audit_legacy_transfer import TransferRollback
        from app.services.audit_legacy_transfer import rollback_transfer, target_rows

        async with self.sessions() as db:
            rows = list(await db.scalars(select(AuditLegacyTransferRow).where(
                AuditLegacyTransferRow.transfer_id == self.legacy["transfer"])))
            current = await target_rows(db, {"audit_atoms": {self.legacy["owned"], self.legacy["filled"]}})
            self.check(len(rows) == 2, "old_journal_rows_survive_migration")
            for row in rows:
                self.check(row.after == current[("audit_atoms", str(row.target_id))], "old_after_matches_new_full_row")
                self.check(row.after["provenance_json"] == [] and row.after["ai_registry_item_id"] is None,
                           "old_after_default_keys_added")
                if row.owned:
                    self.check(row.before is None, "old_owned_before_remains_sql_null")
                else:
                    self.check(row.before["provenance_json"] == [] and row.before["ai_registry_item_id"] is None,
                               "old_before_default_keys_added")
            transfer = await rollback_transfer(db, self.legacy["transfer"], TransferRollback(
                revision=1, reason="Synthetic migration acceptance", confirm=True), self.users["admin"].id)
            self.check(transfer.status == "rolled_back", "old_transfer_rollback_remains_available")
            await db.commit()
        async with self.sessions() as db:
            self.check(await db.get(AuditAtom, self.legacy["owned"]) is None, "old_owned_atom_removed_on_rollback")
            filled = await db.get(AuditAtom, self.legacy["filled"])
            self.check(filled is not None and filled.notes is None and filled.provenance_json == [],
                       "old_fill_empty_before_restored")

    async def case_delete_cascade(self):
        from sqlalchemy import func, select
        from app.models.audit import AuditDocument

        fixture, other = await self.fixture(), await self.fixture(count=1)
        for index in range(2):
            await self.publish(fixture, index)
        comparison = await self.compare(fixture)
        await self.request("POST", f"{AUDIT}/{fixture.case_id}/model-comparisons/{comparison['id']}/commit",
                           json=self.review_body(comparison))
        await self.set_stage(fixture, "atomization", archived=True)
        case = await self.request("GET", f"{AUDIT}/{fixture.case_id}")
        untouched = await self.snapshot(other, events=True)
        # Fixtures have no document files; never call real filesystem cleanup.
        with patch("app.api.routes.audit.remove_audit_case_files") as cleanup:
            deleted = await self.request("DELETE", f"{AUDIT}/{fixture.case_id}", json={
                "confirmation_code": case["case_number"], "reason": "Synthetic QA cleanup",
            })
            self.check(cleanup.call_count == 1, "case_delete_invokes_scoped_file_cleanup")
        self.check(deleted["deleted_atoms_count"] == 2, "case_delete_removes_published_atoms")
        self.check(all(not rows for rows in (await self.snapshot(fixture, events=True)).values()),
                   "case_delete_no_dangling_registry_fk")
        async with self.sessions() as db:
            self.check(await db.scalar(select(func.count(AuditDocument.id)).where(
                AuditDocument.case_id == fixture.case_id)) == 0, "case_delete_removes_documents")
        self.check(await self.snapshot(other, events=True) == untouched, "case_delete_other_case_unchanged")

    async def run(self):
        import httpx
        from fastapi import Request
        from app.api.deps import get_current_user, get_db

        await self.seed()
        previous = dict(self.app.dependency_overrides)

        async def database():
            async with self.sessions() as db:
                try:
                    yield db
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise

        async def current_user(request: Request):
            return self.users[request.headers.get("x-smoke-actor", "admin")]

        self.app.dependency_overrides[get_db] = database
        self.app.dependency_overrides[get_current_user] = current_user
        try:
            with patch("httpx.AsyncHTTPTransport.handle_async_request", side_effect=CheckFailed("external_http_forbidden")), \
                 patch("httpx.HTTPTransport.handle_request", side_effect=CheckFailed("external_http_forbidden")):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app),
                                             base_url="http://localhost", timeout=30) as client:
                    self.client = client
                    for name in SCENARIOS:
                        label = name
                        if name == "skill_archive_data_only":
                            source = "supplied" if self.archive is not None else "synthetic"
                            label = f"{source}_archive_data_only"
                        await self.results.scenario(label, getattr(self, name))
        finally:
            self.app.dependency_overrides.clear()
            self.app.dependency_overrides.update(previous)


async def execute(args, results):
    from sqlalchemy.engine import make_url
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    if not os.environ.get("DATABASE_URL"):
        raise Blocked("explicit_local_database_url_env_required")
    # Prevent configuration import from opening local credential-bearing dotenv files.
    with patch("pydantic_settings.sources.DotEnvSettingsSource._read_env_files", return_value={}):
        from app.config import settings

    runtime_url = make_url(settings.DATABASE_URL)
    ensure_safe_target(runtime_url, args.allow_create_database)
    if settings.DB_SCHEMA or "app.database" in sys.modules:
        raise Blocked("fresh_process_public_schema_required")
    name = "dpms_multisource_" + uuid4().hex[:12]
    admin_url = runtime_url.set(drivername="postgresql+asyncpg", database="postgres")
    temporary_url = runtime_url.set(drivername="postgresql+asyncpg", database=name)
    created, engine = False, None
    try:
        await database_lifecycle(admin_url, name)
        created = True
        settings.DATABASE_URL = temporary_url.render_as_string(hide_password=False)
        settings.DEBUG = False
        engine = create_async_engine(temporary_url, echo=False, hide_parameters=True,
                                     connect_args={"timeout": 10, "server_settings": {
                                         "statement_timeout": "30000", "lock_timeout": "10000"}})
        legacy = await migrate(engine, results)
        from app.main import app
        from app.database import engine as application_engine
        results.check(application_engine.url.database == name, "application_global_engine_fenced")
        paths = app.openapi()["paths"]
        if f"{AUDIT}/{{case_id}}/model-registries/{{registry_id}}/publish" not in paths:
            raise Blocked("publish_contract_not_ready")
        sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        await Acceptance(sessions, app, results, args.archive, legacy).run()
    finally:
        if engine is not None:
            await engine.dispose()
        module = sys.modules.get("app.database")
        if module is not None:
            await module.engine.dispose()
        if created:
            try:
                await database_lifecycle(admin_url, name, drop=True)
            except Exception:
                print(f"BLOCKED disposable_database_cleanup_failed database={name}", flush=True)
                raise Blocked("disposable_database_cleanup_failed") from None
            print("PASS disposable_database_dropped", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-create-database", action="store_true")
    skill_source = parser.add_mutually_exclusive_group()
    skill_source.add_argument("--archive", help="Require the actual supplied audit-tz-atoms.skill at this path")
    skill_source.add_argument("--synthetic-skill", action="store_true",
                              help="Use an in-memory synthetic six-file data-only archive (default)")
    parser.add_argument("--timeout-seconds", type=int, default=240)
    args = parser.parse_args()
    if not 30 <= args.timeout_seconds <= 900:
        parser.error("timeout must be between 30 and 900 seconds")
    logging.disable(logging.CRITICAL)
    skill_source = "supplied" if args.archive is not None else "synthetic"
    print(f"INFO multisource skill_source={skill_source}", flush=True)
    results, blocker = Results(), None
    try:
        asyncio.run(asyncio.wait_for(execute(args, results), timeout=args.timeout_seconds))
    except (Blocked, CheckFailed) as error:
        blocker = str(error)
    except Exception as error:
        blocker = f"exception_type_{type(error).__name__}"
        print(f"locations={safe_location(error)}", flush=True)
    not_run = len(SCENARIOS) - len(results.passed) - len(results.failed) - len(results.blocked)
    status = "BLOCKED" if blocker or results.blocked or not_run else "FAIL" if results.failed else "PASS"
    print(f"{status} multisource skill_source={skill_source} scenarios_passed={len(results.passed)} scenarios_failed={len(results.failed)} "
          f"scenarios_blocked={len(results.blocked)} scenarios_not_run={not_run} checks={results.checks}", flush=True)
    if blocker:
        print(f"blocker={blocker}", flush=True)
    return 0 if status == "PASS" else 2 if status == "BLOCKED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
