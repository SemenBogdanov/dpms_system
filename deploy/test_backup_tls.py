"""Synthetic backup configuration never permits plaintext PostgreSQL transport."""
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("backup_config", Path(__file__).with_name("dpms-backup-db-config.py"))
helper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(helper)


class BackupTLSTests(unittest.TestCase):
    def test_default_and_weak_modes_require_tls(self):
        for suffix in ("", "?sslmode=disable", "?sslmode=allow", "?sslmode=prefer", "?ssl=require"):
            self.assertEqual(self.configure(suffix), "require")

    def test_strong_modes_preserved(self):
        for mode in ("require", "verify-ca", "verify-full"):
            self.assertEqual(self.configure("?sslmode=" + mode), mode)

    def test_unsupported_mode_rejected(self):
        with self.assertRaises(SystemExit):
            self.configure("?sslmode=typo")

    def configure(self, suffix):
        with tempfile.TemporaryDirectory() as directory:
            payload = json.dumps(["DATABASE_URL=postgresql+asyncpg://synthetic:synthetic@db.invalid/fixture" + suffix])
            with patch("sys.argv", ["helper", directory]), patch("sys.stdin", io.StringIO(payload)):
                helper.main()
            path = Path(directory) / "db-connection.json"
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            return json.loads(path.read_text())["sslmode"]


if __name__ == "__main__":
    unittest.main()
