import asyncio
from contextlib import asynccontextmanager
import os
from pathlib import Path
import tempfile
import unittest
import subprocess
import sys

import httpx

from gateway import Settings, create_app
from recovery_state import RecoveryState
from test_gateway import BEARER, HEADERS, MODEL, PAYLOAD, completed, response


class RecoveryStateTests(unittest.IsolatedAsyncioTestCase):
    @asynccontextmanager
    async def client(self, directory, handler, deadline=1):
        app = create_app(Settings(BEARER, MODEL, deadline_seconds=deadline, state_directory=directory),
                         transport=httpx.MockTransport(handler))
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://gateway") as client:
                yield client

    async def test_success_removes_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            async def handler(request):
                self.assertTrue(RecoveryState(directory).pending)
                return completed()
            async with self.client(directory, handler) as client:
                self.assertEqual((await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)).status_code, 200)
            self.assertFalse(RecoveryState(directory).pending)

    async def test_timeout_survives_new_app_and_get_models_does_not_clear(self):
        with tempfile.TemporaryDirectory() as directory:
            calls = []
            async def slow(request):
                calls.append(request.method)
                await asyncio.sleep(0.1)
                return completed()
            async with self.client(directory, slow, 0.02) as client:
                self.assertEqual((await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)).status_code, 504)
            self.assertTrue(RecoveryState(directory).pending)
            async def healthy(request):
                calls.append(request.method)
                return response({"data": [{"id": MODEL}]})
            async with self.client(directory, healthy) as client:
                self.assertEqual((await client.get("/v1/models", headers=HEADERS)).status_code, 200)
                result = await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
                self.assertEqual(result.json()["error"]["code"], "local_model_recovery_required")
            self.assertEqual(calls, ["POST", "GET"])
            self.assertTrue(RecoveryState(directory).pending)

    async def test_failed_connection_is_safe_to_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            async def handler(request):
                raise httpx.ConnectError("synthetic", request=request)
            async with self.client(directory, handler) as client:
                for _ in range(2):
                    self.assertEqual((await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)).status_code, 503)
                    self.assertFalse(RecoveryState(directory).pending)

    async def test_upstream_failure_keeps_marker_across_restart(self):
        for status in (301, 400, 401, 404, 500, 503):
            with tempfile.TemporaryDirectory() as directory:
                calls = []
                async def handler(request):
                    calls.append(request)
                    return response({"error": "synthetic"}, status=status)
                async with self.client(directory, handler) as client:
                    first = await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
                    self.assertIn(first.status_code, (502, 503))
                async with self.client(directory, handler) as client:
                    second = await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
                    self.assertEqual(second.json()["error"]["code"], "local_model_recovery_required")
                self.assertEqual(len(calls), 1)
                self.assertTrue(RecoveryState(directory).pending)

    async def test_complete_rate_limit_refusal_is_retryable(self):
        with tempfile.TemporaryDirectory() as directory:
            async def handler(request):
                return response({"error": "busy"}, status=429)
            async with self.client(directory, handler) as client:
                for _ in range(2):
                    self.assertEqual((await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)).status_code, 429)
                    self.assertFalse(RecoveryState(directory).pending)

    async def test_unconfirmed_200_keeps_marker_across_restart(self):
        cases = [b"{malformed", b"{}", b'{"model":"different","choices":[]}',
                 ('{"model":"' + MODEL + '","choices":[{"message":{"content":"x"},"finish_reason":null}]}').encode(),
                 ('{"model":"' + MODEL + '","choices":[{"message":{"content":""},"finish_reason":"stop"}]}').encode()]
        for body in cases:
            with tempfile.TemporaryDirectory() as directory:
                calls = []
                async def handler(request):
                    calls.append(request)
                    return response(raw=body)
                async with self.client(directory, handler) as client:
                    self.assertEqual((await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)).status_code, 502)
                async with self.client(directory, handler) as client:
                    result = await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
                    self.assertEqual(result.json()["error"]["code"], "local_model_recovery_required")
                self.assertTrue(RecoveryState(directory).pending)
                self.assertEqual(len(calls), 1)

    async def test_incomplete_rate_limit_refusal_keeps_marker(self):
        class Broken(httpx.AsyncByteStream):
            async def __aiter__(self):
                yield b"partial"
                raise httpx.ReadError("synthetic")
        with tempfile.TemporaryDirectory() as directory:
            async def handler(request):
                return httpx.Response(429, stream=Broken())
            async with self.client(directory, handler) as client:
                result = await client.post("/v1/chat/completions", json=PAYLOAD, headers=HEADERS)
                self.assertEqual(result.status_code, 503)
            self.assertTrue(RecoveryState(directory).pending)

    def test_marker_exclusive_and_foreign_marker_cannot_be_cleared(self):
        with tempfile.TemporaryDirectory() as directory:
            first, other = RecoveryState(directory), RecoveryState(directory)
            first.begin()
            with self.assertRaises(FileExistsError):
                other.begin()
            with self.assertRaises(RuntimeError):
                other.finish()
            self.assertTrue(first.pending)
            first.finish()
            self.assertFalse(first.pending)

    def test_private_directory_and_symlink_denied(self):
        with tempfile.TemporaryDirectory() as root:
            directory = Path(root) / "public"
            directory.mkdir(mode=0o755)
            with self.assertRaises(ValueError):
                RecoveryState(str(directory))
            linked = Path(root) / "linked"
            linked.symlink_to(directory, target_is_directory=True)
            with self.assertRaises(ValueError):
                RecoveryState(str(linked))
            private = RecoveryState(str(Path(root) / "private"))
            private.marker.symlink_to(Path(root) / "missing")
            self.assertTrue(private.pending)
            with self.assertRaises(FileExistsError):
                private.begin()

    def test_crash_marker_contains_no_request_data(self):
        with tempfile.TemporaryDirectory() as directory:
            state = RecoveryState(directory)
            state.begin()
            self.assertEqual(state.marker.read_bytes(), b"pending\n")
            self.assertEqual(state.marker.stat().st_mode & 0o777, 0o600)
            self.assertTrue(RecoveryState(directory).pending)

    def test_operator_recovery_archives_marker_without_reading_or_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            state = RecoveryState(directory)
            state.begin()
            state.owned = False

            archived = state.archive_pending()

            self.assertFalse(state.pending)
            self.assertTrue(archived.is_file())
            self.assertEqual(archived.stat().st_mode & 0o777, 0o600)
            self.assertEqual(archived.read_bytes(), b"pending\n")
            with self.assertRaises(FileNotFoundError):
                state.archive_pending()

    def test_operator_recovery_rejects_foreign_marker_shape(self):
        with tempfile.TemporaryDirectory() as directory:
            state = RecoveryState(directory)
            state.marker.write_bytes(b"unexpected")
            state.marker.chmod(0o600)
            with self.assertRaises(ValueError):
                state.archive_pending()

    def test_abrupt_process_exit_keeps_marker(self):
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([
                sys.executable, "-c",
                "import os,sys; from recovery_state import RecoveryState; "
                "RecoveryState(sys.argv[1]).begin(); os._exit(9)", directory,
            ], env={"PYTHONPATH": str(Path(__file__).resolve().parent)}, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 9)
            self.assertTrue(RecoveryState(directory).pending)


if __name__ == "__main__":
    unittest.main()
