"""Local-only HTTP/PG smoke for historical source staging, with own-data cleanup."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
from hashlib import sha256
import json
import os
from urllib.parse import urlparse
from uuid import uuid4

import httpx
from sqlalchemy import delete, func, select
from sqlalchemy.engine import make_url

from app.config import settings
from app.core.security import create_access_token
from app.database import AsyncSessionLocal
from app.models.activity import ActivityEvent
from app.models.audit import AuditAtom, AuditAssignment, AuditCase, AuditEvent
from app.models.audit_legacy import AuditLegacyImport
from app.models.user import League, User, UserRole
from tests.test_audit_legacy_workbook import ATOM_MAPPING, workbook_bytes


async def run() -> None:
    base_url = os.getenv("SMOKE_API_BASE", "http://127.0.0.1:8000").rstrip("/")
    if urlparse(base_url).hostname not in {"127.0.0.1", "localhost", "backend"}:
        raise RuntimeError("Refusing non-local API")
    if make_url(settings.DATABASE_URL).host not in {"127.0.0.1", "localhost", "db"}:
        raise RuntimeError("Refusing non-local DB")
    marker = uuid4().hex
    users = []
    batch_id = None
    passed = []
    source = workbook_bytes([("Исторический источник", [["Код договора", "Код атома", "Название атома"], [f"SYNTHETIC-{marker}", "1", "Тестовый атом"]])])
    digest = sha256(source).hexdigest()
    models = (AuditCase, AuditAtom, AuditAssignment, AuditEvent)

    def request(method, path, user=None, **kwargs):
        headers = {}
        if user is not None:
            headers["Authorization"] = "Bearer " + create_access_token({"sub": str(user.id), "ver": user.auth_version})
        return httpx.request(method, f"{base_url}/api/audit/legacy-imports{path}", headers=headers, timeout=30, **kwargs)

    def expect(response, status, label):
        if response.status_code != status:
            raise AssertionError(f"{label}: expected HTTP {status}, got {response.status_code}")
        passed.append(label)
        return response

    try:
        async with AsyncSessionLocal() as db:
            before = [await db.scalar(select(func.count()).select_from(model)) for model in models]
            for index, role in enumerate((UserRole.admin, UserRole.teamlead, UserRole.executor)):
                user = User(full_name="A1.9 smoke", email=f"a19-{marker}-{index}@example.invalid", role=role, league=League.A, mpw=0, audit_enabled=True, is_active=True)
                db.add(user)
                users.append(user)
            await db.commit()
            for user in users:
                await db.refresh(user)
        admin, lead, employee = users
        expect(request("GET", ""), 401, "anonymous denied")
        for user in (lead, employee):
            expect(request("GET", "", user), 403, "nonadmin list denied")
            expect(request("POST", "", user, files={"file": ("sample.xlsx", source)}), 403, "nonadmin upload denied")
        def upload():
            return request("POST", "", admin, files={"file": ("private-source-name.xlsx", source)})
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: upload(), range(2)))
        first = expect(responses[0], 200, "upload").json()
        second = expect(responses[1], 200, "concurrent duplicate upload").json()
        batch_id = first["id"]
        assert first["id"] == second["id"] and first["sha256"] == digest
        assert "source_bytes" not in first and "private-source-name" not in responses[0].text
        assert first["report"] is None and first["mapping"] is None and first["status"] == "uploaded"
        for method, suffix, kwargs in (("GET", "", {}), ("GET", "/source", {}), ("PUT", "/mapping", {"json": {"revision": 1, "mapping": ATOM_MAPPING}}), ("DELETE", "?revision=1", {})):
            expect(request(method, f"/{batch_id}{suffix}", **kwargs), 401, "anonymous direct endpoint denied")
        expect(request("POST", "", files={"file": ("sample.xlsx", source)}), 401, "anonymous upload denied")
        for user in (lead, employee):
            for method, suffix, kwargs in (("GET", "", {}), ("GET", "/source", {}), ("PUT", "/mapping", {"json": {"revision": 1, "mapping": ATOM_MAPPING}}), ("DELETE", "?revision=1", {})):
                expect(request(method, f"/{batch_id}{suffix}", user, **kwargs), 403, "nonadmin direct endpoint denied")
        checked = expect(request("PUT", f"/{batch_id}/mapping", admin, json={"revision": first["revision"], "mapping": ATOM_MAPPING}), 200, "mapping saved").json()
        assert checked["status"] == "checked" and checked["report"]["valid_rows"] == 1
        assert checked["report"]["ready_for_import"] is False and checked["revision"] == 2
        expect(request("PUT", f"/{batch_id}/mapping", admin, json={"revision": 1, "mapping": ATOM_MAPPING}), 409, "stale mapping blocked")
        expect(request("DELETE", f"/{batch_id}?revision=1", admin), 409, "stale delete blocked")
        reread = expect(request("GET", f"/{batch_id}", admin), 200, "saved report survives reload").json()
        assert reread["mapping"] == checked["mapping"] and reread["revision"] == 2
        expect(request("PUT", f"/{batch_id}/mapping", admin, json={"revision": 2, "mapping": {**ATOM_MAPPING, "sheet_id": "missing"}}), 400, "invalid sheet blocked")
        assert request("GET", f"/{batch_id}", admin).json()["revision"] == 2
        downloaded = expect(request("GET", f"/{batch_id}/source", admin), 200, "source download")
        assert downloaded.content == source and downloaded.headers.get("cache-control") == "no-store"
        assert downloaded.headers.get("x-content-type-options") == "nosniff"
        assert "private-source-name" not in downloaded.headers.get("content-disposition", "")
        expect(request("POST", "", admin, files={"file": ("wrong.xlsm", source)}), 415, "macro extension denied")
        expect(request("POST", "", admin, files={"file": ("broken.xlsx", b"not a workbook")}), 400, "corrupt source denied")
        with ThreadPoolExecutor(max_workers=2) as pool:
            writes = list(pool.map(lambda _: request("PUT", f"/{batch_id}/mapping", admin, json={"revision": 2, "mapping": ATOM_MAPPING}), range(2)))
        assert sorted(response.status_code for response in writes) == [200, 409]
        passed.append("concurrent mapping revision is exclusive")
        async with AsyncSessionLocal() as db:
            after = [await db.scalar(select(func.count()).select_from(model)) for model in models]
            assert after == before, "Staging must not change cases, atoms, assignments or their history"
            assert await db.scalar(select(func.count()).select_from(AuditLegacyImport).where(AuditLegacyImport.sha256 == digest)) == 1
        passed.append("working registry and history unchanged")
        expect(request("DELETE", f"/{batch_id}?revision=3", admin), 204, "delete staging")
        expect(request("GET", f"/{batch_id}/source", admin), 404, "deleted source unavailable")
        expect(request("GET", f"/{batch_id}", admin), 404, "deleted batch unavailable")
        print(json.dumps({"status": "PASS", "checks": len(passed), "working_registry_changed": False}, ensure_ascii=False))
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(AuditLegacyImport).where(AuditLegacyImport.sha256 == digest))
            ids = [user.id for user in users if user.id]
            if ids:
                await db.execute(delete(ActivityEvent).where(ActivityEvent.actor_id.in_(ids)))
                await db.execute(delete(User).where(User.id.in_(ids)))
            await db.commit()


if __name__ == "__main__":
    asyncio.run(run())
