"""Contract tests for audit materials, atom controls, and guarded deletion API."""

import unittest

from app.main import app
from app.models.audit import DEFAULT_AUDIT_CONTEXT
from app.schemas.audit import AuditCaseCreate, AuditCaseDeleteRequest


class AuditCaseControlTests(unittest.TestCase):
    def test_new_case_uses_default_audit_context(self):
        payload = AuditCaseCreate(title="Аудит ТЗ", digital_product="OPEC")

        self.assertEqual(payload.notes, DEFAULT_AUDIT_CONTEXT)

    def test_delete_confirmation_is_normalized(self):
        payload = AuditCaseDeleteRequest(
            confirmation_code="  aud-0042 ",
            reason="  ошибочная загрузка  ",
        )

        self.assertEqual(payload.confirmation_code, "AUD-0042")
        self.assertEqual(payload.reason, "ошибочная загрузка")

    def test_openapi_exposes_material_upload_and_guarded_delete(self):
        paths = app.openapi()["paths"]

        self.assertIn("post", paths["/api/audit/cases/{case_id}/documents"])
        self.assertIn("delete", paths["/api/audit/cases/{case_id}"])
        self.assertIn("patch", paths["/api/audit/cases/{case_id}/atoms/bulk-status"])
        self.assertIn("get", paths["/api/audit/cases/{case_id}/atoms/export"])


if __name__ == "__main__":
    unittest.main()
