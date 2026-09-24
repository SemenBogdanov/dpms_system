"""Run python -m app.workers.server_boot [--once | --healthcheck].

Only reads the SERVER_BOOT_EVENTS_DIR mount. No files are deleted or modified.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import math
import os
from pathlib import Path

from app.models.server_boot import ServerBootImportStatus
from app.services.server_boot import (
    DEFAULT_DIRECTORY, import_boot_events, import_status_read, source_id_from_env, utc_now,
)


logger = logging.getLogger("server_boot")
DEFAULT_POLL_SECONDS = 60


def poll_seconds() -> float:
    value = float(os.environ.get("SERVER_BOOT_POLL_SECONDS", str(DEFAULT_POLL_SECONDS)))
    if not math.isfinite(value):
        raise ValueError("Invalid boot import interval")
    return max(10, value)


async def run_once(session_factory, *, directory=None, source_id=None, now=None):
    directory = Path(directory) if directory is not None else Path(
        os.environ.get("SERVER_BOOT_EVENTS_DIR", str(DEFAULT_DIRECTORY))
    )
    source_id = source_id_from_env() if source_id is None else source_id
    async with session_factory() as db, db.begin():
        return await import_boot_events(db, directory, source_id, now=now)


async def healthcheck(session_factory, *, source_id=None, now=None) -> bool:
    source_id = source_id_from_env() if source_id is None else source_id
    async with session_factory() as db:
        row = await db.get(ServerBootImportStatus, source_id)
        status = import_status_read(row, now or utc_now())
        return (
            status.state in {"ok", "degraded"}
            and status.error_code in {None, "invalid_files"}
            and status.conflicting_files == 0
        )


async def run(session_factory, *, once=False) -> int:
    interval = poll_seconds()
    while True:
        try:
            status = await run_once(session_factory)
            logger.info(
                "import state=%s checked=%d invalid=%d conflicting=%d error_code=%s",
                status.state, status.checked_files, status.invalid_files,
                status.conflicting_files, status.error_code,
            )
            code = 0 if status.state == "ok" else 1
        except Exception:
            # Neither SQL/connection errors nor raw files are safe to log.
            logger.error("server_boot_import_failed")
            code = 1
        if once:
            return code
        await asyncio.sleep(interval)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    try:
        from app.database import AsyncSessionLocal

        if args.healthcheck:
            return 0 if asyncio.run(healthcheck(AsyncSessionLocal)) else 1
        return asyncio.run(run(AsyncSessionLocal, once=args.once))
    except KeyboardInterrupt:
        return 0
    except Exception:
        logger.error("server_boot_worker_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
