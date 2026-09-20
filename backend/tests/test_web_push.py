"""Isolated checks for iPhone push privacy and endpoint safety."""
import base64
import asyncio
import contextlib
import json
import os
import tempfile
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import requests
import httpx
from pywebpush import webpush
from sqlalchemy import func, select
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.database import AsyncSessionLocal, engine
from app.models.user import User
from app.models.web_push import WebPushDelivery, WebPushSubscription
from app.services.web_push import enqueue_push, public_key, save_subscription, validate_subscription
from app.workers.web_push import NoRedirectSession, send_one


def encoded(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode()


class WebPushTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private = ec.generate_private_key(ec.SECP256R1())
        cls.raw_private = cls.private.private_numbers().private_value.to_bytes(32, "big")
        cls.browser_public = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
            Encoding.X962, PublicFormat.UncompressedPoint
        )
        cls.endpoint = "https://web.push.apple.com/push/opaque-subscription"

    def test_public_key_is_derived_from_server_private_key(self):
        with patch.dict(os.environ, {"DPMS_WEB_PUSH_PRIVATE_KEY": encoded(self.raw_private)}):
            self.assertEqual(
                public_key(),
                encoded(self.private.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)),
            )

    def test_raw_private_key_signs_a_web_push_request(self):
        with tempfile.TemporaryDirectory() as directory, contextlib.chdir(directory):
            request = webpush(
                subscription_info={"endpoint": self.endpoint, "keys": {
                    "p256dh": encoded(self.browser_public), "auth": encoded(b"0123456789abcdef"),
                }},
                data='{"title":"Новое сообщение"}',
                vapid_private_key=encoded(self.raw_private),
                vapid_claims={"sub": "mailto:push@example.org"},
                curl=True,
            )
        self.assertIsInstance(request, str)

    def test_only_apple_https_endpoints_are_accepted(self):
        key = encoded(self.browser_public)
        auth = encoded(b"0123456789abcdef")
        validate_subscription(self.endpoint, key, auth)
        for endpoint in (
            "http://web.push.apple.com/push/id",
            "https://web.push.apple.com.evil.example/push/id",
            "https://127.0.0.1/push/id",
            "https://web.push.apple.com:8443/push/id",
            "https://user@web.push.apple.com/push/id",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate_subscription(endpoint, key, auth)

    def test_push_body_contains_no_message_or_audit_content(self):
        delivery = SimpleNamespace(kind="direct", path="/messages/" + str(uuid.uuid4()), event_key="post:123")
        subscription = SimpleNamespace(endpoint=self.endpoint, p256dh=encoded(self.browser_public), auth_value=encoded(b"0123456789abcdef"))
        with patch.dict(os.environ, {"DPMS_WEB_PUSH_PRIVATE_KEY": encoded(self.raw_private), "DPMS_WEB_PUSH_SUBJECT": "mailto:push@example.org"}), patch("app.workers.web_push.webpush") as transmit:
            send_one(delivery, subscription)
        payload = json.loads(transmit.call_args.kwargs["data"])
        self.assertEqual(payload["title"], "Новое сообщение")
        self.assertEqual(payload["path"], delivery.path)
        self.assertNotIn("message", payload)
        self.assertNotIn("document", payload)
        self.assertEqual(transmit.call_args.kwargs["timeout"], 12)

    def test_redirects_cannot_reach_another_host(self):
        with patch.object(requests.Session, "request") as request:
            NoRedirectSession().request("POST", self.endpoint)
        self.assertFalse(request.call_args.kwargs["allow_redirects"])

    @unittest.skipUnless(os.getenv("DPMS_PUSH_TEST_DATABASE") == "1", "needs isolated PostgreSQL")
    def test_transactional_outbox_deduplicates_replayed_event(self):
        async def check():
            async with AsyncSessionLocal() as db:
                user_id = (await db.execute(select(User.id).limit(1))).scalar_one()
                endpoint = f"https://web.push.apple.com/push/{uuid.uuid4()}"
                await save_subscription(
                    db, user_id=user_id, endpoint=endpoint,
                    p256dh=encoded(self.browser_public), auth_value=encoded(b"0123456789abcdef"),
                )
                await db.flush()
                event_key = f"attention:{uuid.uuid4()}"
                await enqueue_push(db, user_id=user_id, event_key=event_key, kind="important", path="/messages?tab=important")
                await enqueue_push(db, user_id=user_id, event_key=event_key, kind="important", path="/messages?tab=important")
                subscription = (await db.execute(select(WebPushSubscription).where(WebPushSubscription.endpoint == endpoint))).scalar_one()
                count = (await db.execute(select(func.count(WebPushDelivery.id)).where(
                    WebPushDelivery.subscription_id == subscription.id, WebPushDelivery.event_key == event_key,
                ))).scalar_one()
                self.assertEqual(count, 1)
                await db.rollback()
            await engine.dispose()
        asyncio.run(check())

    @unittest.skipUnless(os.getenv("DPMS_PUSH_TEST_DATABASE") == "1", "needs isolated PostgreSQL")
    def test_subscription_api_is_scoped_to_current_user(self):
        from app.api.deps import get_current_user
        from app.main import app

        async def check():
            async with AsyncSessionLocal() as db:
                user_id = (await db.execute(select(User.id).limit(1))).scalar_one()
            endpoint = f"https://web.push.apple.com/push/{uuid.uuid4()}"
            payload = {"endpoint": endpoint, "keys": {"p256dh": encoded(self.browser_public), "auth": encoded(b"0123456789abcdef")}}
            app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id=user_id)
            try:
                with patch("app.api.routes.web_push.public_key", return_value="AQID"):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                        response = await client.post("/api/web-push/subscriptions", json=payload)
                        self.assertEqual(response.status_code, 201)
                        response = await client.post("/api/web-push/subscriptions", json=payload)
                        self.assertEqual(response.status_code, 201)
                        async with AsyncSessionLocal() as db:
                            count = (await db.execute(select(func.count(WebPushSubscription.id)).where(WebPushSubscription.endpoint == endpoint))).scalar_one()
                            self.assertEqual(count, 1)
                        response = await client.request("DELETE", "/api/web-push/subscriptions", json=payload)
                        self.assertEqual(response.status_code, 200)
            finally:
                app.dependency_overrides.pop(get_current_user, None)
                async with AsyncSessionLocal() as db:
                    subscription = (await db.execute(select(WebPushSubscription).where(WebPushSubscription.endpoint == endpoint))).scalar_one_or_none()
                    if subscription:
                        await db.delete(subscription)
                        await db.commit()
                await engine.dispose()
        asyncio.run(check())


if __name__ == "__main__":
    unittest.main()
