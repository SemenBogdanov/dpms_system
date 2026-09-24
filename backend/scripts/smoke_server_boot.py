"""Exercise boot import on a disposable PostgreSQL schema, never production."""
from __future__ import annotations

import argparse
import asyncio
import configparser
from datetime import datetime, timedelta, timezone
import importlib.util
import io
from pathlib import Path
import tempfile
from uuid import uuid4

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import func, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.models.server_boot import ServerBootEvent
from app.services.server_boot import import_boot_events, list_server_boots
from app.workers.server_boot import healthcheck, run_once


def event_bytes(event_id: str, now: datetime) -> bytes:
    data = configparser.ConfigParser(interpolation=None)
    data["server_boot"] = {
        "format_version": "1", "event_id": event_id,
        "boot_time_utc": (now - timedelta(days=1)).isoformat(),
        "recorded_at_utc": (now - timedelta(days=1, seconds=-5)).isoformat(),
        "uptime_seconds_at_record": "5.000", "reason": "unknown",
        "clock": "system_clock_not_independently_verified",
    }
    output = io.StringIO()
    data.write(output)
    return output.getvalue().encode()


async def smoke() -> None:
    url = make_url(settings.DATABASE_URL)
    if url.host != "db" or url.database != "dpms" or not url.drivername.startswith("postgresql"):
        raise RuntimeError("Only the local Compose db/dpms is allowed")
    schema = "boot_smoke_" + uuid4().hex
    control = create_async_engine(url)
    engine = create_async_engine(url, connect_args={"server_settings": {"search_path": schema}})
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    module_path = Path(__file__).resolve().parents[1] / "alembic/versions/097_server_boot_events.py"
    spec = importlib.util.spec_from_file_location("boot_migration_smoke", module_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    def migrate(connection, direction):
        with Operations.context(MigrationContext.configure(connection)):
            getattr(migration, direction)()

    created = False
    try:
        async with control.begin() as db:
            await db.execute(text(f'CREATE SCHEMA "{schema}"'))
            created = True
        async with engine.begin() as db:
            await db.run_sync(migrate, "upgrade")
            assert (await db.execute(text("SELECT to_regclass('server_boot_events')"))).scalar()
            await db.run_sync(migrate, "downgrade")
            assert (await db.execute(text("SELECT to_regclass('server_boot_events')"))).scalar() is None
            await db.run_sync(migrate, "upgrade")
        now = datetime.now(timezone.utc).replace(microsecond=0)
        source = "postgres-smoke"
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            path = directory / f"boot-{'a' * 32}.txt"
            original = event_bytes("a" * 32, now)
            path.write_bytes(original)
            results = await asyncio.gather(*[
                run_once(sessions, directory=directory, source_id=source, now=now)
                for _ in range(6)
            ])
            assert all(result.state == "ok" for result in results)
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(ServerBootEvent)) == 1
                report = await list_server_boots(db, source_id=source, now=now)
                assert report.total == report.last_7_days_count == 1
                first_imported = report.items[0].imported_at
            assert await healthcheck(sessions, source_id=source, now=now)
            assert not await healthcheck(sessions, source_id=source, now=now + timedelta(seconds=181))

            path.write_bytes(original.replace(b"5.000", b"6.000"))
            conflict = await run_once(sessions, directory=directory, source_id=source, now=now)
            assert conflict.state == "degraded" and conflict.conflicting_files == 1
            async with sessions() as db:
                report = await list_server_boots(db, source_id=source, now=now)
                assert report.items[0].uptime_seconds == 5
                assert report.items[0].imported_at == first_imported
            path.write_bytes(original)

            invalid_path = directory / f"boot-{'b' * 32}.txt"
            invalid_path.write_bytes(b"invalid")
            invalid = await run_once(sessions, directory=directory, source_id=source, now=now)
            assert invalid.invalid_files == 1 and invalid.state == "degraded"
            invalid_path.unlink()
            missing = await run_once(sessions, directory=directory / "missing", source_id=source, now=now)
            assert missing.error_code == "directory_missing"

            second_path = directory / f"boot-{'c' * 32}.txt"
            second_path.write_bytes(event_bytes("c" * 32, now))
            try:
                async with sessions() as db, db.begin():
                    await import_boot_events(db, directory, source, now=now)
                    raise RuntimeError("synthetic transaction interruption")
            except RuntimeError:
                pass
            async with sessions() as db:
                assert await db.scalar(select(func.count()).select_from(ServerBootEvent)) == 1
            recovered = await run_once(sessions, directory=directory, source_id=source, now=now)
            assert recovered.state == "ok"
            async with sessions() as db:
                report = await list_server_boots(db, source_id=source, now=now)
                assert report.total == 2 and report.import_status.state == "ok"
        print("PASS: PostgreSQL migration cycle, concurrent dedup, immutable conflicts, invalid/missing files, rollback/retry, heartbeat")
    finally:
        await engine.dispose()
        if created:
            async with control.begin() as db:
                await db.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await control.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allow-local-db", action="store_true", required=True)
    parser.parse_args()
    asyncio.run(smoke())
