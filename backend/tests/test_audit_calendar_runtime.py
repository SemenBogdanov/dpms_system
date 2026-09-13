"""Opt-in synthetic PostgreSQL rehearsal, never loads app settings or .env.

Run from backend:
  python -m unittest discover -s tests -p 'test_audit_calendar_*.py'
Set AUDIT_CALENDAR_TEST_DATABASE_URL in the runner environment. Only the two
integrator-approved disposable database names are accepted. Each test creates
and removes its own randomly named schema; ordinary DPMS tables are untouched.
"""
import asyncio
from datetime import date, datetime, timedelta, timezone
import importlib.util
import os
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import unittest
from uuid import UUID, uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
DEPENDENCIES = all(importlib.util.find_spec(name) for name in ("sqlalchemy", "alembic", "asyncpg", "fastapi"))
TEST_URL = os.environ.get("AUDIT_CALENDAR_TEST_DATABASE_URL")
READY = DEPENDENCIES and bool(TEST_URL)


def load_runtime():
    """An isolated model registry prevents importing production configuration."""
    global sa, async_sessionmaker, create_async_engine, models, service, imports, schema, User, migration, Operations, MigrationContext
    import sqlalchemy as sa
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
    from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
    from alembic.operations import Operations
    from alembic.migration import MigrationContext
    class Base(DeclarativeBase):
        pass
    package = ModuleType("app.models")
    package.__path__ = [str(Path(__file__).resolve().parents[1] / "app" / "models")]
    package.Base = Base
    sys.modules["app.models"] = package
    class User(Base):
        __tablename__ = "users"
        id: Mapped[UUID] = mapped_column(primary_key=True)
        full_name: Mapped[str] = mapped_column(sa.String(255))
        email: Mapped[str] = mapped_column(sa.String(255))
        role: Mapped[str] = mapped_column(sa.String(32))
        is_active: Mapped[bool] = mapped_column(sa.Boolean)
        audit_calendar_enabled: Mapped[bool] = mapped_column(sa.Boolean)
        auth_version: Mapped[int] = mapped_column(sa.Integer)
    user_module = ModuleType("app.models.user")
    user_module.User = User
    sys.modules["app.models.user"] = user_module
    # These modules have no configuration, transports or provider dependencies.
    import app.models.audit_calendar as models
    import app.services.audit_calendar as service
    import app.services.audit_calendar_imports as imports
    import app.schemas.audit_calendar as schema
    path = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "087_audit_calendar.py"
    spec = importlib.util.spec_from_file_location("calendar_test_migration_087", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)


