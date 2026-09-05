"""Regression tests for persisted sidebar migrations."""

import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from pydantic import ValidationError

from app.api.deps import get_current_user
from app.api.routes.auth import (
    _clean_sidebar_menu_order,
    _user_to_read,
    import_sidebar_menu_preview,
    router,
)
from app.models.user import League, UserRole
from app.schemas.user import SidebarMenuImportRequest
from app.services.sidebar_menu import (
    CUSTOMIZABLE_SIDEBAR_ITEM_IDS,
    accessible_sidebar_item_ids,
    project_sidebar_menu_import,
)


def import_request(*, groups, item_labels=None, items=None, layout_version=8):
    return SidebarMenuImportRequest.model_validate(
        {
            "format": "dpms-sidebar-menu",
            "version": 1,
            "layout": {
                "version": layout_version,
                "groups": groups,
                "items": items or {},
                "item_labels": item_labels or {},
            },
        }
    )


def user_for(
    *,
    role=UserRole.executor,
    task_workspace_enabled=False,
    feedback_enabled=False,
    audit_enabled=False,
    competency_development_enabled=False,
    competency_constructor_enabled=False,
):
    return SimpleNamespace(
        role=role,
        task_workspace_enabled=task_workspace_enabled,
        feedback_enabled=feedback_enabled,
        audit_enabled=audit_enabled,
        competency_development_enabled=competency_development_enabled,
        competency_constructor_enabled=competency_constructor_enabled,
    )


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


