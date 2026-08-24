"""Contract tests for audit materials, atom controls, and guarded deletion API."""

import unittest

from app.main import app
from app.schemas.audit import AuditCaseDeleteRequest


class AuditCaseControlTests(unittest.TestCase):
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
