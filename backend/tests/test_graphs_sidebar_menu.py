"""The Graphs section remains importable and visible to every active account."""

import unittest
from datetime import datetime, timezone
from uuid import uuid4

from app.models.user import League, User, UserRole
from app.schemas.user import SidebarMenuImportGroup, SidebarMenuImportLayout
from app.services.sidebar_menu import accessible_sidebar_item_ids, project_sidebar_menu_import


class GraphsSidebarMenuTests(unittest.TestCase):
    def user(self, role: UserRole) -> User:
        now = datetime.now(timezone.utc)
        return User(
            id=uuid4(),
            full_name="Graphs test",
            email=f"graphs-{role.value}@example.com",
            role=role,
            league=League.C,
            mpw=0,
            wip_limit=2,
            is_active=True,
            is_new_employee=False,
            task_workspace_enabled=False,
            can_link_queue_tasks_to_projects=False,
            feedback_enabled=False,
            audit_enabled=False,
            audit_calendar_enabled=False,
            competency_development_enabled=False,
            competency_constructor_enabled=False,
            created_at=now,
            updated_at=now,
            wallet_main=0,
            wallet_karma=0,
            quality_score=100,
            password_change_required=False,
        )

    def test_graphs_are_available_without_other_section_grants(self):
        for role in UserRole:
            with self.subTest(role=role):
                allowed = accessible_sidebar_item_ids(self.user(role))
                self.assertIn("graphs", allowed)
                self.assertIn("messages", allowed)

    def test_import_keeps_graphs_for_an_executor(self):
        layout = SidebarMenuImportLayout(
            version=10,
            groups=[
                SidebarMenuImportGroup(
                    id="graphs",
                    label="Графы",
                    item_ids=["graphs", "audit", "messages"],
                )
            ],
        )

        preview = project_sidebar_menu_import(layout, self.user(UserRole.executor))

        self.assertEqual(
            preview.sidebar_menu_order.groups[0].item_ids,
            ["graphs", "messages"],
        )
        self.assertEqual(preview.imported_count, 2)
        self.assertEqual(preview.skipped_inaccessible_count, 1)
        self.assertEqual(preview.skipped_unknown_count, 0)


if __name__ == "__main__":
    unittest.main()
