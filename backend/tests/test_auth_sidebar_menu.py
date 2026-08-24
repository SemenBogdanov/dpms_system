"""Regression tests for persisted sidebar migrations."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from app.api.routes.auth import _clean_sidebar_menu_order, _user_to_read
from app.models.user import League, UserRole


class SidebarMenuSanitizerTests(unittest.TestCase):
    def test_current_user_response_preserves_audit_access_for_non_admin(self):
        now = datetime.now(timezone.utc)
        user = SimpleNamespace(
            id=uuid4(),
            full_name="Аудитор",
            email="auditor@example.com",
            league=League.C,
            role=UserRole.executor,
            mpw=0,
            wip_limit=2,
            is_new_employee=False,
            task_workspace_enabled=False,
            can_link_queue_tasks_to_projects=False,
            feedback_enabled=False,
            audit_enabled=True,
            competency_development_enabled=False,
            competency_constructor_enabled=False,
            is_active=True,
            wallet_main=0,
            wallet_karma=0,
            password_change_required=False,
            plan_started_at=None,
            onboarding_started_at=None,
            onboarding_until=None,
            sidebar_menu_order=None,
            created_at=now,
            updated_at=now,
        )

        result = _user_to_read(user)

        self.assertTrue(result.audit_enabled)
        self.assertEqual(result.role, UserRole.executor)

    def test_preserves_menu_version_for_future_section_backfills(self):
        cleaned = _clean_sidebar_menu_order(
            {
                "version": 7,
                "groups": [
                    {"id": "tasks", "label": "Задачи", "item_ids": ["personal-tasks"]},
                    {"id": "audit", "label": "Аудит", "item_ids": ["audit"]},
                ],
                "items": {},
                "item_labels": {},
            }
        )

        self.assertIsNotNone(cleaned)
        self.assertEqual(cleaned["version"], 7)
        self.assertEqual(cleaned["groups"][1]["id"], "audit")

    def test_invalid_menu_version_falls_back_to_first_schema(self):
        cleaned = _clean_sidebar_menu_order({"version": "7", "groups": [], "items": {}})

        self.assertIsNotNone(cleaned)
        self.assertEqual(cleaned["version"], 1)


if __name__ == "__main__":
    unittest.main()
