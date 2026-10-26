"""Security and protocol tests for the Synology Audit connector."""

import asyncio
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs
from uuid import uuid4

import httpx

from app.config import settings
from app.services.audit_synology import (
    SynologyConnectorError,
    SynologyFileStationClient,
    SynologySessionStore,
    build_path_token,
    decrypt_synology_password,
    encrypt_synology_password,
    ensure_path_within_root,
    normalize_root_path,
    normalize_synology_base_url,
    remote_path_fingerprint,
    verify_path_token,
)


CONNECTOR_KEY = "test-connector-key-that-is-longer-than-32-characters"


class SynologyConnectorTests(unittest.IsolatedAsyncioTestCase):
    def test_saved_password_is_encrypted_and_round_trips(self):
        connection_id = uuid4()
        with patch.object(settings, "INTEGRATION_SECRET_KEY", CONNECTOR_KEY):
            ciphertext = encrypt_synology_password("correct horse battery staple", connection_id)
            self.assertTrue(ciphertext.startswith("v1:"))
            self.assertNotIn("correct horse", ciphertext)
            self.assertEqual(
                decrypt_synology_password(ciphertext, connection_id),
                "correct horse battery staple",
            )
            with self.assertRaises(SynologyConnectorError):
                decrypt_synology_password(ciphertext, uuid4())

    def test_remote_fingerprint_uses_source_not_profile_id(self):
        with (
            patch.object(settings, "INTEGRATION_SECRET_KEY", CONNECTOR_KEY),
            patch.object(settings, "SYNOLOGY_ALLOWED_ORIGINS", "https://nas.example.test:5001"),
        ):
            first = remote_path_fingerprint("https://nas.example.test:5001", "/Audit/TZ.docx")
            second = remote_path_fingerprint("https://nas.example.test:5001/", "/Audit/TZ.docx")
            self.assertEqual(first, second)

    def test_origin_allowlist_is_exact_and_https_only(self):
        with patch.object(settings, "SYNOLOGY_ALLOWED_ORIGINS", "https://nas.example.test:5001"):
            self.assertEqual(
                normalize_synology_base_url("https://nas.example.test:5001"),
                "https://nas.example.test:5001",
            )
            for value in (
                "http://nas.example.test:5001",
                "https://evil.example.test",
                "https://nas.example.test:5001/webapi",
                "https://user:pass@nas.example.test:5001",
            ):
                with self.subTest(value=value), self.assertRaises(SynologyConnectorError):
                    normalize_synology_base_url(value)

    def test_root_may_be_share_listing_but_cannot_be_escaped(self):
        self.assertEqual(normalize_root_path("/"), "/")
        self.assertEqual(ensure_path_within_root("/Audit/Contracts", "/"), "/Audit/Contracts")
        self.assertEqual(ensure_path_within_root("/Audit/Contracts", "/Audit"), "/Audit/Contracts")
        with self.assertRaises(SynologyConnectorError):
            ensure_path_within_root("/Other", "/Audit")
        with self.assertRaises(SynologyConnectorError):
            ensure_path_within_root("/Audit/../Other", "/Audit")

    def test_path_token_is_bound_to_admin_and_connection(self):
        connection_id = uuid4()
        admin_id = uuid4()
        other_admin_id = uuid4()
        with patch.object(settings, "INTEGRATION_SECRET_KEY", CONNECTOR_KEY):
            token = build_path_token(
                connection_id=connection_id,
                config_version=3,
                user_id=admin_id,
                path="/Audit/TZ.docx",
            )
            self.assertEqual(
                verify_path_token(
                    token,
                    connection_id=connection_id,
                    config_version=3,
                    user_id=admin_id,
                ),
                "/Audit/TZ.docx",
            )
            with self.assertRaises(SynologyConnectorError):
                verify_path_token(
                    token,
                    connection_id=connection_id,
                    config_version=3,
                    user_id=other_admin_id,
                )

    async def test_login_uses_post_body_with_otp_and_logout(self):
        seen: list[tuple[str, dict[str, list[str]]]] = []

        async def handler(request: httpx.Request) -> httpx.Response:
            form = parse_qs(request.content.decode("utf-8"))
            seen.append((str(request.url), form))
            api = form.get("api", [""])[0]
            method = form.get("method", [""])[0]
            if api == "SYNO.API.Info":
                return httpx.Response(200, json={
                    "success": True,
                    "data": {
                        "SYNO.API.Auth": {"path": "auth.cgi", "minVersion": 1, "maxVersion": 6},
                        "SYNO.FileStation.List": {"path": "entry.cgi", "minVersion": 1, "maxVersion": 2},
                        "SYNO.FileStation.Download": {"path": "entry.cgi", "minVersion": 1, "maxVersion": 2},
                    },
                })
            if api == "SYNO.API.Auth" and method == "login":
                self.assertEqual(form.get("passwd"), ["test-password"])
                self.assertEqual(form.get("otp_code"), ["123456"])
                self.assertEqual(form.get("format"), ["sid"])
                self.assertNotIn("session", form)
                return httpx.Response(
                    200,
                    headers={"set-cookie": "id=session-id; Path=/; Secure; HttpOnly"},
                    json={"success": True, "data": {"sid": "session-id", "synotoken": "csrf"}},
                )
            if api == "SYNO.FileStation.List" and method == "list_share":
                self.assertNotIn("_sid", form)
                self.assertEqual(form.get("SynoToken"), ["csrf"])
                self.assertEqual(request.headers.get("x-syno-token"), "csrf")
                self.assertIn("id=session-id", request.headers.get("cookie", ""))
                return httpx.Response(200, json={
                    "success": True,
                    "data": {
                        "offset": 0,
                        "total": 1,
                        "shares": [{"name": "Audit", "path": "/Audit", "isdir": True, "additional": {"time": {"mtime": 1}}}],
                    },
                })
            if api == "SYNO.API.Auth" and method == "logout":
                self.assertNotIn("session", form)
                return httpx.Response(200, json={"success": True})
            return httpx.Response(500, json={"success": False})

        with (
            patch.object(settings, "SYNOLOGY_ALLOWED_ORIGINS", "https://nas.example.test"),
            patch.object(settings, "INTEGRATION_SECRET_KEY", CONNECTOR_KEY),
        ):
            client = SynologyFileStationClient(
                base_url="https://nas.example.test",
                account_name="audit-reader",
                password="test-password",
                root_path="/",
                transport=httpx.MockTransport(handler),
            )
            await client.connect(otp_code="123456")
            self.assertEqual(client._password, "")
            page = await client.list_folder("/")
            self.assertEqual(page.items[0].name, "Audit")
            await client.close()

        self.assertTrue(any(form.get("method") == ["logout"] for _, form in seen))
        for url, _ in seen:
            self.assertNotIn("test-password", url)
            self.assertNotIn("123456", url)

    async def test_login_bridges_returned_sid_to_cookie_when_cookie_is_missing(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            form = parse_qs(request.content.decode("utf-8"))
            api = form.get("api", [""])[0]
            method = form.get("method", [""])[0]
            if api == "SYNO.API.Info":
                return httpx.Response(200, json={
                    "success": True,
                    "data": {
                        "SYNO.API.Auth": {"path": "entry.cgi", "minVersion": 1, "maxVersion": 7},
                        "SYNO.FileStation.List": {"path": "entry.cgi", "minVersion": 1, "maxVersion": 2},
                        "SYNO.FileStation.Download": {"path": "entry.cgi", "minVersion": 1, "maxVersion": 2},
                    },
                })
            if api == "SYNO.API.Auth" and method == "login":
                return httpx.Response(200, json={"success": True, "data": {"sid": "fallback-sid"}})
            if api == "SYNO.FileStation.List" and method == "list_share":
                self.assertNotIn("_sid", form)
                self.assertIn("id=fallback-sid", request.headers.get("cookie", ""))
                return httpx.Response(200, json={
                    "success": True,
                    "data": {"offset": 0, "total": 0, "shares": []},
                })
            if api == "SYNO.API.Auth" and method == "logout":
                self.assertNotIn("_sid", form)
                self.assertIn("id=fallback-sid", request.headers.get("cookie", ""))
                return httpx.Response(200, json={"success": True})
            return httpx.Response(500, json={"success": False})

        with (
            patch.object(settings, "SYNOLOGY_ALLOWED_ORIGINS", "https://nas.example.test"),
            patch.object(settings, "INTEGRATION_SECRET_KEY", CONNECTOR_KEY),
        ):
            client = SynologyFileStationClient(
                base_url="https://nas.example.test",
                account_name="audit-reader",
                password="test-password",
                root_path="/",
                transport=httpx.MockTransport(handler),
            )
            await client.connect()
            page = await client.list_folder("/")
            self.assertEqual(page.total, 0)
            self.assertTrue(client.diagnostic_summary()["id_cookie_bridged"])
            await client.close()

    async def test_invalid_session_cookie_is_removed_before_sid_retry(self):
        list_attempts = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal list_attempts
            form = parse_qs(request.content.decode("utf-8"))
            api = form.get("api", [""])[0]
            method = form.get("method", [""])[0]
            if api == "SYNO.API.Info":
                return httpx.Response(200, json={
                    "success": True,
                    "data": {
                        "SYNO.API.Auth": {"path": "entry.cgi", "minVersion": 1, "maxVersion": 7},
                        "SYNO.FileStation.List": {
                            "path": "entry.cgi",
                            "requestFormat": "JSON",
                            "minVersion": 1,
                            "maxVersion": 2,
                        },
                        "SYNO.FileStation.Download": {
                            "path": "entry.cgi",
                            "requestFormat": "JSON",
                            "minVersion": 1,
                            "maxVersion": 2,
                        },
                    },
                })
            if api == "SYNO.API.Auth" and method == "login":
                return httpx.Response(
                    200,
                    headers=[
                        ("set-cookie", "session-cookie=gateway-session; Path=/; Secure; HttpOnly"),
                        ("set-cookie", "id=portal-cookie; Path=/; Secure; HttpOnly"),
                    ],
                    json={"success": True, "data": {"sid": "valid-sid", "synotoken": "csrf"}},
                )
            if api == "SYNO.FileStation.List" and method == "list_share":
                list_attempts += 1
                if list_attempts == 1:
                    self.assertIn("session-cookie=gateway-session", request.headers.get("cookie", ""))
                    self.assertIn("id=valid-sid", request.headers.get("cookie", ""))
                    self.assertNotIn("id=portal-cookie", request.headers.get("cookie", ""))
                    self.assertNotIn("_sid", form)
                    return httpx.Response(200, json={"success": False, "error": {"code": 119}})
                self.assertIn("session-cookie=gateway-session", request.headers.get("cookie", ""))
                self.assertNotIn("id=", request.headers.get("cookie", ""))
                self.assertEqual(form.get("_sid"), ["valid-sid"])
                self.assertEqual(form.get("SynoToken"), ["csrf"])
                self.assertEqual(request.headers.get("x-syno-token"), "csrf")
                return httpx.Response(200, json={
                    "success": True,
                    "data": {"offset": 0, "total": 0, "shares": []},
                })
            if api == "SYNO.API.Auth" and method == "logout":
                self.assertEqual(form.get("_sid"), ["valid-sid"])
                self.assertIn("session-cookie=gateway-session", request.headers.get("cookie", ""))
                self.assertNotIn("id=", request.headers.get("cookie", ""))
                return httpx.Response(200, json={"success": True})
            return httpx.Response(500, json={"success": False})

        with (
            patch.object(settings, "SYNOLOGY_ALLOWED_ORIGINS", "https://nas.example.test"),
            patch.object(settings, "INTEGRATION_SECRET_KEY", CONNECTOR_KEY),
        ):
            client = SynologyFileStationClient(
                base_url="https://nas.example.test",
                account_name="audit-reader",
                password="test-password",
                root_path="/",
                transport=httpx.MockTransport(handler),
            )
            await client.connect()
            page = await client.list_folder("/")
            self.assertEqual(page.total, 0)
            self.assertEqual(list_attempts, 2)
            diagnostics = client.diagnostic_summary()
            self.assertTrue(diagnostics["gateway_cookie_seen"])
            self.assertTrue(diagnostics["id_cookie_bridged"])
            self.assertEqual(
                diagnostics["session_attempts"],
                ["SYNO.FileStation.List:cookie", "SYNO.FileStation.List:sid"],
            )
            await client.close()

    async def test_synotoken_placeholder_is_not_sent(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            form = parse_qs(request.content.decode("utf-8"))
            api = form.get("api", [""])[0]
            method = form.get("method", [""])[0]
            if api == "SYNO.API.Info":
                return httpx.Response(200, json={
                    "success": True,
                    "data": {
                        "SYNO.API.Auth": {"path": "entry.cgi", "minVersion": 1, "maxVersion": 7},
                        "SYNO.FileStation.List": {"path": "entry.cgi", "minVersion": 1, "maxVersion": 2},
                        "SYNO.FileStation.Download": {"path": "entry.cgi", "minVersion": 1, "maxVersion": 2},
                    },
                })
            if api == "SYNO.API.Auth" and method == "login":
                return httpx.Response(
                    200,
                    headers={"set-cookie": "id=session-id; Path=/; Secure; HttpOnly"},
                    json={"success": True, "data": {"sid": "session-id", "synotoken": "--------"}},
                )
            if api == "SYNO.FileStation.List" and method == "list_share":
                self.assertNotIn("SynoToken", form)
                return httpx.Response(200, json={
                    "success": True,
                    "data": {"offset": 0, "total": 0, "shares": []},
                })
            if api == "SYNO.API.Auth" and method == "logout":
                return httpx.Response(200, json={"success": True})
            return httpx.Response(500, json={"success": False})

        with (
            patch.object(settings, "SYNOLOGY_ALLOWED_ORIGINS", "https://nas.example.test"),
            patch.object(settings, "INTEGRATION_SECRET_KEY", CONNECTOR_KEY),
        ):
            client = SynologyFileStationClient(
                base_url="https://nas.example.test",
                account_name="audit-reader",
                password="test-password",
                root_path="/",
                transport=httpx.MockTransport(handler),
            )
            await client.connect()
            await client.list_folder("/")
            await client.close()

    async def test_memory_session_is_bound_to_admin_and_closes(self):
        class FakeClient:
            def __init__(self):
                self.closed = 0

            async def close(self):
                self.closed += 1

        store = SynologySessionStore()
        client = FakeClient()
        admin_id = uuid4()
        connection_id = uuid4()
        active = await store.create(
            user_id=admin_id,
            connection_id=connection_id,
            config_version=1,
            client=client,
        )
        loaded = await store.get(
            active.token,
            user_id=admin_id,
            connection_id=connection_id,
            config_version=1,
        )
        self.assertIs(loaded, active)
        with self.assertRaises(SynologyConnectorError):
            await store.get(
                active.token,
                user_id=uuid4(),
                connection_id=connection_id,
                config_version=1,
            )
        self.assertTrue(await store.remove(active.token, user_id=admin_id))
        self.assertEqual(client.closed, 1)

    async def test_profile_revocation_closes_all_admin_sessions(self):
        class FakeClient:
            def __init__(self):
                self.closed = 0

            async def close(self):
                self.closed += 1

        store = SynologySessionStore()
        profile_id = uuid4()
        other_profile_id = uuid4()
        first = FakeClient()
        second = FakeClient()
        untouched = FakeClient()
        await store.create(
            user_id=uuid4(), connection_id=profile_id, config_version=1, client=first
        )
        await store.create(
            user_id=uuid4(), connection_id=profile_id, config_version=1, client=second
        )
        await store.create(
            user_id=uuid4(), connection_id=other_profile_id, config_version=1, client=untouched
        )
        self.assertEqual(await store.revoke_profile(profile_id), 2)
        self.assertEqual(first.closed, 1)
        self.assertEqual(second.closed, 1)
        self.assertEqual(untouched.closed, 0)
        await store.close_all()

    async def test_candidate_session_can_be_registered_then_rebound(self):
        class FakeClient:
            def __init__(self):
                self.closed = 0

            async def close(self):
                self.closed += 1

        store = SynologySessionStore()
        admin_id = uuid4()
        profile_id = uuid4()
        existing = await store.create(
            user_id=admin_id,
            connection_id=uuid4(),
            config_version=1,
            client=FakeClient(),
        )
        candidate = await store.create(
            user_id=admin_id,
            connection_id=profile_id,
            config_version=3,
            client=FakeClient(),
            replace_user_sessions=False,
        )
        self.assertIs(
            await store.get(
                existing.token,
                user_id=admin_id,
                connection_id=existing.connection_id,
                config_version=1,
            ),
            existing,
        )
        rebound = await store.rebind(
            candidate.token,
            user_id=admin_id,
            connection_id=profile_id,
            from_config_version=3,
            to_config_version=4,
        )
        self.assertIs(rebound, candidate)
        with self.assertRaises(SynologyConnectorError):
            await store.get(
                candidate.token,
                user_id=admin_id,
                connection_id=profile_id,
                config_version=3,
            )
        self.assertIs(
            await store.get(
                candidate.token,
                user_id=admin_id,
                connection_id=profile_id,
                config_version=4,
            ),
            candidate,
        )
        await store.close_all()

    async def test_idle_session_logs_out_without_another_request(self):
        class FakeClient:
            def __init__(self):
                self.closed = 0

            async def close(self):
                self.closed += 1

        store = SynologySessionStore()
        client = FakeClient()
        with patch("app.services.audit_synology.SYNOLOGY_SESSION_IDLE_TTL_SECONDS", 0.01):
            active = await store.create(
                user_id=uuid4(),
                connection_id=uuid4(),
                config_version=1,
                client=client,
            )
            await asyncio.sleep(0.04)
        self.assertEqual(client.closed, 1)
        self.assertFalse(await store.remove(active.token, user_id=active.user_id))


if __name__ == "__main__":
    unittest.main()
