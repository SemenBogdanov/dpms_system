"""Independent review cases for the approved V5 unknown-availability policy."""
import unittest
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from pydantic import ValidationError
from app.schemas.audit_calendar import AvailabilityPaint, FactRestore, NormSet, PlanSave
from app.services.audit_calendar_domain import availability_issues, attendance_state, meeting_instant
from app.services.audit_calendar_math import AvailabilityWindow, Absence


class CalendarDomainRegressions(unittest.TestCase):
    def setUp(self):
        self.day = date(2026, 9, 14)
        self.person = uuid4()

    def windows(self, *ranges):
        return [AvailabilityWindow(str(self.person), self.day, start, end, free) for start, end, free in ranges]

    def check(self, windows=(), absences=()):
        return availability_issues(self.day, 600, 90, [self.person], windows, absences)

    def test_unknown_warns_but_does_not_block(self):
        errors, warnings = self.check()
        self.assertEqual(errors, [])
        self.assertEqual([i['code'] for i in warnings], ['AVAILABILITY_UNKNOWN'])

    def test_nonoverlapping_busy_with_no_free_still_warns(self):
        errors, warnings = self.check(self.windows((720, 780, False)))
        self.assertFalse(errors)
        self.assertTrue(warnings)

    def test_any_free_window_on_day_requires_complete_coverage(self):
        for ranges in [((720, 780, True),), ((600, 660, True),), ((600, 630, True), (660, 690, True))]:
            errors, warnings = self.check(self.windows(*ranges))
            self.assertEqual([e['code'] for e in errors], ['OUTSIDE_AVAILABILITY'])
            self.assertFalse(warnings)
        self.assertEqual(self.check(self.windows((600, 630, True), (630, 690, True))), ([], []))

    def test_busy_and_absence_override_whole_day_free(self):
        errors, _ = self.check(self.windows((0, 1440, True), (630, 660, False)))
        self.assertEqual(errors[0]['code'], 'UNAVAILABLE')
        errors, _ = self.check(self.windows((0, 1440, True)), [Absence(str(self.person), self.day, self.day)])
        self.assertEqual(errors[0]['code'], 'UNAVAILABLE')

    def test_sixty_minute_rule_has_explicit_boundary(self):
        plan = SimpleNamespace(id=uuid4(), date=self.day, start=600)
        cutoff = meeting_instant(self.day, 600) - timedelta(minutes=60)
        self.assertEqual(attendance_state(plan, [], cutoff - timedelta(seconds=1)), 'waiting')
        self.assertEqual(attendance_state(plan, [], cutoff), 'confirmed')
        early = SimpleNamespace(plan_id=plan.id, reported_at=cutoff)
        late = SimpleNamespace(plan_id=plan.id, reported_at=cutoff + timedelta(seconds=1))
        self.assertEqual(attendance_state(plan, [early], cutoff + timedelta(minutes=1)), 'absence')
        self.assertEqual(attendance_state(plan, [late], cutoff + timedelta(minutes=1)), 'late-absence')

    def test_bad_dates_types_intervals_and_actor_spoof_fail_before_write(self):
        valid = dict(date='2026-09-14', start=600, duration=90, group_id=uuid4(),
                     activity='Synthetic', speaker_id=self.person, status='planned')
        for patch in [dict(date='1900-01-01'), dict(date='2101-01-01'), dict(start=True),
                      dict(start=601), dict(duration=0), dict(start=1410, duration=60),
                      dict(actor_id=str(uuid4()))]:
            with self.subTest(patch=patch), self.assertRaises(ValidationError):
                PlanSave.model_validate({**valid, **patch})
        for value in (True, '6', -1, 0.3):
            with self.assertRaises(ValidationError):
                NormSet(group_id=None, effective_from=self.day, value=value, reason='Test')
        self.assertEqual(PlanSave.model_validate({**valid, 'date':'2100-12-31', 'start':1410, 'duration':30}).start, 1410)

    def test_batch_rejects_entire_invalid_patch_set(self):
        with self.assertRaises(ValidationError):
            AvailabilityPaint(user_id=self.person, patches=[
                dict(date='2026-09-14', start=600, end=630, value=True),
                dict(date='2101-01-01', start=600, end=630, value=False),
            ])

    def test_historical_unknown_is_explicit_and_mutually_exclusive(self):
        payload = dict(source_row_id=uuid4(), date='2026-09-01', start=600,
            duration=90, activity='Synthetic historical', speaker_id=None,
            outcome='completed', reason='Evidence confirmed', evidence='Synthetic row 1',
            composition_unknown=True, participants=[], confirm=True)
        FactRestore(**payload)
        for patch in [dict(composition_unknown=False),
                      dict(participants=[dict(user_id=self.person, role='auditor')]),
                      dict(confirm=False)]:
            with self.assertRaises(ValidationError):
                FactRestore.model_validate({**payload, **patch})


if __name__ == '__main__':
    unittest.main()
