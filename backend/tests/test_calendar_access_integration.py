"""Calendar grants remain independent of audit, Q access, and global admin role."""
import unittest
from datetime import datetime, timezone
from uuid import uuid4

from app.models.user import User, UserRole, League
from app.api.routes.auth import _user_to_read
from app.schemas.user import UserCreate, UserUpdate, UserRead
from app.services.sidebar_menu import accessible_sidebar_item_ids, add_calendar_to_granted_menu
from app.services.user_admin_audit import admin_user_snapshot, admin_user_changes


class CalendarAccessIntegrationTests(unittest.TestCase):
    def user(self, role, enabled=False):
        now = datetime.now(timezone.utc)
        return User(
            id=uuid4(), full_name="Calendar test", email="calendar@example.com",
            role=role, league=League.C, mpw=0, wip_limit=2,
            is_active=True, is_new_employee=False, task_workspace_enabled=False,
            can_link_queue_tasks_to_projects=False, feedback_enabled=False,
            audit_enabled=True, audit_calendar_enabled=enabled,
            competency_development_enabled=False, competency_constructor_enabled=False,
            created_at=now, updated_at=now,
            wallet_main=0, wallet_karma=0, quality_score=100,
            password_change_required=False,
        )

    def test_login_and_me_projection_preserves_grant_and_revocation(self):
        for role in UserRole:
            user = self.user(role)
            for enabled in (False, True, False):
                with self.subTest(role=role, enabled=enabled):
                    user.audit_calendar_enabled = enabled
                    payload = _user_to_read(user).model_dump(mode="json")
                    self.assertIs(payload["audit_calendar_enabled"], enabled)
                    self.assertEqual(payload["role"], role.value)

    def test_no_role_bypasses_the_section_grant(self):
        for role in UserRole:
            for enabled in (False, True):
                with self.subTest(role=role, enabled=enabled):
                    user = self.user(role, enabled)
                    self.assertEqual("audit-calendar" in accessible_sidebar_item_ids(user), enabled)
                    self.assertIn("audit", accessible_sidebar_item_ids(user))
                    self.assertIn("messages", accessible_sidebar_item_ids(user))

    def test_calendar_does_not_require_audit_or_q(self):
        user = self.user(UserRole.executor, True)
        user.audit_enabled = False
        allowed = accessible_sidebar_item_ids(user)
        self.assertIn("audit-calendar", allowed)
        self.assertNotIn("audit", allowed)
        self.assertNotIn("queue", allowed)

    def test_new_accounts_and_unrelated_patches_do_not_grant_access(self):
        body = UserCreate(full_name="Calendar test", email="calendar@example.com", password="synthetic-only")
        self.assertFalse(body.audit_calendar_enabled)
        self.assertNotIn("audit_calendar_enabled", UserUpdate(full_name="Changed").model_dump(exclude_unset=True))
        self.assertEqual(UserUpdate(audit_calendar_enabled=False).model_dump(exclude_unset=True), {"audit_calendar_enabled": False})

    def test_grant_is_public_and_admin_history_is_explicit(self):
        user = self.user(UserRole.executor)
        self.assertFalse(UserRead.model_validate(user).audit_calendar_enabled)
        before = admin_user_snapshot(user)
        user.audit_calendar_enabled = True
        fields, old, new = admin_user_changes(before, admin_user_snapshot(user))
        self.assertEqual(fields, ["audit_calendar_enabled"])
        self.assertEqual(old, {"audit_calendar_enabled": False})
        self.assertEqual(new, {"audit_calendar_enabled": True})

    def test_explicit_grant_restores_even_current_menu_without_losing_customizations(self):
        order = {"version": 9, "groups": [{"id": "mine", "label": "Мое", "item_ids": ["messages"]}],
                 "item_labels": {"messages": "Входящие"}}
        updated = add_calendar_to_granted_menu(order)
        self.assertEqual(updated['groups'][0]['item_ids'], ['messages', 'audit-calendar'])
        self.assertEqual(updated['item_labels'], order['item_labels'])
        self.assertEqual(order['groups'][0]['item_ids'], ['messages'])
        self.assertEqual(add_calendar_to_granted_menu(updated), updated)

    def test_legacy_menu_grant_prefers_audit_group_and_keeps_unrelated_items(self):
        order = {"version": 1, "groups": ['tasks', 'audit'],
                 "items": {"tasks": ['messages'], "audit": ['audit']}}
        result = add_calendar_to_granted_menu(order)
        self.assertEqual(result['items']['audit'], ['audit', 'audit-calendar'])
        self.assertEqual(result['items']['tasks'], ['messages'])
        self.assertIsNone(add_calendar_to_granted_menu(None))


if __name__ == "__main__":
    unittest.main()
