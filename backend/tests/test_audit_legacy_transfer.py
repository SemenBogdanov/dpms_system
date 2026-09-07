"""Isolated A1.9 tests. No configured DB, credential files, or production access.

SQLite verifies atomic behavior; PostgreSQL SQL assertions cover lock selection.
Real PostgreSQL migration/concurrency acceptance is a separate integration gate.
"""

import asyncio
from copy import deepcopy
from datetime import date, datetime, timezone
from hashlib import sha256
import importlib.util
from itertools import count
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from time import perf_counter
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import Boolean, Column, DateTime, DefaultClause, JSON, MetaData, String, Table, event, func, select, text, update
from sqlalchemy.dialects import postgresql
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateTable

from app.api.deps import get_current_user, get_db
from app.api.routes import audit_legacy as staging_routes
from app.api.routes import audit_legacy_transfer as routes
from app.models.activity import ActivityEvent
from app.models.audit import AuditAssignment, AuditAtom, AuditCase, AuditEvent, AuditTeamMember
from app.models.audit_legacy import AuditLegacyImport
from app.models.audit_legacy_transfer import AuditLegacyMetric, AuditLegacyProvenance, AuditLegacyTransfer, AuditLegacyTransferRow
from app.models.user import UserRole
from app.schemas.audit_legacy_transfer import TransferCommit, TransferConfig, TransferRollback
from app.services import audit_legacy_transfer as service
from app.services.audit_legacy_workbook import inspect_legacy_workbook
from tests.audit_legacy_transfer_fixtures import combined_rows, workbook, transfer_config


BASE = "/api/audit/legacy-transfers"


class TransferTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = TemporaryDirectory(prefix="dpms-transfer-unit-")
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.directory.name}/isolated.sqlite")
        sequence = count(1)

        @event.listens_for(self.engine.sync_engine, "connect")
        def setup_connection(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
            connection.create_function("next_audit_case_seq", 0, lambda: next(sequence))

        metadata = MetaData()
        self.users = Table("users", metadata,
            Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
            Column("full_name", String(255)), Column("email", String(255)),
            Column("is_active", Boolean), Column("audit_enabled", Boolean),
        )
        included = [AuditLegacyImport, AuditLegacyTransfer, AuditLegacyProvenance, AuditLegacyTransferRow,
                    AuditLegacyMetric, AuditCase, AuditAtom, AuditAssignment, AuditEvent, AuditTeamMember, ActivityEvent]
        for model in included:
            copied = model.__table__.to_metadata(metadata)
            for column in copied.c:
                if isinstance(column.type, postgresql.JSONB):
                    column.type = JSON()
        metadata.tables["audit_cases"].c.case_sequence.server_default = DefaultClause(text("(next_audit_case_seq())"))
        # Referenced external models are represented only by IDs, never credentials/config.
        for foreign in list(fk for table in metadata.tables.values() for fk in table.foreign_keys):
            name = foreign.target_fullname.split(".")[0]
            if name not in metadata.tables:
                Table(name, metadata, Column("id", postgresql.UUID(as_uuid=True), primary_key=True))
        # Rollback scans mapped FKs; real-shaped audit child tables are needed for that scan.
        from app.models import Base
        for name in service.reference_tables():
            mapped = Base.metadata.tables[name]
            if name not in metadata.tables:
                Table(name, metadata, Column("id", postgresql.UUID(as_uuid=True), primary_key=True))
            existing = metadata.tables[name]
            for column in mapped.c:
                if column.name not in existing.c and any(fk.target_fullname.startswith(("audit_cases.", "audit_atoms.", "audit_events.", "audit_assignments.", "audit_legacy_metrics.")) for fk in column.foreign_keys):
                    existing.append_column(Column(column.name, postgresql.UUID(as_uuid=True)))
        self.metadata = metadata
        self.admin_id, self.member_id = uuid4(), uuid4()
        async with self.engine.begin() as connection:
            await connection.run_sync(metadata.create_all)
            await connection.execute(self.users.insert(), [
                {"id": self.admin_id, "full_name": "Administrator", "email": "admin@example.test", "is_active": True, "audit_enabled": True},
                {"id": self.member_id, "full_name": "Reviewer", "email": "reviewer@example.test", "is_active": True, "audit_enabled": True},
            ])
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False, autoflush=False)
        self.user = SimpleNamespace(id=self.admin_id, role=UserRole.admin, audit_enabled=True, is_active=True)
        self.lock = asyncio.Lock()

        async def lock_transfers(db):
            if not db.info.get("test_lock"):
                await self.lock.acquire()
                db.info["test_lock"] = True

        async def database():
            async with self.sessions() as db:
                try:
                    yield db
                    await db.commit()
                except BaseException:
                    await db.rollback()
                    raise
                finally:
                    if db.info.pop("test_lock", False):
                        self.lock.release()

        self.patchers = [patch.object(service, "lock_transfers", side_effect=lock_transfers),
                         patch.object(staging_routes, "_lock_staging", side_effect=lock_transfers)]
        for patcher in self.patchers:
            patcher.start()
        self.app = FastAPI()
        self.app.include_router(routes.router, prefix=BASE)
        self.app.include_router(staging_routes.router, prefix="/api/audit/legacy-imports")
        self.app.dependency_overrides[get_db] = database
        self.app.dependency_overrides[get_current_user] = lambda: self.user
        self.client = AsyncClient(transport=ASGITransport(app=self.app), base_url="http://test")

    async def asyncTearDown(self):
        await self.client.aclose()
        for patcher in self.patchers:
            patcher.stop()
        await self.engine.dispose()
        self.directory.cleanup()

    async def source(self, rows, *, reordered=False):
        data, datasets = workbook(rows, reordered=reordered)
        async with self.sessions() as db:
            source = AuditLegacyImport(sha256=sha256(data).hexdigest(), size_bytes=len(data), source_bytes=data,
                                       inspection=inspect_legacy_workbook(data), status="uploaded", revision=1)
            db.add(source)
            await db.commit()
            return source.id, datasets

    def simple_rows(self, **atom):
        return {"cases": [{"case_key": "PRIVATE-CONTRACT-001", "title": "Imported case", "digital_product": "Product"}],
                "atoms": [{"case_key": "PRIVATE-CONTRACT-001", "atom_key": "A1", "title": "Atom", "state": "ready",
                           "occurred_at": "2026-08-01", **atom}]}

    async def create(self, rows=None, config=None, *, reordered=False):
        rows = rows or self.simple_rows()
        source_id, datasets = await self.source(rows, reordered=reordered)
        config = {"namespace": "test", "datasets": datasets, "cases": {key: {"mode": "create"} for key in dict.fromkeys(
            row["case_key"] for values in rows.values() for row in values)}, **(config or {})}
        result = await self.client.post(BASE, json={"source_id": str(source_id), "config": config})
        self.assertEqual(result.status_code, 200, result.text)
        return result.json()

    async def preview(self, transfer, *, ready=True):
        result = await self.client.post(f"{BASE}/{transfer['id']}/preview", json={"revision": transfer["revision"]})
        self.assertEqual(result.status_code, 200, result.text)
        body = result.json()
        self.assertEqual(body["preview"]["ready"], ready, body["preview"])
        return body

    async def commit(self, transfer):
        return await self.client.post(f"{BASE}/{transfer['id']}/commit", json={
            "revision": transfer["revision"], "preview_hash": transfer["preview"]["preview_hash"], "confirm": True,
        })

    async def rollback(self, transfer):
        return await self.client.post(f"{BASE}/{transfer['id']}/rollback", json={
            "revision": transfer["revision"], "reason": "Synthetic rollback", "confirm": True,
        })

    async def model_count(self, model):
        async with self.sessions() as db:
            return await db.scalar(select(func.count()).select_from(model))

    async def test_full_cycle_private_preview_dates_retry_and_source_retention(self):
        transfer = await self.create()
        self.assertNotIn("PRIVATE-CONTRACT-001", str(transfer))
        preview = await self.preview(transfer)
        self.assertNotIn("PRIVATE-CONTRACT-001", str(preview))
        self.assertEqual(await self.model_count(AuditAtom), 0)
        committed = await self.commit(preview)
        self.assertEqual(committed.status_code, 200, committed.text)
        self.assertEqual(committed.json()["revision"], 2)
        retry = await self.commit(preview)
        self.assertEqual(retry.json(), committed.json())
        async with self.sessions() as db:
            atom = (await db.execute(select(AuditAtom))).scalar_one()
            self.assertEqual(atom.legacy_transfer_id, UUID(transfer["id"]))
            self.assertEqual(service.json_value(atom.legacy_effective_at), "2026-07-31T21:00:00+00:00")
            event_row = (await db.execute(select(AuditEvent))).scalar_one()
            self.assertEqual(event_row.event_type, "legacy_atom_snapshot")
            self.assertIsNone(event_row.actor_id)
        deletion = await self.client.delete(f"/api/audit/legacy-imports/{transfer['source_id']}?revision=1")
        self.assertEqual(deletion.status_code, 409)
        rolled_back = await self.rollback(committed.json())
        self.assertEqual(rolled_back.status_code, 200, rolled_back.text)
        self.assertEqual(rolled_back.json()["status"], "rolled_back")
        self.assertEqual(await self.model_count(AuditCase), 0)
        self.assertEqual(await self.model_count(AuditAtom), 0)
        self.assertEqual(await self.model_count(AuditEvent), 0)
        self.assertEqual(await self.model_count(AuditLegacyImport), 1)
        self.assertEqual(await self.model_count(AuditLegacyTransferRow), 3)
        self.assertEqual((await self.rollback(committed.json())).json(), rolled_back.json())

    async def test_joint_five_dataset_transfer(self):
        rows = combined_rows(date(2026, 9, 8))
        async with self.sessions() as db:
            case = AuditCase(title="Synthetic existing case", digital_product="Synthetic existing product", notes=None)
            db.add(case)
            db.add(AuditTeamMember(user_id=self.member_id, role="member"))
            await db.commit()
            case_id = case.id
        source, datasets = await self.source(rows)
        config = transfer_config(datasets, case_id, self.member_id)
        response = await self.client.post(BASE, json={"source_id": str(source), "config": config})
        self.assertEqual(response.status_code, 200, response.text)
        preview = await self.preview(response.json())
        self.assertEqual(preview["preview"]["total_rows"], 13)
        committed = await self.commit(preview)
        self.assertEqual(committed.status_code, 200, committed.text)
        self.assertEqual(await self.model_count(AuditCase), 3)
        self.assertEqual(await self.model_count(AuditAtom), 2)
        self.assertEqual(await self.model_count(AuditAssignment), 1)
        self.assertEqual(await self.model_count(AuditLegacyMetric), 3)
        async with self.sessions() as db:
            events = (await db.execute(select(AuditEvent))).scalars().all()
            self.assertEqual(len(events), 7)
            self.assertTrue(all(event.actor_id in (None, self.member_id) for event in events))
            self.assertTrue(any(event.historical_actor_name == "Synthetic Former Reviewer" for event in events))
            assignment = (await db.execute(select(AuditAssignment))).scalar_one()
            assigned_case = await db.get(AuditCase, assignment.case_id)
            self.assertEqual(assigned_case.responsible_user_id, self.member_id)
            self.assertEqual(assigned_case.workflow_stage, "atomization")
        rolled_back = await self.rollback(committed.json())
        self.assertEqual(rolled_back.status_code, 200, rolled_back.text)
        self.assertEqual(await self.model_count(AuditCase), 1)

    async def test_exact_errors_after_issue_cap_do_not_read_target_db(self):
        transfer = await self.create()
        normalized = {"parser_version": "a19-transfer-v1", "records": [], "issues": [
            {"sheet_id": "1", "row": index, "field": None, "code": "warning", "severity": "warning", "message": "warning"}
            for index in range(500)], "error_count": 1, "warning_count": 500, "issue_count": 501, "total_rows": 501}
        with patch.object(service, "_normalise", return_value=normalized), patch.object(service, "_target_snapshot") as targets:
            preview = await self.preview(transfer, ready=False)
        self.assertEqual(preview["preview"]["counts"]["errors"], 1)
        targets.assert_not_called()

    async def test_missing_case_mapping_resolvable_and_revision_invalidates_preview(self):
        transfer = await self.create(config={"cases": {}})
        preview = await self.preview(transfer, ready=False)
        mapping_key = preview["preview"]["rows"][0]["changes"]["case_mapping_key"]
        config = transfer["config"]
        config["cases"][mapping_key] = {"mode": "create"}
        result = await self.client.put(f"{BASE}/{transfer['id']}/config", json={"revision": 1, "config": config})
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["revision"], 2)
        self.assertIsNone(result.json()["preview"])
        stale = await self.client.post(f"{BASE}/{transfer['id']}/preview", json={"revision": 1})
        self.assertEqual(stale.status_code, 409)
        await self.preview(result.json())

    async def test_cross_file_dedup_and_dependency_blocks_parent_rollback(self):
        preview = await self.preview(await self.create())
        first = (await self.commit(preview)).json()
        second = await self.preview(await self.create(reordered=True))
        self.assertEqual(second["preview"]["counts"]["duplicate"], 2)
        committed = await self.commit(second)
        self.assertEqual(committed.status_code, 200, committed.text)
        self.assertEqual(await self.model_count(AuditAtom), 1)
        self.assertEqual((await self.rollback(first)).status_code, 409)
        self.assertEqual((await self.rollback(committed.json())).status_code, 200)
        self.assertEqual((await self.rollback(first)).status_code, 200)

    async def test_same_key_changed_payload_blocks_and_same_batch_duplicates_dedup(self):
        rows = self.simple_rows()
        rows["atoms"].append(deepcopy(rows["atoms"][0]))
        first = await self.preview(await self.create(rows))
        self.assertEqual(first["preview"]["counts"]["duplicate"], 1)
        self.assertEqual((await self.commit(first)).status_code, 200)
        changed = await self.preview(await self.create(self.simple_rows(title="Changed")), ready=False)
        self.assertIn("source_key_conflict", {item["code"] for item in changed["preview"]["issues"]})

    async def test_live_target_change_invalidates_preview(self):
        committed = (await self.commit(await self.preview(await self.create()))).json()
        preview = await self.preview(await self.create(reordered=True))
        async with self.sessions() as db:
            await db.execute(update(AuditAtom).values(notes="Live edit"))
            await db.commit()
        result = await self.commit(preview)
        self.assertEqual(result.status_code, 409, result.text)
        self.assertEqual(result.json()["detail"]["code"], "stale_preview")
        self.assertEqual((await self.rollback(committed)).status_code, 409)

    async def test_live_event_or_document_blocks_rollback(self):
        committed = (await self.commit(await self.preview(await self.create()))).json()
        async with self.sessions() as db:
            atom = (await db.execute(select(AuditAtom))).scalar_one()
            db.add(AuditEvent(case_id=atom.case_id, atom_id=atom.id, event_type="live_change", message="Live event"))
            await db.commit()
        result = await self.rollback(committed)
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()["detail"]["code"], "rollback_live_reference")
        self.assertEqual(await self.model_count(AuditAtom), 1)

    async def test_journal_failure_rolls_back_all_target_changes(self):
        preview = await self.preview(await self.create())
        with patch.object(service, "record_journal", side_effect=RuntimeError("Synthetic journal failure")):
            with self.assertRaises(RuntimeError):
                await self.commit(preview)
        for model in (AuditCase, AuditAtom, AuditEvent, AuditLegacyProvenance, AuditLegacyTransferRow):
            self.assertEqual(await self.model_count(model), 0)
        self.assertEqual((await self.client.get(f"{BASE}/{preview['id']}")).json()["status"], "previewed")

    async def test_actor_scope_distinct_allowed_overall_and_detail_overlap_block(self):
        rows = {"cases": self.simple_rows()["cases"], "daily_totals": [
            {"case_key": "PRIVATE-CONTRACT-001", "metric_date": "2026-08-01", "metric_type": "verified", "value": 3},
        ]}
        transfer = await self.create(rows)
        config = transfer["config"]
        # Derive a second aggregate dataset with a different explicit actor default.
        config["datasets"][1]["defaults"] = {"actor_name": "Alice"}
        config["datasets"].append({**config["datasets"][1], "defaults": {"actor_name": "Bob"}})
        config["actors"] = {name: {"mode": "historical", "historical_name": name} for name in ("Alice", "Bob")}
        updated = await self.client.put(f"{BASE}/{transfer['id']}/config", json={"revision": 1, "config": config})
        preview = await self.preview(updated.json())
        committed = await self.commit(preview)
        self.assertEqual(committed.status_code, 200, committed.text)
        self.assertEqual(await self.model_count(AuditLegacyMetric), 2)
        rows["daily_totals"][0]["value"] = 7
        total = await self.preview(await self.create(rows, config={"namespace": "other", "cases": {
            "PRIVATE-CONTRACT-001": {"mode": "existing", "target_case_id": committed.json()["preview"]["rows"][0]["target_id"]},
        }}), ready=False)
        self.assertIn("aggregate_coverage_overlap", {issue["code"] for issue in total["preview"]["issues"]})

    async def test_pagination_includes_unresolved_rows_beyond_500(self):
        rows = {"cases": self.simple_rows()["cases"], "atoms": [
            {"case_key": "PRIVATE-CONTRACT-001", "atom_key": f"A{index}", "title": "Atom", "state": "draft"}
            for index in range(550)]}
        preview = await self.preview(await self.create(rows))
        self.assertEqual(len(preview["preview"]["rows"]), 500)
        self.assertEqual(preview["preview"]["next_offset"], 500)
        page = await self.client.get(f"{BASE}/{preview['id']}/preview/rows?offset=500&limit=500")
        self.assertEqual(page.status_code, 200, page.text)
        self.assertEqual(len(page.json()["rows"]), 51)
        self.assertIsNone(page.json()["next_offset"])

    async def test_admin_only_and_strict_confirmation(self):
        transfer = await self.create()
        self.user.role = next(role for role in UserRole if role != UserRole.admin)
        self.assertEqual((await self.client.get(BASE)).status_code, 403)
        self.assertEqual((await self.client.get(BASE + "/options")).status_code, 403)
        self.assertEqual((await self.client.post(f"{BASE}/{transfer['id']}/preview", json={"revision": 1})).status_code, 403)
        for value in (False, 1, "true"):
            with self.assertRaises(ValueError):
                TransferCommit(revision=1, preview_hash="a" * 64, confirm=value)

    async def test_thousand_atom_commit_and_rollback_are_batched(self):
        rows = {"cases": self.simple_rows()["cases"], "atoms": [
            {"case_key": "PRIVATE-CONTRACT-001", "atom_key": f"A{index}", "title": "Atom", "state": "ready", "occurred_at": "2026-08-01"}
            for index in range(1000)]}
        preview = await self.preview(await self.create(rows))
        statements = []

        def record_sql(_connection, _cursor, statement, _parameters, _context, _many):
            statements.append(statement)

        event.listen(self.engine.sync_engine, "before_cursor_execute", record_sql)
        started = perf_counter()
        committed = await self.commit(preview)
        commit_seconds = perf_counter() - started
        commit_statements = len(statements)
        self.assertEqual(committed.status_code, 200, committed.text)
        self.assertLess(commit_statements, 100)
        started = perf_counter()
        rolled_back = await self.rollback(committed.json())
        rollback_seconds = perf_counter() - started
        self.assertEqual(rolled_back.status_code, 200, rolled_back.text)
        self.assertLess(len(statements) - commit_statements, 100)
        self.assertLess(commit_seconds + rollback_seconds, 30)
        print(f"A1.9 synthetic 1000 atoms: commit={commit_seconds:.3f}s/{commit_statements} SQL, rollback={rollback_seconds:.3f}s/{len(statements)-commit_statements} SQL")

    async def test_events_only_later_batch_reuses_case_reference(self):
        first = (await self.commit(await self.preview(await self.create()))).json()
        target_case_id = first["preview"]["rows"][0]["target_id"]
        rows = {"events": [{"case_key": "PRIVATE-CONTRACT-001", "atom_key": "A1", "event_key": "later-review",
                           "event_type": "alpha_reviewed", "occurred_at": "2026-08-02", "alpha_result": "present"}]}
        preview = await self.preview(await self.create(rows, config={"cases": {"PRIVATE-CONTRACT-001": {
            "mode": "existing", "target_case_id": target_case_id}}}))
        committed = await self.commit(preview)
        self.assertEqual(committed.status_code, 200, committed.text)
        self.assertEqual((await self.rollback(first)).status_code, 409)

    async def test_new_atom_event_replay_and_contradictory_snapshot(self):
        rows = self.simple_rows(state=None, occurred_at=None)
        rows["events"] = [
            {"case_key": "PRIVATE-CONTRACT-001", "atom_key": "A1", "event_key": "verified",
             "event_type": "atom_status_changed", "occurred_at": "2026-08-01", "previous_state": "draft", "state": "ready"},
            {"case_key": "PRIVATE-CONTRACT-001", "atom_key": "A1", "event_key": "alpha",
             "event_type": "alpha_reviewed", "occurred_at": "2026-08-02", "alpha_result": "present"},
        ]
        preview = await self.preview(await self.create(rows))
        self.assertEqual((await self.commit(preview)).status_code, 200)
        async with self.sessions() as db:
            atom = (await db.execute(select(AuditAtom))).scalar_one()
            self.assertEqual(atom.state, "ready")
            self.assertEqual(atom.alpha_result, "present")
            self.assertEqual(atom.alpha_date, date(2026, 8, 2))
        rows["atoms"][0].update(state="excluded", occurred_at="2026-08-01")
        preview = await self.preview(await self.create(rows, config={"namespace": "contradiction"}), ready=False)
        self.assertIn("snapshot_state_conflict", {issue["code"] for issue in preview["preview"]["issues"]})

    async def test_two_source_aliases_fill_one_target_rollback_restores_original(self):
        async with self.sessions() as db:
            case = AuditCase(title="Imported case", digital_product="Product", contract_date=None, notes=None)
            db.add(case)
            await db.commit()
            case_id = str(case.id)
        rows = {"cases": [
            {"case_key": "ALIAS1", "title": "Imported case", "digital_product": "Product", "contract_date": "2026-01-01"},
            {"case_key": "ALIAS2", "title": "Imported case", "digital_product": "Product", "contract_date": "2026-01-01"},
        ]}
        config = {"cases": {key: {"mode": "existing", "target_case_id": case_id, "fill_empty": ["contract_date"]} for key in ("ALIAS1", "ALIAS2")}}
        committed = await self.commit(await self.preview(await self.create(rows, config=config)))
        self.assertEqual(committed.status_code, 200, committed.text)
        result = await self.rollback(committed.json())
        self.assertEqual(result.status_code, 200, result.text)
        async with self.sessions() as db:
            self.assertIsNone((await db.get(AuditCase, UUID(case_id))).contract_date)

    async def test_explicit_fill_empty_atom_does_not_default_existing_state_to_draft(self):
        async with self.sessions() as db:
            case = AuditCase(title="Imported case", digital_product="Product")
            db.add(case)
            await db.flush()
            atom = AuditAtom(case_id=case.id, item_code="LIVE", title="Atom", digital_product="Product", state="ready")
            db.add(atom)
            await db.commit()
            case_id, atom_id = str(case.id), str(atom.id)
        rows = self.simple_rows(state=None, occurred_at=None, work_type="Filled work")
        row_key = "atoms:" + service.source_identity("atoms", rows["atoms"][0])
        config = {"cases": {"PRIVATE-CONTRACT-001": {"mode": "existing", "target_case_id": case_id}},
                  "row_decisions": {row_key: {"action": "fill_empty", "target_id": atom_id, "fill_empty": ["work_type"]}}}
        committed = await self.commit(await self.preview(await self.create(rows, config=config)))
        self.assertEqual(committed.status_code, 200, committed.text)
        async with self.sessions() as db:
            atom = await db.get(AuditAtom, UUID(atom_id))
            self.assertEqual(atom.state, "ready")
            self.assertEqual(atom.work_type, "Filled work")
        rolled_back = await self.rollback(committed.json())
        self.assertEqual(rolled_back.status_code, 200, rolled_back.text)
        async with self.sessions() as db:
            self.assertIsNone((await db.get(AuditAtom, UUID(atom_id))).work_type)

    async def test_current_assignment_requires_eligible_member_and_ended_stays_historical(self):
        rows = {"cases": self.simple_rows()["cases"], "assignments": [{
            "case_key": "PRIVATE-CONTRACT-001", "assignment_key": "old", "actor_name": "Past member",
            "assigned_at": "2026-08-01", "is_current": "true",
        }]}
        preview = await self.preview(await self.create(rows, config={
            "apply_current_assignments": True, "actors": {"Past member": {"mode": "user", "user_id": str(self.member_id)}}}), ready=False)
        self.assertIn("current_assignment_ineligible", {issue["code"] for issue in preview["preview"]["issues"]})
        config = deepcopy(preview["config"])
        config["datasets"][1]["defaults"] = {"ended_at": "2026-08-02"}
        config["datasets"][1]["fields"].pop("is_current")
        updated = await self.client.put(f"{BASE}/{preview['id']}/config", json={"revision": preview["revision"], "config": config})
        ready = await self.preview(updated.json())
        committed = await self.commit(ready)
        self.assertEqual(committed.status_code, 200, committed.text)
        self.assertEqual(await self.model_count(AuditAssignment), 0)
        async with self.sessions() as db:
            history = (await db.execute(select(AuditEvent))).scalar_one()
            self.assertEqual(history.payload_json["ended_at"], "2026-08-01T21:00:00+00:00")

    async def test_same_namespace_unrelated_case_is_outside_lock_and_freshness_scope(self):
        first = (await self.commit(await self.preview(await self.create()))).json()
        unrelated_id = UUID(first["preview"]["rows"][0]["target_id"])
        rows = self.simple_rows()
        for dataset in rows.values():
            for row in dataset:
                row["case_key"] = "OTHER-CASE"
        preview = await self.preview(await self.create(rows))
        async with self.sessions() as db:
            await db.execute(update(AuditCase).where(AuditCase.id == unrelated_id).values(notes="Unrelated edit"))
            await db.commit()
        with patch.object(service, "lock_targets", wraps=service.lock_targets) as locked:
            committed = await self.commit(preview)
        self.assertEqual(committed.status_code, 200, committed.text)
        self.assertNotIn(unrelated_id, locked.await_args.args[1])

    async def test_archived_case_blocks_current_assignment_but_allows_history_only(self):
        async with self.sessions() as db:
            case = AuditCase(title="Imported case", digital_product="Product", status="archived")
            db.add(case)
            db.add(AuditTeamMember(user_id=self.member_id, role="member"))
            await db.commit()
            case_id = case.id
        rows = {"cases": self.simple_rows()["cases"], "assignments": [{
            "case_key": "PRIVATE-CONTRACT-001", "assignment_key": "assigned-1", "actor_name": "Reviewer",
            "assigned_at": "2026-08-01T09:00:00+03:00", "is_current": "true",
        }]}
        config = {
            "apply_current_assignments": True,
            "cases": {"PRIVATE-CONTRACT-001": {"mode": "existing", "target_case_id": str(case_id)}},
            "actors": {"Reviewer": {"mode": "user", "user_id": str(self.member_id)}},
        }
        preview = await self.preview(await self.create(rows, config=config), ready=False)
        self.assertIn("current_assignment_archived_case", {issue["code"] for issue in preview["preview"]["issues"]})
        self.assertEqual((await self.commit(preview)).status_code, 409)
        self.assertEqual(await self.model_count(AuditAssignment), 0)
        self.assertEqual(await self.model_count(AuditEvent), 0)
        config = deepcopy(preview["config"])
        config["apply_current_assignments"] = False
        updated = await self.client.put(f"{BASE}/{preview['id']}/config", json={"revision": preview["revision"], "config": config})
        historical = await self.preview(updated.json())
        committed = await self.commit(historical)
        self.assertEqual(committed.status_code, 200, committed.text)
        self.assertEqual(await self.model_count(AuditAssignment), 0)
        async with self.sessions() as db:
            case = await db.get(AuditCase, case_id)
            self.assertEqual(case.status, "archived")
            self.assertIsNone(case.responsible_user_id)
            self.assertEqual(case.workflow_stage, "unassigned")
            history = (await db.execute(select(AuditEvent))).scalar_one()
            self.assertTrue(history.payload_json["historical_only"])
            self.assertEqual(service.json_value(history.occurred_at), "2026-08-01T06:00:00+00:00")

    async def test_current_assignment_hash_preserves_time_and_normalizes_timezone(self):
        async with self.sessions() as db:
            db.add(AuditTeamMember(user_id=self.member_id, role="member"))
            await db.commit()
        rows = {"cases": self.simple_rows()["cases"], "assignments": [{
            "case_key": "PRIVATE-CONTRACT-001", "assignment_key": "assigned-1", "actor_name": "Reviewer",
            "assigned_at": "2026-08-01T09:00:00+03:00", "is_current": "true",
        }]}
        config = {"apply_current_assignments": True, "actors": {"Reviewer": {"mode": "user", "user_id": str(self.member_id)}}}
        first = await self.commit(await self.preview(await self.create(rows, config=config)))
        self.assertEqual(first.status_code, 200, first.text)
        rows["assignments"][0]["assigned_at"] = "2026-08-01T06:00:00Z"
        equivalent = await self.preview(await self.create(rows, config=config, reordered=True))
        self.assertEqual(equivalent["preview"]["counts"]["duplicate"], 2)
        self.assertEqual((await self.commit(equivalent)).status_code, 200)
        rows["assignments"][0]["assigned_at"] = "2026-08-01T10:00:00+03:00"
        changed = await self.preview(await self.create(rows, config=config), ready=False)
        self.assertIn("source_key_conflict", {issue["code"] for issue in changed["preview"]["issues"]})
        self.assertEqual((await self.commit(changed)).status_code, 409)
        self.assertEqual(await self.model_count(AuditAssignment), 1)
        self.assertEqual(await self.model_count(AuditEvent), 1)
        async with self.sessions() as db:
            history = (await db.execute(select(AuditEvent))).scalar_one()
            self.assertEqual(service.json_value(history.occurred_at), "2026-08-01T06:00:00+00:00")

    async def test_same_batch_current_assignment_changed_time_is_a_conflict(self):
        async with self.sessions() as db:
            db.add(AuditTeamMember(user_id=self.member_id, role="member"))
            await db.commit()
        rows = {"cases": self.simple_rows()["cases"], "assignments": [
            {"case_key": "PRIVATE-CONTRACT-001", "assignment_key": "assigned-1", "actor_name": "Reviewer",
             "assigned_at": assigned_at, "is_current": "true"}
            for assigned_at in ("2026-08-01T09:00:00+03:00", "2026-08-01T10:00:00+03:00")
        ]}
        config = {"apply_current_assignments": True, "actors": {"Reviewer": {"mode": "user", "user_id": str(self.member_id)}}}
        preview = await self.preview(await self.create(rows, config=config), ready=False)
        self.assertIn("duplicate_source_conflict", {issue["code"] for issue in preview["preview"]["issues"]})
        self.assertEqual((await self.commit(preview)).status_code, 409)
        self.assertEqual(await self.model_count(AuditAssignment), 0)


