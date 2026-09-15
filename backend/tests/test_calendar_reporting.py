"""Pure synthetic workload regressions; no app settings, database or real data."""
from copy import deepcopy
from datetime import date, datetime, timedelta
from types import SimpleNamespace as Row
import unittest

from app.services.audit_calendar_reporting import workload_report


MONDAY = date(2026, 9, 14)


def member(uid, role="auditor", active=True):
    return dict(user_id=uid, code=uid.upper(), full_name="Synthetic " + uid,
                role=role, active=active, can_manage=False)


def fixture():
    return dict(start=MONDAY, end=MONDAY + timedelta(days=6), baseline=MONDAY, version=7,
                members=[member("a"), member("t", "tech"), member("s", "speaker"),
                         member("old", active=False), member("empty", "observer")],
                groups=[Row(id="g", archived=False, legacy=False)],
                versions=[Row(group_id="g", effective_from=MONDAY, auditor_id="a", tech_id="t")],
                norms=[Row(group_id=None, effective_from=MONDAY, value=6, revision=1),
                       Row(group_id="g", effective_from=MONDAY, value=3, revision=2)],
                plans=[], participants=[], facts=[], windows=[], absences=[])


def plan(identity="p", *, day=MONDAY, group="g", status="planned", duration=60, speaker="s", start=600):
    return Row(id=identity, date=day, group_id=group, status=status, duration=duration,
               speaker_id=speaker, start=start)


def window(uid="a", day=MONDAY, start=600, end=1080, available=True):
    return Row(user_id=uid, date=day, start=start, end=end, available=available)


def rows(data):
    return {row["user_id"]: row for row in workload_report(**data)["members"]}


