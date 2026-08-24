"""Standalone lease-based worker for the allowlisted canonical audit-tz runtime."""

from __future__ import annotations

import asyncio
import logging
import signal

from app.config import settings
from app.database import AsyncSessionLocal
from app.services.audit_tz_runtime import (
    AuditTZRuntimeError,
    claim_runtime_job,
    fail_claimed_runtime_job,
    process_runtime_job,
    reconcile_orphan_audit_tz_run_files,
    worker_identity,
)


logger = logging.getLogger("dpms.audit_tz_worker")


async def _sleep(stop_event: asyncio.Event) -> None:
    try:
        await asyncio.wait_for(
            stop_event.wait(),
            timeout=max(0.2, settings.AUDIT_TZ_WORKER_POLL_SECONDS),
        )
    except asyncio.TimeoutError:
        pass


async def run() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signal_name in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(signal_name, stop_event.set)
        except NotImplementedError:
            pass

    if not settings.AUDIT_TZ_WORKER_ENABLED:
        logger.info("audit_tz_worker=disabled")
        await stop_event.wait()
        return

    identity = worker_identity()
    next_reconcile_at = 0.0
    logger.info("audit_tz_worker=started")
    while not stop_event.is_set():
        try:
            async with AsyncSessionLocal() as db:
                removed = 0
                if loop.time() >= next_reconcile_at:
                    removed = await reconcile_orphan_audit_tz_run_files(db)
                    next_reconcile_at = loop.time() + 30.0
                job = await claim_runtime_job(db, identity)
                await db.commit()
            if removed:
                logger.info("audit_tz_worker_orphan_runs_removed=%s", removed)
            if job is None:
                await _sleep(stop_event)
                continue
            try:
                await process_runtime_job(job, AsyncSessionLocal)
            except AuditTZRuntimeError as error:
                await fail_claimed_runtime_job(job, AsyncSessionLocal, error_code=error.code)
                logger.error("audit_tz_worker_job=failed error_code=%s", error.code)
            except Exception:
                await fail_claimed_runtime_job(
                    job,
                    AsyncSessionLocal,
                    error_code="runtime_internal_error",
                )
                logger.error("audit_tz_worker_job=failed error_code=runtime_internal_error")
        except Exception:
            logger.error("audit_tz_worker_cycle=failed error_code=worker_cycle_error")
            await _sleep(stop_event)
    logger.info("audit_tz_worker=stopped")


if __name__ == "__main__":
    asyncio.run(run())