class TransferSQLTests(unittest.IsolatedAsyncioTestCase):
    async def test_postgres_locks_include_child_tables_and_live_writer_exclusion(self):
        db = AsyncMock(spec=AsyncSession)
        db.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        await service.lock_transfers(db)
        self.assertIn("pg_advisory_xact_lock", str(db.execute.await_args.args[0]))
        db.execute.return_value = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [uuid4()]))
        await service.lock_targets(db, [uuid4()])
        statements = [str(call.args[0].compile(dialect=postgresql.dialect())) for call in db.execute.await_args_list]
        sql = "\n".join(statements)
        self.assertNotIn("LOCK TABLE", sql)
        self.assertNotIn("FROM users", sql)
        self.assertIn("FOR UPDATE", sql)
        self.assertIn("audit_events", sql)
        self.assertIn("audit_cases", sql)

    async def test_provenance_uniqueness_and_metric_actor_scope(self):
        sql = str(CreateTable(AuditLegacyProvenance.__table__).compile(dialect=postgresql.dialect()))
        self.assertIn("UNIQUE (namespace, kind, source_key_hash)", sql)
        metrics = str(CreateTable(AuditLegacyMetric.__table__).compile(dialect=postgresql.dialect()))
        self.assertIn("UNIQUE (case_id, metric_date, metric_type, actor_scope)", metrics)

    async def test_migration_chain_nonempty_guard_and_article(self):
        path = Path(__file__).resolve().parents[1] / "alembic/versions/083_audit_legacy_transfer.py"
        spec = importlib.util.spec_from_file_location("transfer_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        self.assertEqual(migration.down_revision, "082_audit_legacy_upload")
        self.assertLessEqual(len(migration.revision), 32)
        with patch.object(migration, "op") as operations:
            operations.get_bind.return_value.execute.return_value.scalar_one.return_value = 1
            with self.assertRaisesRegex(RuntimeError, "nonempty"):
                migration.downgrade()
            operations.drop_table.assert_not_called()
        with patch.object(migration, "op") as operations:
            migration.upgrade()
            self.assertEqual(operations.create_table.call_count, 4)
            self.assertIn("legacy_atom_snapshot", migration.ARTICLE["body"])


if __name__ == "__main__":
    unittest.main()
