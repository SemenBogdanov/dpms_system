"""Dependency-free V5 math/interval tests; no application or database startup."""

from dataclasses import FrozenInstanceError, replace
from datetime import date, datetime, timedelta
from decimal import Decimal, localcontext
from pathlib import Path
import random
import sys
import unittest


# Support both repository-root discovery and the backend's app import convention.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.audit_calendar_math import (
    MAX_DATE,
    MIN_DATE,
    Absence,
    AvailabilityWindow,
    CumulativeTotals,
    MeetingRecord,
    TargetChange,
    TargetSchedule,
    absent_people,
    availability_value,
    count_completed,
    cumulative,
    daily_target,
    date_window,
    day_range,
    paint_availability,
    set_target,
    target_between,
    validate_date,
    weekday_count,
)


D = date.fromisoformat
BASELINE = D("2026-08-28")
TODAY = D("2026-09-11")


def schedule():
    return TargetSchedule(BASELINE, (
        TargetChange(BASELINE, 6),
        TargetChange(BASELINE, 3, "G1"),
        TargetChange(BASELINE, 3, "G2"),
    ))


def fact(record_id, day=BASELINE, **changes):
    return replace(MeetingRecord(record_id, day, "G1"), **changes)


def window(start=600, end=1080, value=True, person="person-a", day=TODAY):
    return AvailabilityWindow(person, day, start, end, value)


def paint(windows, start, end, value, **changes):
    query = dict(person_id="person-a", day=TODAY, start_minute=start, end_minute=end, value=value)
    query.update(changes)
    return paint_availability(windows, **query)


def coverage(windows, start, end, **changes):
    query = dict(person_id="person-a", day=TODAY, start_minute=start, end_minute=end)
    query.update(changes)
    return availability_value(windows, **query)


class CalendarDateTests(unittest.TestCase):
    def test_inclusive_range_and_leap_days(self):
        self.assertEqual(day_range(D("2024-02-28"), D("2024-03-01")), (
            D("2024-02-28"), D("2024-02-29"), D("2024-03-01"),
        ))
        self.assertEqual(len(day_range(D("2024-01-01"), D("2024-12-31"))), 366)
        self.assertEqual(len(day_range(D("2000-02-28"), D("2000-03-01"))), 3)
        self.assertEqual(len(day_range(D("2100-02-28"), D("2100-03-01"))), 2)

    def test_minimum_and_maximum_dates(self):
        for day in (MIN_DATE, MAX_DATE):
            with self.subTest(day=day):
                self.assertEqual(validate_date(day), day)
                self.assertEqual(day_range(day, day), (day,))
        self.assertEqual(date_window(MAX_DATE), (MAX_DATE,))
        self.assertEqual(date_window(D("2100-12-30"), 366), (D("2100-12-30"), MAX_DATE))
        self.assertEqual(date_window(MIN_DATE, 1), (MIN_DATE,))

    def test_range_and_window_validation(self):
        for start, end in ((TODAY, BASELINE), (D("2024-01-01"), D("2025-01-01"))):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                day_range(start, end)
        for days in (0, -1, 367, True, 14.0):
            with self.subTest(days=days), self.assertRaises(ValueError):
                date_window(TODAY, days)
        self.assertEqual(date_window(TODAY, 7)[0], TODAY)
        self.assertEqual(date_window(TODAY, 7)[-1], D("2026-09-17"))

    def test_no_implicit_parsing_or_device_datetime(self):
        for invalid in (D("1999-12-31"), D("2101-01-01"), "2026-09-11",
                        datetime(2026, 9, 11), None, True):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                validate_date(invalid)

    def test_weekdays_match_daily_reference_at_boundaries(self):
        for start in (MIN_DATE, D("2024-02-25"), TODAY, D("2100-12-18")):
            days = date_window(start, 366)
            self.assertEqual(weekday_count(days[0], days[-1]), sum(day.weekday() < 5 for day in days))
        self.assertEqual(weekday_count(D("2026-08-29"), D("2026-08-30")), 0)


