"""Opt-in workload route regressions using only synthetic fixture records.

From backend, in the integrator's already configured disposable environment:
  DPMS_CALENDAR_HTTP_TESTS=1 python -m unittest discover -s tests \
      -p 'test_calendar_workload_http.py' -v

No application/settings imports happen without opt-in. The existing fixture
owns the connection and rollback; this module never creates or migrates a DB.
"""
from datetime import timedelta
import os
import unittest
from uuid import uuid4


@unittest.skipUnless(
    os.getenv("DPMS_CALENDAR_HTTP_TESTS") == "1", "isolated PostgreSQL opt-in required"
)
class CalendarWorkloadHTTPTests(unittest.IsolatedAsyncioTestCase):
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

        # Retain the module alias, not an imported TestCase that discovery could
        # collect again; reuse its setup/helpers without inheriting its tests.
        self.fixture = fixture
        await self.fixture.CalendarHTTPTests.asyncSetUp(self)
        self.addAsyncCleanup(self.fixture.CalendarHTTPTests.asyncTearDown, self)
        self.day = self.today + timedelta(days=7 - self.today.weekday())
        self.actor = self.people["helper"]

    def body(self, operation, payload):
        return self.fixture.CalendarHTTPTests.body(self, operation, payload)

    async def command(self, body):
        return await self.fixture.CalendarHTTPTests.command(self, body)

    async def send(self, operation, payload):
        self.actor = self.people["helper"]
        response = await self.command(self.body(operation, payload))
        self.assertEqual(response.status_code, 200, response.text)
        answer = response.json()
        self.version = answer["version"]
        return answer["result"]

    async def plan(self, *, day=None, start=600, duration=90, group=None):
        return await self.send("plan.save", {
            "date": (day or self.day).isoformat(), "start": start, "duration": duration,
            "group_id": group or self.group_id, "activity": "Synthetic workload meeting",
            "speaker_id": str(self.people["speaker"].id), "status": "planned",
            "reason": "Synthetic workload fixture",
        })

    async def paint(self, *, code="employee", day=None, start=600, end=660, value=True):
        return await self.send("availability.paint", {
            "user_id": str(self.people[code].id), "patches": [{
                "date": (day or self.day).isoformat(), "start": start, "end": end, "value": value,
            }],
        })

    async def workload(self, *, start=None, end=None, group=None, actor="employee", status=200):
        self.actor = self.people[actor]
        params = {"from": (start or self.day).isoformat(), "to": (end or self.day).isoformat()}
        if group is not None:
            params["group"] = str(group)
        response = await self.client.get("/api/audit-calendar/workload", params=params)
        self.assertEqual(response.status_code, status, response.text)
        return response.json() if status == 200 else response

    def employee(self, report, code="employee"):
        matches = [row for row in report["members"] if row["user_id"] == str(self.people[code].id)]
        self.assertEqual(len(matches), 1, code)
        return matches[0]

    async def test_plan_then_reduced_free_time_reports_150_percent(self):
        await self.plan(duration=90)
        await self.paint(end=660)
        report = await self.workload()
        self.assertEqual(report["version"], self.version)
        self.assertEqual(report["period"], {
            "from": self.day.isoformat(), "to": self.day.isoformat(), "group_id": None,
        })
        self.assertEqual(report["working_days"], 1)
        self.assertEqual(report["working_window"], {"start": 600, "end": 1080, "slot_minutes": 30})
        row = self.employee(report)
        self.assertEqual((row["code"], row["full_name"], row["role"], row["active"]),
                         ("employee", "Test employee", "auditor", True))
        self.assertEqual((row["free_slots"], row["free_minutes"]), (2, 60))
        self.assertEqual((row["filled_days"], row["partial_days"], row["unfilled_days"]), (0, 1, 0))
        self.assertEqual((row["planned_meetings"], row["planned_minutes"],
                          row["planned_work_minutes"], row["outside_work_minutes"]), (1, 90, 90, 0))
        self.assertEqual(row["power_percent"], 150)
        self.assertAlmostEqual(row["target"], 0.3)
        self.assertAlmostEqual(row["norm_percent"], 100 / 0.3)
        for code in ("tech", "speaker"):
            self.assertEqual(self.employee(report, code)["planned_meetings"], 1)
            self.assertEqual(self.employee(report, code)["planned_minutes"], 90)
        self.assertEqual(self.employee(report, "helper")["planned_meetings"], 0)

    async def test_zero_free_time_keeps_power_null_even_with_bookings(self):
        await self.plan(duration=90)
        initial = self.employee(await self.workload())
        self.assertEqual(initial["unfilled_days"], 1)
        self.assertEqual(initial["free_minutes"], 0)
        self.assertEqual(initial["planned_work_minutes"], 90)
        self.assertIsNone(initial["power_percent"])
        await self.paint(start=600, end=1080, value=False)
        report = await self.workload()
        row = self.employee(report)
        self.assertEqual((row["filled_days"], row["partial_days"], row["absence_days"]), (1, 0, 0))
        self.assertEqual((row["free_slots"], row["free_minutes"]), (0, 0))
        self.assertEqual((row["planned_meetings"], row["planned_minutes"]), (1, 90))
        self.assertIsNone(row["power_percent"])
        self.assertAlmostEqual(row["norm_percent"], 100 / 0.3)
        helper = self.employee(report, "helper")
        self.assertEqual(helper["target"], 0)
        self.assertIsNone(helper["norm_percent"])
        self.assertIsNone(helper["power_percent"])

    async def test_work_window_clips_weekday_and_separates_weekend_and_evening_minutes(self):
        saturday = self.day + timedelta(days=5)
        await self.plan(start=570, duration=60)
        await self.plan(start=1050, duration=90)
        await self.plan(start=1200, duration=60)
        await self.plan(day=saturday, start=600, duration=120)
        await self.paint(start=0, end=1440)
        await self.paint(day=saturday, start=0, end=1440)
        report = await self.workload(end=saturday)
        self.assertEqual(report["working_days"], 5)
        row = self.employee(report)
        self.assertEqual((row["filled_days"], row["unfilled_days"]), (1, 4))
        self.assertEqual((row["free_slots"], row["free_minutes"]), (16, 480))
        self.assertEqual(row["planned_meetings"], 4)
        self.assertEqual(row["planned_minutes"], 330)
        self.assertEqual(row["planned_work_minutes"], 60)
        self.assertEqual(row["outside_work_minutes"], 270)
        self.assertEqual(row["power_percent"], 12.5)
        weekend = self.employee(await self.workload(start=saturday, end=saturday))
        self.assertEqual((weekend["planned_meetings"], weekend["planned_minutes"]), (1, 120))
        self.assertEqual((weekend["planned_work_minutes"], weekend["outside_work_minutes"]), (0, 120))
        self.assertEqual(weekend["free_minutes"], 0)
        self.assertIsNone(weekend["power_percent"])

    async def test_group_filter_selects_plans_and_norm_without_duplicating_availability(self):
        group = await self.send("group.save", {
            "code": "G2", "label": "Synthetic second group", "effective_from": self.day.isoformat(),
            "auditor_id": str(self.people["employee"].id), "tech_id": str(self.people["tech"].id),
            "reason": "Synthetic shared membership",
        })
        second_id = group["id"]
        await self.plan(duration=90)
        await self.plan(group=second_id, start=720, duration=30)
        await self.paint()
        report = await self.workload()
        self.assertCountEqual([row["code"] for row in report["members"]],
                              ["helper", "employee", "tech", "speaker"])
        combined = self.employee(report)
        self.assertEqual((combined["planned_meetings"], combined["planned_minutes"]), (2, 120))
        self.assertEqual(combined["free_minutes"], 60)
        self.assertEqual(combined["partial_days"], 1)
        self.assertAlmostEqual(combined["target"], 0.6)
        self.assertEqual(combined["power_percent"], 200)
        for gid, minutes, power in [(self.group_id, 90, 150), (second_id, 30, 50)]:
            with self.subTest(group=gid):
                selected = await self.workload(group=gid)
                self.assertEqual(selected["period"]["group_id"], str(gid))
                self.assertCountEqual([row["code"] for row in selected["members"]],
                                      ["employee", "tech", "speaker"])
                row = self.employee(selected)
                self.assertEqual((row["planned_meetings"], row["planned_minutes"]), (1, minutes))
                self.assertEqual(row["free_minutes"], 60)
                self.assertAlmostEqual(row["target"], 0.3)
                self.assertEqual(row["power_percent"], power)

    async def test_access_is_scoped_and_inactive_member_remains_visible_to_authorized_actor(self):
        for actor in ("employee", "helper"):
            with self.subTest(actor=actor):
                await self.workload(actor=actor)
        for actor in ("admin", "outsider", "denied"):
            with self.subTest(actor=actor):
                await self.workload(actor=actor, status=403)
        self.actor = self.people["admin"]
        response = await self.client.post("/api/audit-calendar/admin/members", json={
            "request_id": str(uuid4()), "expected_version": self.version,
            "user_id": str(self.people["employee"].id), "code": "employee", "role": "auditor",
            "can_manage": False, "active": False,
        })
        self.assertEqual(response.status_code, 200, response.text)
        self.version = response.json()["version"]
        await self.workload(actor="employee", status=403)
        row = self.employee(await self.workload(actor="helper"))
        self.assertFalse(row["active"])
        self.assertEqual(row["planned_meetings"], 0)
        self.assertAlmostEqual(row["target"], 0.3)

    async def test_date_and_group_validation_and_inclusive_366_day_limit(self):
        await self.workload(group=uuid4(), status=404)
        self.actor = self.people["helper"]
        invalid = [
            {"from": "1900-01-01", "to": "1900-01-02"},
            {"from": "2101-01-01", "to": "2101-01-02"},
            {"from": "2026-09-99", "to": "2026-09-30"},
            {"from": self.day.isoformat(), "to": (self.day - timedelta(days=1)).isoformat()},
            {"from": self.day.isoformat(), "to": (self.day + timedelta(days=366)).isoformat()},
            {"from": self.day.isoformat(), "to": self.day.isoformat(), "group": "not-a-uuid"},
            {"from": self.day.isoformat()}, {"to": self.day.isoformat()},
        ]
        for params in invalid:
            with self.subTest(params=params):
                response = await self.client.get("/api/audit-calendar/workload", params=params)
                self.assertEqual(response.status_code, 422, response.text)
        report = await self.workload(end=self.day + timedelta(days=365))
        self.assertEqual(report["working_days"], 262)
        self.assertEqual(report["version"], self.version)
