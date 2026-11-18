"""DB-login-only C# -> Npgsql VerifyFull -> PostgreSQL -> Python worker.

Default: skipped. Opt in with OUTLOOK_TEST_DOTNET=1. This test ALWAYS creates a
new private /tmp/dpms-outlook-pg.* cluster; input database URLs are ignored. It
never imports app settings, reads .env, touches another cluster or uses real
mail. PostgreSQL 17, OpenSSL, .NET 10 and already cached NuGet packages are
required. OUTLOOK_TEST_PG_BIN can select the local PostgreSQL binary directory.

Run from any cwd (use the isolated test venv):
  OUTLOOK_TEST_DOTNET=1 python -B -m unittest discover \
    -s /absolute/repo/backend/tests -p test_mail_import_db_client.py -v

Builds and redacted logs stay in the sibling dpms-release-artifacts directory
under outlook-direct-db-20261117/test-client-*. Private generated TLS material
is confined to the temporary cluster and deleted after the server stops.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import socket
import ssl
import tempfile
import unittest
from unittest.mock import patch
from uuid import uuid4
import xml.etree.ElementTree as ET

from test_mail_import import BACKEND, load_source, require_dependencies, sync_payload
import test_mail_import_http as http


REPO = BACKEND.parent
ARTIFACTS = REPO.parent / "dpms-release-artifacts/outlook-direct-db-20261117"


@unittest.skipUnless(os.getenv("OUTLOOK_TEST_DOTNET") == "1", "explicit OUTLOOK_TEST_DOTNET=1 required")
class PostgresClientLiveTests(unittest.IsolatedAsyncioTestCase):
    # Reuse only the isolated schema100 fixture, not its HTTP test cases.
    run_migration = http.PostgresHTTPTests.run_migration
    drop_schema = http.PostgresHTTPTests.drop_schema

    async def stop_process(self, process):
        if process.returncode is None:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            await asyncio.wait_for(process.wait(), 5)

    async def command(self, arguments, *, timeout=30, log=None, input=None, expect_failure=False):
        process = await asyncio.create_subprocess_exec(
            *map(str, arguments), env=self.environment, cwd=self.artifacts,
            stdin=asyncio.subprocess.PIPE if input is not None else asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(input), timeout)
        finally:
            await self.stop_process(process)
        if input is not None and b"synthetic-disposable-only" in output:
            raise RuntimeError("Provisioning echoed a password; output not persisted")
        if log:
            (self.artifacts / log).write_bytes(output)
        if expect_failure:
            self.assertNotEqual(process.returncode, 0, "Unsafe provisioning must fail closed")
            self.assertTrue(b"Unsafe inherited/PUBLIC privileges" in output, "Expected the ACL safety gate to reject provisioning")
        elif process.returncode:
            raise RuntimeError(f"Synthetic fixture command failed: {Path(arguments[0]).name}, exit {process.returncode}")

    async def provision(self, label, login, owner, *, expect_failure=False):
        await self.command([
            self.pg / "psql", "-X", "-h", self.cluster, "-p", str(self.port),
            "-U", "outlook_fixture_admin", "-d", "dpms_outlook_test",
            "-v", f"app_schema={self.schema_name}", "-v", f"bridge_role={login}",
            "-v", f"owner_id={owner.id}", "-v", "include_body=true", "-v", "include_attachments=true",
            "-f", REPO / "connectors/outlook-windows/provision-db-role.sql",
        ], input=b"synthetic-disposable-only\n" * 2, log=f"provision-{label}.log", expect_failure=expect_failure)

    async def assert_provision_rejects_public_extras(self):
        from sqlalchemy import text
        outside = '"outlook_acl_' + uuid4().hex + '"'
        async with self.engine.begin() as connection:
            await connection.execute(text(f"CREATE SCHEMA {outside}"))
            await connection.execute(text(f"GRANT USAGE ON SCHEMA {outside} TO PUBLIC"))
            await connection.execute(text(f"CREATE TABLE {outside}.synthetic (id integer)"))
        cases = (
            ("column", ["GRANT SELECT(body_text) ON mail_import_items TO PUBLIC"],
             ["REVOKE SELECT(body_text) ON mail_import_items FROM PUBLIC"]),
            ("outside-table", [f"GRANT SELECT ON {outside}.synthetic TO PUBLIC"],
             [f"REVOKE SELECT ON {outside}.synthetic FROM PUBLIC"]),
            ("outside-function", [f"CREATE FUNCTION {outside}.synthetic() RETURNS integer LANGUAGE sql SECURITY DEFINER AS 'SELECT 1'"],
             [f"DROP FUNCTION {outside}.synthetic()"]),
            ("outside-sequence", [f"CREATE SEQUENCE {outside}.counter", f"GRANT USAGE ON SEQUENCE {outside}.counter TO PUBLIC"],
             [f"DROP SEQUENCE {outside}.counter"]),
            ("schema-create", [f"GRANT CREATE ON SCHEMA {outside} TO PUBLIC"],
             [f"REVOKE CREATE ON SCHEMA {outside} FROM PUBLIC"]),
            ("database-create", ["GRANT CREATE ON DATABASE dpms_outlook_test TO PUBLIC"],
             ["REVOKE CREATE ON DATABASE dpms_outlook_test FROM PUBLIC"]),
        )
        for label, setup, cleanup in cases:
            login = "outlook_live_" + uuid4().hex
            async with self.engine.begin() as connection:
                for statement in setup:
                    await connection.execute(text(statement))
            try:
                await self.provision(label, login, self.owner, expect_failure=True)
                async with self.engine.connect() as connection:
                    self.assertFalse(await connection.scalar(text(
                        "SELECT EXISTS (SELECT 1 FROM pg_catalog.pg_roles WHERE rolname = :name)"
                    ), {"name": login}))
                    self.assertFalse(await connection.scalar(text(
                        "SELECT EXISTS (SELECT 1 FROM mail_import_db_logins WHERE role_name = :name)"
                    ), {"name": login}))
            finally:
                async with self.engine.begin() as connection:
                    for statement in cleanup:
                        await connection.execute(text(statement))
        async with self.engine.begin() as connection:
            await connection.execute(text(f"DROP SCHEMA {outside} CASCADE"))

    async def stop_cluster(self):
        if (self.cluster / "data/postmaster.pid").exists():
            await self.command([self.pg / "pg_ctl", "-D", self.cluster / "data", "-m", "immediate", "-w", "-t", "10", "stop"], timeout=15)

    async def asyncSetUp(self):
        async with asyncio.timeout(240):
            await self.prepare()

    async def prepare(self):
        require_dependencies(self)
        from sqlalchemy import text

        self.pg = Path(os.environ.get("OUTLOOK_TEST_PG_BIN", "/opt/homebrew/opt/postgresql@17/bin"))
        self.dotnet = shutil.which("dotnet")
        openssl = shutil.which("openssl")
        if not self.dotnet or not openssl or not (self.pg / "initdb").is_file():
            self.fail("Opt-in requires local .NET, OpenSSL and PostgreSQL 17 binaries")
        package_cache = Path.home() / ".nuget/packages"
        if not (package_cache / "npgsql/10.0.3/npgsql.10.0.3.nupkg").is_file():
            self.fail("Precached NuGet dependencies required; this harness never restores from the network")
        ARTIFACTS.mkdir(parents=True, exist_ok=True)
        self.artifacts = Path(tempfile.mkdtemp(prefix="test-client-", dir=ARTIFACTS))
        home = self.artifacts / "home"
        home.mkdir(mode=0o700)
        temporary = tempfile.TemporaryDirectory(prefix="dpms-outlook-pg.", dir="/tmp")
        self.cluster = Path(temporary.name)
        self.addCleanup(temporary.cleanup)
        self.fixture_id = uuid4().hex
        (self.cluster / "fixture-id").write_text(self.fixture_id)
        # Never inherit PG*, SSL*, app settings, proxies or user TLS defaults.
        self.environment = {
            "PATH": os.environ.get("PATH", os.defpath), "HOME": str(home),
            "TMPDIR": str(self.artifacts), "LANG": "en_US.UTF-8",
            "DOTNET_CLI_HOME": str(home), "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
            "DOTNET_CLI_TELEMETRY_OPTOUT": "1", "DOTNET_NOLOGO": "1",
            "NUGET_PACKAGES": str(self.artifacts / "packages"),
            "NUGET_HTTP_CACHE_PATH": str(self.artifacts / "nuget-http"),
            "MSBUILDDISABLENODEREUSE": "1",
        }
        config = ET.Element("configuration")
        sources = ET.SubElement(config, "packageSources")
        ET.SubElement(sources, "clear")
        ET.SubElement(sources, "add", key="local-cache-only", value=str(package_cache))
        ET.ElementTree(config).write(self.artifacts / "NuGet.Config", encoding="utf-8")
        self.project = REPO / "connectors/outlook-windows/Tests/Tests.csproj"
        self.build = self.artifacts / "build"
        await self.command([self.dotnet, "restore", self.project, "--configfile", self.artifacts / "NuGet.Config",
                            "--artifacts-path", self.build, "-p:NuGetAudit=false", "--disable-parallel"], timeout=90, log="restore.log")
        await self.command([self.dotnet, "build", self.project, "--no-restore", "--artifacts-path", self.build,
                            "--disable-build-servers"], timeout=90, log="build.log")

        for name in ("root", "untrusted"):
            await self.command([openssl, "req", "-x509", "-newkey", "rsa:2048", "-noenc", "-days", "1",
                                "-subj", f"/CN=DPMS disposable {name}", "-addext", "basicConstraints=critical,CA:TRUE",
                                "-keyout", self.cluster / f"{name}.key", "-out", self.cluster / f"{name}.crt"])
        await self.command([openssl, "req", "-new", "-newkey", "rsa:2048", "-noenc", "-subj", "/CN=localhost",
                            "-keyout", self.cluster / "server.key", "-out", self.cluster / "server.csr"])
        (self.cluster / "server.ext").write_text(
            "subjectAltName=DNS:localhost\nbasicConstraints=critical,CA:FALSE\n"
            "keyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\n")
        await self.command([openssl, "x509", "-req", "-in", self.cluster / "server.csr", "-CA", self.cluster / "root.crt",
                            "-CAkey", self.cluster / "root.key", "-set_serial", "2", "-days", "1",
                            "-extfile", self.cluster / "server.ext", "-out", self.cluster / "server.crt"])
        (self.cluster / "server.key").chmod(0o600)
        with socket.socket() as reservation:
            reservation.bind(("127.0.0.1", 0))
            self.port = reservation.getsockname()[1]
        self.assertGreaterEqual(self.port, 1024)
        await self.command([self.pg / "initdb", "-D", self.cluster / "data", "-U", "outlook_fixture_admin",
                            "--auth-local=trust", "--auth-host=reject", "--encoding=UTF8", "--no-locale"])
        (self.cluster / "data/postgresql.conf").write_text(
            f"listen_addresses = '127.0.0.1,::1'\nport = {self.port}\n"
            f"unix_socket_directories = '{self.cluster}'\nssl = on\n"
            f"ssl_cert_file = '{self.cluster}/server.crt'\nssl_key_file = '{self.cluster}/server.key'\n"
            "password_encryption = 'scram-sha-256'\nlog_statement = 'none'\n"
            "log_min_error_statement = 'panic'\nlog_error_verbosity = 'terse'\n")
        (self.cluster / "data/pg_hba.conf").write_text(
            "local all all trust\nhostssl dpms_outlook_test all 127.0.0.1/32 scram-sha-256\n"
            "hostssl dpms_outlook_test all ::1/128 scram-sha-256\n")
        self.addAsyncCleanup(self.stop_cluster)
        await self.command([self.pg / "pg_ctl", "-D", self.cluster / "data", "-l", self.cluster / "postgres.log",
                            "-w", "-t", "15", "start"], timeout=20)
        await self.command([self.pg / "createdb", "-h", self.cluster, "-p", str(self.port),
                            "-U", "outlook_fixture_admin", "dpms_outlook_test"])
        environment = patch.dict(os.environ, {
            **self.environment, "OUTLOOK_TEST_POSTGRES": "1",
            "OUTLOOK_TEST_DATABASE_URL": f"postgresql+asyncpg://outlook_fixture_admin@/dpms_outlook_test?host={self.cluster}&port={self.port}",
        }, clear=True)
        environment.start()
        self.addCleanup(environment.stop)
        # Includes the existing disposable_url identity/ownership guards.
        await http.PostgresHTTPTests.asyncSetUp(self)
        load_source("app.models.mail_import_queue", BACKEND / "app/models/mail_import_queue.py")
        self.worker_service = load_source("app.services.mail_import_queue", BACKEND / "app/services/mail_import_queue.py")
        self.worker = load_source("_outlook_live_worker_" + self.fixture_id, BACKEND / "app/workers/mail_import_queue.py")
        self.migration = load_source("_outlook_live_migration_" + self.fixture_id, BACKEND / "alembic/versions/101_mail_import_db_queue.py")
        self.login = "outlook_live_" + uuid4().hex
        self.other_login = "outlook_live_" + uuid4().hex
        self.unmapped_login = "outlook_live_" + uuid4().hex
        async with self.engine.begin() as connection:
            await connection.run_sync(lambda conn: self.run_migration(conn, "upgrade"))
        await self.assert_provision_rejects_public_extras()
        # Execute the DBA package itself. A detached subprocess has no controlling
        # terminal, so psql's password prompt consumes only these synthetic bytes.
        for label, login, owner in (("primary", self.login, self.owner),
                                    ("other", self.other_login, self.other),
                                    ("unmapped", self.unmapped_login, self.other)):
            await self.provision(label, login, owner)
        async with self.engine.begin() as connection:
            await connection.execute(text("DELETE FROM mail_import_db_logins WHERE role_name = :name"),
                                     {"name": self.unmapped_login})
        self.environment.update({
            "OUTLOOK_TEST_DOTNET": "1", "OUTLOOK_TEST_TLS_FIXTURE": str(self.cluster),
            "OUTLOOK_TEST_FIXTURE_ID": self.fixture_id, "OUTLOOK_TEST_PORT": str(self.port),
            "OUTLOOK_TEST_SCHEMA": self.schema_name, "OUTLOOK_TEST_LOGIN": self.login,
            "OUTLOOK_TEST_OTHER_LOGIN": self.other_login, "OUTLOOK_TEST_UNMAPPED_LOGIN": self.unmapped_login,
        })

    async def rows(self, sql):
        from sqlalchemy import text
        async with self.engine.connect() as connection:
            return (await connection.execute(text(sql))).mappings().all()

    async def wait_for(self, predicate, process):
        async with asyncio.timeout(30):
            while not await predicate():
                if process.returncode is not None:
                    self.fail(f"C# exited before the required handshake; see {self.artifacts / 'live.log'}")
                await asyncio.sleep(0.05)

    async def pending(self):
        return bool(await self.rows("SELECT 1 FROM mail_import_queue WHERE state = 'pending'"))

    async def marker(self, name):
        return (self.cluster / name).is_file()

    async def disable_mapping(self):
        from sqlalchemy import text
        async with self.engine.begin() as connection:
            changed = await connection.execute(text(
                "UPDATE mail_import_db_logins SET enabled = false WHERE role_name = :role_name"
            ), {"role_name": self.login})
            self.assertEqual(changed.rowcount, 1)

    async def assert_http_rejects_db_device(self):
        import asyncpg
        value = secrets.token_urlsafe(32)
        tls = ssl.create_default_context(cafile=self.cluster / "root.crt")
        connection = await asyncio.wait_for(asyncpg.connect(
            host="localhost", port=self.port, database="dpms_outlook_test", user=self.other_login,
            password="synthetic-disposable-only", ssl=tls, timeout=10, command_timeout=10,
        ), 15)
        try:
            result = json.loads(await connection.fetchval(
                f'SELECT "{self.schema_name}".mail_import_db_connect($1,$2)::text',
                "Synthetic legacy rejection", value,
            ))
            self.assertEqual(result.get("protocol_version"), 1)
            self.assertTrue(result.get("device_secret") == value)
            response = await self.client.post(http.PREFIX + "/sync", json=sync_payload(),
                                              headers={"Authorization": "Bearer " + value})
            self.assertEqual(response.status_code, 401, "DB-bound secret must not enter legacy HTTPS import")
            self.assertEqual(len(await self.rows("SELECT 1 FROM mail_import_items")), 0)
        finally:
            await asyncio.wait_for(connection.close(), 5)

    async def test_real_tls_cross_language_round_trip(self):
        async with asyncio.timeout(95):
            await self.round_trip()

    async def round_trip(self):
        await self.assert_http_rejects_db_device()
        devices_before_probe = await self.rows("SELECT count(*) FROM mail_import_devices")
        log = (self.artifacts / "live.log").open("wb")
        self.addCleanup(log.close)
        process = await asyncio.create_subprocess_exec(
            self.dotnet, "test", str(self.project), "--no-build", "--no-restore",
            "--artifacts-path", str(self.build), "--filter", "FullyQualifiedName~PostgresLiveTests",
            "--logger", "trx;LogFileName=live.trx", "--results-directory", str(self.artifacts),
            env=self.environment, cwd=self.artifacts, stdout=log, stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        self.addAsyncCleanup(self.stop_process, process)
        await self.wait_for(lambda: self.marker("connection-checked"), process)
        self.assertEqual(await self.rows("SELECT count(*) FROM mail_import_devices"), devices_before_probe)
        self.assertFalse(await self.rows("SELECT 1 FROM mail_import_queue"))
        self.assertFalse(await self.rows("SELECT 1 FROM mail_import_items"))
        (self.cluster / "connection-check-verified").touch()
        await self.wait_for(self.pending, process)
        devices = await self.rows("SELECT id, owner_id, include_body, include_attachments, pairing_code_hash "
                                  "FROM mail_import_devices WHERE name = 'Synthetic TLS laptop'")
        self.assertEqual(len(devices), 1)
        self.device_id = devices[0]["id"]
        self.assertEqual(devices[0]["owner_id"], self.owner.id)
        self.assertTrue(devices[0]["include_body"])
        self.assertTrue(devices[0]["include_attachments"])
        self.assertIsNone(devices[0]["pairing_code_hash"])
        requests = await self.rows("SELECT request_id FROM mail_import_queue WHERE state = 'pending'")
        self.assertEqual(len(requests), 1)
        (self.cluster / "first-request-id").write_text(str(requests[0]["request_id"]))
        await asyncio.sleep(1.25)
        self.assertFalse(await self.marker("first-ack"), "enqueue is not a final ACK")
        self.assertEqual(len(await self.rows("SELECT 1 FROM mail_import_items")), 0)

        # Execute the actual worker tick while deliberately withholding its import
        # transaction commit. No SQL/worker/client implementation is mocked.
        held = asyncio.Event()
        release = asyncio.Event()
        factory = self.factory

        class HeldSession:
            async def __aenter__(inner):
                inner.db = factory()
                await inner.db.__aenter__()
                return inner

            async def __aexit__(inner, *error):
                return await inner.db.__aexit__(*error)

            def __getattr__(inner, name):
                return getattr(inner.db, name)

            def begin(inner):
                from contextlib import asynccontextmanager

                @asynccontextmanager
                async def transaction():
                    async with inner.db.begin():
                        yield
                        # run_once first commits cleanup, then processes one row.
                        if inner.db.info.get("hold_import"):
                            held.set()
                            await release.wait()
                return transaction()

            def begin_nested(inner):
                inner.db.info["hold_import"] = True
                return inner.db.begin_nested()

        worker_task = asyncio.create_task(self.worker.run_once(HeldSession))
        try:
            await asyncio.wait_for(held.wait(), 10)
            await asyncio.sleep(1.25)
            self.assertFalse(await self.marker("first-ack"), "uncommitted worker result is not an ACK")
            self.assertTrue(await self.pending())
            self.assertEqual(len(await self.rows("SELECT 1 FROM mail_import_items")), 0)
            release.set()
            self.assertTrue(await asyncio.wait_for(worker_task, 10))
        finally:
            release.set()
            if not worker_task.done():
                worker_task.cancel()
            await asyncio.gather(worker_task, return_exceptions=True)

        await self.wait_for(lambda: self.marker("first-ack"), process)
        await self.wait_for(self.pending, process)
        self.assertTrue(await asyncio.wait_for(self.worker.run_once(self.factory), 10))
        await self.wait_for(lambda: self.marker("repeat-ack"), process)
        items = await self.rows("SELECT subject, body_text, body_html, body_captured, attachments_captured FROM mail_import_items")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["subject"], "Synthetic TLS subject \u041f\u043e\u0447\u0442\u0430")
        self.assertEqual(items[0]["body_text"], "Synthetic full text")
        self.assertEqual(items[0]["body_html"], "<p>Synthetic full text</p>")
        self.assertTrue(items[0]["body_captured"])
        self.assertTrue(items[0]["attachments_captured"])
        attachments = await self.rows("SELECT sha256 FROM mail_import_attachments")
        self.assertEqual([row["sha256"] for row in attachments], [hashlib.sha256(b"Synthetic TLS attachment\n").hexdigest()])
        receipts = await self.rows("SELECT state, payload, result FROM mail_import_queue ORDER BY created_at")
        self.assertEqual(len(receipts), 2)
        self.assertEqual([row["state"] for row in receipts], ["done", "done"])
        self.assertTrue(all(row["payload"] is None for row in receipts))
        self.assertEqual([row["result"]["created"] for row in receipts], [1, 0])
        self.assertEqual([row["result"]["unchanged"] for row in receipts], [0, 1])
        response = await self.client.post(http.PREFIX + f"/devices/{self.device_id}/revoke", json={})
        self.assertEqual(response.status_code, 200)
        (self.cluster / "revoked").write_text("ok")
        await self.wait_for(lambda: self.marker("revoke-rejected"), process)

        await self.wait_for(self.pending, process)
        await self.disable_mapping()
        self.assertTrue(await asyncio.wait_for(self.worker.run_once(self.factory), 10))
        rejected = await self.rows("SELECT state, payload, error_status FROM mail_import_queue ORDER BY created_at")
        self.assertEqual(len(rejected), 3)
        self.assertEqual(rejected[-1], {"state": "error", "payload": None, "error_status": 401})
        self.assertEqual(len(await self.rows("SELECT 1 FROM mail_import_items")), 1)
        (self.cluster / "mapping-disabled").write_text("ok")
        await self.wait_for(lambda: self.marker("mapping-rejected"), process)
        self.assertEqual(await asyncio.wait_for(process.wait(), 30), 0, f"See {self.artifacts / 'live.log'}")
        devices = await self.rows("SELECT owner_id FROM mail_import_devices")
        self.assertEqual(sum(row["owner_id"] == self.owner.id for row in devices), 2)
        self.assertFalse(await asyncio.wait_for(self.worker.run_once(self.factory), 10))
        result = ET.parse(self.artifacts / "live.trx")
        ns = {"t": "http://microsoft.com/schemas/VisualStudio/TeamTest/2010"}
        counters = result.find("t:ResultSummary/t:Counters", ns)
        self.assertIsNotNone(counters)
        self.assertEqual((counters.get("total"), counters.get("passed"), counters.get("failed")), ("4", "4", "0"))
        print(f"Synthetic TLS integration evidence: {self.artifacts}")
