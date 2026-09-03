"""Regression tests for personal-storage quota boundaries and payloads."""

import unittest
from types import SimpleNamespace

from pydantic import ValidationError

from app.schemas.storage_quota import (
    StorageQuotaRequestCreate,
    StorageQuotaRequestDecision,
)
from app.services.storage_quota import MIB, quota_state


def account(*, used: int, reserved: int = 0, limit: int = 50 * MIB):
    return SimpleNamespace(
        used_bytes=used,
        reserved_bytes=reserved,
        limit_bytes=limit,
    )


class StorageQuotaStateTests(unittest.TestCase):
    def test_warning_threshold_starts_at_eighty_percent(self):
        below = quota_state(account(used=40 * MIB - 1))
        at_threshold = quota_state(account(used=40 * MIB))

        self.assertEqual(below[2], "normal")
        self.assertEqual(at_threshold[2], "warning")

    def test_critical_threshold_starts_at_ninety_percent(self):
        below = quota_state(account(used=45 * MIB - 1))
        at_threshold = quota_state(account(used=45 * MIB))

        self.assertEqual(below[2], "warning")
        self.assertEqual(at_threshold[2], "critical")

    def test_reserved_bytes_participate_in_hard_stop(self):
        available, percent, level, _ = quota_state(
            account(used=49 * MIB, reserved=MIB)
        )

        self.assertEqual(available, 0)
        self.assertEqual(percent, 100.0)
        self.assertEqual(level, "blocked")

    def test_existing_overage_is_preserved_and_blocked(self):
        available, percent, level, _ = quota_state(account(used=60 * MIB))

        self.assertEqual(available, 0)
        self.assertEqual(percent, 120.0)
        self.assertEqual(level, "blocked")


class StorageQuotaDecisionSchemaTests(unittest.TestCase):
    def test_request_reason_cannot_be_whitespace(self):
        with self.assertRaises(ValidationError):
            StorageQuotaRequestCreate(
                requested_limit_bytes=100 * MIB,
                reason=" " * 10,
            )

    def test_decision_comment_cannot_be_whitespace(self):
        with self.assertRaises(ValidationError):
            StorageQuotaRequestDecision(
                decision="approved",
                comment="   ",
            )

    def test_rejection_cannot_set_approved_limit(self):
        with self.assertRaises(ValidationError):
            StorageQuotaRequestDecision(
                decision="rejected",
                comment="Недостаточно обоснования",
                approved_limit_bytes=100 * MIB,
            )

    def test_approval_may_use_requested_limit(self):
        decision = StorageQuotaRequestDecision(
            decision="approved",
            comment="Согласовано",
        )

        self.assertIsNone(decision.approved_limit_bytes)


if __name__ == "__main__":
    unittest.main()