class CalendarReportingTests(unittest.TestCase):
    def test_contract_empty_inactive_and_missing_denominators(self):
        data = fixture()
        result = workload_report(**data)
        self.assertEqual(result["period"], {"from": data["start"], "to": data["end"], "group_id": None})
        self.assertEqual(result["version"], 7)
        self.assertEqual(result["working_days"], 5)
        self.assertEqual(result["working_window"], {"start": 600, "end": 1080, "slot_minutes": 30})
        values = rows(data)
        self.assertEqual(len(values), 5)
        self.assertFalse(values["old"]["active"])
        self.assertEqual(values["empty"]["unfilled_days"], 5)
        self.assertEqual(values["empty"]["target"], 0)
        self.assertIsNone(values["empty"]["power_percent"])
        self.assertIsNone(values["empty"]["norm_percent"])
        self.assertIsNone(values["a"]["power_percent"])
        self.assertEqual(values["a"]["norm_percent"], 0)

    def test_raw_coverage_busy_partial_absence_and_weekend(self):
        data = fixture()
        data["windows"] = [window(), window(start=0, end=1440),
                           window(day=MONDAY + timedelta(days=1), start=600, end=630, available=False),
                           window(day=MONDAY + timedelta(days=2)),
                           window(day=MONDAY + timedelta(days=3), start=0, end=600),
                           window(day=MONDAY + timedelta(days=4), available=False),
                           window(day=MONDAY + timedelta(days=5))]
        data["absences"] = [Row(user_id="a", start_date=MONDAY + timedelta(days=2),
                                end_date=MONDAY + timedelta(days=2), status="active")]
        value = rows(data)["a"]
        self.assertEqual((value["filled_days"], value["partial_days"], value["unfilled_days"],
                          value["absence_days"]), (2, 1, 1, 1))
        self.assertEqual((value["free_slots"], value["free_minutes"]), (16, 480))
        self.assertEqual(value["target"], 1.5)

    def test_overlapping_busy_wins_and_cancelled_absence_does_not_block(self):
        data = fixture()
        data["windows"] = [window(), window(start=630, end=690, available=False), window()]
        data["absences"] = [Row(user_id="a", start_date=MONDAY, end_date=MONDAY, status="cancelled")]
        value = rows(data)["a"]
        self.assertEqual(value["filled_days"], 1)
        self.assertEqual(value["absence_days"], 0)
        self.assertEqual(value["free_slots"], 14)
        self.assertEqual(value["free_minutes"], 420)

    def test_snapshots_not_current_composition_and_distinct_plans(self):
        data = fixture()
        data["plans"] = [plan(), plan(), plan("cancel", status="cancelled"),
                         plan("draft", status="draft"), plan("cancel-fact"),
                         plan("weekend", day=MONDAY + timedelta(days=5), duration=90)]
        data["participants"] = [Row(plan_id=p.id, user_id="old", role="auditor") for p in data["plans"]]
        data["participants"] += [Row(plan_id="p", user_id="old", role="observer"),
                                 Row(plan_id="p", user_id="s", role="speaker")]
        data["facts"] = [Row(plan_id="p", outcome="completed", duration=120),
                         Row(plan_id="cancel-fact", outcome="cancelled", date=date(2026, 10, 1)),
                         Row(plan_id=None, outcome="completed")]
        values = rows(data)
        for uid in ("old", "s"):
            self.assertEqual(values[uid]["planned_meetings"], 2)
            self.assertEqual(values[uid]["planned_minutes"], 150)
            self.assertEqual(values[uid]["planned_work_minutes"], 60)
            self.assertEqual(values[uid]["outside_work_minutes"], 90)
        self.assertEqual(values["a"]["planned_meetings"], 0)
        self.assertEqual(values["t"]["planned_meetings"], 0)

    def test_full_group_norm_for_both_members_and_two_percentages(self):
        data = fixture()
        data["plans"] = [plan(duration=90)]
        data["participants"] = [Row(plan_id="p", user_id=uid) for uid in ("a", "t")]
        data["windows"] = [window(end=660)]
        values = rows(data)
        self.assertEqual(values["a"]["target"], 1.5)
        self.assertEqual(values["t"]["target"], 1.5)
        self.assertAlmostEqual(values["a"]["norm_percent"], 100 / 1.5)
        self.assertEqual(values["a"]["power_percent"], 150)
        self.assertEqual(values["a"]["planned_work_minutes"], 90)
        self.assertEqual(values["a"]["free_minutes"], 60)
        self.assertIsNone(values["t"]["power_percent"])

    def test_historical_revisions_composition_and_archived_groups_retained(self):
        data = fixture()
        data["groups"][0].archived = True
        data["groups"][0].legacy = True
        data["norms"] += [Row(group_id="g", effective_from=MONDAY, value=10, revision=3),
                          Row(group_id="g", effective_from=MONDAY + timedelta(days=2), value=20, revision=4)]
        data["versions"][0].auditor_id = "old"
        data["versions"] += [Row(group_id="g", effective_from=MONDAY + timedelta(days=2), auditor_id="a", tech_id="t"),
                             Row(group_id="g", effective_from=MONDAY + timedelta(days=7), auditor_id="s", tech_id="t")]
        values = rows(data)
        self.assertEqual(values["old"]["target"], 2)
        self.assertEqual(values["a"]["target"], 6)
        self.assertEqual(values["t"]["target"], 8)
        self.assertEqual(values["s"]["target"], 0)

    def test_membership_in_multiple_groups_sums_norm_not_person_minutes(self):
        data = fixture()
        data["groups"].append(Row(id="g2", archived=False, legacy=False))
        data["versions"].append(Row(group_id="g2", effective_from=MONDAY, auditor_id="a", tech_id="t"))
        data["norms"].append(Row(group_id="g2", effective_from=MONDAY, value=2, revision=3))
        data["windows"] = [window()]
        data["plans"] = [plan(), plan("p2", group="g2")]
        data["participants"] = [Row(plan_id=p.id, user_id="a") for p in data["plans"]]
        value = rows(data)["a"]
        self.assertEqual((value["target"], value["planned_meetings"], value["planned_minutes"]), (2.5, 2, 120))
        self.assertEqual(value["free_minutes"], 480)
        self.assertEqual(value["filled_days"], 1)
        data["group_id"] = "g"
        selected = rows(data)
        self.assertEqual(set(selected), {"a", "t", "s"})
        self.assertEqual((selected["a"]["target"], selected["a"]["planned_minutes"]), (1.5, 60))

    def test_members_without_norm_and_weekend_membership_are_in_group_report(self):
        data = fixture()
        data["group_id"] = "g"
        data["norms"] = data["norms"][:1]
        data["versions"].append(Row(group_id="g", effective_from=MONDAY + timedelta(days=5), auditor_id="old", tech_id="t"))
        values = rows(data)
        self.assertEqual(set(values), {"a", "t", "old"})
        self.assertTrue(all(row["target"] == 0 and row["norm_percent"] is None for row in values.values()))

    def test_power_uses_only_weekday_work_window_but_reports_all_booking_minutes(self):
        data = fixture()
        data["windows"] = [window(start=600, end=660)]
        data["plans"] = [plan("morning", start=570, duration=60),
                         plan("evening", start=1050, duration=90),
                         plan("night", start=1200, duration=60),
                         plan("weekend", day=MONDAY + timedelta(days=5), duration=120)]
        data["participants"] = [Row(plan_id=p.id, user_id="a") for p in data["plans"]]
        data["plans"].append(data["plans"][0])
        value = rows(data)["a"]
        self.assertEqual(value["planned_meetings"], 4)
        self.assertEqual(value["planned_minutes"], 330)
        self.assertEqual(value["planned_work_minutes"], 60)
        self.assertEqual(value["outside_work_minutes"], 270)
        self.assertEqual(value["power_percent"], 100)

    def test_power_denominator_respects_partial_busy_absence_and_completed_facts(self):
        data = fixture()
        data["windows"] = [window(end=660), window(start=630, end=660, available=False),
                           window(day=MONDAY + timedelta(days=1))]
        data["absences"] = [Row(user_id="a", start_date=MONDAY + timedelta(days=1),
                                end_date=MONDAY + timedelta(days=1), status="active")]
        data["plans"] = [plan(duration=60), plan("absent", day=MONDAY + timedelta(days=1), duration=30)]
        data["participants"] = [Row(plan_id=p.id, user_id="a") for p in data["plans"]]
        data["facts"] = [Row(plan_id="p", outcome="completed", duration=120)]
        value = rows(data)["a"]
        self.assertEqual(value["partial_days"], 1)
        self.assertEqual(value["absence_days"], 1)
        self.assertEqual(value["free_minutes"], 30)
        self.assertEqual(value["planned_work_minutes"], 90)
        self.assertEqual(value["power_percent"], 300)
        self.assertEqual(value["target"], 1.5)
        data["windows"] = []
        value = rows(data)["a"]
        self.assertEqual(value["planned_meetings"], 2)
        self.assertIsNone(value["power_percent"])

    def test_no_norm_does_not_prevent_free_time_power(self):
        data = fixture()
        data["norms"] = data["norms"][:1]
        data["windows"] = [window()]
        data["plans"] = [plan(duration=120)]
        data["participants"] = [Row(plan_id="p", user_id="a")]
        value = rows(data)["a"]
        self.assertEqual(value["power_percent"], 25)
        self.assertIsNone(value["norm_percent"])

    def test_outside_only_bookings_have_zero_power_only_with_known_free_time(self):
        data = fixture()
        data["windows"] = [window()]
        data["plans"] = [plan("before", start=540, duration=60),
                         plan("after", start=1080, duration=60),
                         plan("weekend", day=MONDAY + timedelta(days=6), duration=30)]
        data["participants"] = [Row(plan_id=p.id, user_id="a") for p in data["plans"]]
        value = rows(data)["a"]
        self.assertEqual(value["planned_meetings"], 3)
        self.assertEqual(value["outside_work_minutes"], 150)
        self.assertEqual(value["planned_work_minutes"], 0)
        self.assertEqual(value["power_percent"], 0)
        data["windows"] = []
        self.assertIsNone(rows(data)["a"]["power_percent"])

    def test_selected_period_and_scoped_members_are_not_expanded_by_plan_links(self):
        data = fixture()
        data["plans"] = [plan("before", day=MONDAY - timedelta(days=1)),
                         plan("after", day=MONDAY + timedelta(days=7)),
                         plan("foreign", group="not-in-scope"), plan()]
        data["participants"] = [Row(plan_id=p.id, user_id="a") for p in data["plans"]]
        data["participants"].append(Row(plan_id="p", user_id="not-in-scope"))
        data["windows"] = [window(uid="not-in-scope")]
        values = rows(data)
        self.assertNotIn("not-in-scope", values)
        self.assertEqual(values["a"]["planned_meetings"], 1)
        self.assertEqual(values["a"]["planned_minutes"], 60)

    def test_baseline_weekdays_and_absence_never_reduce_target(self):
        data = fixture()
        data["start"] = MONDAY - timedelta(days=7)
        data["absences"] = [Row(user_id="a", start_date=data["start"], end_date=data["end"], status="active")]
        values = rows(data)
        self.assertEqual(values["a"]["target"], 1.5)
        self.assertEqual(values["a"]["absence_days"], 10)
        self.assertEqual(values["a"]["filled_days"], 0)
        self.assertEqual(values["a"]["unfilled_days"], 0)

    def test_date_limits_inclusive_and_inputs_unchanged(self):
        data = fixture()
        before = deepcopy(data)
        workload_report(**data)
        self.assertEqual(data, before)
        for first, last in [(MONDAY, MONDAY - timedelta(days=1)),
                            (MONDAY, MONDAY + timedelta(days=366)),
                            (date(1999, 12, 31), MONDAY), (datetime(2026, 9, 14), MONDAY)]:
            with self.subTest(first=first, last=last), self.assertRaises(ValueError):
                workload_report(**{**data, "start": first, "end": last})
        self.assertEqual(workload_report(**{**data, "start": date(2100, 12, 31), "end": date(2100, 12, 31)})["working_days"], 1)
        result = workload_report(**{**data, "end": MONDAY + timedelta(days=365)})
        self.assertEqual(result["working_days"], 262)


if __name__ == "__main__":
    unittest.main()
