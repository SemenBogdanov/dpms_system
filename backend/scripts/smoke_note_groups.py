"""Local-only ID65 database/API smoke with unique users and verified cleanup.

Uses the configured local API/database after migration080. No schema changes,
container operations, real users or existing data are modified.
Run: PYTHONPATH=. python scripts/smoke_note_groups.py
"""
from __future__ import annotations

import asyncio
import uuid

from sqlalchemy import delete, func, select

from app.core.security import create_access_token
from app.database import AsyncSessionLocal
from app.models.contact import Contact
from app.models.note_group import NoteGroup, NoteShareBatch
from app.models.personal_task import PersonalTask
from app.models.quick_note import QuickNote
from app.models.quick_note_share import QuickNoteShare
from app.models.user import League, User, UserRole
from app.models.work_entity import WorkEntity, WorkEntityMember
from scripts.smoke_quick_note_collaboration import async_request, ensure_safe_target, expect


async def main():
    ensure_safe_target()
    ids = {role: uuid.uuid4() for role in ("owner", "recipient", "stranger")}
    marker = uuid.uuid4().hex
    users = []
    try:
        async with AsyncSessionLocal() as db:
            for role, id in ids.items():
                user = User(id=id, full_name=f"ID65 smoke {role}", email=f"id65-{role}-{marker}@example.invalid",
                    league=League.B, role=UserRole.executor, is_active=True, task_workspace_enabled=True)
                users.append(user); db.add(user)
            await db.flush()
            db.add(Contact(requester_id=ids["owner"], recipient_id=ids["recipient"], status="accepted"))
            project = WorkEntity(owner_id=ids["owner"], title=f"ID65 project {marker}", entity_type="project", visibility="shared")
            task = PersonalTask(owner_id=ids["owner"], title=f"ID65 task {marker}")
            db.add_all([project, task]); await db.flush()
            db.add(WorkEntityMember(entity_id=project.id, user_id=ids["recipient"], role="viewer"))
            await db.commit()
            project_id, task_id = str(project.id), str(task.id)
            tokens = {role: create_access_token({"sub": str(user.id), "ver": user.auth_version}) for role, user in zip(ids, users)}

        async def call(method, path, body=None, *, role="owner", status=200):
            code, payload = await async_request(method, path, tokens[role], json_body=body)
            return expect(code, status, payload, f"ID65 {method} {path.split('?')[0]}")

        root = "/api/note-groups"
        group = await call("POST", root, {"title": "Private ID65 group"})
        group_id = group["id"]
        note = await call("POST", "/api/quick-notes", {"body": "Private ID65 note", "group_id": group_id})
        incoming = await call("POST", "/api/quick-notes", {"body": "Recipient-owned note"}, role="recipient")
        await call("POST", f"{root}/move", {"note_ids": [note["id"], incoming["id"]], "group_id": None}, status=404)
        unchanged = await call("GET", f"/api/quick-notes/{note['id']}")
        assert unchanged["group_id"] == group_id, "Mixed-ownership bulk move changed an owned note"
        group = await call("PATCH", f"{root}/{group_id}", {"base_revision": group["revision"], "title": "Renamed private ID65 group"})
        await call("PATCH", f"{root}/{group_id}", {"base_revision": 1, "title": "Stale rename"}, status=409)
        await call("PATCH", f"{root}/{group_id}", {"base_revision": group["revision"], "title": "Cross-user rename"}, role="recipient", status=404)
        for kind, id in (("entity", project_id), ("personal_task", task_id)):
            await call("POST", f"{root}/sources/group/{group_id}/links", {"target_type": kind, "target_id": id})
        new_note = await call("POST", "/api/quick-notes", {"body": "New dynamic note", "group_id": group_id})
        links = await call("GET", f"{root}/sources/note/{new_note['id']}/links")
        assert len(links) == 2 and all(link["inherited"] for link in links), "New note did not inherit both contexts"
        for kind, id in (("entity", project_id), ("personal_task", task_id)):
            backlinks = await call("GET", f"{root}/backlinks?target_type={kind}&target_id={id}")
            assert {item["id"] for item in backlinks["notes"]} == {note["id"], new_note["id"]}
        project_backlinks = f"{root}/backlinks?target_type=entity&target_id={project_id}"
        assert await call("GET", project_backlinks, role="recipient") == {"notes": [], "groups": []}
        await call("GET", f"{root}/backlinks?target_type=personal_task&target_id={task_id}", role="recipient", status=404)
        await call("POST", f"{root}/sources/note/{incoming['id']}/links", {"target_type": "personal_task", "target_id": task_id}, role="recipient", status=404)
        await call("POST", f"{root}/share/preview", {"group_id": group_id, "recipient_ids": [str(ids["stranger"])]}, status=403)

        selection = {"group_id": group_id, "recipient_ids": [str(ids["recipient"])], "project_id": project_id}
        preview = await call("POST", f"{root}/share/preview", selection)
        assert preview["new_share_count"] == 2
        await call("PATCH", f"/api/quick-notes/{note['id']}", {"base_revision": note["revision"], "body": "Changed after preview"})
        await call("POST", f"{root}/share/{preview['id']}/apply", {}, status=409)
        preview = await call("POST", f"{root}/share/preview", selection)
        first, replay = await asyncio.gather(*[call("POST", f"{root}/share/{preview['id']}/apply", {}) for _ in range(2)])
        assert first == replay and first["changed_share_count"] == 2, "Duplicate apply was not idempotent"
        audit = await call("GET", f"{root}/share/audit")
        assert len(audit) == 1 and audit[0]["result"]["id"] == preview["id"]
        assert await call("GET", f"{root}/share/audit", role="recipient") == []
        shared = await call("GET", f"/api/quick-notes/{note['id']}", role="recipient")
        assert shared["note"]["group_id"] is None
        visible = await call("GET", project_backlinks, role="recipient")
        assert visible["groups"] == [] and len(visible["notes"]) == 2
        assert await call("GET", root, role="recipient") == []
        await call("GET", f"{root}/sources/group/{group_id}/links", role="recipient", status=404)

        for item in (note, new_note):
            shares = await call("GET", f"/api/quick-notes/{item['id']}/shares")
            assert len(shares) == 1
            await call("DELETE", f"/api/quick-notes/shares/{shares[0]['id']}")
            await call("GET", f"/api/quick-notes/{item['id']}", role="recipient", status=404)
        assert await call("GET", project_backlinks, role="recipient") == {"notes": [], "groups": []}
        await call("POST", f"{root}/share/{preview['id']}/apply", {})
        assert await call("GET", project_backlinks, role="recipient") == {"notes": [], "groups": []}, "Replay reopened revoked access"
        await call("POST", f"{root}/move", {"note_ids": [new_note["id"]], "group_id": None})
        assert await call("GET", f"{root}/sources/note/{new_note['id']}/links") == []
        group = await call("PATCH", f"{root}/{group_id}", {"base_revision": group["revision"], "archived": True})
        await call("DELETE", f"{root}/{group_id}?base_revision={group['revision']}")
        for item in (note, new_note):
            assert (await call("GET", f"/api/quick-notes/{item['id']}"))["group_id"] is None
        print("PASS ID65: atomic move, revision, dynamic context, ACL, preview/apply/replay/revoke, audit, note-preserving delete")
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(PersonalTask).where(PersonalTask.owner_id.in_(ids.values())))
            await db.execute(delete(WorkEntity).where(WorkEntity.owner_id.in_(ids.values())))
            await db.execute(delete(User).where(User.id.in_(ids.values())))
            await db.commit()
            for model, column in ((User, User.id), (NoteGroup, NoteGroup.owner_id), (QuickNote, QuickNote.owner_id),
                                  (NoteShareBatch, NoteShareBatch.owner_id), (QuickNoteShare, QuickNoteShare.owner_id)):
                count = (await db.execute(select(func.count()).select_from(model).where(column.in_(ids.values())))).scalar_one()
                assert count == 0, f"ID65 fixture cleanup incomplete: {model.__tablename__}"
        print("PASS ID65: unique-user fixture cleanup verified")


if __name__ == "__main__":
    asyncio.run(main())
