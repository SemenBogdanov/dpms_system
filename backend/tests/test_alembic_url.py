"""Offline regression checks: no app imports, runtime config, or database access."""
import ast
from configparser import ConfigParser
from pathlib import Path
from types import SimpleNamespace
import unittest


SOURCE = Path(__file__).resolve().parents[1] / "alembic" / "env.py"


class AlembicUrlTests(unittest.TestCase):
    def configured_url(self, url):
        parser = ConfigParser()
        parser.add_section("alembic")
        config = SimpleNamespace(
            set_main_option=lambda name, value: parser.set("alembic", name, value)
        )
        tree = ast.parse(SOURCE.read_text())
        assignments = [
            node for node in tree.body
            if isinstance(node, ast.Expr)
            and isinstance(node.value, ast.Call)
            and isinstance(node.value.func, ast.Attribute)
            and isinstance(node.value.func.value, ast.Name)
            and node.value.func.value.id == "config"
            and node.value.func.attr == "set_main_option"
            and node.value.args
            and isinstance(node.value.args[0], ast.Constant)
            and node.value.args[0].value == "sqlalchemy.url"
        ]
        self.assertEqual(len(assignments), 1)
        code = compile(ast.Module(body=assignments, type_ignores=[]), str(SOURCE), "exec")
        exec(code, {"config": config, "settings": SimpleNamespace(DATABASE_URL=url)})
        return parser.get("alembic", "sqlalchemy.url")

    def test_plain_url_is_unchanged(self):
        url = "postgresql+asyncpg://fixture:fixture@db.invalid/fixture?ssl=require"
        self.assertEqual(self.configured_url(url), url)

    def test_percent_encoded_values_are_unchanged(self):
        url = "postgresql+asyncpg://fixture%40user:fixture%25%2F%3A@db.invalid/db%20name?ssl=require"
        self.assertEqual(self.configured_url(url), url)

    def test_interpolation_looking_values_are_literal(self):
        url = "postgresql+asyncpg://fixture:%(fixture)s%%@db.invalid/fixture"
        self.assertEqual(self.configured_url(url), url)


if __name__ == "__main__":
    unittest.main()
