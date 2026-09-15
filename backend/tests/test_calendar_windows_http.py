"""Available windows: real router/domain/PG, rolled back isolated fixtures only."""
import os
import unittest
from datetime import timedelta
from unittest.mock import patch as mock_patch
from uuid import UUID, uuid4

import test_calendar_controls_http as helpers


@unittest.skipUnless(os.getenv("DPMS_CALENDAR_HTTP_TESTS") == "1", "isolated PostgreSQL opt-in required")
class CalendarWindowsHTTPTests(unittest.IsolatedAsyncioTestCase):
    body = helpers.CalendarControlsHTTPTests.body
    command = helpers.CalendarControlsHTTPTests.command
    calendar_state = helpers.CalendarControlsHTTPTests.calendar_state
    send = helpers.CalendarControlsHTTPTests.send
    patch = helpers.CalendarControlsHTTPTests.patch
    paint = helpers.CalendarControlsHTTPTests.paint

    async def asyncSetUp(self):
        await helpers.CalendarControlsHTTPTests.asyncSetUp(self)

    async def batch(self, status=200, **query):
        response = await self.client.get("/api/audit-calendar/meeting-windows", params={
            "from": self.day.isoformat(), "to": self.day.isoformat(), "duration": 30, **query})
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    async def options(self, status=200, **query):
        response = await self.client.get("/api/audit-calendar/meeting-window-options", params={
            "date": self.day.isoformat(), "start": 600, "duration": 30, **query})
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def cell(self, result, start=600, day=None):
        return next(c for c in result["cells"] if c["start"] == start and c["date"] == (day or self.day).isoformat())

    async def free_trio(self, **kwargs):
        for code in ("employee", "tech", "speaker"):
            await self.paint(code, **kwargs)

    def plan(self, **kwargs):
        return {"date": self.day.isoformat(), "start": 600, "duration": 30,
            "group_id": self.group_id, "speaker_id": str(self.people["speaker"].id),
            "activity": "Window search fixture", "status": "planned", **kwargs}

    async def test_unknown_is_yellow_with_three_attributed_warnings(self):
        result = await self.batch()
        self.assertEqual(len(result["cells"]), 16)
        self.assertEqual(self.cell(result)["status"], "warning")
        self.assertEqual(self.cell(result)["uncertain"], 1)
        options = (await self.options())["options"]
        self.assertEqual(len(options), 1)
        self.assertEqual(options[0]["group_id"], self.group_id)
        self.assertEqual(len(options[0]["warnings"]), 3)
        self.assertEqual({w["participant_code"] for w in options[0]["warnings"]}, {"employee", "tech", "speaker"})
        self.assertTrue(all(w["code"] == "AVAILABILITY_UNKNOWN" for w in options[0]["warnings"]))
        await self.send("plan.save", self.plan())

    async def test_green_full_window_partial_busy_absence_and_adjacent_boundary(self):
        await self.free_trio(end=660)
        self.assertEqual(self.cell(await self.batch(duration=60))["status"], "available")
        self.assertEqual(self.cell(await self.batch(duration=90))["status"], "unavailable")
        self.assertFalse((await self.options(duration=90))["options"])
        await self.paint("tech", start=630, end=660, value=False)
        self.assertEqual(self.cell(await self.batch())["status"], "available")
        self.assertEqual(self.cell(await self.batch(), 630)["status"], "unavailable")
        self.assertEqual(self.cell(await self.batch(duration=60))["status"], "unavailable")
        await self.send("absence.add", {"user_id": str(self.people["speaker"].id),
            "start_date": self.day.isoformat(), "end_date": self.day.isoformat(), "reason": "Synthetic absence"})
        self.assertFalse((await self.options())["options"])

    async def test_hidden_group_booking_and_cancelled_booking(self):
        other = await self.send("group.save", {"code": "G2", "label": "Hidden group",
            "effective_from": self.today.isoformat(), "auditor_id": str(self.people["employee"].id),
            "tech_id": str(self.people["tech"].id), "reason": "Synthetic"})
        saved = await self.send("plan.save", self.plan(group_id=other["id"], status="draft"))
        self.assertEqual(self.cell(await self.batch(group=self.group_id))["status"], "unavailable")
        self.assertFalse((await self.options(group=self.group_id))["options"])
        self.assertEqual(self.cell(await self.batch(group=self.group_id), 630)["status"], "warning")
        await self.send("plan.save", self.plan(id=saved["id"], group_id=other["id"], status="cancelled", reason="Cancelled"))
        self.assertEqual(self.cell(await self.batch(group=self.group_id))["status"], "warning")

    async def test_completed_fact_blocks_even_without_plan(self):
        from sqlalchemy.ext.asyncio import async_sessionmaker
        # Fact-child guards require the outer transaction's XID, not a savepoint.
        fixture = async_sessionmaker(self.connection, expire_on_commit=False, join_transaction_mode="rollback_only")
        async with fixture.begin() as db:
            fact = self.models.AuditCalendarFact(scope_id=self.scope_id, date=self.day, start=600, duration=30,
                group_id=UUID(self.group_id), activity="Synthetic future fixture", speaker_id=self.people["speaker"].id,
                outcome="completed", reason="Fixture", evidence="", recorded_by_id=self.people["helper"].id,
                participant_snapshot=[{"user_id": str(self.people["employee"].id), "role": "auditor"}], origin="native")
            db.add(fact)
            await db.flush()
            db.add(self.models.AuditCalendarFactParticipant(scope_id=self.scope_id, fact_id=fact.id,
                user_id=self.people["employee"].id, role="auditor"))
        self.assertEqual(self.cell(await self.batch())["status"], "unavailable")
        self.assertFalse((await self.options())["options"])

    async def test_distinct_variants_green_precedes_unknown_and_speaker_filter(self):
        async with self.factory.begin() as db:
            db.add(self.models.AuditCalendarMember(scope_id=self.scope_id, user_id=self.people["outsider"].id,
                code="S2", role="speaker", can_manage=False, active=True))
        await self.free_trio()
        first = self.cell(await self.batch())
        self.assertEqual((first["status"], first["confirmed"], first["uncertain"]), ("available", 1, 1))
        options = (await self.options())["options"]
        self.assertEqual([v["status"] for v in options], ["available", "warning"])
        filtered = self.cell(await self.batch(speaker_id=str(self.people["outsider"].id)))
        self.assertEqual((filtered["status"], filtered["confirmed"], filtered["uncertain"]), ("warning", 0, 1))

    async def test_effective_composition_and_revoked_participant(self):
        async with self.factory.begin() as db:
            db.add(self.models.AuditCalendarMember(scope_id=self.scope_id, user_id=self.people["outsider"].id,
                code="A2", role="auditor", can_manage=False, active=True))
            await db.flush()
            db.add(self.models.AuditCalendarGroupVersion(scope_id=self.scope_id, group_id=UUID(self.group_id),
                effective_from=self.next_day, auditor_id=self.people["outsider"].id,
                tech_id=self.people["tech"].id, reason="New future composition"))
        today_option = (await self.options())["options"][0]
        next_option = (await self.options(date=self.next_day.isoformat()))["options"][0]
        self.assertEqual(today_option["auditor_id"], str(self.people["employee"].id))
        self.assertEqual(next_option["auditor_id"], str(self.people["outsider"].id))
        from app.models.user import User
        async with self.factory.begin() as db:
            person = await db.get(User, self.people["outsider"].id)
            person.audit_calendar_enabled = False
        self.assertFalse((await self.options(date=self.next_day.isoformat()))["options"])
        self.assertTrue((await self.options())["options"])

    async def test_range_boundaries_full_day_past_archive_and_validation(self):
        normal = await self.batch(duration=60)
        self.assertEqual(self.cell(normal, 1050)["status"], "unavailable")
        full = await self.batch(duration=60, full_day=True)
        self.assertEqual(len(full["cells"]), 48)
        self.assertEqual(self.cell(full, 1410)["status"], "unavailable")
        self.assertEqual(self.cell(full, 0)["status"], "warning")
        past = self.today - timedelta(days=1)
        self.assertTrue(all(c["status"] == "unavailable" for c in (await self.batch(**{"from": past.isoformat(), "to": past.isoformat()}))["cells"]))
        for query in ({"to": (self.day + timedelta(days=31)).isoformat()}, {"duration": 15}, {"duration": 510}, {"from": "1900-01-01"}):
            await self.batch(status=422, **query)
        await self.options(status=422, start=1410, duration=60)
        await self.options(status=422, start=605)
        await self.batch(status=422, speaker_id=str(self.people["employee"].id))
        await self.batch(status=404, group=str(uuid4()))
        await self.send("scope.archive", {"archived": True, "reason": "Synthetic"}, actor="admin")
        self.actor = self.people["helper"]
        self.assertFalse((await self.options())["options"])
        self.assertTrue(all(c["status"] == "unavailable" for c in (await self.batch())["cells"]))

    async def test_acl_unchanged_and_no_writes_from_search(self):
        before = await self.calendar_state()
        for actor in ("employee", "helper"):
            self.actor = self.people[actor]
            await self.batch()
            await self.options()
        for actor in ("admin", "outsider", "denied"):
            self.actor = self.people[actor]
            await self.batch(status=403)
            await self.options(status=403)
        after = await self.calendar_state()
        before["scope"].pop("now")
        after["scope"].pop("now")
        self.assertEqual(before, after)

    async def test_stale_highlight_cannot_create_double_booking(self):
        await self.free_trio()
        self.assertEqual(self.cell(await self.batch())["status"], "available")
        self.assertTrue((await self.options())["options"])
        stale = self.body("plan.save", self.plan())
        await self.send("plan.save", self.plan())
        self.assertFalse((await self.options())["options"])
        self.assertEqual((await self.command(stale)).status_code, 409)
        self.assertEqual((await self.command(self.body("plan.save", self.plan()))).status_code, 422)

    async def test_query_count_is_independent_of_cells_and_variant_cap_is_explicit(self):
        from sqlalchemy import event
        statements = []
        def capture(*args):
            statements.append(args[2])
        event.listen(self.engine.sync_engine, "before_cursor_execute", capture)
        try:
            await self.batch()
            short = len(statements)
            statements.clear()
            result = await self.batch(to=(self.day + timedelta(days=30)).isoformat(), full_day=True)
            self.assertEqual(len(result["cells"]), 31 * 48)
            self.assertEqual(len(statements), short)
            self.assertLess(short, 20)
        finally:
            event.remove(self.engine.sync_engine, "before_cursor_execute", capture)
        with mock_patch("app.services.audit_calendar_windows.MAX_VARIANTS", 0):
            await self.batch(status=422)
            await self.options(status=422)
        for limit in ("MAX_PERSON_INTERVALS", "MAX_VARIANT_INTERVALS", "MAX_CONTEXT_ROWS"):
            with mock_patch(f"app.services.audit_calendar_windows.{limit}", 0):
                await self.batch(status=422)
                await self.options(status=422)


if __name__ == "__main__":
    unittest.main()
