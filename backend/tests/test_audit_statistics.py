"""Contract tests for the audit statistics aggregation."""

from datetime import date, datetime, timezone
import unittest
from uuid import uuid4

from app.main import app
from app.services.audit_statistics import (
    AuditStatisticsAtomRecord,
    AuditStatisticsCaseRecord,
    AuditStatisticsStateEvent,
    build_audit_statistics,
)


def utc(day: int) -> datetime:
    return datetime(2026, 8, day, 9, 0, tzinfo=timezone.utc)


class AuditStatisticsContractTests(unittest.TestCase):
    def test_openapi_exposes_statistics_period(self):
        operation = app.openapi()["paths"]["/api/audit/statistics"]["get"]

        self.assertEqual(operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"], "#/components/schemas/AuditStatisticsRead")
        days = next(parameter for parameter in operation["parameters"] if parameter["name"] == "days")
        self.assertEqual(days["schema"]["minimum"], 7)
        self.assertEqual(days["schema"]["maximum"], 366)

    def test_builds_pipeline_metrics_and_daily_verification_trend(self):
        case_atomizing = AuditStatisticsCaseRecord(uuid4(), "atomization", "atomization")
        case_fixing = AuditStatisticsCaseRecord(uuid4(), "atomization", "fixing")
        case_ready = AuditStatisticsCaseRecord(uuid4(), "ready", "ready")
        case_unassigned = AuditStatisticsCaseRecord(uuid4(), "draft", "unassigned")
        case_archived = AuditStatisticsCaseRecord(uuid4(), "archived", "ready")

        atom_transitioned = AuditStatisticsAtomRecord(
            uuid4(), case_atomizing.id, "ready", "present", None, utc(19)
        )
        atom_draft = AuditStatisticsAtomRecord(
            uuid4(), case_atomizing.id, "draft", None, None, utc(20)
        )
        atom_needs_work = AuditStatisticsAtomRecord(
            uuid4(), case_fixing.id, "ready", "not_present", "not_confirmed", utc(18)
        )
        atom_final_one = AuditStatisticsAtomRecord(
            uuid4(), case_ready.id, "ready", "present", "confirmed", utc(22)
        )
        atom_final_two = AuditStatisticsAtomRecord(
            uuid4(), case_ready.id, "ready", "not_applicable", "not_applicable", utc(22)
        )
        atom_excluded = AuditStatisticsAtomRecord(
            uuid4(), case_archived.id, "excluded", None, None, utc(19)
        )
        events = [
            AuditStatisticsStateEvent(
                atom_transitioned.id,
                utc(21),
                "draft",
                "ready",
            ),
            AuditStatisticsStateEvent(
                atom_excluded.id,
                utc(23),
                "ready",
                "excluded",
            ),
        ]

        result = build_audit_statistics(
            [case_atomizing, case_fixing, case_ready, case_unassigned, case_archived],
            [
                atom_transitioned,
                atom_draft,
                atom_needs_work,
                atom_final_one,
                atom_final_two,
                atom_excluded,
            ],
            events,
            period_start=date(2026, 8, 20),
            period_end=date(2026, 8, 24),
        )

        self.assertEqual(
            result["contracts"],
            {
                "total": 5,
                "in_progress": 2,
                "alpha_review_completed": 2,
                "alpha_commission_completed": 2,
                "beta_commission_completed": 1,
            },
        )
        self.assertEqual(
            result["atoms"],
            {
                "total": 5,
                "excluded": 1,
                "verified": 4,
                "alpha_review_completed": 4,
                "alpha_review_needs_work": 1,
                "alpha_commission_completed": 3,
                "alpha_commission_needs_work": 1,
                "beta_commission_completed": 2,
            },
        )
        self.assertEqual(
            [point["verified_count"] for point in result["trend"]],
            [0, 1, 2, 0, 0],
        )
        self.assertEqual(
            [point["cumulative_verified_count"] for point in result["trend"]],
            [2, 3, 5, 4, 4],
        )


if __name__ == "__main__":
    unittest.main()
