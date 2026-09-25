"""Recovery article is immutable, copyable and non-destructive to existing articles."""
import hashlib
import importlib.util
from pathlib import Path
import re
import unittest
from unittest.mock import patch
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
import sqlalchemy as sa


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "boot_guide_migration", ROOT / "backend/alembic/versions/098_server_boot_guide.py",
)
MIGRATION = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MIGRATION)


class BootGuideTests(unittest.TestCase):
    def setUp(self):
        self.engine = sa.create_engine("sqlite:///:memory:")
        metadata = sa.MetaData()
        self.table = sa.Table("knowledge_articles", metadata, *(
            sa.Column(column.name, column.type, primary_key=column.name == "id", unique=column.name == "slug")
            for column in MIGRATION._article_table().columns
        ))
        metadata.create_all(self.engine)

    def tearDown(self):
        self.engine.dispose()

    def publish(self, connection):
        with patch.object(MIGRATION, "op", Operations(MigrationContext.configure(connection))):
            MIGRATION.upgrade()

    def test_revision_and_document_match_frozen_snapshot(self):
        self.assertEqual(MIGRATION.revision, "098_server_boot_guide")
        self.assertEqual(MIGRATION.down_revision, "097_server_boot_events")
        self.assertEqual(
            (ROOT / "docs/stability/BOOT-JOURNAL-GUIDE.md").read_text(),
            MIGRATION.ARTICLE["body"],
        )

    def test_complete_code_and_unit_match_release_byte_for_byte(self):
        for language, filename in (("python", "record_boot.py"), ("ini", "dpms-boot-record.service")):
            blocks = re.findall(r"^```" + language + r"\n(.*?)^```$", MIGRATION.ARTICLE["body"], re.M | re.S)
            self.assertEqual(len(blocks), 1)
            original = (ROOT / "deploy/stability" / filename).read_bytes()
            self.assertEqual(blocks[0].encode(), original)
            self.assertIn(hashlib.sha256(original).hexdigest() + "  " + filename, MIGRATION.ARTICLE["body"])
            if language == "python":
                compile(blocks[0], filename, "exec")

    def test_publish_repeat_preserves_single_complete_article(self):
        with self.engine.begin() as connection:
            self.publish(connection)
            self.publish(connection)
            rows = connection.execute(sa.select(self.table)).mappings().all()
            self.assertEqual(len(rows), 1)
            for name, value in MIGRATION.ARTICLE.items():
                self.assertEqual(rows[0][name], value)
            self.assertIsNotNone(rows[0]["published_at"])

    def test_existing_user_article_slug_is_never_overwritten(self):
        with self.engine.begin() as connection:
            user_article = {**MIGRATION.ARTICLE, "id": uuid4(), "body": "User draft", "status": "draft"}
            connection.execute(self.table.insert().values(**user_article))
            self.publish(connection)
            rows = connection.execute(sa.select(self.table)).mappings().all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["body"], "User draft")
            self.assertEqual(rows[0]["status"], "draft")

    def test_existing_id_with_other_slug_is_never_overwritten(self):
        with self.engine.begin() as connection:
            connection.execute(self.table.insert().values(**{**MIGRATION.ARTICLE, "slug": "user-article"}))
            self.publish(connection)
            self.assertEqual(connection.scalar(sa.select(sa.func.count()).select_from(self.table)), 1)
            self.assertEqual(connection.scalar(sa.select(self.table.c.slug)), "user-article")

    def test_repeat_preserves_manual_edits_and_publication_state(self):
        with self.engine.begin() as connection:
            self.publish(connection)
            connection.execute(self.table.update().values(body="Manual revision", status="draft", updated_by_id=uuid4()))
            self.publish(connection)
            row = connection.execute(sa.select(self.table)).mappings().one()
            self.assertEqual((row["body"], row["status"]), ("Manual revision", "draft"))

    def test_transaction_failure_rolls_back_publication(self):
        with self.assertRaisesRegex(RuntimeError, "interrupted"):
            with self.engine.begin() as connection:
                self.publish(connection)
                raise RuntimeError("interrupted")
        with self.engine.begin() as connection:
            self.assertEqual(connection.scalar(sa.select(sa.func.count()).select_from(self.table)), 0)

    def test_downgrade_does_not_delete_article(self):
        with self.engine.begin() as connection:
            self.publish(connection)
            with self.assertRaisesRegex(RuntimeError, "forward migration"):
                MIGRATION.downgrade()
            self.assertEqual(connection.scalar(sa.select(sa.func.count()).select_from(self.table)), 1)


if __name__ == "__main__":
    unittest.main()