class TargetTests(unittest.TestCase):
    def test_v5_initial_norms_and_no_implicit_legacy_or_unknown_quota(self):
        norms = schedule()
        self.assertEqual(daily_target(norms, BASELINE), Decimal(6))
        self.assertEqual(daily_target(norms, D("2026-08-27")), Decimal(0))
        self.assertEqual(daily_target(norms, D("2026-08-29")), Decimal(0))
        self.assertEqual(daily_target(norms, TODAY, group_id="G1"), Decimal("0.3"))
        for group in ("G21", "UNKNOWN"):
            self.assertEqual(daily_target(norms, TODAY, group_id=group), Decimal(0))
        self.assertEqual(target_between(norms, D("2026-08-31"), TODAY), Decimal(60))
        self.assertEqual(target_between(norms, D("2026-08-31"), TODAY, group_id="G1"), Decimal(3))

    def test_six_to_four_preserves_yesterday_and_later_future_norm(self):
        initial = schedule()
        future = set_target(initial, TargetChange(D("2026-09-21"), 8), today=TODAY)
        changed = set_target(future, TargetChange(TODAY, 4), today=TODAY)
        self.assertEqual(daily_target(changed, D("2026-09-10")), Decimal(6))
        self.assertEqual(daily_target(changed, TODAY), Decimal(4))
        self.assertEqual(daily_target(changed, D("2026-09-21")), Decimal(8))
        self.assertEqual(target_between(changed, BASELINE, D("2026-09-10")), Decimal(60))
        self.assertEqual(target_between(changed, BASELINE, TODAY), Decimal(64))
        replaced = set_target(changed, TargetChange(TODAY, 5), today=TODAY)
        self.assertEqual(len(replaced.changes), len(changed.changes))
        self.assertEqual(daily_target(replaced, TODAY), Decimal(5))
        self.assertEqual(len(initial.changes), 3)

    def test_past_edits_rejected_for_team_and_group_as_day_advances(self):
        for group in (None, "G1"):
            changed = set_target(schedule(), TargetChange(TODAY, 4, group), today=TODAY)
            for effective, today in ((D("2026-09-10"), TODAY), (TODAY, D("2026-09-12"))):
                with self.subTest(group=group, effective=effective), self.assertRaises(ValueError):
                    set_target(changed, TargetChange(effective, 2, group), today=today)
        with self.assertRaises(ValueError):
            set_target(schedule(), TargetChange(MIN_DATE, 1), today=MIN_DATE)

    def test_group_changes_independent_fractional_and_zero(self):
        initial = schedule()
        future = set_target(initial, TargetChange(D("2026-09-21"), 9, "G1"), today=TODAY)
        changed = set_target(future, TargetChange(D("2026-09-07"), 4, "G1"), today=D("2026-09-07"))
        self.assertEqual(daily_target(changed, D("2026-09-04"), group_id="G1"), Decimal("0.3"))
        self.assertEqual(target_between(changed, D("2026-08-31"), TODAY, group_id="G1"), Decimal("3.5"))
        self.assertEqual(daily_target(changed, TODAY, group_id="G2"), Decimal("0.3"))
        self.assertEqual(daily_target(changed, TODAY), Decimal(6))
        self.assertEqual(daily_target(changed, D("2026-09-21"), group_id="G1"), Decimal("0.9"))
        for group in (None, "G1"):
            zero = set_target(changed, TargetChange(TODAY, 0, group), today=TODAY)
            self.assertEqual(daily_target(zero, TODAY, group_id=group), Decimal(0))
        self.assertNotEqual(
            sum(daily_target(initial, TODAY, group_id=group) for group in ("G1", "G2")),
            daily_target(initial, TODAY),
        )

    def test_group_target_starts_only_at_explicit_first_version(self):
        norms = TargetSchedule(BASELINE, (TargetChange(BASELINE, 6), TargetChange(TODAY, 3, "G1")))
        self.assertEqual(daily_target(norms, D("2026-09-10"), group_id="G1"), Decimal(0))
        self.assertEqual(daily_target(norms, TODAY, group_id="G1"), Decimal("0.3"))

    def test_retired_group_keeps_historical_quota_after_later_zero_norm(self):
        # Current group eligibility is not an input to historical arithmetic.
        retired = set_target(schedule(), TargetChange(D("2026-09-14"), 0, "G1"), today=TODAY)
        self.assertEqual(target_between(retired, D("2026-08-31"), TODAY, group_id="G1"), Decimal(3))
        self.assertEqual(target_between(retired, D("2026-09-14"), D("2026-09-25"), group_id="G1"), Decimal(0))
        self.assertEqual(target_between(retired, D("2026-08-31"), D("2026-09-25"), group_id="G1"), Decimal(3))

    def test_integer_validation_and_invalid_schedule_shapes(self):
        for value in (-1, 1001, 0.3, float("inf"), float("nan"), "6", True, Decimal(6)):
            with self.subTest(value=value), self.assertRaises(ValueError):
                TargetChange(BASELINE, value)
        for changes in ((), (TargetChange(TODAY, 6),),
                        (TargetChange(BASELINE, 6), TargetChange(BASELINE, 4)),
                        (TargetChange(MIN_DATE, 6),), (object(),)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                TargetSchedule(BASELINE, changes)
        for group in ("", " ", 7):
            with self.subTest(group=group), self.assertRaises(ValueError):
                TargetChange(BASELINE, 3, group)

    def test_schedule_is_immutable_and_copies_input_sequence(self):
        entries = [TargetChange(BASELINE, 6)]
        norms = TargetSchedule(BASELINE, entries)
        entries.clear()
        self.assertEqual(len(norms.changes), 1)
        with self.assertRaises(FrozenInstanceError):
            norms.baseline = TODAY
        with self.assertRaises(FrozenInstanceError):
            norms.changes[0].value = 4

    def test_segment_sums_match_reference_with_weekend_changes(self):
        start = D("2024-02-01")
        days = date_window(start, 90)
        entries = tuple(TargetChange(days[index], index % 7, group)
                        for group in (None, "G1") for index in (0, 2, 10, 20, 32, 63))
        norms = TargetSchedule(start, tuple(reversed(entries)))
        for group in (None, "G1", "MISSING"):
            tenths = 0
            for day in days:
                applicable = [entry for entry in entries if entry.group_id == group and entry.effective_from <= day]
                value = max(applicable, key=lambda entry: entry.effective_from).value if applicable else 0
                tenths += value * (10 if group is None else 1) * (day.weekday() < 5)
            self.assertEqual(target_between(norms, days[0], days[-1], group_id=group), Decimal(tenths) / 10)

    def test_no_rounding_even_with_low_decimal_context(self):
        norms = schedule()
        with localcontext() as context:
            context.prec = 1
            self.assertEqual(target_between(norms, BASELINE, TODAY, group_id="G1"), Decimal("3.3"))
            self.assertEqual(cumulative(norms, (), TODAY, today=D("2026-09-12")).target, Decimal(66))

    def test_target_bounds_and_baseline_are_respected(self):
        norms = TargetSchedule(MIN_DATE, (TargetChange(MIN_DATE, 6),))
        self.assertEqual(daily_target(norms, MIN_DATE), Decimal(0))
        self.assertEqual(daily_target(norms, MAX_DATE), Decimal(6))
        late = TargetSchedule(MAX_DATE, (TargetChange(MAX_DATE, 4),))
        self.assertEqual(daily_target(late, MAX_DATE), Decimal(4))
        self.assertEqual(target_between(schedule(), D("2026-08-01"), D("2026-08-27")), Decimal(0))
        with self.assertRaises(ValueError):
            target_between(norms, MIN_DATE, MAX_DATE)


class CumulativeTests(unittest.TestCase):
    def test_surplus_carries_and_weekend_facts_reduce_deficit(self):
        norms = schedule()
        friday = tuple(fact(f"friday-{i}") for i in range(4))
        first = cumulative(norms, friday, BASELINE, today=TODAY)
        self.assertEqual(first, CumulativeTotals(BASELINE, Decimal(6), 4, Decimal(2), Decimal(2)))
        catchup = friday + tuple(fact(f"weekend-{i}", D("2026-08-29")) for i in range(4))
        weekend = cumulative(norms, catchup, D("2026-08-30"), today=TODAY)
        self.assertEqual((weekend.completed, weekend.balance, weekend.backlog), (8, Decimal(-2), Decimal(0)))
        monday = cumulative(norms, catchup, D("2026-08-31"), today=TODAY)
        self.assertEqual(monday.backlog, Decimal(4))
        completed = catchup + tuple(fact(f"monday-{i}", D("2026-08-31")) for i in range(5))
        self.assertEqual(cumulative(norms, completed, D("2026-08-31"), today=TODAY).balance, Decimal(-1))

    def test_only_unique_completed_facts_count_and_ninety_minutes_is_one(self):
        ninety = fact("one", duration_minutes=90)
        records = [ninety, ninety, fact("cancel", outcome="cancelled"), fact("failed", outcome="failed"),
                   fact("unset", outcome=None), fact("plan", kind="plan"),
                   fact("old", D("2026-08-27")), fact("future", D("2026-09-01")),
                   fact("other", group_id="G2")]
        snapshot = list(records)
        self.assertEqual(count_completed(records, BASELINE, BASELINE), 2)
        group = cumulative(schedule(), records, BASELINE, today=TODAY, group_id="G1")
        self.assertEqual((group.target, group.completed, group.balance, group.backlog),
                         (Decimal("0.3"), 1, Decimal("-0.7"), Decimal(0)))
        self.assertEqual(records, snapshot)

    def test_conflicting_duplicate_identity_rejected_in_either_order(self):
        original = fact("one")
        for conflicting in (replace(original, outcome="cancelled"), replace(original, group_id="G2"),
                            replace(original, day=TODAY), replace(original, duration_minutes=90)):
            for records in ((original, conflicting), (conflicting, original)):
                with self.subTest(records=records), self.assertRaises(ValueError):
                    count_completed(records, BASELINE, BASELINE, group_id="G1")

    def test_distinct_identities_are_not_fuzzy_deduplicated(self):
        self.assertEqual(count_completed([fact("one"), fact("two")], BASELINE, BASELINE), 2)

    def test_today_and_future_neither_accrue_debt_nor_reduce_closed_day_debt(self):
        records = [fact("closed", D("2026-09-10")), fact("today", TODAY), fact("future", D("2026-09-12"))]
        result = cumulative(schedule(), records, MAX_DATE, today=TODAY)
        self.assertEqual(result.through, D("2026-09-10"))
        self.assertEqual((result.target, result.completed, result.backlog), (Decimal(60), 1, Decimal(59)))
        earlier = cumulative(schedule(), records, BASELINE, today=TODAY)
        self.assertEqual((earlier.target, earlier.completed), (Decimal(6), 0))
        next_day = cumulative(schedule(), records, MAX_DATE, today=D("2026-09-12"))
        self.assertEqual((next_day.target, next_day.completed), (Decimal(66), 2))

    def test_before_baseline_and_minimum_date_have_no_closed_days(self):
        for norms, end, today in (
            (schedule(), MAX_DATE, BASELINE),
            (schedule(), D("2026-08-27"), TODAY),
            (TargetSchedule(MIN_DATE, (TargetChange(MIN_DATE, 6),)), MAX_DATE, MIN_DATE),
        ):
            self.assertEqual(cumulative(norms, (), end, today=today),
                             CumulativeTotals(None, Decimal(0), 0, Decimal(0), Decimal(0)))

    def test_history_longer_than_selected_period_and_max_boundary(self):
        norms = TargetSchedule(MIN_DATE, (TargetChange(MIN_DATE, 6),))
        result = cumulative(norms, [fact("last-day", MAX_DATE)], MAX_DATE, today=MAX_DATE)
        self.assertEqual(result.through, D("2100-12-30"))
        span = (result.through - MIN_DATE).days + 1
        weekdays = sum((MIN_DATE + timedelta(days=i)).weekday() < 5 for i in range(span))
        self.assertEqual(result.target, Decimal(weekdays * 6))
        self.assertEqual(result.completed, 0)

    def test_fact_input_validation_and_required_today(self):
        for changes in ({"record_id": ""}, {"day": D("2101-01-01")}, {"kind": "unknown"},
                        {"outcome": "unknown"}, {"duration_minutes": 0}, {"duration_minutes": 45},
                        {"duration_minutes": True}, {"duration_minutes": 1470}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                replace(fact("one"), **changes)
        with self.assertRaises(ValueError):
            count_completed([object()], BASELINE, BASELINE)
        with self.assertRaises(ValueError):
            count_completed((fact("same") for _ in range(100_001)), BASELINE, BASELINE)
        with self.assertRaises(TypeError):
            cumulative(schedule(), (), TODAY)
        with self.assertRaises(ValueError):
            cumulative(schedule(), (), TODAY, today=datetime(2026, 9, 11))


class AvailabilityTests(unittest.TestCase):
    def test_partial_paint_splits_both_residuals_and_preserves_other_records(self):
        other_person = window(person="person-b")
        other_day = window(day=D("2026-09-12"))
        original = [window(), other_person, other_day]
        snapshot = list(original)
        changed = paint(original, 720, 780, False)
        self.assertEqual(changed, (window(600, 720), window(780, 1080), other_person, other_day, window(720, 780, False)))
        self.assertIs(changed[2], other_person)
        self.assertEqual(original, snapshot)
        self.assertIs(coverage(changed, 600, 720), True)
        self.assertIs(coverage(changed, 720, 780), False)
        self.assertIs(coverage(changed, 780, 1080), True)

    def test_clear_preserves_residuals_and_produces_unknown_gap(self):
        changed = paint([window()], 720, 780, None)
        self.assertEqual(changed, (window(600, 720), window(780, 1080)))
        self.assertIsNone(coverage(changed, 720, 780))
        self.assertIsNone(coverage(changed, 600, 1080))

    def test_full_day_free_busy_clear_include_outside_matrix_hours(self):
        original = [window(0, 60, False), window(), window(1380, 1440, False), window(person="person-b")]
        for value in (True, False, None):
            with self.subTest(value=value):
                changed = paint(original, 0, 1440, value)
                self.assertIn(original[-1], changed)
                self.assertIs(coverage(changed, 0, 1440), value)
                self.assertIs(coverage(changed, 0, 30), value)
                self.assertIs(coverage(changed, 1410, 1440), value)

    def test_coverage_merges_free_windows_but_busy_has_precedence(self):
        free = [window(660, 780), window(600, 690), window(630, 660)]
        self.assertIs(coverage(free, 600, 780), True)
        self.assertIsNone(coverage([window(600, 660), window(690, 780)], 600, 780))
        self.assertIsNone(coverage([], 600, 630))
        for windows in (free + [window(720, 750, False)], [window(720, 750, False)] + free):
            self.assertIs(coverage(windows, 600, 780), False)
        self.assertIs(coverage([window(600, 630, False)], 600, 780), False)

    def test_touching_endpoints_are_not_overlaps(self):
        windows = [window(570, 600, False), window(600, 630), window(630, 660, False)]
        self.assertIs(coverage(windows, 600, 630), True)
        self.assertEqual(paint(windows, 600, 630, None), (windows[0], windows[2]))

    def test_paint_overrides_imported_overlaps_only_inside_new_interval(self):
        original = [window(0, 1440), window(600, 900, False)]
        changed = paint(original, 660, 720, True)
        self.assertIs(coverage(changed, 660, 720), True)
        self.assertIs(coverage(changed, 600, 660), False)
        self.assertIs(coverage(changed, 720, 900), False)
        self.assertIs(coverage(changed, 0, 600), True)
        cleared = paint(original, 660, 720, None)
        self.assertIsNone(coverage(cleared, 660, 720))

    def test_absence_endpoints_override_free_without_changing_targets(self):
        norms = schedule()
        before = target_between(norms, BASELINE, TODAY)
        absences = tuple(Absence(f"person-{i}", TODAY, D("2026-09-15")) for i in range(5))
        for day in (TODAY, D("2026-09-15")):
            self.assertEqual(len(absent_people(absences + absences, day)), 5)
            self.assertIs(coverage([window(0, 1440, person="person-0", day=day)], 0, 1440,
                                   person_id="person-0", day=day, absences=absences), False)
        for day in (D("2026-09-10"), D("2026-09-16")):
            self.assertEqual(absent_people(absences, day), frozenset())
        self.assertIs(coverage([window(0, 1440)], 0, 1440, absences=absences), True)
        self.assertEqual(target_between(norms, BASELINE, TODAY), before)
        self.assertEqual(daily_target(norms, TODAY), Decimal(6))
        self.assertEqual(daily_target(norms, TODAY, group_id="G1"), Decimal("0.3"))

    def test_interval_dates_are_bounded_before_mutation_including_max_day(self):
        original = [window()]
        for day in (D("1999-12-31"), D("2101-01-01"), datetime(2026, 9, 11)):
            with self.subTest(day=day), self.assertRaises(ValueError):
                paint(original, 0, 1440, True, day=day)
            self.assertEqual(original, [window()])
        for day in (MIN_DATE, MAX_DATE):
            changed = paint([], 0, 1440, True, day=day)
            self.assertIs(coverage(changed, 0, 1440, day=day), True)
            self.assertEqual(changed[0].day, day)

    def test_invalid_intervals_and_non_boolean_states_fail(self):
        original = [window()]
        for start, end in ((-30, 60), (0, 1470), (600, 600), (660, 630),
                           (601, 630), (600, 631), (True, 30), (600.0, 630), (1440, 1440)):
            with self.subTest(start=start, end=end):
                for operation in (lambda: paint(original, start, end, True),
                                  lambda: coverage(original, start, end)):
                    with self.assertRaises(ValueError):
                        operation()
        for value in (0, 1, "free", [], 0.0):
            with self.subTest(value=value), self.assertRaises(ValueError):
                paint(original, 600, 630, value)
        for value in (0, 1, None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                window(value=value)
        for operation in (lambda: paint([window(), object()], 600, 630, True),
                          lambda: coverage([object()], 600, 630)):
            with self.assertRaises(ValueError):
                operation()
        self.assertEqual(original, [window()])

    def test_absence_range_validation(self):
        for start, end in ((TODAY, BASELINE), (D("2024-01-01"), D("2025-01-01")),
                           (MIN_DATE, D("2101-01-01"))):
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                Absence("person", start, end)
        self.assertEqual(absent_people([Absence("person", MAX_DATE, MAX_DATE)], MAX_DATE), {"person"})

    def test_repeated_paints_match_independent_half_hour_reference(self):
        rng = random.Random(20260911)
        unrelated = window(0, 1440, person="other")
        windows = (unrelated,)
        expected = [None] * 48
        for _ in range(80):
            first = rng.randrange(48)
            last = rng.randrange(first + 1, 49)
            value = rng.choice((True, False, None))
            windows = paint(windows, first * 30, last * 30, value)
            expected[first:last] = [value] * (last - first)
            self.assertIn(unrelated, windows)
            for slot in range(48):
                self.assertIs(coverage(windows, slot * 30, (slot + 1) * 30), expected[slot])
            self.assertEqual(paint(windows, first * 30, last * 30, value), windows)


if __name__ == "__main__":
    unittest.main()
