"""Regression tests for persisted sidebar migrations."""

import unittest

from app.api.routes.auth import _clean_sidebar_menu_order


class SidebarMenuSanitizerTests(unittest.TestCase):
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
