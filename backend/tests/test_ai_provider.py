"""Security and protocol tests for the OpenAI-compatible provider."""

from types import SimpleNamespace
import unittest
from unittest.mock import patch

import httpx

from app.config import settings
from app.services.ai_provider import (
    AIProviderError,
    decrypt_ai_api_key,
    encrypt_ai_api_key,
    generate_text,
    get_ready_ai_provider,
    normalize_ai_base_url,
)


INTEGRATION_KEY = "test-integration-key-that-is-longer-than-32-characters"


class AIProviderTests(unittest.IsolatedAsyncioTestCase):
    def test_api_key_round_trip_is_encrypted(self):
        with patch.object(settings, "INTEGRATION_SECRET_KEY", INTEGRATION_KEY):
            encrypted = encrypt_ai_api_key("provider-secret")
            self.assertNotIn("provider-secret", encrypted)
            self.assertEqual(decrypt_ai_api_key(encrypted), "provider-secret")

    def test_provider_url_requires_https_allowlist(self):
        with patch.object(settings, "AI_PROVIDER_ALLOWED_ORIGINS", "https://ai.example.test"):
            self.assertEqual(normalize_ai_base_url("https://ai.example.test/v1"), "https://ai.example.test/v1")
            for value in (
                "http://ai.example.test/v1",
                "https://other.example.test/v1",
                "https://user:pass@ai.example.test/v1",
                "https://ai.example.test/v1?debug=1",
            ):
                with self.subTest(value=value), self.assertRaises(AIProviderError):
                    normalize_ai_base_url(value)

    async def test_generate_text_uses_server_side_bearer_key(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            self.assertEqual(request.url.path, "/v1/chat/completions")
            self.assertEqual(request.headers.get("authorization"), "Bearer provider-secret")
            self.assertNotIn("provider-secret", str(request.url))
            payload = __import__("json").loads(request.content)
            self.assertEqual(payload["model"], "test-model")
            return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

        with (
            patch.object(settings, "INTEGRATION_SECRET_KEY", INTEGRATION_KEY),
            patch.object(settings, "AI_PROVIDER_ALLOWED_ORIGINS", "https://ai.example.test"),
        ):
            provider = SimpleNamespace(
                enabled=True,
                base_url="https://ai.example.test/v1",
                model_name="test-model",
                api_key_ciphertext=encrypt_ai_api_key("provider-secret"),
                config_version=1,
                last_test_status="ok",
                last_verified_config_version=1,
            )
            result = await generate_text(
                provider,
                [{"role": "user", "content": "test"}],
                transport=httpx.MockTransport(handler),
            )
        self.assertEqual(result, "OK")

    async def test_provider_http_errors_are_actionable_and_redacted(self):
        cases = {
            400: "invalid_provider_request",
            401: "invalid_credentials",
            402: "provider_balance_required",
            403: "provider_access_forbidden",
            404: "model_or_endpoint_not_found",
            429: "rate_limited",
            503: "provider_unavailable",
        }

        with (
            patch.object(settings, "INTEGRATION_SECRET_KEY", INTEGRATION_KEY),
            patch.object(settings, "AI_PROVIDER_ALLOWED_ORIGINS", "https://ai.example.test"),
        ):
            provider = SimpleNamespace(
                enabled=True,
                base_url="https://ai.example.test/v1",
                model_name="test-model",
                api_key_ciphertext=encrypt_ai_api_key("provider-secret"),
                config_version=1,
                last_test_status="ok",
                last_verified_config_version=1,
            )
            for status_code, expected_code in cases.items():
                async def handler(_: httpx.Request, status=status_code) -> httpx.Response:
                    return httpx.Response(status, json={"error": {"message": "remote diagnostic"}})

                with self.subTest(status_code=status_code), self.assertRaises(AIProviderError) as context:
                    await generate_text(
                        provider,
                        [{"role": "user", "content": "test"}],
                        transport=httpx.MockTransport(handler),
                    )
                self.assertEqual(context.exception.code, expected_code)
                self.assertNotIn("remote diagnostic", context.exception.message)

    async def test_rate_limit_preserves_bounded_retry_after(self):
        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(429, headers={"Retry-After": "75"})

        with (
            patch.object(settings, "INTEGRATION_SECRET_KEY", INTEGRATION_KEY),
            patch.object(settings, "AI_PROVIDER_ALLOWED_ORIGINS", "https://ai.example.test"),
        ):
            provider = SimpleNamespace(
                enabled=True,
                base_url="https://ai.example.test/v1",
                model_name="test-model",
                api_key_ciphertext=encrypt_ai_api_key("provider-secret"),
                config_version=1,
                last_test_status="ok",
                last_verified_config_version=1,
            )
            with self.assertRaises(AIProviderError) as context:
                await generate_text(
                    provider,
                    [{"role": "user", "content": "test"}],
                    transport=httpx.MockTransport(handler),
                )

        self.assertEqual(context.exception.code, "rate_limited")
        self.assertEqual(context.exception.retry_after_seconds, 75)

    async def test_redirect_is_blocked(self):
        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(307, headers={"location": "https://other.example.test/v1/chat/completions"})

        with (
            patch.object(settings, "INTEGRATION_SECRET_KEY", INTEGRATION_KEY),
            patch.object(settings, "AI_PROVIDER_ALLOWED_ORIGINS", "https://ai.example.test"),
        ):
            provider = SimpleNamespace(
                enabled=True,
                base_url="https://ai.example.test/v1",
                model_name="test-model",
                api_key_ciphertext=encrypt_ai_api_key("provider-secret"),
                config_version=1,
                last_test_status="ok",
                last_verified_config_version=1,
            )
            with self.assertRaises(AIProviderError) as context:
                await generate_text(
                    provider,
                    [{"role": "user", "content": "test"}],
                    transport=httpx.MockTransport(handler),
                )
        self.assertEqual(context.exception.code, "redirect_blocked")

    async def test_disabled_provider_can_only_be_used_by_admin_health_check(self):
        async def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json={"choices": [{"message": {"content": "OK"}}]})

        with (
            patch.object(settings, "INTEGRATION_SECRET_KEY", INTEGRATION_KEY),
            patch.object(settings, "AI_PROVIDER_ALLOWED_ORIGINS", "https://ai.example.test"),
        ):
            provider = SimpleNamespace(
                enabled=False,
                base_url="https://ai.example.test/v1",
                model_name="test-model",
                api_key_ciphertext=encrypt_ai_api_key("provider-secret"),
                config_version=1,
                last_test_status="ok",
                last_verified_config_version=1,
            )
            with self.assertRaises(AIProviderError) as context:
                await generate_text(
                    provider,
                    [{"role": "user", "content": "test"}],
                    transport=httpx.MockTransport(handler),
                )
            self.assertEqual(context.exception.code, "provider_disabled")
            result = await generate_text(
                provider,
                [{"role": "user", "content": "test"}],
                allow_disabled=True,
                allow_unverified=True,
                transport=httpx.MockTransport(handler),
            )
        self.assertEqual(result, "OK")

    async def test_unverified_version_is_rejected_before_network_call(self):
        provider = SimpleNamespace(
            enabled=True,
            base_url="https://ai.example.test/v1",
            model_name="test-model",
            api_key_ciphertext="not-used",
            config_version=2,
            last_test_status="ok",
            last_verified_config_version=1,
        )

        class FakeDb:
            async def scalar(self, _statement):
                return provider

        with self.assertRaises(AIProviderError) as context:
            await get_ready_ai_provider(FakeDb())
        self.assertEqual(context.exception.code, "provider_unverified")
        with self.assertRaises(AIProviderError) as context:
            await generate_text(provider, [{"role": "user", "content": "test"}])
        self.assertEqual(context.exception.code, "provider_unverified")


if __name__ == "__main__":
    unittest.main()