@unittest.skipUnless(READY, "Requires dependencies and AUDIT_CALENDAR_TEST_DATABASE_URL for an approved disposable DB")
class CalendarRuntimeTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        load_runtime()
        from sqlalchemy.engine import make_url
        cls.url = make_url(TEST_URL)
        if cls.url.database not in ("dpms_calendar_v5_test", "dpms_calendar_v5_upgrade"):
            raise RuntimeError("Refusing calendar tests outside the two approved disposable databases")
        if not cls.url.drivername.startswith("postgresql"):
            raise RuntimeError("Calendar runtime tests require PostgreSQL")
        cls.url = cls.url.set(drivername="postgresql+asyncpg")

    async def asyncSetUp(self):
        self.schema_name = "ac_synthetic_" + uuid4().hex
        self.engine = create_async_engine(self.url, connect_args={"server_settings": {"search_path": self.schema_name}})
        async with self.engine.begin() as conn:
            await conn.execute(sa.text(f'CREATE SCHEMA "{self.schema_name}"'))
            await conn.execute(sa.text("""CREATE TABLE users(id uuid PRIMARY KEY, full_name varchar(255) NOT NULL,
                email varchar(255) NOT NULL, role varchar(32) NOT NULL, is_active boolean NOT NULL, auth_version integer NOT NULL)"""))
            def upgrade(sync):
                with Operations.context(MigrationContext.configure(sync)):
                    migration.upgrade()
            await conn.run_sync(upgrade)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.today = datetime.now(service.MOSCOW).date()
        self.now = datetime.combine(self.today, datetime.min.time(), service.MOSCOW) + timedelta(hours=23)
        self.actors = {name: SimpleNamespace(id=uuid4(), auth_version=0) for name in ("admin", "helper", "auditor", "tech", "speaker", "other", "denied")}
        async with self.sessions.begin() as db:
            for name, actor in self.actors.items():
                db.add(User(id=actor.id, full_name="Synthetic " + name, email=name + "@synthetic.invalid",
                    role="admin" if name == "admin" else "employee", is_active=True,
                    audit_calendar_enabled=name not in ("admin", "denied"), auth_version=0))
        self.version = 0
        await self.setup_scope()

    async def asyncTearDown(self):
        if hasattr(self, "engine"):
            async with self.engine.begin() as conn:
                await conn.execute(sa.text(f'DROP SCHEMA "{self.schema_name}" CASCADE'))
            await self.engine.dispose()

    async def call(self, actor, method, *args, import_service=False, **kwargs):
        async with self.sessions.begin() as db:
            cls = imports.CalendarImportService if import_service else service.CalendarService
            return await getattr(cls(db, self.actors[actor], now=self.now), method)(*args, **kwargs)

    async def setup_scope(self):
        result = await self.call("admin", "setup", schema.Setup(request_id=uuid4(), name="Synthetic scope", baseline=date(2026, 8, 28)))
        self.version = result["version"]
        self.scope_id = UUID(result["result"]["id"])
        for name, role in [("helper", "observer"), ("auditor", "auditor"), ("tech", "tech"), ("speaker", "speaker"), ("other", "auditor")]:
            result = await self.call("admin", "save_member", schema.MemberSave(request_id=uuid4(), expected_version=self.version,
                user_id=self.actors[name].id, code=name, role=role, can_manage=name == "helper", active=True))
            self.version = result["version"]

    def body(self, operation, payload, *, version=None, request_id=None):
        return schema.command_adapter.validate_python({"request_id": request_id or uuid4(),
            "expected_version": self.version if version is None else version, "operation": operation, "payload": payload})

    async def command(self, operation, payload, *, actor="helper", **kwargs):
        result = await self.call(actor, "command", self.body(operation, payload, **kwargs))
        self.version = result["version"]
        return result["result"]

    async def group(self, code="SYNTH-G"):
        result = await self.command("group.save", {"code": code, "label": code, "effective_from": self.today,
            "auditor_id": self.actors["auditor"].id, "tech_id": self.actors["tech"].id, "reason": "Synthetic group"})
        return UUID(result["id"])

    def plan_payload(self, group, **updates):
        return {"date": self.today, "start": 600, "duration": 60, "group_id": group,
                "activity": "SYNTH", "speaker_id": self.actors["speaker"].id, "status": "planned", **updates}

    def assert_status(self, code):
        from fastapi import HTTPException
        class Expected:
            def __enter__(inner):
                return inner
            def __exit__(inner, kind, exc, tb):
                self.assertIsInstance(exc, HTTPException)
                self.assertEqual(exc.status_code, code)
                return True
        return Expected()

    async def test_admin_has_no_calendar_read_or_write_bypass(self):
        admin = await self.call("admin", "admin_state")
        self.assertIn("users", admin)
        self.assertNotIn("plans", admin)
        for name in ("admin", "denied"):
            with self.assert_status(403):
                await self.call(name, "state", self.today, self.today)
            with self.assert_status(403):
                await self.call(name, "imports", import_service=True)
        with self.assert_status(403):
            await self.call("speaker", "admin_state")

    async def test_membership_requires_explicit_section_grant(self):
        with self.assert_status(422):
            await self.call("admin", "save_member", schema.MemberSave(request_id=uuid4(), expected_version=self.version,
                user_id=self.actors["denied"].id, code="denied", role="observer", can_manage=False, active=True))

    async def test_scope_stale_and_replay_body_conflict(self):
        gid = await self.group()
        body = self.body("plan.save", self.plan_payload(gid))
        first = await self.call("helper", "command", body)
        self.assertEqual(first, await self.call("helper", "command", body))
        changed = body.model_copy(update={"expected_version": first["version"]})
        with self.assert_status(409):
            await self.call("helper", "command", changed)
        with self.assert_status(409):
            await self.call("helper", "command", self.body("plan.save", self.plan_payload(gid, start=720)))

    async def test_revocation_checked_before_replay(self):
        gid = await self.group()
        body = self.body("plan.save", self.plan_payload(gid))
        await self.call("helper", "command", body)
        async with self.sessions.begin() as db:
            await db.execute(sa.update(User).where(User.id == self.actors["helper"].id).values(audit_calendar_enabled=False, auth_version=1))
        with self.assert_status(403):
            await self.call("helper", "command", body)

    async def test_ownership_and_helper_guard(self):
        with self.assert_status(403):
            await self.command("norm.set", {"group_id": None, "effective_from": self.today, "value": 4, "reason": "Not helper"}, actor="speaker")
        with self.assert_status(403):
            await self.command("absence.add", {"user_id": self.actors["auditor"].id, "start_date": self.today,
                "end_date": self.today, "reason": "Not owner"}, actor="speaker")
        await self.command("availability.paint", {"user_id": self.actors["speaker"].id, "patches": [
            {"date": self.today, "start": 0, "end": 1440, "value": True}]}, actor="speaker")

    async def test_unknown_free_union_busy_and_absence_on_save(self):
        gid = await self.group()
        result = await self.command("plan.save", self.plan_payload(gid))
        self.assertTrue(result["warnings"])
        await self.command("availability.paint", {"user_id": self.actors["auditor"].id, "patches": [
            {"date": self.today, "start": 720, "end": 750, "value": True}]})
        with self.assert_status(422):
            await self.command("plan.save", self.plan_payload(gid, start=720))
        await self.command("availability.paint", {"user_id": self.actors["auditor"].id, "patches": [
            {"date": self.today, "start": 750, "end": 780, "value": True}]})
        await self.command("plan.save", self.plan_payload(gid, start=720))
        await self.command("absence.add", {"user_id": self.actors["auditor"].id, "start_date": self.today,
            "end_date": self.today, "reason": "Synthetic absence"})
        state = await self.call("helper", "state", self.today, self.today)
        self.assertTrue(any(i["code"] == "UNAVAILABLE" for p in state["plans"] for i in p["issues"]))

    async def test_concurrent_shared_participant_bookings_serialize(self):
        first_group, second_group = await self.group("FIRST"), await self.group("SECOND")
        bodies = [self.body("plan.save", self.plan_payload(g)) for g in (first_group, second_group)]
        results = await asyncio.gather(*(self.call("helper", "command", body) for body in bodies), return_exceptions=True)
        self.assertEqual(sum(isinstance(r, dict) for r in results), 1)
        self.assertEqual([r.status_code for r in results if not isinstance(r, dict)], [409])

    async def test_fact_90_minutes_counts_once_and_freezes_children(self):
        gid = await self.group()
        plan = await self.command("plan.save", self.plan_payload(gid, duration=90))
        payload = {k: v for k, v in self.plan_payload(gid, duration=90).items() if k != "status"}
        payload.update(plan_id=plan["id"], outcome="completed", reason="Fixture completion", evidence="Synthetic document", auditor_absent_minutes=5)
        fact = await self.command("fact.record", payload)
        state = await self.call("helper", "state", self.today, self.today)
        self.assertEqual(state["stats"]["fact"], 1)
        self.assertEqual(state["stats"]["through"], (self.today - timedelta(days=1)).isoformat())
        with self.assert_status(409):
            await self.command("plan.save", self.plan_payload(gid, id=plan["id"], start=720))
        for sql in ["UPDATE audit_calendar_facts SET reason='tampered'", "DELETE FROM audit_calendar_fact_participants",
                    "UPDATE audit_calendar_plans SET activity='tampered'", "DELETE FROM audit_calendar_plan_participants"]:
            with self.assertRaises(sa.exc.DBAPIError):
                async with self.sessions.begin() as db:
                    await db.execute(sa.text(sql))
        async with self.sessions.begin() as db:
            saved = await db.get(models.AuditCalendarFact, UUID(fact["id"]))
            self.assertEqual(saved.reason, "Fixture completion")

    async def test_more_than_five_minutes_and_unfinished_fact_rejected(self):
        gid = await self.group()
        plan = await self.command("plan.save", self.plan_payload(gid))
        payload = {k: v for k, v in self.plan_payload(gid).items() if k != "status"}
        payload.update(plan_id=plan["id"], outcome="completed", reason="Synthetic", evidence="Synthetic", auditor_absent_minutes=6)
        with self.assert_status(422):
            await self.command("fact.record", payload)
        payload.update(auditor_absent_minutes=0, start=1380, duration=60)
        with self.assert_status(422):
            await self.command("fact.record", payload)

    async def test_norm_versions_archive_and_filter_independent_targets(self):
        gid = await self.group()
        await self.command("norm.set", {"group_id": None, "effective_from": self.today, "value": 4, "reason": "Synthetic norm"})
        await self.command("norm.set", {"group_id": None, "effective_from": self.today + timedelta(days=2), "value": 0, "reason": "Zero norm"})
        before = await self.call("helper", "state", self.today, self.today + timedelta(days=6))
        filtered = await self.call("helper", "state", self.today, self.today + timedelta(days=6), person_id=self.actors["speaker"].id, query="no matches")
        self.assertEqual(before["stats"]["target"], filtered["stats"]["target"])
        self.assertEqual(before["stats"]["backlog"], filtered["stats"]["backlog"])
        self.assertEqual(len(before["stats"]["daily_targets"]), 7)
        await self.command("scope.archive", {"archived": True, "reason": "Synthetic archive"})
        with self.assert_status(409):
            await self.command("plan.save", self.plan_payload(gid))
        self.assertTrue((await self.call("helper", "state", self.today, self.today))["scope"]["archived"])

    async def preview_source(self, source, **kwargs):
        result = await self.call("helper", "preview", schema.ImportPreview(request_id=uuid4(), expected_version=self.version,
            source=source, mapping={"S1": self.actors["speaker"].id}, **kwargs), import_service=True)
        self.version = result["version"]
        return result

    async def apply_source(self, preview):
        result = await self.call("helper", "apply", UUID(preview["id"]), schema.ImportApply(request_id=uuid4(),
            expected_version=self.version, confirm=True, reason="Explicit synthetic acceptance"), import_service=True)
        self.version = result["version"]
        return result

    async def test_source_preview_apply_replay_and_working_revision(self):
        from test_audit_calendar_schema import source_fixture
        source = source_fixture()
        preview = await self.preview_source(source)
        self.assertEqual(preview["status"], "ready")
        await self.apply_source(preview)
        await self.apply_source(preview)
        state = await self.call("helper", "state", date(2026, 9, 1), date(2026, 9, 1))
        self.assertEqual(len(state["plans"]), 1)
        self.assertEqual(len(state["facts"]), 0)
        gid = await self.group()
        plan_id = state["plans"][0]["id"]
        with self.assert_status(422):
            await self.command("plan.save", self.plan_payload(gid, id=plan_id))
        revised = await self.command("plan.revise", self.plan_payload(gid, id=plan_id, reason="Explicit working revision"))
        self.assertEqual(revised["origin"], "working-revision")
        self.assertIsNotNone(revised["source_id"])

    async def test_historic_restore_a_plus_a_conflict_and_fixed_group_binding(self):
        from test_audit_calendar_schema import source_fixture
        source = source_fixture()
        source["data"]["plans"].append({**source["data"]["plans"][0], "id": "synthetic-second", "sourceRow": 3})
        preview = await self.preview_source(source)
        await self.apply_source(preview)
        state = await self.call("helper", "state", date(2026, 9, 1), date(2026, 9, 1))
        group_id = state["groups"][0]["id"]
        async with self.sessions.begin() as db:
            await db.execute(sa.update(models.AuditCalendarGroup).values(code="RENAMED").where(models.AuditCalendarGroup.id == UUID(group_id)))
        payload = {"source_row_id": preview["rows"][0]["id"], "date": "2026-09-01", "start": 600,
            "duration": 60, "activity": "SYNTH", "speaker_id": self.actors["speaker"].id, "outcome": "completed",
            "reason": "Synthetic historic evidence", "evidence": "Fixture document", "confirm": True,
            "composition_unknown": False, "participants": [
                {"user_id": self.actors["auditor"].id, "role": "auditor"},
                {"user_id": self.actors["other"].id, "role": "auditor"},
                {"user_id": self.actors["speaker"].id, "role": "speaker"}]}
        fact = await self.command("fact.restore", payload)
        self.assertEqual(fact["group_id"], group_id)
        with self.assert_status(422):
            await self.command("fact.restore", {**payload, "source_row_id": preview["rows"][1]["id"]})
        with self.assert_status(422):
            await self.command("fact.restore", {**payload, "source_row_id": preview["rows"][1]["id"], "date": "2026-09-12"})

    async def test_full_synthetic_v5_bootstrap_keeps_g21_unknown(self):
        from test_audit_calendar_schema import source_fixture
        source = source_fixture()
        source["data"]["plans"][0]["groupId"] = "G21"
        source["data"]["planning"] = {"trackingStart": "2026-08-28",
            "dailyTargets": [{"from": "2026-08-28", "value": 6}, {"from": "2026-09-01", "value": 4}],
            "groupTargets": [{"groupId": f"G{i}", "from": "2026-08-28", "value": 3} for i in range(1, 21)], "absences": []}
        pairs = {f"G{i}": {"auditor_id": self.actors["auditor"].id, "tech_id": self.actors["tech"].id} for i in range(1, 21)}
        preview = await self.preview_source(source, bootstrap_history=True, group_mapping=pairs)
        self.assertEqual(preview["issues"], [])
        await self.apply_source(preview)
        state = await self.call("helper", "state", date(2026, 8, 28), date(2026, 9, 11))
        self.assertEqual(len(state["groups"]), 21)
        g21 = next(g for g in state["groups"] if g["code"] == "G21")
        self.assertTrue(g21["legacy"])
        self.assertEqual(g21["versions"], [])
        self.assertFalse(any(n["group_id"] == g21["id"] for n in state["norms"]))
        self.assertEqual(sum(not g["legacy"] for g in state["groups"]), 20)
        self.assertEqual(sum(n["group_id"] is not None for n in state["norms"]), 20)

    async def test_import_busy_windows_block_future_plan_in_preview(self):
        from test_audit_calendar_schema import source_fixture
        await self.group("MODERN")
        source = source_fixture()
        source["data"]["plans"][0].update(date=self.today.isoformat(), groupId="MODERN", origin="native")
        source["data"]["availability"] = [{"personId": "S1", "date": self.today.isoformat(), "start": 600, "end": 660, "available": False}]
        preview = await self.preview_source(source)
        self.assertTrue(any(i["code"] == "UNAVAILABLE" for i in preview["issues"]))
        with self.assert_status(409):
            await self.apply_source(preview)

    async def test_immutable_source_events_norms_and_downgrade(self):
        from test_audit_calendar_schema import source_fixture
        preview = await self.preview_source(source_fixture())
        await self.apply_source(preview)
        for table in ("import_batches", "import_rows", "import_mappings", "import_applications", "events", "norm_revisions", "idempotency"):
            with self.subTest(table=table), self.assertRaises(sa.exc.DBAPIError):
                async with self.sessions.begin() as db:
                    await db.execute(sa.text(f"DELETE FROM audit_calendar_{table}"))
        with self.assertRaises(RuntimeError):
            migration.downgrade()

    async def test_availability_residuals_and_absence_history(self):
        uid = self.actors["speaker"].id
        await self.command("availability.paint", {"user_id": uid, "patches": [
            {"date": self.today, "start": 0, "end": 1440, "value": True}]}, actor="speaker")
        await self.command("availability.paint", {"user_id": uid, "patches": [
            {"date": self.today, "start": 600, "end": 660, "value": None}]}, actor="speaker")
        state = await self.call("helper", "state", self.today, self.today)
        self.assertEqual(sorted((w["start"], w["end"]) for w in state["availability"]), [(0, 600), (660, 1440)])
        absence_id = uuid4()
        async with self.sessions.begin() as db:
            db.add(models.AuditCalendarAbsence(id=absence_id, scope_id=self.scope_id, user_id=uid,
                start_date=self.today-timedelta(days=2), end_date=self.today+timedelta(days=2),
                reason="Synthetic existing history", version=1, status="active"))
        ended = await self.command("absence.end", {"id": absence_id, "reason": "Explicit end today"}, actor="speaker")
        self.assertEqual(ended["after"]["end_date"], (self.today-timedelta(days=1)).isoformat())
        self.assertEqual(ended["after"]["reason"], "Synthetic existing history")
        with self.assertRaises(sa.exc.DBAPIError):
            async with self.sessions.begin() as db:
                await db.execute(sa.text("DELETE FROM audit_calendar_absences"))

    async def test_standalone_source_fact_stays_unlinked_and_old_json_keeps_norms(self):
        from test_audit_calendar_schema import source_fixture
        source = source_fixture()
        source["data"]["facts"] = [{"id": "synthetic-standalone", "kind": "fact", "date": "2026-09-01",
            "start": 720, "duration": 90, "groupId": "OLD-SYNTH", "activity": "SYNTH",
            "speakerId": "S1", "sourceRow": 38, "origin": "source", "outcome": "completed", "planId": None,
            "participantIds": ["S1"], "participantSnapshot": [{"id": "S1", "name": "Synthetic speaker", "role": "speaker"}]}]
        await self.command("norm.set", {"group_id": None, "effective_from": self.today, "value": 4, "reason": "Preserve this norm"})
        preview = await self.preview_source(source)
        self.assertEqual(preview["issues"], [])
        await self.apply_source(preview)
        state = await self.call("helper", "state", date(2026, 9, 1), date(2026, 9, 1))
        self.assertEqual(len(state["facts"]), 1)
        self.assertIsNone(state["facts"][0]["plan_id"])
        self.assertTrue(state["facts"][0]["composition_unknown"])
        self.assertTrue(any(n["value"] == 4 and n["reason"] == "Preserve this norm" for n in state["norms"]))

    def standalone_source(self):
        from test_audit_calendar_schema import source_fixture
        source = source_fixture()
        source["data"]["facts"] = [{"id": "canonical-standalone", "kind": "fact", "date": "2026-09-01",
            "start": 600, "duration": 60, "groupId": "OLD-SYNTH", "activity": "SYNTH", "speakerId": "S1",
            "sourceRow": 38, "origin": "source", "outcome": "completed", "planId": None,
            "participantIds": ["S1"], "participantSnapshot": [{"id": "S1", "name": "Synthetic", "role": "speaker"}]}]
        return source

    async def test_regression_canonical_fact_identity_across_export_batches(self):
        source = self.standalone_source()
        first = await self.preview_source(source)
        await self.apply_source(first)
        source["exportedAt"] = "2026-09-12T12:00:00Z"
        second = await self.preview_source(source)
        await self.apply_source(second)
        alias = next(r for r in second["rows"] if r["kind"] == "fact")
        with self.assert_status(409):
            await self.command("fact.restore", {"source_row_id": alias["id"], "date": "2026-09-02",
                "start": 900, "duration": 60, "activity": "SYNTH", "speaker_id": self.actors["speaker"].id,
                "outcome": "completed", "reason": "Must not duplicate", "evidence": "Synthetic",
                "confirm": True, "composition_unknown": True, "participants": []})
        async with self.sessions.begin() as db:
            self.assertEqual(await db.scalar(sa.select(sa.func.count()).select_from(models.AuditCalendarFact)), 1)
        # The SQL guard protects the same identity even with a new row UUID.
        with self.assertRaises(sa.exc.DBAPIError):
            async with self.sessions.begin() as db:
                await db.execute(sa.text("""INSERT INTO audit_calendar_facts
                    (id,scope_id,plan_id,source_row_id,date,start,duration,group_id,activity,speaker_id,outcome,
                     reason,evidence,recorded_by_id,recorded_at,participant_snapshot,planned_snapshot,composition_unknown,origin,auditor_absent_minutes)
                    SELECT :new_id,scope_id,NULL,:alias,date,900,duration,group_id,activity,speaker_id,outcome,
                           reason,evidence,recorded_by_id,recorded_at,participant_snapshot,planned_snapshot,composition_unknown,origin,auditor_absent_minutes
                    FROM audit_calendar_facts LIMIT 1"""), {"new_id": uuid4(), "alias": UUID(alias["id"])})

    async def test_regression_historical_entry_cannot_use_future_native_draft(self):
        from test_audit_calendar_schema import source_fixture
        source = source_fixture()
        plan = source["data"]["plans"][0]
        plan.update(origin="native", status="draft", date=(self.today+timedelta(days=1)).isoformat(), groupId="G1")
        plan.pop("sourceRow")
        snapshot = {k: plan[k] for k in ("date", "start", "duration", "groupId", "activity", "speakerId", "status")}
        source["data"]["facts"] = [{"id": "injected-historical", "kind": "fact", "date": "2026-09-01",
            "start": 600, "duration": 60, "groupId": "G2", "activity": "SYNTH", "speakerId": "S1",
            "origin": "historical-entry", "outcome": "completed", "planId": plan["id"], "plannedSnapshot": snapshot,
            "compositionUnknown": True, "participantSnapshot": [], "reason": "Forged provenance",
            "sourceEvidence": "Synthetic evidence does not establish source identity"}]
        preview = await self.preview_source(source)
        codes = {i["code"] for i in preview["issues"]}
        self.assertIn("HISTORICAL_SOURCE", codes)
        self.assertIn("HISTORICAL_ATTRIBUTION", codes)
        with self.assert_status(409):
            await self.apply_source(preview)
        async with self.sessions.begin() as db:
            self.assertEqual(await db.scalar(sa.select(sa.func.count()).select_from(models.AuditCalendarFact)), 0)

    async def test_regression_modern_fact_conflicts_with_known_historical_speaker(self):
        source = self.standalone_source()
        source["data"]["plans"][0]["groupId"] = "G1"
        source["data"]["facts"][0]["groupId"] = "G1"
        source["data"]["planning"] = {"trackingStart": "2026-08-28", "dailyTargets": [{"from": "2026-08-28", "value": 6}],
            "groupTargets": [{"groupId": "G1", "from": "2026-08-28", "value": 3}], "absences": []}
        preview = await self.preview_source(source, bootstrap_history=True, group_mapping={"G1": {
            "auditor_id": self.actors["auditor"].id, "tech_id": self.actors["tech"].id}})
        await self.apply_source(preview)
        state = await self.call("helper", "state", date(2026, 9, 1), date(2026, 9, 1))
        self.assertTrue(state["facts"][0]["composition_unknown"])
        self.assertEqual(state["facts"][0]["participant_snapshot"], [])
        with self.assert_status(422):
            await self.command("fact.record", {"plan_id": state["plans"][0]["id"], "date": "2026-09-01", "start": 600,
                "duration": 60, "group_id": state["groups"][0]["id"], "activity": "SYNTH", "speaker_id": self.actors["speaker"].id,
                "outcome": "completed", "reason": "Conflicting fixture", "evidence": "Synthetic", "auditor_absent_minutes": 0})

    async def test_documented_historical_entry_import_uses_original_group(self):
        from test_audit_calendar_schema import source_fixture
        source = source_fixture()
        plan = source["data"]["plans"][0]
        snapshot = {k: plan[k] for k in ("date", "start", "duration", "groupId", "activity", "speakerId", "status")}
        source["data"]["facts"] = [{"id": "documented-historical", "kind": "fact", "date": "2026-09-01",
            "start": 600, "duration": 60, "groupId": "OLD-SYNTH", "activity": "SYNTH", "speakerId": "S1",
            "origin": "historical-entry", "outcome": "completed", "planId": plan["id"], "plannedSnapshot": snapshot,
            "compositionUnknown": True, "participantSnapshot": [], "reason": "Documented synthetic history",
            "sourceEvidence": "Synthetic source document"}]
        preview = await self.preview_source(source)
        self.assertEqual(preview["issues"], [])
        await self.apply_source(preview)
        state = await self.call("helper", "state", date(2026, 9, 1), date(2026, 9, 1))
        self.assertEqual(state["facts"][0]["group_id"], state["plans"][0]["group_id"])
        self.assertEqual(state["facts"][0]["plan_id"], state["plans"][0]["id"])
        self.assertEqual(state["facts"][0]["evidence"], "Synthetic source document")


if __name__ == "__main__":
    unittest.main()
