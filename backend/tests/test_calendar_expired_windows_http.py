"""Opt-in retrospective window tests against the current saved calendar snapshot.

From backend, only after the integrator coordinates the disposable PostgreSQL DB:
  DPMS_CALENDAR_HTTP_TESTS=1 python -m unittest discover -s tests \
      -p 'test_calendar_expired_windows_http.py' -v

Fixture helpers retain their guarded, rollback-only database setup. Importing
this module does not import application/settings modules or connect to a DB.
"""
from datetime import datetime, time, timedelta
import os
import unittest
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

import test_calendar_parallel_http as parallel_fixture
import test_calendar_timeline_http as timeline_fixture


@unittest.skipUnless(
    os.getenv("DPMS_CALENDAR_HTTP_TESTS") == "1", "isolated PostgreSQL opt-in required"
)
class CalendarExpiredWindowsHTTPTests(unittest.IsolatedAsyncioTestCase):
    body = parallel_fixture.CalendarParallelHTTPTests.body
    command = parallel_fixture.CalendarParallelHTTPTests.command
    submit = parallel_fixture.CalendarParallelHTTPTests.submit
    send = parallel_fixture.CalendarParallelHTTPTests.send
    group = parallel_fixture.CalendarParallelHTTPTests.group
    plan_payload = parallel_fixture.CalendarParallelHTTPTests.plan_payload
    plan = parallel_fixture.CalendarParallelHTTPTests.plan
    fact_payload = parallel_fixture.CalendarParallelHTTPTests.fact_payload
    record = parallel_fixture.CalendarParallelHTTPTests.record
    calendar_state = parallel_fixture.CalendarParallelHTTPTests.calendar_state
    evidence = parallel_fixture.CalendarParallelHTTPTests.evidence
    synthetic_fact = timeline_fixture.CalendarTimelineHTTPTests.fact

    async def asyncSetUp(self):
        await parallel_fixture.CalendarParallelHTTPTests.asyncSetUp(self)

    async def batch(self, *, actor="helper", status=200, **query):
        self.actor = self.people[actor]
        response = await self.client.get("/api/audit-calendar/meeting-windows", params={
            "from": self.day.isoformat(), "to": self.day.isoformat(), "duration": 30, **query,
        })
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    async def options(self, *, actor="helper", status=200, **query):
        self.actor = self.people[actor]
        response = await self.client.get("/api/audit-calendar/meeting-window-options", params={
            "date": self.day.isoformat(), "start": 780, "duration": 30, **query,
        })
        self.assertEqual(response.status_code, status, response.text)
        return response.json()

    def cell(self, result, start=780):
        matches = [cell for cell in result["cells"] if cell["date"] == self.day.isoformat() and cell["start"] == start]
        self.assertEqual(len(matches), 1)
        return matches[0]

    def assert_cell(self, result, status, confirmed, uncertain, *, start=780):
        self.assertEqual(self.cell(result, start), {
            "date": self.day.isoformat(), "start": start, "status": status,
            "confirmed": confirmed, "uncertain": uncertain,
        })

    def set_time(self, hour=13, minute=0, *, microsecond=1):
        self.now = datetime.combine(self.day, time(hour, minute, microsecond=microsecond), ZoneInfo("Europe/Moscow"))

    async def clear_availability(self, codes):
        for code in codes:
            await self.send("availability.paint", {
                "user_id": str(self.people[code].id), "patches": [{
                    "date": self.day.isoformat(), "start": 720, "end": 960, "value": None,
                }],
            })

    async def test_before_exact_and_after_start_preserve_future_options_guard(self):
        boundary = datetime.combine(self.day, time(13), ZoneInfo("Europe/Moscow"))
        before = await self.evidence()
        for delta, status, option_count in ((-1, "available", 4), (0, "available", 4), (1, "expired", 0)):
            with self.subTest(microseconds=delta):
                self.now = boundary + timedelta(microseconds=delta)
                result = await self.batch()
                self.assertEqual(datetime.fromisoformat(result["now"]), self.now)
                self.assert_cell(result, status, 4, 0)
                self.assertEqual(len((await self.options())["options"]), option_count)
        self.assertEqual(await self.evidence(), before)

    async def test_many_variants_are_one_expired_cell_not_four_opportunities(self):
        for code in (*self.trios["G1"], *self.trios["G2"]):
            await self.send("availability.paint", {
                "user_id": str(self.people[code].id), "patches": [
                    {"date": self.day.isoformat(), "start": 720, "end": 780, "value": None},
                    {"date": self.day.isoformat(), "start": 810, "end": 960, "value": None},
                ],
            })
        self.now = datetime.combine(self.day + timedelta(days=1), time(12), ZoneInfo("Europe/Moscow"))
        result = await self.batch()
        self.assertEqual(len(result["cells"]), 16)
        self.assertEqual(len({(c["date"], c["start"]) for c in result["cells"]}), 16)
        expired = [c for c in result["cells"] if c["status"] == "expired"]
        self.assertEqual(expired, [{
            "date": self.day.isoformat(), "start": 780, "status": "expired", "confirmed": 4, "uncertain": 0,
        }])
        self.assertTrue(all(c["status"] == "unavailable" and c["confirmed"] == c["uncertain"] == 0
            for c in result["cells"] if c["start"] != 780))
        self.assertEqual((await self.options())["options"], [])

    async def test_uncertain_only_past_is_unavailable_and_zeros_uncertain_count(self):
        await self.clear_availability((*self.trios["G1"], *self.trios["G2"]))
        self.set_time(microsecond=0)
        self.assert_cell(await self.batch(), "warning", 0, 4)
        self.assertEqual(len((await self.options())["options"]), 4)
        self.set_time()
        result = await self.batch()
        self.assert_cell(result, "unavailable", 0, 0)
        self.assertTrue(all(c["status"] == "unavailable" and c["uncertain"] == 0
            for c in result["cells"] if c["start"] <= 780))
        self.assert_cell(result, "warning", 0, 4, start=810)
        self.assertEqual((await self.options())["options"], [])

    async def test_mixed_past_variants_require_confirmed_and_retain_separate_uncertain_count(self):
        await self.clear_availability(("speaker2",))
        self.set_time()
        self.assert_cell(await self.batch(), "expired", 2, 2)
        uncertain_only = await self.batch(speaker_id=str(self.people["speaker2"].id))
        self.assert_cell(uncertain_only, "unavailable", 0, 0)
        confirmed_only = await self.batch(speaker_id=str(self.people["speaker"].id))
        self.assert_cell(confirmed_only, "expired", 2, 0)

    async def test_all_participants_reserved_by_plans_and_completed_facts_are_not_expired(self):
        first, second = await self.plan(), await self.plan("G2")
        self.set_time()
        self.assert_cell(await self.batch(), "unavailable", 0, 0)
        self.set_time(14, 1)
        await self.record(first)
        await self.record(second)
        result = await self.batch()
        self.assert_cell(result, "unavailable", 0, 0)
        self.assert_cell(result, "unavailable", 0, 0, start=810)
        self.assertEqual((await self.options())["options"], [])

    async def test_independent_free_group_beside_another_meeting_is_expired(self):
        first = await self.plan()
        self.set_time()
        self.assert_cell(await self.batch(), "expired", 1, 0)
        self.assert_cell(await self.batch(group=self.groups["G1"]), "unavailable", 0, 0)
        self.assert_cell(await self.batch(group=self.groups["G2"]), "expired", 1, 0)
        self.set_time(14, 1)
        await self.record(first)
        self.assert_cell(await self.batch(), "expired", 1, 0)

    async def test_cancelled_plans_and_standalone_cancelled_facts_do_not_block(self):
        plan = await self.plan()
        await self.send("plan.save", {
            **self.plan_payload(), "id": plan["id"], "status": "cancelled", "reason": "Synthetic cancellation",
        })
        await self.synthetic_fact(start=780, outcome="cancelled")
        self.set_time()
        self.assert_cell(await self.batch(), "expired", 4, 0)

    async def test_cancelled_fact_does_not_release_its_still_planned_original_slot(self):
        plan = await self.plan()
        await self.synthetic_fact(plan=plan, start=780, outcome="cancelled")
        self.set_time()
        self.assert_cell(await self.batch(), "expired", 1, 0)
        self.assert_cell(await self.batch(group=self.groups["G1"]), "unavailable", 0, 0)

    async def test_retrospective_result_uses_current_absence_status_not_historical_proof(self):
        absence = await self.send("absence.add", {
            "user_id": str(self.people["employee"].id), "start_date": self.day.isoformat(),
            "end_date": self.day.isoformat(), "reason": "Synthetic absence",
        })
        self.set_time()
        blocked = await self.batch(group=self.groups["G1"])
        self.assert_cell(blocked, "unavailable", 0, 0)
        await self.send("absence.end", {"id": absence["id"], "reason": "Synthetic current correction"})
        corrected = await self.batch(group=self.groups["G1"])
        self.assertEqual(corrected["version"], blocked["version"] + 1)
        self.assert_cell(corrected, "expired", 2, 0)
        self.assertEqual((await self.options(group=self.groups["G1"]))["options"], [])

    async def test_acl_filters_range_and_resource_limits_stay_read_only(self):
        self.set_time()
        before = await self.evidence()
        for actor in ("employee", "helper"):
            self.assert_cell(await self.batch(actor=actor), "expired", 4, 0)
            self.assertEqual((await self.options(actor=actor))["options"], [])
        for actor in ("admin", "outsider", "denied"):
            await self.batch(actor=actor, status=403)
            await self.options(actor=actor, status=403)
        self.assert_cell(await self.batch(group=self.groups["G1"], speaker_id=str(self.people["speaker"].id)), "expired", 1, 0)
        await self.batch(group=str(uuid4()), status=404)
        await self.options(group=str(uuid4()), status=404)
        await self.batch(speaker_id=str(self.people["employee"].id), status=422)
        await self.options(speaker_id=str(self.people["employee"].id), status=422)
        longest = await self.batch(**{"to": (self.day + timedelta(days=30)).isoformat()})
        self.assertEqual(len(longest["cells"]), 31 * 16)
        for query in (
            {"to": (self.day + timedelta(days=31)).isoformat()},
            {"to": (self.day - timedelta(days=1)).isoformat()},
            {"from": "1999-12-31", "to": "1999-12-31"},
            {"from": "2101-01-01", "to": "2101-01-01"},
            {"duration": 15}, {"duration": 510},
        ):
            await self.batch(status=422, **query)
        await self.options(status=422, start=605)
        await self.options(status=422, start=1410, duration=60)
        full = await self.batch(full_day=True, duration=60)
        self.assertEqual(len(full["cells"]), 48)
        self.assert_cell(full, "unavailable", 0, 0, start=1410)
        for limit in ("MAX_VARIANTS", "MAX_PERSON_INTERVALS", "MAX_VARIANT_INTERVALS", "MAX_CONTEXT_ROWS"):
            with patch(f"app.services.audit_calendar_windows.{limit}", 0):
                await self.batch(status=422)
                await self.options(status=422)
        self.assertEqual(await self.evidence(), before)
        self.actor = self.people["admin"]
        response = await self.command(self.body("scope.archive", {"archived": True, "reason": "Synthetic archive"}))
        self.assertEqual(response.status_code, 200, response.text)
        archived = await self.batch()
        self.assertTrue(all(c["status"] == "unavailable" and c["confirmed"] == c["uncertain"] == 0 for c in archived["cells"]))
        self.assertEqual((await self.options())["options"], [])
