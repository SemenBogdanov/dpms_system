"""Portable smoke fixture selection, without app configuration or a database."""

from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from zipfile import ZipFile

from scripts.smoke_audit_multisource import Blocked, CheckFailed, skill_archive_fixture


MAX_BYTES = 2 * 1024 * 1024


class MultisourceSmokeFixtureTests(unittest.TestCase):
    def test_default_is_deterministic_synthetic_without_host_reads(self):
        with patch.object(Path, "open", side_effect=AssertionError("host file read")):
            fixture = skill_archive_fixture(None, MAX_BYTES)
            repeated = skill_archive_fixture(None, MAX_BYTES)
        self.assertEqual(fixture.source, "synthetic")
        self.assertNotEqual(fixture.expected_slug, "audit-tz-atoms")
        self.assertEqual(fixture.data, repeated.data)
        with ZipFile(BytesIO(fixture.data)) as archive:
            self.assertEqual(len(archive.infolist()), fixture.expected_file_count)
            self.assertEqual(fixture.expected_file_count, 6)
            self.assertGreater(sum(item.file_size for item in archive.infolist()), 64 * 1024)
            self.assertLess(sum(item.file_size for item in archive.infolist()), 128 * 1024)
            self.assertTrue(all(Path(name).suffix in {".md", ".txt", ".csv", ".json"}
                                for name in archive.namelist()))

    def test_explicit_missing_archive_never_falls_back(self):
        with TemporaryDirectory() as directory:
            with self.assertRaisesRegex(Blocked, "^supplied_archive_missing$"):
                skill_archive_fixture(str(Path(directory) / "missing.skill"), MAX_BYTES)

    def test_explicit_archive_returns_exact_bytes_with_supplied_label(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "actual.skill"
            data = skill_archive_fixture(None, MAX_BYTES).data
            source.write_bytes(data)
            fixture = skill_archive_fixture(str(source), MAX_BYTES)
        self.assertEqual(fixture.source, "supplied")
        self.assertEqual(fixture.filename, "actual.skill")
        self.assertEqual(fixture.data, data)
        self.assertEqual(fixture.expected_slug, "audit-tz-atoms")

    def test_explicit_invalid_archive_is_not_replaced(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "invalid.skill"
            source.write_bytes(b"not a zip")
            self.assertEqual(skill_archive_fixture(str(source), MAX_BYTES).data, b"not a zip")

    def test_explicit_symlink_and_wrong_suffix_are_rejected(self):
        with TemporaryDirectory() as directory:
            source = Path(directory) / "wrong.txt"
            source.write_bytes(b"synthetic")
            link = Path(directory) / "linked.skill"
            link.symlink_to(source)
            for path in (source, link):
                with self.subTest(path=path.name), self.assertRaisesRegex(
                    CheckFailed, "^supplied_archive_regular_skill_file$"
                ):
                    skill_archive_fixture(str(path), MAX_BYTES)

    def test_size_guards_apply_to_both_modes(self):
        with self.assertRaisesRegex(CheckFailed, "^synthetic_archive_size_bound$"):
            skill_archive_fixture(None, 1)
        with TemporaryDirectory() as directory:
            source = Path(directory) / "oversized.skill"
            source.write_bytes(b"xx")
            with patch.object(Path, "open", side_effect=AssertionError("oversized file read")):
                with self.assertRaisesRegex(CheckFailed, "^supplied_archive_size_bound$"):
                    skill_archive_fixture(str(source), 1)


if __name__ == "__main__":
    unittest.main()
