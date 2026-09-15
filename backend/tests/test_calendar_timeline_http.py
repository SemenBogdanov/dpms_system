"""Opt-in, rollback-only timeline HTTP regressions with synthetic calendar data.

The integrator must coordinate the disposable PostgreSQL environment before
running with DPMS_CALENDAR_HTTP_TESTS=1. No DB creation or migration occurs here.
"""
from datetime import datetime, timedelta
import os
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4


@unittest.skipUnless(
    os.getenv("DPMS_CALENDAR_HTTP_TESTS") == "1", "isolated PostgreSQL opt-in required"
)
class CalendarTimelineHTTPTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        from sqlalchemy.engine import make_url

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
        self.day = self.today + timedelta(days=7)
        self.actor = self.people["helper"]
        response = await self.client.get("/api/audit-calendar/state", params={
            "from": self.day.isoformat(), "to": self.day.isoformat(),
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.scope_id = UUID(response.json()["scope"]["id"])

    def body(self, operation, payload):
        return self.fixture.CalendarHTTPTests.body(self, operation, payload)

    async def command(self, body):
        return await self.fixture.CalendarHTTPTests.command(self, body)

    async def send(self, operation, payload):
        self.actor = self.people["helper"]
        response = await self.command(self.body(operation, payload))
        self.assertEqual(response.status_code, 200, response.text)
        self.version = response.json()["version"]
        return response.json()["result"]

    async def member(self, code, role, *, active=True):
        self.actor = self.people["admin"]
        response = await self.client.post("/api/audit-calendar/admin/members", json={
            "request_id": str(uuid4()), "expected_version": self.version,
            "user_id": str(self.people[code].id), "code": code, "role": role,
            "can_manage": False, "active": active,
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.version = response.json()["version"]

    async def timeline(self, *, day=None, actor="employee", status=200):
        self.actor = self.people[actor]
        response = await self.client.get("/api/audit-calendar/availability-timeline", params={
            "date": (day or self.day).isoformat(),
        })
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    async def plan(self, *, day=None, start=600, status="planned"):
        return await self.send("plan.save", {
            "date": (day or self.day).isoformat(), "start": start, "duration": 30,
            "group_id": self.group_id, "speaker_id": str(self.people["speaker"].id),
            "activity": "Synthetic timeline plan", "status": status,
        })

    async def fact(self, *, day=None, plan=None, start=600, outcome="completed",
                   participants=None, unknown=False, group=True):
        from sqlalchemy.ext.asyncio import async_sessionmaker

        if participants is None:
            participants = [] if unknown else [("employee", "auditor"), ("tech", "tech"), ("speaker", "speaker")]
        snapshot = [{"user_id": str(self.people[code].id), "role": role} for code, role in participants]
        # The immutable fact-child guard requires the outer transaction's XID.
        factory = async_sessionmaker(self.connection, expire_on_commit=False, join_transaction_mode="rollback_only")
        async with factory.begin() as db:
            fact = self.models.AuditCalendarFact(
                scope_id=self.scope_id, plan_id=UUID(plan["id"]) if plan else None,
                date=day or self.day, start=start, duration=30,
                group_id=UUID(self.group_id) if group else None,
                activity="Synthetic timeline fact", speaker_id=self.people["speaker"].id,
                outcome=outcome, reason="Synthetic evidence", evidence="Synthetic protocol",
                recorded_by_id=self.people["helper"].id, participant_snapshot=snapshot,
                composition_unknown=unknown, origin="native",
            )
            db.add(fact)
            await db.flush()
            for code, role in participants:
                db.add(self.models.AuditCalendarFactParticipant(
                    scope_id=self.scope_id, fact_id=fact.id, user_id=self.people[code].id, role=role,
                ))
            await db.flush()
            return str(fact.id)

    async def paint(self, code, start, end, available, *, day=None):
        return await self.send("availability.paint", {
            "user_id": str(self.people[code].id), "patches": [{
                "date": (day or self.day).isoformat(), "start": start, "end": end, "value": available,
            }],
        })

    def people_set(self, meeting):
        return {(row["user_id"], row["role"]) for row in meeting["participants"]}

    async def receipts(self):
        from sqlalchemy import func, select

        async with self.factory() as db:
            counts = [await db.scalar(select(func.count()).select_from(model))
                for model in (self.models.AuditCalendarEvent, self.models.AuditCalendarIdempotency)]
            version = await db.scalar(select(self.models.AuditCalendarScope.version)
                .where(self.models.AuditCalendarScope.id == self.scope_id))
        return version, counts

    async def test_calendar_acl_and_read_only_snapshot(self):
        await self.plan()
        before = await self.receipts()
        for actor in ("helper", "employee"):
            result = await self.timeline(actor=actor)
            self.assertEqual(set(result), {"version", "date", "members", "availability", "absences", "locks", "meetings"})
            self.assertEqual(result["version"], self.version)
            self.assertEqual(result["date"], self.day.isoformat())
            self.assertCountEqual([m["code"] for m in result["members"]], ["helper", "employee", "tech", "speaker"])
        for actor in ("admin", "outsider", "denied"):
            await self.timeline(actor=actor, status=403)
        self.assertEqual(await self.receipts(), before)
        await self.member("employee", "auditor", active=False)
        await self.timeline(actor="employee", status=403)
        result = await self.timeline(actor="helper")
        employee = next(m for m in result["members"] if m["code"] == "employee")
        self.assertFalse(employee["active"])
        self.assertIn((str(self.people["employee"].id), "auditor"), self.people_set(result["meetings"][0]))

    async def test_strict_date_bounds_and_weekend_single_day(self):
        before = await self.receipts()
        for value in (None, "1999-12-31", "2101-01-01", "2026-02-30", "2026-1-01", "1789459200", "2026-09-15T00:00:00Z"):
            response = await self.client.get("/api/audit-calendar/availability-timeline", params={} if value is None else {"date": value})
            self.assertEqual(response.status_code, 422, (value, response.text))
        for value in ("2000-01-01", "2100-12-31"):
            response = await self.client.get("/api/audit-calendar/availability-timeline", params={"date": value})
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["date"], value)
            self.assertEqual(response.json()["meetings"], [])
        saturday = self.day + timedelta(days=(5 - self.day.weekday()) % 7)
        saved = await self.plan(day=saturday)
        result = await self.timeline(day=saturday)
        self.assertEqual([m["id"] for m in result["meetings"]], [saved["id"]])
        self.assertEqual((await self.timeline(day=saturday + timedelta(days=1)))["meetings"], [])
        self.assertEqual((await self.receipts())[0], before[0] + 1)

    async def test_plan_uses_saved_composition_after_group_and_role_change(self):
        saved = await self.plan(day=self.day + timedelta(days=1))
        await self.member("outsider", "auditor")
        await self.send("group.save", {
            "id": self.group_id, "code": "G1", "label": "Changed current composition",
            "effective_from": self.day.isoformat(), "auditor_id": str(self.people["outsider"].id),
            "tech_id": str(self.people["tech"].id), "reason": "Synthetic replacement",
        })
        await self.member("employee", "observer", active=False)
        result = await self.timeline(day=self.day + timedelta(days=1), actor="helper")
        meeting = result["meetings"][0]
        self.assertEqual((meeting["id"], meeting["group_code"]), (saved["id"], "G1"))
        self.assertEqual(self.people_set(meeting), {
            (str(self.people["employee"].id), "auditor"),
            (str(self.people["tech"].id), "tech"),
            (str(self.people["speaker"].id), "speaker"),
        })
        employee = next(m for m in result["members"] if m["code"] == "employee")
        self.assertEqual((employee["role"], employee["active"]), ("observer", False))

    async def test_fact_participants_keep_historical_roles_and_no_live_group_members(self):
        fact_id = await self.fact(participants=[("helper", "auditor"), ("employee", "tech"), ("speaker", "speaker")])
        await self.member("helper", "observer", active=False)
        result = await self.timeline()
        self.assertEqual(len(result["meetings"]), 1)
        meeting = result["meetings"][0]
        self.assertEqual((meeting["id"], meeting["kind"], meeting["status"]), (fact_id, "fact", "completed"))
        self.assertEqual(len(meeting["participants"]), 3)
        self.assertEqual(self.people_set(meeting), {
            (str(self.people["helper"].id), "auditor"),
            (str(self.people["employee"].id), "tech"),
            (str(self.people["speaker"].id), "speaker"),
        })
        self.assertFalse(next(m for m in result["members"] if m["code"] == "helper")["active"])

    async def test_plans_and_facts_keep_original_slots_across_dates_and_exclude_cancelled(self):
        same = await self.plan(start=600)
        moved = await self.plan(start=660)
        failed = await self.plan(start=720)
        draft = await self.plan(start=780, status="draft")
        await self.plan(start=840, status="cancelled")
        other = await self.plan(day=self.day + timedelta(days=1), start=900)
        shifted = await self.plan(start=960)
        same_fact = await self.fact(plan=same)
        moved_fact = await self.fact(plan=moved, day=self.day + timedelta(days=1))
        await self.fact(plan=failed, day=self.day + timedelta(days=1), outcome="cancelled", start=720)
        incoming_fact = await self.fact(plan=other, start=900)
        shifted_fact = await self.fact(plan=shifted, start=1020)
        await self.fact(outcome="cancelled", start=990)
        result = await self.timeline()
        self.assertEqual(result["date"], self.day.isoformat())
        self.assertEqual([(m["id"], m["kind"], m["start"], m["duration"], m["status"]) for m in result["meetings"]], [
            (same_fact, "fact", 600, 30, "completed"),
            (same["id"], "plan", 600, 30, "planned"),
            (moved["id"], "plan", 660, 30, "planned"),
            (failed["id"], "plan", 720, 30, "planned"),
            (draft["id"], "plan", 780, 30, "draft"),
            (incoming_fact, "fact", 900, 30, "completed"),
            (shifted["id"], "plan", 960, 30, "planned"),
            (shifted_fact, "fact", 1020, 30, "completed"),
        ])
        next_day = await self.timeline(day=self.day + timedelta(days=1))
        self.assertEqual(next_day["date"], (self.day + timedelta(days=1)).isoformat())
        self.assertEqual([(m["id"], m["kind"], m["start"], m["duration"], m["status"]) for m in next_day["meetings"]], [
            (moved_fact, "fact", 600, 30, "completed"),
            (other["id"], "plan", 900, 30, "planned"),
        ])

    async def test_unknown_composition_stays_unassigned_even_with_saved_speaker(self):
        fact_id = await self.fact(unknown=True, group=False)
        result = await self.timeline()
        self.assertEqual(result["meetings"], [{
            "id": fact_id, "kind": "fact", "start": 600, "duration": 30,
            "activity": "Synthetic timeline fact", "status": "completed", "group_code": "", "participants": [],
        }])

    async def test_raw_free_busy_absence_and_locks_remain_separate_and_day_scoped(self):
        saved = await self.plan()
        await self.paint("employee", 600, 660, True)
        await self.paint("employee", 660, 690, False)
        await self.paint("employee", 720, 750, True, day=self.day + timedelta(days=1))
        await self.paint("tech", 0, 1440, True)
        absent = await self.send("absence.add", {
            "user_id": str(self.people["tech"].id), "start_date": self.day.isoformat(),
            "end_date": (self.day + timedelta(days=1)).isoformat(), "reason": "Synthetic active absence",
        })
        cancelled = await self.send("absence.add", {
            "user_id": str(self.people["speaker"].id), "start_date": self.day.isoformat(),
            "end_date": self.day.isoformat(), "reason": "Synthetic cancelled absence",
        })
        await self.send("absence.end", {"id": cancelled["id"], "reason": "Synthetic cancellation"})
        closed = await self.send("availability.lock", {
            "user_id": str(self.people["employee"].id), "date": self.day.isoformat(), "reason": "Synthetic lock",
        })
        await self.send("availability.lock", {
            "user_id": str(self.people["speaker"].id), "date": self.day.isoformat(), "reason": "Synthetic lock",
        })
        request = await self.send("availability.request", {
            "user_id": str(self.people["speaker"].id), "date": self.day.isoformat(), "reason": "Synthetic reopen",
        })
        await self.send("availability.resolve", {"id": request["id"], "action": "approve", "reason": "Synthetic approval"})
        result = await self.timeline()
        self.assertEqual([m["id"] for m in result["meetings"]], [saved["id"]])
        self.assertCountEqual(result["availability"], [
            {"user_id": str(self.people[code].id), "date": self.day.isoformat(), "start": start, "end": end, "available": free}
            for code, start, end, free in [("employee", 600, 660, True), ("employee", 660, 690, False), ("tech", 0, 1440, True)]
        ])
        self.assertEqual(result["absences"], [absent])
        self.assertEqual(len(result["locks"]), 2)
        actual_lock = next(lock for lock in result["locks"] if lock["user_id"] == str(self.people["employee"].id))
        self.assertEqual(
            {**actual_lock, "locked_at": datetime.fromisoformat(actual_lock["locked_at"])},
            {**closed, "locked_at": datetime.fromisoformat(closed["locked_at"])},
        )
        self.assertFalse(next(lock for lock in result["locks"] if lock["user_id"] == str(self.people["speaker"].id))["locked"])
        self.assertEqual((await self.timeline(day=self.day + timedelta(days=1)))["absences"], [absent])
        after = await self.timeline(day=self.day + timedelta(days=2))
        self.assertEqual((after["availability"], after["absences"], after["locks"], after["meetings"]), ([], [], [], []))

    async def test_row_caps_fail_explicitly_without_partial_calendar(self):
        await self.plan()
        before = await self.receipts()
        for name in ("MAX_TIMELINE_MEMBERS", "MAX_TIMELINE_ROWS"):
            with patch(f"app.services.audit_calendar_timeline.{name}", 0):
                result = await self.timeline(status=422)
                self.assertEqual(result["detail"]["code"], "TIMELINE_TOO_LARGE")
        self.assertEqual(await self.receipts(), before)
