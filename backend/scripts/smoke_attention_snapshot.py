"""Local PostgreSQL regression for worker-driven inbox refresh and isolation."""
import asyncio
from datetime import datetime, timedelta, timezone
import uuid

from sqlalchemy import select
from sqlalchemy.engine import make_url

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.messages import MessageThread, MessageThreadParticipant, UserAttentionItem
from app.models.user import League, User, UserRole
from app.services.messages import emit_attention_event, get_attention_snapshot, mark_attention_read


async def main():
    if make_url(settings.DATABASE_URL).host not in {"localhost", "127.0.0.1", "db"}:
        raise RuntimeError("Inbox smoke requires a local database")
    async with AsyncSessionLocal() as db:
        try:
            marker = uuid.uuid4().hex
            owner, outsider = [User(
                id=uuid.uuid4(), full_name="Inbox regression",
                email=f"inbox-{suffix}-{marker}@example.invalid",
                league=League.C, role=UserRole.executor,
            ) for suffix in ("owner", "outsider")]
            db.add_all([owner, outsider])
            await db.flush()
            assert (await get_attention_snapshot(db, owner.id))[:2] == (0, 0)

            thread = MessageThread(
                id=uuid.uuid4(), created_by_id=owner.id,
                subject="Snapshot regression", request_id=uuid.uuid4(),
                updated_at=datetime.now(timezone.utc),
            )
            db.add(thread)
            await db.flush()
            db.add(MessageThreadParticipant(thread_id=thread.id, user_id=owner.id, unread_count=2))
            await db.flush()
            before_post = await get_attention_snapshot(db, owner.id)
            assert before_post[:2] == (1, 0)
            thread.updated_at += timedelta(seconds=1)
            await db.flush()
            after_post = await get_attention_snapshot(db, owner.id)
            assert before_post[:2] == after_post[:2] and before_post[2] != after_post[2]

            async def send(key):
                await emit_attention_event(
                    db, target_user_ids=[owner.id], kind="important",
                    event_type="deadline.reminder", source_type="deadline_tracker",
                    source_key=marker, title=key, link="/deadline-trackers",
                    dedupe_key=f"snapshot:{key}:{marker}",
                    idempotency_key=f"snapshot:{key}:{marker}",
                )
                await db.flush()

            await send("first")
            before = await get_attention_snapshot(db, owner.id)
            assert before[:2] == (1, 1)
            item = (await db.execute(select(UserAttentionItem).where(
                UserAttentionItem.user_id == owner.id,
            ))).scalar_one()
            await mark_attention_read(db, user_id=owner.id, item_id=item.id)
            await send("second")
            after = await get_attention_snapshot(db, owner.id)
            assert before[:2] == after[:2] and before[2] != after[2]
            assert await get_attention_snapshot(db, outsider.id) == (0, 0, "|")
            print("Inbox snapshot: empty, threads, unchanged counts, read replacement and owner isolation PASS")
        finally:
            await db.rollback()


if __name__ == "__main__":
    asyncio.run(main())
