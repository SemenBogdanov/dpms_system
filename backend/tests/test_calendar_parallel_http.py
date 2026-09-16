"""Opt-in HTTP regressions for independent meetings in the same calendar slot.

Run from backend only after the integrator coordinates the disposable database:
  DPMS_CALENDAR_HTTP_TESTS=1 python -m unittest discover -s tests \
      -p 'test_calendar_parallel_http.py' -v

Only synthetic, rolled-back records are used. No DB creation or migration occurs.
Application imports and connections remain behind the explicit opt-in guard.
"""
from datetime import datetime, time, timedelta
import os
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo


@unittest.skipUnless(
    os.getenv("DPMS_CALENDAR_HTTP_TESTS") == "1", "isolated PostgreSQL opt-in required"
)
class CalendarParallelHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy import event
        from sqlalchemy.engine import make_url
        from sqlalchemy.ext.asyncio import async_sessionmaker
        from sqlalchemy.sql.elements import ReleaseSavepointClause, RollbackToSavepointClause

        try:
            url = make_url(os.environ["DATABASE_URL"])
        except Exception:
            raise RuntimeError("A valid disposable PostgreSQL DATABASE_URL is required") from None
        if (url.database != "dpms_calendar_v5_http_test"
                or url.host not in {"dpms-local-db-1", "localhost", "127.0.0.1"}
                or url.drivername != "postgresql+asyncpg" or url.query):
            raise RuntimeError("Only the local dpms_calendar_v5_http_test asyncpg database is allowed")

        import test_calendar_http_integration as fixture
        from app.models import audit_calendar as models

        self.fixture, self.models = fixture, models
        await fixture.CalendarHTTPTests.asyncSetUp(self)
        self.addAsyncCleanup(fixture.CalendarHTTPTests.asyncTearDown, self)

        def release_rolled_back_savepoint(connection, cursor, statement, parameters, context, executemany):
            compiled = context.compiled
            if compiled is not None and isinstance(compiled.statement, RollbackToSavepointClause):
                # PostgreSQL keeps a rolled-back savepoint open. Release it so a
                # later rollback_only fact insert really uses the outer XID.
                connection.execute(ReleaseSavepointClause(compiled.statement.ident))

        event.listen(self.connection.sync_connection, "after_cursor_execute", release_rolled_back_savepoint)
        self.addCleanup(event.remove, self.connection.sync_connection, "after_cursor_execute", release_rolled_back_savepoint)
        self.day = self.today + timedelta(days=7)
        self.now = datetime.combine(self.today, time(12), ZoneInfo("Europe/Moscow"))
        clock = patch("app.api.routes.audit_calendar.CalendarService",
            side_effect=lambda db, actor: fixture.CalendarService(db, actor, now=self.now))
        clock.start()
        self.addCleanup(clock.stop)
        self.fact_factory = async_sessionmaker(self.connection, expire_on_commit=False,
            join_transaction_mode="rollback_only")
        self.actor = self.people["helper"]
        initial = await self.calendar_state()
        self.scope_id = UUID(initial["scope"]["id"])
        self.groups = {"G1": self.group_id}
        self.trios = {"G1": ("employee", "tech", "speaker")}

        async with self.factory.begin() as db:
            for code in ("auditor2", "tech2", "speaker2"):
                user = fixture.User(id=uuid4(), email=f"{code}-{uuid4()}@example.com",
                    full_name=f"Parallel test {code}", role=fixture.UserRole.executor,
                    league=fixture.League.C, is_active=True, audit_calendar_enabled=True, auth_version=0)
                db.add(user)
                self.people[code] = SimpleNamespace(id=user.id, auth_version=0)
        for code, role in (("auditor2", "auditor"), ("tech2", "tech"), ("speaker2", "speaker")):
            self.actor = self.people["admin"]
            response = await self.client.post("/api/audit-calendar/admin/members", json={
                "request_id": str(uuid4()), "expected_version": self.version,
                "user_id": str(self.people[code].id), "code": code, "role": role,
                "can_manage": False, "active": True,
            })
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["version"], self.version + 1)
            self.version = response.json()["version"]
        await self.group("G2", "auditor2", "tech2", "speaker2")
        for code in (*self.trios["G1"], *self.trios["G2"]):
            await self.send("availability.paint", {
                "user_id": str(self.people[code].id), "patches": [{
                    "date": self.day.isoformat(), "start": 720, "end": 960, "value": True,
                }],
            })

    def body(self, operation, payload):
        return self.fixture.CalendarHTTPTests.body(self, operation, payload)

    async def command(self, body):
        return await self.fixture.CalendarHTTPTests.command(self, body)

    async def submit(self, body, *, status=200):
        self.actor = self.people["helper"]
        response = await self.command(body)
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    async def send(self, operation, payload):
        answer = await self.submit(self.body(operation, payload))
        self.assertEqual(answer["version"], self.version + 1)
        self.version = answer["version"]
        return answer["result"]

    async def group(self, code, auditor, tech, speaker):
        saved = await self.send("group.save", {
            "code": code, "label": f"Parallel test {code}", "effective_from": self.day.isoformat(),
            "auditor_id": str(self.people[auditor].id), "tech_id": str(self.people[tech].id),
            "reason": "Synthetic independent group",
        })
        self.groups[code], self.trios[code] = saved["id"], (auditor, tech, speaker)

    def plan_payload(self, group="G1", *, start=780):
        return {
            "date": self.day.isoformat(), "start": start, "duration": 60,
            "group_id": self.groups[group], "speaker_id": str(self.people[self.trios[group][2]].id),
            "activity": f"Parallel meeting {group}", "status": "planned",
            "reason": "Synthetic planned meeting",
        }

    async def plan(self, group="G1", *, start=780):
        result = await self.send("plan.save", self.plan_payload(group, start=start))
        self.assertEqual((result["date"], result["start"], result["duration"], result["status"]),
                         (self.day.isoformat(), start, 60, "planned"))
        self.assertEqual((result["issues"], result["warnings"]), ([], []))
        return result

    def fact_payload(self, plan, *, start=None):
        return {
            "plan_id": plan["id"], "date": plan["date"],
            "start": plan["start"] if start is None else start, "duration": plan["duration"],
            "group_id": plan["group_id"], "activity": plan["activity"], "speaker_id": plan["speaker_id"],
            "outcome": "completed", "reason": "Synthetic completion", "evidence": f"Protocol {plan['id']}",
            "auditor_absent_minutes": 0,
        }

    async def record(self, plan, *, actual_day=None, outcome="completed"):
        body = self.body("fact.record", self.fact_payload(plan))
        body["payload"]["outcome"] = outcome
        if actual_day is not None:
            body["payload"]["date"] = actual_day.isoformat()
        # Successful fact/participant inserts need the outer XID for the PG guard.
        # Expected failures and all other requests keep the fixture's savepoints.
        savepoint_factory = self.factory
        self.factory = self.fact_factory
        try:
            answer = await self.submit(body)
        finally:
            self.factory = savepoint_factory
        self.assertEqual(answer["version"], self.version + 1)
        self.version = answer["version"]
        return body, answer

    async def calendar_state(self):
        self.actor = self.people["helper"]
        response = await self.client.get("/api/audit-calendar/state", params={
            "from": self.day.isoformat(), "to": self.day.isoformat(),
        })
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def expected_people(self, group):
        return {(str(self.people[code].id), role)
            for code, role in zip(self.trios[group], ("auditor", "tech", "speaker"))}

    async def evidence(self):
        from sqlalchemy import select

        result = {}
        async with self.factory() as db:
            result["version"] = await db.scalar(select(self.models.AuditCalendarScope.version)
                .where(self.models.AuditCalendarScope.id == self.scope_id))
            for name, model in (
                ("plans", self.models.AuditCalendarPlan), ("plan_people", self.models.AuditCalendarPlanParticipant),
                ("facts", self.models.AuditCalendarFact), ("fact_people", self.models.AuditCalendarFactParticipant),
                ("absences", self.models.AuditCalendarAbsence), ("events", self.models.AuditCalendarEvent),
                ("receipts", self.models.AuditCalendarIdempotency),
            ):
                rows = (await db.scalars(select(model).where(model.scope_id == self.scope_id).order_by(model.id))).all()
                result[name] = [{column.name: getattr(row, column.name) for column in model.__table__.columns} for row in rows]
        return result

    def assert_conflict(self, answer, code, user, record):
        issues = [issue for issue in answer["detail"]["issues"] if issue["code"] == code]
        self.assertEqual([(issue["user_id"], issue["record_id"]) for issue in issues],
                         [(str(self.people[user].id), record)])

    async def test_disjoint_1300_plans_and_facts_keep_independent_ids_and_receipts(self):
        first, second = await self.plan(), await self.plan("G2")
        self.assertNotEqual(first["id"], second["id"])
        self.assertTrue(self.expected_people("G1").isdisjoint(self.expected_people("G2")))
        before = await self.evidence()
        for group, plan in (("G1", first), ("G2", second)):
            self.assertEqual({(str(p["user_id"]), p["role"]) for p in before["plan_people"]
                if p["plan_id"] == UUID(plan["id"])}, self.expected_people(group))

        self.now = datetime.combine(self.day, time(13, 59), ZoneInfo("Europe/Moscow"))
        await self.submit(self.body("fact.record", self.fact_payload(first)), status=422)
        self.assertEqual(await self.evidence(), before)
        self.now = datetime.combine(self.day, time(14, 1), ZoneInfo("Europe/Moscow"))
        first_body, first_answer = await self.record(first)
        second_body, second_answer = await self.record(second)
        self.assertNotEqual(first_answer["result"]["id"], second_answer["result"]["id"])
        after = await self.evidence()
        self.assertEqual(after["version"], before["version"] + 2)
        self.assertEqual((len(after["facts"]), len(after["fact_people"])), (2, 6))
        self.assertEqual(after["plans"], before["plans"])
        self.assertEqual(after["plan_people"], before["plan_people"])
        self.assertEqual(len(after["events"]), len(before["events"]) + 2)
        self.assertEqual(len(after["receipts"]), len(before["receipts"]) + 2)
        for group, plan, body, answer in (("G1", first, first_body, first_answer), ("G2", second, second_body, second_answer)):
            fact = answer["result"]
            self.assertEqual((fact["plan_id"], fact["date"], fact["start"], fact["duration"], fact["group_id"], fact["outcome"]),
                             (plan["id"], self.day.isoformat(), 780, 60, self.groups[group], "completed"))
            self.assertEqual({(p["user_id"], p["role"]) for p in fact["participant_snapshot"]}, self.expected_people(group))
            self.assertEqual({(str(p["user_id"]), p["role"]) for p in after["fact_people"]
                if p["fact_id"] == UUID(fact["id"])}, self.expected_people(group))
            self.assertEqual(fact["planned_snapshot"]["id"], plan["id"])
            receipts = [r for r in after["receipts"] if r["request_id"] == UUID(body["request_id"])]
            self.assertEqual(len(receipts), 1)
            self.assertEqual(receipts[0]["response"], answer)
            events = [e for e in after["events"] if e["action"] == "fact.record"
                and e["detail"]["command"]["request_id"] == body["request_id"]]
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["detail"]["result"]["id"], fact["id"])
            self.assertEqual(await self.submit(body), answer)
        self.assertEqual(await self.evidence(), after)
        state = await self.calendar_state()
        self.assertEqual(state["stats"]["fact"], 2)
        self.assertEqual({f["plan_id"] for f in state["facts"]}, {first["id"], second["id"]})

    async def test_linked_fact_outcome_is_visible_when_actual_date_is_outside_query_period(self):
        cancelled, completed = await self.plan(), await self.plan("G2")
        actual_day = self.day + timedelta(days=1)
        self.now = datetime.combine(actual_day, time(14, 1), ZoneInfo("Europe/Moscow"))
        await self.record(cancelled, actual_day=actual_day, outcome="cancelled")
        await self.record(completed, actual_day=actual_day)
        before = await self.evidence()
        state = await self.calendar_state()
        self.assertEqual(state["facts"], [])
        self.assertEqual(state["stats"]["fact"], 0)
        self.assertEqual({p["id"]: p["fact_outcome"] for p in state["plans"]}, {
            cancelled["id"]: "cancelled", completed["id"]: "completed",
        })
        self.assertTrue(all(p["status"] == "planned" for p in state["plans"]))
        response = await self.client.get("/api/audit-calendar/state", params={
            "from": actual_day.isoformat(), "to": actual_day.isoformat(),
        })
        self.assertEqual(response.status_code, 200, response.text)
        actual = response.json()
        self.assertEqual(actual["plans"], [])
        self.assertEqual({f["plan_id"]: f["outcome"] for f in actual["facts"]}, {
            cancelled["id"]: "cancelled", completed["id"]: "completed",
        })
        self.assertEqual(await self.evidence(), before)

    async def test_shared_auditor_tech_or_speaker_cannot_be_double_booked(self):
        existing = await self.plan()
        for code, trio, shared in (
            ("SHARED_A", ("employee", "tech2", "speaker2"), "employee"),
            ("SHARED_T", ("auditor2", "tech", "speaker2"), "tech"),
            ("SHARED_S", ("auditor2", "tech2", "speaker"), "speaker"),
        ):
            with self.subTest(shared=shared):
                await self.group(code, *trio)
                before = await self.evidence()
                rejected = await self.submit(self.body("plan.save", self.plan_payload(code)), status=422)
                self.assert_conflict(rejected, "PARTICIPANT_CONFLICT", shared, existing["id"])
                self.assertEqual(await self.evidence(), before)
        accepted = await self.plan("G2")
        self.assertNotEqual(accepted["id"], existing["id"])

    async def test_cancelled_absence_no_longer_blocks_an_independent_parallel_plan(self):
        first = await self.plan()
        absence = await self.send("absence.add", {
            "user_id": str(self.people["tech2"].id), "start_date": self.day.isoformat(),
            "end_date": self.day.isoformat(), "reason": "Synthetic future absence",
        })
        before = await self.evidence()
        rejected = await self.submit(self.body("plan.save", self.plan_payload("G2")), status=422)
        self.assertEqual([(issue["code"], issue.get("user_id")) for issue in rejected["detail"]["issues"]],
                         [("UNAVAILABLE", str(self.people["tech2"].id))])
        self.assertEqual(await self.evidence(), before)
        ended = await self.send("absence.end", {"id": absence["id"], "reason": "Synthetic cancellation"})
        self.assertEqual((ended["before"]["status"], ended["after"]["status"]), ("active", "cancelled"))
        second = await self.plan("G2")
        state = await self.calendar_state()
        self.assertEqual({p["id"] for p in state["plans"]}, {first["id"], second["id"]})
        saved_absences = [a for a in state["absences"] if a["id"] == absence["id"]]
        self.assertEqual(len(saved_absences), 1)
        self.assertEqual((saved_absences[0]["status"], saved_absences[0]["reason"]),
                         ("cancelled", "Synthetic future absence"))

    async def test_shared_participant_fact_conflict_preserves_receipts_and_adjacent_fact_is_allowed(self):
        first = await self.plan()
        await self.group("SHARED_A", "employee", "tech2", "speaker2")
        later = await self.plan("SHARED_A", start=840)
        self.now = datetime.combine(self.day, time(15, 1), ZoneInfo("Europe/Moscow"))
        _, first_answer = await self.record(first)
        before = await self.evidence()
        rejected = await self.submit(self.body("fact.record", self.fact_payload(later, start=780)), status=422)
        self.assert_conflict(rejected, "FACT_CONFLICT", "employee", first_answer["result"]["id"])
        self.assertEqual(await self.evidence(), before)
        _, later_answer = await self.record(later)
        self.assertEqual((later_answer["result"]["plan_id"], later_answer["result"]["start"]), (later["id"], 840))
        self.assertEqual(len((await self.evidence())["facts"]), 2)

    async def test_no_second_fact_or_rewrite_of_frozen_plan_history_and_receipts(self):
        from sqlalchemy import delete, update
        from sqlalchemy.exc import DBAPIError

        plan = await self.plan()
        self.now = datetime.combine(self.day, time(14, 1), ZoneInfo("Europe/Moscow"))
        body, answer = await self.record(plan)
        frozen = await self.evidence()
        self.now = datetime.combine(self.day, time(16, 1), ZoneInfo("Europe/Moscow"))
        # A non-overlapping actual time reaches the plan_id uniqueness guard,
        # rather than being rejected only for overlap with the existing fact.
        await self.submit(self.body("fact.record", self.fact_payload(plan, start=900)), status=409)
        await self.submit(self.body("plan.save", {**self.plan_payload(start=900), "id": plan["id"]}), status=409)
        changed_retry = {**body, "payload": {**body["payload"], "reason": "Attempted receipt replacement"}}
        await self.submit(changed_retry, status=409)
        self.assertEqual(await self.submit(body), answer)
        self.assertEqual(await self.evidence(), frozen)

        fact_id, plan_id = UUID(answer["result"]["id"]), UUID(plan["id"])
        mutations = (
            update(self.models.AuditCalendarFact).where(self.models.AuditCalendarFact.id == fact_id).values(reason="Tampered"),
            delete(self.models.AuditCalendarFactParticipant).where(self.models.AuditCalendarFactParticipant.fact_id == fact_id),
            update(self.models.AuditCalendarPlan).where(self.models.AuditCalendarPlan.id == plan_id).values(activity="Tampered"),
            delete(self.models.AuditCalendarPlanParticipant).where(self.models.AuditCalendarPlanParticipant.plan_id == plan_id),
            update(self.models.AuditCalendarEvent).where(self.models.AuditCalendarEvent.action == "fact.record",
                self.models.AuditCalendarEvent.scope_id == self.scope_id).values(detail={"tampered": True}),
            delete(self.models.AuditCalendarIdempotency).where(self.models.AuditCalendarIdempotency.request_id == UUID(body["request_id"])),
        )
        for mutation in mutations:
            with self.subTest(statement=str(mutation)), self.assertRaises(DBAPIError) as blocked:
                async with self.factory.begin() as db:
                    await db.execute(mutation)
            self.assertEqual(blocked.exception.orig.sqlstate, "23514")
            self.assertEqual(await self.evidence(), frozen)
