"""Planning/CAS HTTP contracts on the opt-in disposable calendar database."""
import copy
import os
import unittest
from datetime import timedelta
from uuid import UUID, uuid4

import test_calendar_controls_http as helpers


@unittest.skipUnless(os.getenv("DPMS_CALENDAR_HTTP_TESTS") == "1", "isolated PostgreSQL opt-in required")
class CalendarPlanningHTTPTests(unittest.IsolatedAsyncioTestCase):
    body = helpers.CalendarControlsHTTPTests.body
    command = helpers.CalendarControlsHTTPTests.command
    calendar_state = helpers.CalendarControlsHTTPTests.calendar_state
    send = helpers.CalendarControlsHTTPTests.send
    patch = helpers.CalendarControlsHTTPTests.patch
    paint = helpers.CalendarControlsHTTPTests.paint
    person_day = helpers.CalendarControlsHTTPTests.person_day
    lock_day = helpers.CalendarControlsHTTPTests.lock_day
    rows = helpers.CalendarControlsHTTPTests.rows

    async def asyncSetUp(self):
        await helpers.CalendarControlsHTTPTests.asyncSetUp(self)

    def intent(self, *, person="employee", day=None, start=600, end=630, value=True, before=None):
        return self.body("availability.paint", {"user_id": str(self.people[person].id),
            "patches": [self.patch(day, start, end, value)],
            "expected": [self.patch(day, minute, minute+30, before) for minute in range(start, end, 30)]})

    async def options(self, **params):
        response = await self.client.get("/api/audit-calendar/meeting-options", params={
            "date": self.day.isoformat(), "start": 600, "duration": 30, **params})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["groups"]

    async def test_independent_stale_edits_and_same_target_do_not_conflict(self):
        first = self.intent()
        other_user = self.intent(person="tech")
        other_day = self.intent(day=self.next_day)
        other_cell = self.intent(start=630, end=660)
        same = self.intent()
        for body in (first, other_user, other_day, other_cell, same):
            response = await self.command(body)
            self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["result"]["unchanged"])
        self.assertEqual(response.json()["result"]["changed_cells"], 0)
        self.assertEqual(len((await self.calendar_state())["availability"]), 4)

    async def test_fourteen_full_days_use_exact_672_cell_baseline(self):
        body = self.intent(start=0, end=1440)
        body["payload"]["patches"] = [self.patch(day=self.day+timedelta(days=i), start=0, end=1440) for i in range(14)]
        body["payload"]["expected"] = [self.patch(day=self.day+timedelta(days=i), start=t, end=t+30, value=None)
            for i in range(14) for t in range(0, 1440, 30)]
        result = await self.command(body)
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["result"]["changed_cells"], 672)

    async def test_restored_original_value_allows_new_intent_but_keeps_history(self):
        stale = self.intent()
        self.assertEqual((await self.command(self.intent(value=False))).status_code, 200)
        self.assertEqual((await self.command(self.intent(value=None, before=False))).status_code, 200)
        result = await self.command(stale)
        self.assertEqual(result.status_code, 200, result.text)
        events = await self.rows(self.models.AuditCalendarEvent, self.models.AuditCalendarEvent.action == "availability.paint")
        self.assertEqual(len(events), 3)

    async def test_conflict_is_atomic_and_replay_never_overwrites_newer_data(self):
        stale = self.intent(start=600, end=660, value=False)
        first = self.intent()
        saved = await self.command(first)
        self.assertEqual(saved.status_code, 200)
        before = await self.calendar_state()
        conflict = await self.command(stale)
        self.assertEqual(conflict.status_code, 409)
        self.assertEqual(conflict.json()["detail"]["code"], "AVAILABILITY_CHANGED")
        self.assertEqual(conflict.json()["detail"]["conflicts"][0]["current"], True)
        after = await self.calendar_state()
        self.assertEqual(before["availability"], after["availability"])
        self.assertEqual(before["scope"]["version"], after["scope"]["version"])
        newer = self.intent(value=False, before=True)
        self.assertEqual((await self.command(newer)).status_code, 200)
        self.assertEqual((await self.command(first)).json(), saved.json())
        current = await self.calendar_state()
        self.assertFalse(current["availability"][0]["available"])
        tampered = copy.deepcopy(first)
        tampered["payload"]["patches"][0]["value"] = False
        self.assertEqual((await self.command(tampered)).status_code, 409)

    async def test_schema_exact_coverage_and_legacy_cas(self):
        valid = self.intent()
        variants = [[], [self.patch(start=630, end=660)], [self.patch(end=660)],
                    [self.patch(), self.patch()], [self.patch(value="true")]]
        for expected in variants:
            body = copy.deepcopy(valid); body["payload"]["expected"] = expected
            response = await self.command(body)
            self.assertEqual(response.status_code, 422, response.text)
        old = copy.deepcopy(valid); del old["payload"]["expected"]
        null_old = copy.deepcopy(valid); null_old["payload"]["expected"] = None
        self.assertEqual((await self.command(valid)).status_code, 200)
        for body in (old, null_old):
            body["request_id"] = str(uuid4())
            self.assertEqual((await self.command(body)).status_code, 409)

    async def test_whole_day_residuals_and_overlapping_last_intent(self):
        body = self.intent(start=0, end=1440)
        body["payload"]["patches"].append(self.patch(start=600, end=630, value=False))
        response = await self.command(body)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(response.json()["result"]["changed_cells"], 48)
        windows = (await self.calendar_state())["availability"]
        self.assertEqual([(w["start"], w["end"], w["available"]) for w in sorted(windows, key=lambda w: w["start"])],
                         [(0, 600, True), (600, 630, False), (630, 1440, True)])
        intent = self.intent(start=600, end=630, value=None, before=False)
        self.assertEqual((await self.command(intent)).status_code, 200)
        self.assertEqual(len((await self.calendar_state())["availability"]), 2)

    async def test_legacy_receipt_replays_without_new_optional_field(self):
        from app.schemas.audit_calendar import AvailabilityCommand
        from app.services.audit_calendar import body_hash

        body = self.intent()
        del body["payload"]["expected"]
        legacy = AvailabilityCommand.model_validate(body).model_dump(mode="json")
        del legacy["payload"]["expected"]
        receipt = {"version": self.version, "result": {"legacy": True}}
        async with self.factory.begin() as db:
            db.add(self.models.AuditCalendarIdempotency(scope_id=self.scope_id,
                actor_id=self.people["helper"].id, request_id=UUID(body["request_id"]),
                body_hash=body_hash("availability.paint", legacy), response=receipt))
        self.assertEqual((await self.command(body)).json(), receipt)
        body["payload"]["expected"] = None
        self.assertEqual((await self.command(body)).json(), receipt)
        body["payload"]["patches"][0]["value"] = False
        self.assertEqual((await self.command(body)).status_code, 409)
        self.assertFalse((await self.calendar_state())["availability"])

    async def test_options_reject_frozen_plan_even_when_fact_is_on_another_day(self):
        plan = await self.send("plan.save", {"date": self.day.isoformat(), "start": 600,
            "duration": 30, "group_id": self.group_id, "speaker_id": str(self.people["speaker"].id),
            "activity": "Frozen test", "status": "planned"})
        async with self.factory.begin() as db:
            db.add(self.models.AuditCalendarFact(scope_id=self.scope_id, plan_id=UUID(plan["id"]),
                date=self.next_day, start=900, duration=30, group_id=UUID(self.group_id),
                activity="Moved fact", outcome="cancelled", reason="Synthetic", evidence="",
                recorded_by_id=self.people["helper"].id, participant_snapshot=[], origin="native"))
        option = (await self.options(plan_id=plan["id"]))[0]
        self.assertFalse(option["eligible"])
        self.assertIn("PLAN_FROZEN", [i["code"] for i in option["issues"]])

    async def test_scoped_cas_rechecks_locks_absences_archive_and_ownership(self):
        stale = self.intent()
        await self.lock_day()
        self.assertEqual((await self.command(stale)).status_code, 409)
        absence_intent = self.intent(day=self.next_day)
        await self.send("absence.add", {"user_id": str(self.people["employee"].id), "start_date": self.next_day.isoformat(),
            "end_date": self.next_day.isoformat(), "reason": "Absence after editing began"})
        blocked = await self.command(absence_intent)
        self.assertEqual(blocked.status_code, 409)
        self.assertEqual(blocked.json()["detail"]["code"], "AVAILABILITY_ABSENCE")
        self.actor = self.people["employee"]
        self.assertEqual((await self.command(self.intent(person="tech"))).status_code, 403)
        self.actor = self.people["helper"]
        future = self.intent(day=self.next_day+timedelta(days=1))
        await self.send("scope.archive", {"archived": True, "reason": "Archive after editing began"}, actor="admin")
        self.actor = self.people["helper"]
        self.assertEqual((await self.command(future)).status_code, 409)

    async def test_options_unknown_is_warning_but_busy_and_partial_are_ineligible(self):
        first = (await self.options())[0]
        self.assertTrue(first["eligible"])
        self.assertEqual(len(first["warnings"]), 2)
        self.assertTrue(any(w["message"].startswith("employee:") and w["participant_name"] for w in first["warnings"]))
        await self.paint(end=630)
        self.assertTrue((await self.options())[0]["eligible"])
        partial = (await self.options(duration=60))[0]
        self.assertFalse(partial["eligible"])
        self.assertEqual(partial["issues"][0]["user_id"], str(self.people["employee"].id))
        await self.paint(code="tech", end=630, value=False)
        busy = (await self.options())[0]
        self.assertFalse(busy["eligible"])
        self.assertTrue(any(i["message"].startswith("tech:") for i in busy["issues"]))

    async def test_options_validate_time_speaker_and_exclude_own_plan(self):
        self.assertFalse((await self.options(speaker_id=str(self.people["employee"].id)))[0]["eligible"])
        payload = {"date": self.day.isoformat(), "start": 600, "duration": 30, "group_id": self.group_id,
                   "speaker_id": str(self.people["speaker"].id), "activity": "Synthetic", "status": "planned"}
        saved = await self.send("plan.save", payload)
        self.assertFalse((await self.options())[0]["eligible"])
        self.assertTrue((await self.options(plan_id=saved["id"]))[0]["eligible"])
        self.assertTrue((await self.options(start=630))[0]["eligible"])
        self.assertTrue(all(i["participant_code"] for i in (await self.options())[0]["issues"]))
        for query in ({"date": "1900-01-01"}, {"start": 1410, "duration": 60}, {"duration": 15}):
            response = await self.client.get("/api/audit-calendar/meeting-options", params={"date": self.day.isoformat(), "start": 600, "duration": 30, **query})
            self.assertEqual(response.status_code, 422, response.text)
        state = await self.calendar_state()
        self.assertTrue(state["plans"][0]["warnings"][0]["participant_code"])


if __name__ == "__main__":
    unittest.main()
