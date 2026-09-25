"""Isolated SQLite tests; no app imports, configuration, seed or working database."""

from __future__ import annotations

from datetime import datetime, timedelta
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import asyncpg


BACKEND = Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
MIGRATION_PATH = BACKEND / "alembic/versions/099_graphs_hierarchy_knowledge.py"
spec = importlib.util.spec_from_file_location("graphs_hierarchy_knowledge_migration", MIGRATION_PATH)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)

EDITOR_ID = UUID("11df6fa6-731e-4d45-9791-af39825f99b6")
OTHER_ID = UUID("9fdf6fa6-731e-4d45-9791-af39825f99b6")


class GraphsHierarchyKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.engine = sa.create_engine("sqlite:///:memory:")
        self.addCleanup(self.engine.dispose)
        self.bind = self.engine.connect()
        self.addCleanup(self.bind.close)
        self.bind.exec_driver_sql("PRAGMA foreign_keys=ON")
        schema = sa.MetaData()
        users = sa.Table("users", schema, sa.Column("id", sa.Uuid(), primary_key=True))
        # Mirror the KnowledgeArticle contract without importing app.models or settings.
        self.articles = sa.Table(
            "knowledge_articles",
            schema,
            sa.Column("id", sa.Uuid(), primary_key=True),
            sa.Column("slug", sa.String(160), nullable=False, unique=True),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("summary", sa.String(500), nullable=False),
            sa.Column("section", sa.String(80), nullable=False),
            sa.Column("body", sa.Text(), nullable=False),
            sa.Column(
                "status",
                sa.Enum("draft", "published", name="knowledgestatus", create_constraint=True),
                nullable=False,
            ),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("created_by_id", sa.Uuid(), sa.ForeignKey("users.id")),
            sa.Column("updated_by_id", sa.Uuid(), sa.ForeignKey("users.id")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("published_at", sa.DateTime(timezone=True)),
        )
        schema.create_all(self.bind)
        self.bind.execute(users.insert().values(id=EDITOR_ID))
        self.operations = Operations(MigrationContext.configure(self.bind))

    def run_migration(self, name):
        with patch.object(migration, "op", self.operations):
            getattr(migration, name)()

    def rows(self):
        return [dict(row) for row in self.bind.execute(sa.select(self.articles)).mappings()]

    def insert_existing(self, **changes):
        now = datetime(2026, 9, 20, 12, 0)
        values = {
            **migration.ARTICLE,
            "id": OTHER_ID,
            "created_by_id": None,
            "updated_by_id": None,
            "created_at": now,
            "updated_at": now,
            "published_at": now,
            **changes,
        }
        self.bind.execute(self.articles.insert().values(**values))
        return self.rows()[0]

    def test_upgrade_publishes_complete_article_in_general(self):
        self.run_migration("upgrade")
        statement = sa.select(self.articles).where(
            self.articles.c.slug == "graphs-hierarchy-guide",
            self.articles.c.section == "general",
            self.articles.c.status == "published",
        )
        article = dict(self.bind.execute(statement).mappings().one())
        for name, value in migration.ARTICLE.items():
            self.assertEqual(article[name], value, name)
        self.assertIsNone(article["created_by_id"])
        self.assertIsNone(article["updated_by_id"])
        self.assertIsNotNone(article["published_at"])
        self.assertEqual(article["created_at"], article["updated_at"])
        self.assertEqual(article["created_at"], article["published_at"])
        self.assertLessEqual(len(article["slug"]), 160)
        self.assertLessEqual(len(article["title"]), 255)
        self.assertLessEqual(len(article["summary"]), 500)
        self.assertLessEqual(len(article["section"]), 80)
        self.assertGreater(len(article["body"]), 10000)

    def test_upgrade_is_idempotent_without_timestamp_churn(self):
        self.run_migration("upgrade")
        before = self.rows()
        self.run_migration("upgrade")
        self.assertEqual(self.rows(), before)

    def test_foreign_slug_owner_is_never_replaced_or_deleted(self):
        for status in ("draft", "published"):
            with self.subTest(status=status):
                self.bind.execute(self.articles.delete())
                self.insert_existing(
                    title="User-owned article",
                    body="User content",
                    status=status,
                    created_by_id=EDITOR_ID,
                    published_at=None if status == "draft" else datetime(2026, 9, 20),
                )
                before = self.rows()
                self.run_migration("upgrade")
                self.run_migration("downgrade")
                self.assertEqual(self.rows(), before)

    def test_same_content_with_a_different_id_is_not_owned_by_migration(self):
        self.insert_existing()
        before = self.rows()
        self.run_migration("upgrade")
        self.run_migration("downgrade")
        self.assertEqual(self.rows(), before)

    def test_same_id_with_another_slug_is_preserved_without_unique_error(self):
        self.insert_existing(id=migration.ARTICLE["id"], slug="renamed-user-guide")
        before = self.rows()
        self.run_migration("upgrade")
        self.run_migration("downgrade")
        self.assertEqual(self.rows(), before)

    def test_downgrade_only_removes_pristine_release_snapshot(self):
        self.insert_existing(slug="unrelated-guide", body="Unrelated content")
        unrelated = self.rows()
        self.run_migration("upgrade")
        self.assertEqual(len(self.rows()), 2)
        self.run_migration("downgrade")
        self.assertEqual(self.rows(), unrelated)
        self.run_migration("downgrade")
        self.assertEqual(self.rows(), unrelated)

    def test_upgrade_after_downgrade_restores_the_article(self):
        self.run_migration("upgrade")
        self.run_migration("downgrade")
        self.assertEqual(self.rows(), [])
        self.run_migration("upgrade")
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.rows()[0]["body"], migration.ARTICLE["body"])

    def test_each_edit_is_preserved_by_reupgrade_and_downgrade(self):
        self.run_migration("upgrade")
        original = self.rows()[0]
        changes = {
            "id": OTHER_ID,
            "slug": "renamed-hierarchy-guide",
            "title": "Revised title",
            "summary": "Revised summary",
            "section": "tasks",
            "body": migration.ARTICLE["body"] + "\nUser addition",
            "status": "draft",
            "sort_order": 42,
            "created_by_id": EDITOR_ID,
            "updated_by_id": EDITOR_ID,
            "created_at": original["created_at"] - timedelta(days=1),
            "updated_at": original["updated_at"] + timedelta(days=1),
            "published_at": original["published_at"] + timedelta(days=1),
        }
        for field, value in changes.items():
            with self.subTest(field=field):
                self.bind.execute(self.articles.delete())
                self.bind.execute(self.articles.insert().values(**original))
                self.bind.execute(self.articles.update().values(**{field: value}))
                before = self.rows()
                self.run_migration("upgrade")
                self.run_migration("downgrade")
                self.assertEqual(self.rows(), before)
        self.bind.execute(self.articles.update().values(published_at=None))
        before = self.rows()
        self.run_migration("downgrade")
        self.assertEqual(self.rows(), before)

    def test_reverted_api_content_is_retained_by_editor_marker(self):
        self.run_migration("upgrade")
        self.bind.execute(
            self.articles.update().values(body="Temporary edit", updated_by_id=EDITOR_ID)
        )
        self.bind.execute(self.articles.update().values(body=migration.ARTICLE["body"]))
        before = self.rows()
        self.run_migration("upgrade")
        self.run_migration("downgrade")
        self.assertEqual(self.rows(), before)

    def test_runtime_does_not_read_markdown_or_repository_files(self):
        with (
            patch("builtins.open", side_effect=AssertionError("Unexpected runtime file read")),
            patch.object(Path, "read_text", side_effect=AssertionError("Unexpected Markdown read")),
        ):
            self.run_migration("upgrade")
            self.assertEqual(self.rows()[0]["body"], migration.ARTICLE["body"])
            self.run_migration("downgrade")
        self.assertEqual(self.rows(), [])

    def test_postgresql_statement_uses_uuid_enum_and_conflict_do_nothing(self):
        bind = Mock()
        bind.dialect = postgresql.dialect()
        with patch.object(migration.op, "get_bind", return_value=bind):
            migration.upgrade()
        statement = bind.execute.call_args.args[0]
        compiled = str(statement.compile(dialect=postgresql.dialect()))
        self.assertIn("ON CONFLICT DO NOTHING", compiled)
        self.assertNotIn("DO UPDATE", compiled)
        self.assertNotIn("RETURNING", compiled)
        driver_sql = str(statement.compile(dialect=asyncpg.dialect()))
        self.assertIn("::UUID", driver_sql)
        self.assertIn("::knowledgestatus", driver_sql)
        self.assertEqual(statement.compile().params["status"], "published")

    def test_postgresql_downgrade_is_guarded_by_snapshot_and_edit_markers(self):
        bind = Mock()
        with patch.object(migration.op, "get_bind", return_value=bind):
            migration.downgrade()
        statement = bind.execute.call_args.args[0]
        sql = str(statement.compile(dialect=postgresql.dialect()))
        for field in migration.ARTICLE:
            self.assertIn(f"knowledge_articles.{field} =", sql)
        self.assertIn("knowledge_articles.created_by_id IS NULL", sql)
        self.assertIn("knowledge_articles.updated_by_id IS NULL", sql)
        self.assertIn("knowledge_articles.updated_at = knowledge_articles.created_at", sql)
        self.assertIn("knowledge_articles.published_at = knowledge_articles.created_at", sql)

    def test_article_matches_both_reviewable_markdown_copies(self):
        body = (BACKEND / "app/content/graphs_hierarchy.md").read_text(encoding="utf-8")
        self.assertEqual(migration.ARTICLE["body"], body)
        guide = (REPO / "docs/graphs/HIERARCHY-GUIDE.md").read_text(encoding="utf-8")
        introduction, _, _ = guide.partition("\n## Для сопровождения пункта 2.3\n")
        self.assertEqual(introduction, f"# {migration.ARTICLE['title']}\n\n{body}")
        self.assertIn("## Проверочный сценарий", body)
        self.assertIn("Проект>Задача*3#важно", body)
        self.assertIn("1500", body)
        self.assertIn("3000", body)
        self.assertIn("250", body)
        self.assertIn("не ищет его родителя", body)
        self.assertNotIn("```", body)
        self.assertFalse(any(line.startswith("|") for line in body.splitlines()))

    def test_revision_identity_and_parent_are_stable(self):
        self.assertEqual(migration.revision, "099_graphs_hierarchy_knowledge")
        self.assertEqual(migration.down_revision, "098_server_boot_guide")
        self.assertLessEqual(len(migration.revision), 32)
        self.assertIsNone(migration.branch_labels)
        self.assertIsNone(migration.depends_on)
        self.assertEqual(
            [path.name for path in MIGRATION_PATH.parent.glob("099_*.py")],
            [MIGRATION_PATH.name],
        )


if __name__ == "__main__":
    unittest.main()
