#!/usr/bin/env python3
"""Migrate a fresh local database, run every graph privacy test, then drop it.

    python scripts/smoke_work_entity_note_privacy.py --allow-local-db

Uses the configured local PostgreSQL server, never the application database.
The suite's read-model fixtures remain isolated schemas without foreign keys;
the preceding upgrade-to-head checks the real migration chain separately.
"""
import argparse
import asyncio
import io
from pathlib import Path
import os
import re
import sys
import unittest
from uuid import uuid4

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine


BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
TEMPORARY_DATABASE_RE = re.compile(r"dpms_note_privacy_[0-9a-f]{32}")
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "db"}


async def database_operation(admin_url, database_name, *, drop=False):
    if not TEMPORARY_DATABASE_RE.fullmatch(database_name):
        raise RuntimeError("Unexpected temporary database name")
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT", echo=False)
    try:
        async with engine.connect() as connection:
            if drop:
                await connection.execute(text(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = :name AND pid <> pg_backend_pid()"
                ), {"name": database_name})
                await connection.execute(text(f'DROP DATABASE IF EXISTS "{database_name}"'))
            else:
                await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        await engine.dispose()


async def migrate(database_url):
    engine = create_async_engine(database_url, echo=False)
    try:
        async with engine.connect() as connection:
            def upgrade(sync_connection):
                # An explicit connection keeps Alembic off the application DB.
                config = Config(str(BACKEND / "alembic.ini"))
                config.set_main_option("script_location", str(BACKEND / "alembic"))
                config.attributes["connection"] = sync_connection
                command.upgrade(config, "head")

            await connection.run_sync(upgrade)
    finally:
        await engine.dispose()


def run(*, allow_local_db):
    from app.config import settings

    source_url = make_url(settings.DATABASE_URL)
    if (
        not allow_local_db
        or source_url.get_backend_name() != "postgresql"
        or source_url.host not in LOCAL_HOSTS
        or source_url.query
    ):
        raise RuntimeError("Explicit opt-in and a local PostgreSQL URL without query overrides are required")

    name = f"dpms_note_privacy_{uuid4().hex}"
    admin_url = source_url.set(database="postgres")
    temporary_url = source_url.set(database=name)
    original_database_url, original_schema = settings.DATABASE_URL, settings.DB_SCHEMA
    previous_test_url = os.environ.get("DPMS_NOTE_PRIVACY_TEST_URL")
    created = False
    phase = "create_database"
    try:
        asyncio.run(database_operation(admin_url, name))
        created = True
        print(f"Privacy smoke temporary database: {name}", flush=True)
        settings.DATABASE_URL = temporary_url.render_as_string(hide_password=False)
        settings.DB_SCHEMA = ""
        os.environ["DPMS_NOTE_PRIVACY_TEST_URL"] = settings.DATABASE_URL
        phase = "migrations"
        asyncio.run(migrate(temporary_url))
        print("Privacy smoke migrations: head OK", flush=True)
        phase = "unittest"
        suite = unittest.defaultTestLoader.discover(
            str(BACKEND / "tests"), pattern="test_work_entity_note_privacy.py",
        )
        expected = suite.countTestCases()
        # Connection exceptions can contain operational details; do not print
        # the runner's raw traceback. Test identities are safe diagnostics.
        result = unittest.TextTestRunner(stream=io.StringIO(), verbosity=2).run(suite)
        for test, _ in result.failures:
            print(f"FAIL: {test.id()}")
        for test, _ in result.errors:
            print(f"ERROR: {test.id()}")
        print(
            f"Privacy smoke tests: run={result.testsRun}, failures={len(result.failures)}, "
            f"errors={len(result.errors)}, skipped={len(result.skipped)}",
            flush=True,
        )
        if not expected or result.testsRun != expected or result.skipped or not result.wasSuccessful():
            raise RuntimeError("Privacy suite did not pass completely")
    except BaseException:
        print(f"Privacy smoke failed during: {phase}", file=sys.stderr)
        raise
    finally:
        settings.DATABASE_URL, settings.DB_SCHEMA = original_database_url, original_schema
        if previous_test_url is None:
            os.environ.pop("DPMS_NOTE_PRIVACY_TEST_URL", None)
        else:
            os.environ["DPMS_NOTE_PRIVACY_TEST_URL"] = previous_test_url
        if created:
            asyncio.run(database_operation(admin_url, name, drop=True))
            print(f"Privacy smoke cleanup: dropped {name}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-local-db", action="store_true")
    arguments = parser.parse_args()
    try:
        run(allow_local_db=arguments.allow_local_db)
    except Exception as error:
        print(f"Privacy smoke failed: {type(error).__name__}", file=sys.stderr)
        sys.exit(1)
