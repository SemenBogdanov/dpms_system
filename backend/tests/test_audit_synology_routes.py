"""Database-backed concurrency tests for Synology profile mutations."""

import asyncio
import os
import unittest
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, select

from app.api.routes.audit_synology import (
    _verify_and_save_connection,
    activate_synology_connection,
    update_synology_connection,
)
from app.config import settings
from app.database import AsyncSessionLocal, engine
from app.models.audit import AuditSynologyConnection, AuditSynologyEvent
from app.models.user import User, UserRole
from app.schemas.audit_synology import AuditSynologyActivateRequest, AuditSynologySaveRequest
from app.services.audit_synology import synology_session_store


CONNECTOR_KEY = "test-connector-key-that-is-longer-than-32-characters"
TEST_ORIGIN = "https://nas.example.test:5001"


class ImmediateClient:
    def __init__(self, **_):
        self.closed = False

    def diagnostic_summary(self):
        return {}

    async def connect(self, **_):
        return None

    async def list_folder(self, *_args, **_kwargs):
        return None

    async def close(self):
        self.closed = True


class BarrierClient(ImmediateClient):
    barrier: asyncio.Barrier

    async def list_folder(self, *_args, **_kwargs):
        await self.barrier.wait()
        return None


@unittest.skipUnless(os.getenv("DPMS_RUN_DB_TESTS") == "1", "database concurrency tests disabled")
class SynologyRouteConcurrencyTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.mutation_lock_patcher = patch(
            "app.api.routes.audit_synology.synology_profile_mutation_lock",
            asyncio.Lock(),
        )
        self.mutation_lock_patcher.start()
        async with AsyncSessionLocal() as db:
            self.admin_id = (
                await db.execute(select(User.id).where(User.role == UserRole.admin).limit(1))
            ).scalar_one()
        self.profile_id = None
        self.profile_name = f"Synology concurrency {uuid4()}"
        with (
            patch.object(settings, "INTEGRATION_SECRET_KEY", CONNECTOR_KEY),
            patch.object(settings, "SYNOLOGY_ALLOWED_ORIGINS", TEST_ORIGIN),
            patch("app.api.routes.audit_synology.SynologyFileStationClient", ImmediateClient),
        ):
            async with AsyncSessionLocal() as db:
                admin = await db.get(User, self.admin_id)
                result = await _verify_and_save_connection(
                    AuditSynologySaveRequest(
                        display_name=self.profile_name,
                        base_url=TEST_ORIGIN,
                        account_name="auditor",
                        password="test-password",
                        root_path="/",
                    ),
                    admin=admin,
                    db=db,
                    connection=None,
                )
                self.profile_id = result.connection.id

    async def asyncTearDown(self):
        await synology_session_store.close_all()
        if self.profile_id is not None:
            async with AsyncSessionLocal() as db:
                await db.execute(
                    delete(AuditSynologyEvent).where(
                        AuditSynologyEvent.connection_id == self.profile_id
                    )
                )
                await db.execute(
                    delete(AuditSynologyConnection).where(
                        AuditSynologyConnection.id == self.profile_id
                    )
                )
                await db.commit()
        await engine.dispose()
        self.mutation_lock_patcher.stop()

    async def _version(self) -> int:
        async with AsyncSessionLocal() as db:
            return await db.scalar(
                select(AuditSynologyConnection.config_version).where(
                    AuditSynologyConnection.id == self.profile_id
                )
            )

    async def _update(self, version: int, account_name: str):
        async with AsyncSessionLocal() as db:
            admin = await db.get(User, self.admin_id)
            return await update_synology_connection(
                self.profile_id,
                AuditSynologySaveRequest(
                    display_name=self.profile_name,
                    base_url=TEST_ORIGIN,
                    account_name=account_name,
                    root_path="/",
                    expected_config_version=version,
                ),
                admin=admin,
                db=db,
            )

    async def _activate(self, version: int):
        async with AsyncSessionLocal() as db:
            admin = await db.get(User, self.admin_id)
            return await activate_synology_connection(
                self.profile_id,
                AuditSynologyActivateRequest(expected_config_version=version),
                admin=admin,
                db=db,
            )

    @staticmethod
    def _assert_single_winner(results):
        failures = [item for item in results if isinstance(item, Exception)]
        successes = [item for item in results if not isinstance(item, Exception)]
        assert len(successes) == 1
        assert len(failures) == 1
        assert isinstance(failures[0], HTTPException)
        assert failures[0].status_code == 409

    async def test_concurrent_updates_use_compare_and_swap(self):
        version = await self._version()
        BarrierClient.barrier = asyncio.Barrier(2)
        with (
            patch.object(settings, "INTEGRATION_SECRET_KEY", CONNECTOR_KEY),
            patch.object(settings, "SYNOLOGY_ALLOWED_ORIGINS", TEST_ORIGIN),
            patch("app.api.routes.audit_synology.SynologyFileStationClient", BarrierClient),
        ):
            results = await asyncio.gather(
                self._update(version, "auditor-a"),
                self._update(version, "auditor-b"),
                return_exceptions=True,
            )
        self._assert_single_winner(results)
        self.assertEqual(await self._version(), version + 1)

    async def test_update_and_activation_cannot_both_commit_stale_version(self):
        version = await self._version()
        BarrierClient.barrier = asyncio.Barrier(2)
        with (
            patch.object(settings, "INTEGRATION_SECRET_KEY", CONNECTOR_KEY),
            patch.object(settings, "SYNOLOGY_ALLOWED_ORIGINS", TEST_ORIGIN),
            patch("app.api.routes.audit_synology.SynologyFileStationClient", BarrierClient),
        ):
            results = await asyncio.gather(
                self._update(version, "auditor-updated"),
                self._activate(version),
                return_exceptions=True,
            )
        self._assert_single_winner(results)
        self.assertEqual(await self._version(), version + 1)


if __name__ == "__main__":
    unittest.main()
