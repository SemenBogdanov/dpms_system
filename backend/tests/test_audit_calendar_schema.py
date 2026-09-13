"""Synthetic contract/parser checks; no app settings, DB or external network."""
import copy
from datetime import date, datetime, timezone
import importlib.util
from pathlib import Path
import sys
import unittest
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
HAS_PYDANTIC = importlib.util.find_spec("pydantic") is not None
if HAS_PYDANTIC:
    from pydantic import ValidationError
    from app.schemas.audit_calendar import command_adapter, MemberSave, Setup, ImportApply
    from app.services.audit_calendar_source import parse_source, required_people


def source_fixture():
    return {"application": "audit-meeting-constructor", "version": 1,
            "exportedAt": "2026-09-11T12:00:00Z", "source": "synthetic-fixture",
            "data": {"version": 1, "plans": [{"id": "synthetic-plan", "kind": "plan",
                "date": "2026-09-01", "start": 600, "duration": 60, "groupId": "OLD-SYNTH",
                "activity": "SYNTH", "speakerId": "S1", "sourceRow": 2, "origin": "source", "status": "planned"}],
                "facts": [], "availability": [], "notifications": [], "log": [],
                "decision": {"checked": [], "participants": "", "comment": "", "result": "pilot", "recorded": None}}}


@unittest.skipUnless(HAS_PYDANTIC, "Pydantic is not installed")
class CalendarSchemaTests(unittest.TestCase):
    def setUp(self):
        self.uid, self.gid = str(uuid4()), str(uuid4())

    def command(self, operation, payload):
        return command_adapter.validate_python({"request_id": str(uuid4()), "expected_version": 1,
                                                 "operation": operation, "payload": payload})

    def plan(self, **updates):
        return {"date": "2026-09-15", "start": 600, "duration": 60, "group_id": self.gid,
                "activity": "SYNTH", "speaker_id": self.uid, "status": "planned", **updates}

    def test_plan_contract(self):
        value = self.command("plan.save", self.plan())
        self.assertEqual(value.payload.start, 600)

    def test_unknown_command_and_fields_rejected(self):
        for operation, payload in [("fact.delete", {}), ("plan.save", self.plan(actor=self.uid)),
                                   ("plan.save", self.plan(origin="source")), ("plan.save", self.plan(source_id=self.uid))]:
            with self.subTest(operation=operation, payload=payload), self.assertRaises(ValidationError):
                self.command(operation, payload)

    def test_invalid_dates_and_intervals(self):
        for updates in [{"date": "1900-01-01"}, {"date": "2101-01-01"}, {"date": "2026-02-30"},
                        {"date": 1780000000}, {"date": "2026-09-01T00:00:00Z"}, {"start": 610},
                        {"duration": 0}, {"duration": 90.0}, {"start": True}, {"start": 1410, "duration": 60}]:
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                self.command("plan.save", self.plan(**updates))

    def test_supported_max_date_and_ninety_minutes(self):
        self.command("plan.save", self.plan(date="2100-12-31", duration=90))

    def test_scope_version_is_strict(self):
        for version in [-1, True, "1"]:
            with self.assertRaises(ValidationError):
                command_adapter.validate_python({"request_id": str(uuid4()), "expected_version": version,
                                                 "operation": "plan.save", "payload": self.plan()})

    def test_working_revision_is_explicit(self):
        with self.assertRaises(ValidationError):
            self.command("plan.revise", self.plan())
        self.command("plan.revise", self.plan(id=str(uuid4()), reason="Documented revision"))

    def test_fact_restore_snapshot_xor_and_duplicates(self):
        base = {k: v for k, v in self.plan().items() if k not in ("group_id", "status")}
        base.update(source_row_id=str(uuid4()), outcome="completed", reason="Synthetic evidence",
                    evidence="Fixture document", confirm=True, composition_unknown=True, participants=[])
        self.command("fact.restore", base)
        for updates in [{"participants": [{"user_id": self.uid, "role": "auditor"}]},
                        {"composition_unknown": False}, {"confirm": 1},
                        {"composition_unknown": False, "participants": [{"user_id": self.uid, "role": "auditor"}] * 2}]:
            with self.subTest(updates=updates), self.assertRaises(ValidationError):
                self.command("fact.restore", {**base, **updates})

    def test_notice_requires_aware_time(self):
        payload = {"plan_id": str(uuid4()), "user_id": self.uid, "reason": "Fixture", "reported_at": "2026-09-01T10:00:00"}
        with self.assertRaises(ValidationError):
            self.command("notice.record", payload)
        self.command("notice.record", {**payload, "reported_at": "2026-09-01T10:00:00+03:00"})

    def test_bulk_availability_limits_and_strict_values(self):
        patch = {"date": "2026-09-01", "start": 0, "end": 1440, "value": None}
        self.command("availability.paint", {"user_id": self.uid, "patches": [patch]})
        for patches in [[], [{**patch, "value": 1}], [{**patch, "start": 1440}], [patch] * 673,
                        [patch, {**patch, "date": "2026-09-15"}]]:
            with self.assertRaises(ValidationError):
                self.command("availability.paint", {"user_id": self.uid, "patches": patches})

    def test_absence_and_norm_bounds(self):
        for start, end in [("2026-09-02", "2026-09-01"), ("2026-01-01", "2027-01-02")]:
            with self.assertRaises(ValidationError):
                self.command("absence.add", {"user_id": self.uid, "start_date": start, "end_date": end, "reason": "Fixture"})
        self.command("norm.set", {"group_id": None, "effective_from": "2026-09-01", "value": 0, "reason": "Zero norm"})
        for value in [True, -1, 1001, 0.3]:
            with self.assertRaises(ValidationError):
                self.command("norm.set", {"group_id": None, "effective_from": "2026-09-01", "value": value, "reason": "Fixture"})

    def test_membership_does_not_accept_global_helper_or_grant(self):
        with self.assertRaises(ValidationError):
            MemberSave.model_validate({"request_id": str(uuid4()), "expected_version": 1, "user_id": self.uid,
                "code": "S", "role": "speaker", "can_manage": False, "active": True, "audit_calendar_enabled": True})

    def test_old_export_without_planning_is_preserved(self):
        source = source_fixture()
        parsed, digest = parse_source(source)
        self.assertIsNone(parsed.data.planning)
        self.assertNotIn("planning", source["data"])
        self.assertEqual(required_people(parsed), {"S1"})
        self.assertEqual(len(digest), 64)

    def test_canonical_source_hash_and_body_changes(self):
        source = source_fixture()
        self.assertEqual(parse_source(source)[1], parse_source(dict(reversed(list(source.items()))))[1])
        changed = copy.deepcopy(source)
        changed["data"]["plans"][0]["activity"] = "CHANGED"
        self.assertNotEqual(parse_source(source)[1], parse_source(changed)[1])

    def test_source_bad_references_and_unsafe_unknown_fields(self):
        for change in [lambda s: s["data"]["plans"].append(copy.deepcopy(s["data"]["plans"][0])),
                       lambda s: s["data"].update(browserActor={"admin": True}),
                       lambda s: s["data"]["plans"][0].update(date="2101-01-01"),
                       lambda s: s["data"]["plans"][0].update(sourceRow=39),
                       lambda s: s.update(version=True)]:
            source = source_fixture()
            change(source)
            with self.assertRaises(ValueError):
                parse_source(source)

    def test_source_working_revision_needs_own_original(self):
        source = source_fixture()
        source["data"]["plans"][0].update(origin="working-revision", sourceId="some-other-id")
        with self.assertRaises(ValueError):
            parse_source(source)

    def test_source_norms_are_not_last_write_wins(self):
        source = source_fixture()
        source["data"]["planning"] = {"trackingStart": "2026-08-28", "dailyTargets": [
            {"from": "2026-08-28", "value": 6}, {"from": "2026-08-28", "value": 4}], "groupTargets": [], "absences": []}
        with self.assertRaises(ValueError):
            parse_source(source)


if __name__ == "__main__":
    unittest.main()
