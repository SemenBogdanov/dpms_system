"""Atomic verify-and-save behavior for the AI provider admin route."""

from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
from uuid import uuid4

from fastapi import HTTPException

from app.api.routes.ai_provider import _read, save_ai_provider
from app.config import settings
from app.models.ai_provider import AIProviderConfig, AIProviderEvent
from app.schemas.ai_provider import AIProviderUpsert
from app.services.ai_provider import AIProviderError, encrypt_ai_api_key


INTEGRATION_KEY = "test-integration-key-that-is-longer-than-32-characters"
TEST_ORIGIN = "https://ai.example.test"


class FakeSession:
    def __init__(self, config: AIProviderConfig | None):
        self.config = config
        self.events: list[AIProviderEvent] = []
        self.rollbacks = 0
        self.commits = 0

    async def scalar(self, _statement):
        return self.config

    async def rollback(self):
        self.rollbacks += 1

    async def commit(self):
        self.commits += 1

    def add(self, value):
        if isinstance(value, AIProviderConfig):
            self.config = value
        elif isinstance(value, AIProviderEvent):
            self.events.append(value)

    async def flush(self):
        return None

    async def refresh(self, _value):
        return None


class ExpiringAdmin:
    """Models a dependency ORM object expired by the route transaction rollback."""

    def __init__(self, db: FakeSession):
        self.db = db
        self.expected_id = uuid4()

    @property
    def id(self):
        if self.db.rollbacks:
            raise RuntimeError("admin ORM state expired")
        return self.expected_id


class AIProviderRouteTests(unittest.IsolatedAsyncioTestCase):
    def test_empty_profile_uses_non_secret_defaults(self):
        with (
            patch.object(settings, "AI_PROVIDER_DEFAULT_DISPLAY_NAME", "ROX-1"),
            patch.object(settings, "AI_PROVIDER_DEFAULT_BASE_URL", "https://api.rox.one/v1"),
            patch.object(settings, "AI_PROVIDER_DEFAULT_MODEL_NAME", "cx/gpt-5.6-sol-max"),
        ):
            result = _read(None)

        self.assertFalse(result.configured)
        self.assertEqual(result.display_name, "ROX-1")
        self.assertEqual(result.base_url, "https://api.rox.one/v1")
        self.assertEqual(result.model_name, "cx/gpt-5.6-sol-max")
        self.assertFalse(result.api_key_configured)

    def _config(self) -> AIProviderConfig:
        now = datetime.now(timezone.utc)
        return AIProviderConfig(
            id=uuid4(),
            provider_kind="openai_compatible",
            display_name="Рабочий профиль",
            base_url=f"{TEST_ORIGIN}/v1",
            model_name="working-model",
            api_key_ciphertext=encrypt_ai_api_key("working-key"),
            enabled=True,
            config_version=3,
            last_tested_at=now,
            last_test_status="ok",
            last_verified_config_version=3,
            created_at=now,
            updated_at=now,
        )

    async def test_failed_candidate_does_not_replace_working_profile(self):
        with (
            patch.object(settings, "INTEGRATION_SECRET_KEY", INTEGRATION_KEY),
            patch.object(settings, "AI_PROVIDER_ALLOWED_ORIGINS", TEST_ORIGIN),
        ):
            config = self._config()
            original_ciphertext = config.api_key_ciphertext
            db = FakeSession(config)
            admin = ExpiringAdmin(db)
            body = AIProviderUpsert(
                display_name="Новый профиль",
                base_url=f"{TEST_ORIGIN}/v1",
                model_name="broken-model",
                api_key="broken-key",
                enabled=True,
                expected_config_version=3,
            )
            with patch(
                "app.api.routes.ai_provider.generate_text",
                new=AsyncMock(side_effect=AIProviderError("invalid_credentials", "bad", 502)),
            ):
                with self.assertRaises(HTTPException) as context:
                    await save_ai_provider(body, admin=admin, db=db)

            self.assertEqual(context.exception.status_code, 502)
            self.assertEqual(config.display_name, "Рабочий профиль")
            self.assertEqual(config.model_name, "working-model")
            self.assertEqual(config.api_key_ciphertext, original_ciphertext)
            self.assertEqual(config.config_version, 3)
            self.assertEqual(config.last_test_status, "ok")
            self.assertEqual(config.last_verified_config_version, 3)
            self.assertEqual(db.commits, 1)
            self.assertEqual(db.events[-1].event_type, "candidate_verification")
            self.assertEqual(db.events[-1].actor_id, admin.expected_id)
            self.assertNotIn("broken-key", str(db.events[-1].payload_json))

    async def test_successful_candidate_is_saved_with_ok_status(self):
        with (
            patch.object(settings, "INTEGRATION_SECRET_KEY", INTEGRATION_KEY),
            patch.object(settings, "AI_PROVIDER_ALLOWED_ORIGINS", TEST_ORIGIN),
        ):
            config = self._config()
            original_ciphertext = config.api_key_ciphertext
            db = FakeSession(config)
            admin = ExpiringAdmin(db)
            body = AIProviderUpsert(
                display_name="Проверенный профиль",
                base_url=f"{TEST_ORIGIN}/v1",
                model_name="verified-model",
                enabled=False,
                expected_config_version=3,
            )
            verify = AsyncMock(return_value="OK")
            with patch("app.api.routes.ai_provider.generate_text", new=verify):
                result = await save_ai_provider(body, admin=admin, db=db)

            self.assertTrue(result.configured)
            self.assertEqual(result.last_test_status, "ok")
            self.assertEqual(result.last_verified_config_version, 4)
            self.assertFalse(result.enabled)
            self.assertFalse(result.ready_for_use)
            self.assertEqual(config.display_name, "Проверенный профиль")
            self.assertEqual(config.model_name, "verified-model")
            self.assertEqual(config.api_key_ciphertext, original_ciphertext)
            self.assertEqual(config.config_version, 4)
            self.assertEqual(config.last_test_status, "ok")
            self.assertEqual(config.last_verified_config_version, 4)
            self.assertEqual(db.events[-1].event_type, "config_verified_saved")
            self.assertEqual(db.events[-1].actor_id, admin.expected_id)
            verify.assert_awaited_once()

    async def test_stale_version_is_rejected_before_provider_call(self):
        with (
            patch.object(settings, "INTEGRATION_SECRET_KEY", INTEGRATION_KEY),
            patch.object(settings, "AI_PROVIDER_ALLOWED_ORIGINS", TEST_ORIGIN),
        ):
            db = FakeSession(self._config())
            body = AIProviderUpsert(
                display_name="Устаревшая форма",
                base_url=f"{TEST_ORIGIN}/v1",
                model_name="model",
                enabled=True,
                expected_config_version=2,
            )
            verify = AsyncMock(return_value="OK")
            with patch("app.api.routes.ai_provider.generate_text", new=verify):
                with self.assertRaises(HTTPException) as context:
                    await save_ai_provider(body, admin=SimpleNamespace(id=uuid4()), db=db)

            self.assertEqual(context.exception.status_code, 409)
            verify.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
