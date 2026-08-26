"""Security and API contract tests for audit contract reference reveal."""

import unittest
from unittest.mock import patch

from app.main import app
from app.services.audit_contract_reference import (
    AuditContractReferenceError,
    decrypt_contract_reference,
    encrypt_contract_reference,
)


TEST_SECRET = "audit-contract-reference-test-secret-2026"


class AuditContractReferenceCryptoTests(unittest.TestCase):
    @patch(
        "app.services.audit_contract_reference.get_integration_secret",
        return_value=TEST_SECRET,
    )
    def test_reference_round_trip_uses_ciphertext(self, _secret):
        reference = "АЦ-05-04-2024-1803-02-0111"

        ciphertext = encrypt_contract_reference(reference)

        self.assertTrue(ciphertext.startswith("v1:"))
        self.assertNotIn(reference, ciphertext)
        self.assertEqual(decrypt_contract_reference(ciphertext), reference)

    @patch(
        "app.services.audit_contract_reference.get_integration_secret",
        return_value="",
    )
    def test_missing_key_blocks_encryption(self, _secret):
        with self.assertRaises(AuditContractReferenceError) as context:
            encrypt_contract_reference("AUDIT-42")

        self.assertEqual(context.exception.code, "encryption_key_not_configured")

    @patch(
        "app.services.audit_contract_reference.get_integration_secret",
        return_value=TEST_SECRET,
    )
    def test_invalid_ciphertext_is_rejected(self, _secret):
        with self.assertRaises(AuditContractReferenceError) as context:
            decrypt_contract_reference("v1:not-a-valid-token")

        self.assertEqual(context.exception.code, "contract_reference_unavailable")


class AuditContractReferenceOpenAPITests(unittest.TestCase):
    def test_reveal_endpoint_is_post_only(self):
        operations = app.openapi()["paths"][
            "/api/audit/cases/{case_id}/contract-reference/reveal"
        ]

        self.assertIn("post", operations)
        self.assertNotIn("get", operations)


if __name__ == "__main__":
    unittest.main()
