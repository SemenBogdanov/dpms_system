"""Direct-DB Inbox queue consumer; --healthcheck reads only a local heartbeat."""
import argparse
import asyncio
import logging
import math
import os
from pathlib import Path
import time


logger = logging.getLogger("mail_import_queue")


def heartbeat_path():
    return Path(os.environ.get("MAIL_IMPORT_QUEUE_HEARTBEAT", "/tmp/mail-import-queue.heartbeat"))


def poll_seconds():
    value = float(os.environ.get("MAIL_IMPORT_QUEUE_POLL_SECONDS", "1"))
    if not math.isfinite(value) or not 0.5 <= value <= 60:
        raise ValueError("Invalid queue poll interval")
    return value


def healthy(*, now=None):
    try:
        path = heartbeat_path()
        if path.is_symlink() or not path.is_file():
            return False
        age = (time.time() if now is None else now) - path.stat().st_mtime
        return 0 <= age <= max(120, poll_seconds() * 4)
    except (OSError, ValueError):
        return False


async def run_once(session_factory):
    from app.services.mail_import_queue import cleanup, process_next
    async with session_factory() as db, db.begin():
        await cleanup(db)
    async with session_factory() as db, db.begin():
        return await process_next(db)


async def run(session_factory, *, once=False):
    interval = poll_seconds()
    heartbeat_path().unlink(missing_ok=True)
    while True:
        try:
            await run_once(session_factory)
            heartbeat_path().touch(mode=0o600)
            code = 0
        except Exception:
            # Never log SQL exceptions, connection parameters or request contents.
            logger.error("mail_import_queue_tick_failed")
            code = 1
        if once:
            return code
        await asyncio.sleep(interval)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--healthcheck", action="store_true")
    args = parser.parse_args(argv)
    if args.healthcheck:
        return 0 if healthy() else 1
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    try:
        from app.database import AsyncSessionLocal, engine
        engine.echo = False
        engine.sync_engine.hide_parameters = True
        return asyncio.run(run(AsyncSessionLocal, once=args.once))
    except KeyboardInterrupt:
        return 0
    except Exception:
        logger.error("mail_import_queue_worker_failed")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
