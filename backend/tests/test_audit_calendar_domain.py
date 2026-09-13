"""Dependency-free rule tests, distinct from the integrator-owned math suite."""
from datetime import date, datetime, timedelta
from pathlib import Path
import sys
from types import SimpleNamespace as NS
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.services.audit_calendar_domain import MOSCOW, availability_issues, composition_issues, conflict_issues, attendance_state, historical_source_issues
from app.services.audit_calendar_math import AvailabilityWindow as Window, Absence


class CalendarDomainTests(unittest.TestCase):
    day = date(2026, 9, 14)

    def test_unknown_day_is_warning_not_free(self):
        errors, warnings = availability_issues(self.day, 600, 60, ["A"], [], [])
        self.assertFalse(errors)
        self.assertEqual(warnings[0]["code"], "AVAILABILITY_UNKNOWN")

    def test_free_windows_must_cover_entire_interval(self):
        for windows in [[Window("A", self.day, 600, 630, True)], [Window("A", self.day, 900, 960, True)]]:
            errors, warnings = availability_issues(self.day, 600, 60, ["A"], windows, [])
            self.assertEqual(errors[0]["code"], "OUTSIDE_AVAILABILITY")
            self.assertFalse(warnings)

    def test_adjacent_free_union_covers(self):
        self.assertEqual(availability_issues(self.day, 600, 60, ["A"], [Window("A", self.day, 600, 630, True),
            Window("A", self.day, 630, 660, True)], []), ([], []))

    def test_busy_and_absence_override_free(self):
        free = Window("A", self.day, 0, 1440, True)
        for windows, absences in [([free, Window("A", self.day, 630, 660, False)], []),
                                  ([free], [Absence("A", self.day, self.day)])]:
            self.assertEqual(availability_issues(self.day, 600, 60, ["A"], windows, absences)[0][0]["code"], "UNAVAILABLE")

    def test_modern_role_and_grant_validation(self):
        members = {uid: NS(active=True, role=role) for uid, role in [("A", "auditor"), ("T", "tech"), ("S", "speaker")]}
        users = {uid: NS(is_active=True, audit_calendar_enabled=True) for uid in members}
        group, version = NS(legacy=False, archived=False), NS(auditor_id="A", tech_id="T")
        self.assertFalse(composition_issues(group, version, members, users, "ACT", "S")[0])
        users["A"].audit_calendar_enabled = False
        self.assertTrue(composition_issues(group, version, members, users, "ACT", "S")[0])

    def test_shared_participant_across_groups_blocks(self):
        candidate = NS(id="new", date=self.day, start=600, duration=90)
        other = NS(id="old", date=self.day, start=660, duration=30, status="planned", outcome="completed")
        self.assertTrue(conflict_issues(candidate, ["A"], [other], {"old": {"A"}}))
        other.start = 690
        self.assertFalse(conflict_issues(candidate, ["A"], [other], {"old": {"A"}}))

    def test_historical_completed_conflict_and_cancelled_exclusion(self):
        candidate = NS(date=self.day, start=600, duration=60)
        other = NS(id="fact", date=self.day, start=600, duration=60, outcome="completed")
        self.assertEqual(conflict_issues(candidate, ["A"], [other], {"fact": {"A"}}, facts=True)[0]["code"], "FACT_CONFLICT")
        other.outcome = "cancelled"
        self.assertFalse(conflict_issues(candidate, ["A"], [other], {"fact": {"A"}}, facts=True))

    def test_notice_rule_60_minutes_and_late(self):
        plan = NS(id="plan", date=self.day, start=600)
        cutoff = datetime(2026, 9, 14, 9, tzinfo=MOSCOW)
        self.assertEqual(attendance_state(plan, [], cutoff - timedelta(seconds=1)), "waiting")
        self.assertEqual(attendance_state(plan, [], cutoff), "confirmed")
        self.assertEqual(attendance_state(plan, [NS(plan_id="plan", reported_at=cutoff)], cutoff), "absence")
        self.assertEqual(attendance_state(plan, [NS(plan_id="plan", reported_at=cutoff + timedelta(minutes=1))], cutoff + timedelta(hours=1)), "late-absence")

    def test_historical_source_validator_rejects_native_future_group_injection(self):
        original = {"kind": "plan", "origin": "native", "date": "2026-09-20", "sourceRow": None, "groupId": "G1"}
        codes = {i["code"] for i in historical_source_issues(original, date(2026, 9, 1), self.day, actual_group_code="G2")}
        self.assertIn("HISTORICAL_SOURCE", codes)
        self.assertIn("HISTORICAL_ATTRIBUTION", codes)
        original.update(origin="source", date="2026-09-01", sourceRow=2)
        self.assertFalse(historical_source_issues(original, date(2026, 9, 1), self.day, actual_group_code="G1"))
        self.assertTrue(historical_source_issues(original, date(2026, 9, 12), self.day, actual_group_code="G1"))


if __name__ == "__main__":
    unittest.main()