class SidebarMenuImportPreviewTests(unittest.TestCase):
    def test_route_is_authenticated_post_and_preview_does_not_persist(self):
        route = next(
            route
            for route in router.routes
            if route.path == "/me/sidebar-menu/import-preview"
        )
        self.assertIn("POST", route.methods)
        self.assertIn(get_current_user, [dependency.call for dependency in route.dependant.dependencies])

        user = user_for()
        user.sidebar_menu_order = {"sentinel": "unchanged"}
        request = import_request(
            groups=[{"id": "main", "label": "Основное", "item_ids": ["messages"]}]
        )

        preview = import_sidebar_menu_preview(request, user=user)

        self.assertEqual(preview.imported_count, 1)
        self.assertEqual(user.sidebar_menu_order, {"sentinel": "unchanged"})

    def test_admin_with_feedback_can_import_every_customizable_item(self):
        admin = user_for(role=UserRole.admin, feedback_enabled=True)
        item_ids = sorted(CUSTOMIZABLE_SIDEBAR_ITEM_IDS)
        request = import_request(
            groups=[{"id": "all", "label": "Все разделы", "item_ids": item_ids}],
        )

        preview = project_sidebar_menu_import(request.layout, admin)

        self.assertEqual(accessible_sidebar_item_ids(admin), CUSTOMIZABLE_SIDEBAR_ITEM_IDS)
        self.assertEqual(preview.sidebar_menu_order.groups[0].item_ids, item_ids)
        self.assertEqual(preview.imported_count, len(item_ids))
        self.assertEqual(preview.required_added_count, 0)
        self.assertEqual(preview.skipped_unknown_count, 0)
        self.assertEqual(preview.skipped_inaccessible_count, 0)

    def test_limited_user_skips_unknown_inaccessible_and_duplicate_items(self):
        limited_user = user_for(audit_enabled=True)
        request = import_request(
            groups=[
                {
                    "id": "first",
                    "label": "Первый блок",
                    "item_ids": [
                        "quick-notes",
                        "my-tasks",
                        "missing-feature",
                        "quick-notes",
                    ],
                },
                {
                    "id": "second",
                    "label": "Второй блок",
                    "item_ids": ["audit", "dashboard"],
                },
            ],
        )

        preview = project_sidebar_menu_import(request.layout, limited_user)

        self.assertEqual(
            preview.sidebar_menu_order.groups[0].item_ids,
            ["quick-notes", "messages"],
        )
        self.assertEqual(preview.sidebar_menu_order.groups[1].item_ids, ["audit"])
        self.assertEqual(preview.referenced_item_count, 6)
        self.assertEqual(preview.imported_count, 2)
        self.assertEqual(preview.skipped_unknown_count, 1)
        self.assertEqual(preview.skipped_inaccessible_count, 2)
        self.assertEqual(preview.skipped_duplicate_count, 1)
        self.assertEqual(preview.required_added_count, 1)

    def test_preserves_group_order_labels_and_accessible_item_labels(self):
        request = import_request(
            groups=[
                {"id": "notes", "label": "  Мои материалы  ", "item_ids": ["quick-notes"]},
                {"id": "people", "label": "Коллеги", "item_ids": ["contacts", "messages"]},
            ],
            item_labels={
                "quick-notes": "  Блокнот  ",
                "contacts": "Люди",
                "dashboard": "Недоступная подпись",
                "unknown": "Неизвестная подпись",
            },
        )

        preview = project_sidebar_menu_import(request.layout, user_for())

        self.assertEqual(
            [group.id for group in preview.sidebar_menu_order.groups],
            ["notes", "people"],
        )
        self.assertEqual(
            [group.label for group in preview.sidebar_menu_order.groups],
            ["Мои материалы", "Коллеги"],
        )
        self.assertEqual(
            preview.sidebar_menu_order.item_labels,
            {"quick-notes": "Блокнот", "contacts": "Люди"},
        )
        self.assertEqual(
            preview.sidebar_menu_order.items,
            {"notes": ["quick-notes"], "people": ["contacts", "messages"]},
        )

    def test_legacy_items_map_is_used_when_group_has_no_item_ids(self):
        request = import_request(
            groups=[{"id": "custom", "label": "Работа"}],
            items={"custom": ["contacts", "messages"]},
        )

        preview = project_sidebar_menu_import(request.layout, user_for())

        self.assertEqual(
            preview.sidebar_menu_order.groups[0].item_ids,
            ["contacts", "messages"],
        )

    def test_zero_accessible_references_leave_only_required_messages(self):
        request = import_request(
            groups=[
                {
                    "id": "closed",
                    "label": "Закрытые разделы",
                    "item_ids": ["dashboard", "unknown"],
                }
            ]
        )

        preview = project_sidebar_menu_import(request.layout, user_for())

        self.assertEqual(preview.sidebar_menu_order.groups[0].item_ids, ["messages"])
        self.assertEqual(preview.imported_count, 0)
        self.assertEqual(preview.skipped_inaccessible_count, 1)
        self.assertEqual(preview.skipped_unknown_count, 1)
        self.assertEqual(preview.required_added_count, 1)

    def test_empty_group_receives_required_item_backfill(self):
        request = import_request(
            groups=[{"id": "empty", "label": "Пустая кнопка", "item_ids": []}]
        )

        preview = project_sidebar_menu_import(request.layout, user_for())

        self.assertEqual(preview.sidebar_menu_order.groups[0].item_ids, ["messages"])
        self.assertEqual(preview.imported_count, 0)
        self.assertEqual(preview.required_added_count, 1)

    def test_malformed_envelope_and_oversize_layout_are_rejected(self):
        with self.assertRaises(ValidationError):
            SidebarMenuImportRequest.model_validate(
                {"format": "other", "version": 1, "layout": {}}
            )

        with self.assertRaises(ValidationError):
            import_request(
                groups=[
                    {"id": f"group-{index}", "label": "Группа", "item_ids": []}
                    for index in range(33)
                ]
            )

        with self.assertRaises(ValidationError):
            import_request(
                groups=[
                    {"id": "same", "label": "Первая", "item_ids": ["messages"]},
                    {"id": "same", "label": "Вторая", "item_ids": ["contacts"]},
                ]
            )

    def test_accepts_frontend_export_metadata_and_rejects_version_mismatch(self):
        payload = {
            "format": "dpms-sidebar-menu",
            "version": 1,
            "menu_schema_version": 8,
            "exported_at": "2026-09-03T10:15:00.000Z",
            "layout": {
                "version": 8,
                "groups": [
                    {"id": "main", "label": "Основное", "item_ids": ["messages"]}
                ],
                "items": {"main": ["messages"]},
                "item_labels": {},
            },
        }

        request = SidebarMenuImportRequest.model_validate(payload)
        self.assertEqual(request.menu_schema_version, 8)

        payload["menu_schema_version"] = 7
        with self.assertRaises(ValidationError):
            SidebarMenuImportRequest.model_validate(payload)


if __name__ == "__main__":
    unittest.main()
