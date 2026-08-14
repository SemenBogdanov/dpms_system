"""Focused attention inbox and subject-based correspondence API."""
from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import and_, or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.security import decode_access_token
from app.database import AsyncSessionLocal
from app.models.contact import Contact
from app.models.messages import MessagePost, MessageThread, MessageThreadParticipant
from app.models.quick_note import QuickNote
from app.models.quick_note_share import QuickNoteShare
from app.models.user import User
from app.schemas.messages import (
    AttentionContextRead,
    AttentionItemRead,
    AttentionSummaryRead,
    MessageParticipantRead,
    MessagePostCreate,
    MessagePostRead,
    MessageThreadCreate,
    MessageThreadDetailRead,
    MessageThreadRead,
)
from app.services.attention_realtime import AttentionConnection, attention_hub
from app.services.email_outbox import enqueue_message_notification
from app.services.messages import (
    get_attention_summary,
    list_attention_items,
    mark_attention_context_read,
    mark_attention_read,
)
from app.services.quick_note_realtime import hub_registry as note_hub_registry
from app.services.quick_note_shares import activate_quick_note_shares


router = APIRouter()


async def _accepted_contact(
    db: AsyncSession, first_user_id: UUID, second_user_id: UUID
) -> bool:
    result = await db.execute(
        select(Contact.id).where(
            Contact.status == "accepted",
            or_(
                and_(
                    Contact.requester_id == first_user_id,
                    Contact.recipient_id == second_user_id,
                ),
                and_(
                    Contact.requester_id == second_user_id,
                    Contact.recipient_id == first_user_id,
                ),
            ),
        )
    )
    return result.scalar_one_or_none() is not None


async def _participant_or_404(
    db: AsyncSession,
    thread_id: UUID,
    user_id: UUID,
    *,
    for_update: bool = False,
) -> MessageThreadParticipant:
    stmt = select(MessageThreadParticipant).where(
        MessageThreadParticipant.thread_id == thread_id,
        MessageThreadParticipant.user_id == user_id,
    )
    if for_update:
        stmt = stmt.with_for_update()
    participant = (await db.execute(stmt)).scalar_one_or_none()
    if participant is None:
        raise HTTPException(status_code=404, detail="Переписка не найдена")
    return participant


async def _thread_users(
    db: AsyncSession, thread_id: UUID
) -> list[tuple[MessageThreadParticipant, User]]:
    rows = (
        await db.execute(
            select(MessageThreadParticipant, User)
            .join(User, User.id == MessageThreadParticipant.user_id)
            .where(MessageThreadParticipant.thread_id == thread_id)
            .order_by(MessageThreadParticipant.joined_at.asc())
        )
    ).all()
    return list(rows)


def _participant_reads(
    rows: list[tuple[MessageThreadParticipant, User]],
) -> list[MessageParticipantRead]:
    return [
        MessageParticipantRead(
            user_id=user.id,
            full_name=user.full_name,
            email=user.email,
        )
        for _, user in rows
    ]


async def _quick_note_preview(
    db: AsyncSession, quick_note_id: UUID | None, user_id: UUID
) -> tuple[str | None, bool]:
    if quick_note_id is None:
        return None, False
    note = (
        await db.execute(
            select(QuickNote).where(
                QuickNote.id == quick_note_id,
                or_(
                    QuickNote.owner_id == user_id,
                    QuickNote.id.in_(
                        select(QuickNoteShare.note_id).where(
                            QuickNoteShare.recipient_id == user_id,
                            QuickNoteShare.status == "active",
                        )
                    ),
                ),
            )
        )
    ).scalar_one_or_none()
    return (note.title, True) if note else (None, False)


async def _post_read(
    db: AsyncSession, post: MessagePost, current_user_id: UUID
) -> MessagePostRead:
    author = (await db.execute(select(User).where(User.id == post.author_id))).scalar_one()
    note_title, note_available = await _quick_note_preview(
        db, post.quick_note_id, current_user_id
    )
    return MessagePostRead(
        id=post.id,
        thread_id=post.thread_id,
        author_id=post.author_id,
        author_name=author.full_name,
        author_email=author.email,
        body=post.body,
        quick_note_id=post.quick_note_id if note_available else None,
        quick_note_title=note_title,
        quick_note_available=note_available,
        created_at=post.created_at,
    )


async def _thread_detail(
    db: AsyncSession, thread_id: UUID, current_user_id: UUID
) -> MessageThreadDetailRead:
    participant = await _participant_or_404(db, thread_id, current_user_id)
    thread = (
        await db.execute(select(MessageThread).where(MessageThread.id == thread_id))
    ).scalar_one()
    participant_rows = await _thread_users(db, thread.id)
    post_rows = (
        await db.execute(
            select(MessagePost, User)
            .join(User, User.id == MessagePost.author_id)
            .where(MessagePost.thread_id == thread.id)
            .order_by(MessagePost.created_at.desc(), MessagePost.id.desc())
        )
    ).all()
    if not post_rows:
        raise HTTPException(status_code=409, detail="В переписке отсутствует первое сообщение")
    note_ids = {
        post.quick_note_id
        for post, _ in post_rows
        if post.quick_note_id is not None
    }
    note_titles: dict[UUID, str] = {}
    if note_ids:
        accessible_notes = (
            await db.execute(
                select(QuickNote.id, QuickNote.title).where(
                    QuickNote.id.in_(note_ids),
                    or_(
                        QuickNote.owner_id == current_user_id,
                        QuickNote.id.in_(
                            select(QuickNoteShare.note_id).where(
                                QuickNoteShare.recipient_id == current_user_id,
                                QuickNoteShare.status == "active",
                            )
                        ),
                    ),
                )
            )
        ).all()
        note_titles = {note_id: title for note_id, title in accessible_notes}

    posts = [post for post, _ in post_rows]
    post_reads = [
        MessagePostRead(
            id=post.id,
            thread_id=post.thread_id,
            author_id=post.author_id,
            author_name=author.full_name,
            author_email=author.email,
            body=post.body,
            quick_note_id=(
                post.quick_note_id
                if post.quick_note_id in note_titles
                else None
            ),
            quick_note_title=note_titles.get(post.quick_note_id),
            quick_note_available=post.quick_note_id in note_titles,
            created_at=post.created_at,
        )
        for post, author in post_rows
    ]
    return MessageThreadDetailRead(
        id=thread.id,
        subject=thread.subject,
        created_by_id=thread.created_by_id,
        participants=_participant_reads(participant_rows),
        last_post_preview=" ".join(posts[-1].body.split())[:180],
        last_post_at=posts[-1].created_at,
        unread_count=participant.unread_count,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        posts=post_reads,
    )


async def _owned_note_or_404(
    db: AsyncSession, note_id: UUID | None, owner_id: UUID
) -> QuickNote | None:
    if note_id is None:
        return None
    note = (
        await db.execute(
            select(QuickNote).where(
                QuickNote.id == note_id,
                QuickNote.owner_id == owner_id,
            )
        )
    ).scalar_one_or_none()
    if note is None:
        raise HTTPException(
            status_code=404,
            detail="Можно приложить только собственную доступную заметку",
        )
    return note


async def _share_note_without_attention(
    db: AsyncSession,
    *,
    note: QuickNote | None,
    owner_id: UUID,
    recipient_ids: list[UUID],
) -> list[UUID]:
    if note is None:
        return []
    return await activate_quick_note_shares(
        db,
        note_id=note.id,
        owner_id=owner_id,
        recipient_ids=recipient_ids,
    )


async def _broadcast_note_access(
    note_id: UUID | None, recipient_ids: list[UUID], actor_id: UUID
) -> None:
    if note_id is None or not recipient_ids:
        return
    hub = await note_hub_registry.try_get(note_id)
    if hub is not None:
        await hub.broadcast(
            {
                "type": "access.changed",
                "note_id": str(note_id),
                "actor_id": str(actor_id),
                "recipients": [str(user_id) for user_id in recipient_ids],
            }
        )


def _attention_read(row) -> AttentionItemRead:
    item, event, actor = row
    return AttentionItemRead(
        id=item.id,
        kind=item.kind,
        event_type=event.event_type,
        title=event.title,
        body=event.body,
        link=event.link,
        source_type=event.source_type,
        source_key=event.source_key,
        actor_id=event.actor_id,
        actor_name=actor.full_name if actor else None,
        actor_email=actor.email if actor else None,
        is_read=item.is_read,
        created_at=event.created_at,
        updated_at=item.updated_at,
    )


@router.get("/summary", response_model=AttentionSummaryRead)
async def attention_summary(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    direct_count, important_count = await get_attention_summary(db, current_user.id)
    return AttentionSummaryRead(
        direct_count=direct_count,
        important_count=important_count,
    )


@router.get("/attention", response_model=list[AttentionItemRead])
async def attention_list(
    kind: str = Query(..., pattern="^(direct|important)$"),
    unread_only: bool = Query(True),
    limit: int = Query(100, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = await list_attention_items(
        db,
        user_id=current_user.id,
        kind=kind,
        unread_only=unread_only,
        limit=limit,
    )
    return [_attention_read(row) for row in rows]


@router.post("/attention/context/read")
async def read_attention_context(
    payload: AttentionContextRead,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    count = await mark_attention_context_read(
        db,
        user_id=current_user.id,
        source_type=payload.source_type,
        source_key=payload.source_key,
    )
    await db.commit()
    if count:
        await attention_hub.send_to_user(current_user.id, {"type": "attention.changed"})
    return {"marked": count}


@router.post("/attention/{item_id}/read")
async def read_attention_item(
    item_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    item = await mark_attention_read(db, user_id=current_user.id, item_id=item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Событие не найдено")
    await db.commit()
    await attention_hub.send_to_user(current_user.id, {"type": "attention.changed"})
    return {"read": True, "item_id": str(item.id)}


@router.get("/threads", response_model=list[MessageThreadRead])
async def list_threads(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    rows = (
        await db.execute(
            select(MessageThread, MessageThreadParticipant)
            .join(
                MessageThreadParticipant,
                MessageThreadParticipant.thread_id == MessageThread.id,
            )
            .where(MessageThreadParticipant.user_id == current_user.id)
            .order_by(MessageThread.updated_at.desc(), MessageThread.id.desc())
            .limit(100)
        )
    ).all()
    if not rows:
        return []

    thread_ids = [thread.id for thread, _ in rows]
    all_participants = (
        await db.execute(
            select(MessageThreadParticipant, User)
            .join(User, User.id == MessageThreadParticipant.user_id)
            .where(MessageThreadParticipant.thread_id.in_(thread_ids))
            .order_by(
                MessageThreadParticipant.thread_id.asc(),
                MessageThreadParticipant.joined_at.asc(),
            )
        )
    ).all()
    participants_by_thread: dict[
        UUID, list[tuple[MessageThreadParticipant, User]]
    ] = {thread_id: [] for thread_id in thread_ids}
    for member, user in all_participants:
        participants_by_thread[member.thread_id].append((member, user))

    latest_posts = list(
        (
            await db.execute(
                select(MessagePost)
                .where(MessagePost.thread_id.in_(thread_ids))
                .distinct(MessagePost.thread_id)
                .order_by(
                    MessagePost.thread_id.asc(),
                    MessagePost.created_at.desc(),
                    MessagePost.id.desc(),
                )
            )
        ).scalars().all()
    )
    latest_by_thread = {post.thread_id: post for post in latest_posts}

    result: list[MessageThreadRead] = []
    for thread, current_participant in rows:
        last = latest_by_thread.get(thread.id)
        if last is None:
            continue
        result.append(
            MessageThreadRead(
                id=thread.id,
                subject=thread.subject,
                created_by_id=thread.created_by_id,
                participants=_participant_reads(participants_by_thread[thread.id]),
                last_post_preview=" ".join(last.body.split())[:180],
                last_post_at=last.created_at,
                unread_count=current_participant.unread_count,
                created_at=thread.created_at,
                updated_at=thread.updated_at,
            )
        )
    return result


@router.post("/threads", response_model=MessageThreadDetailRead, status_code=201)
async def create_thread(
    payload: MessageThreadCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if payload.recipient_id == current_user.id:
        raise HTTPException(status_code=400, detail="Нельзя написать самому себе")
    recipient = (
        await db.execute(
            select(User).where(
                User.id == payload.recipient_id,
                User.is_active.is_(True),
            )
        )
    ).scalar_one_or_none()
    if recipient is None:
        raise HTTPException(status_code=404, detail="Получатель не найден")
    if not await _accepted_contact(db, current_user.id, recipient.id):
        raise HTTPException(
            status_code=403,
            detail="Написать можно только принятому контакту",
        )
    note = await _owned_note_or_404(db, payload.quick_note_id, current_user.id)

    existing = (
        await db.execute(
            select(MessageThread).where(
                MessageThread.created_by_id == current_user.id,
                MessageThread.request_id == payload.request_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        participants = {user.id for _, user in await _thread_users(db, existing.id)}
        first_post = (
            await db.execute(
                select(MessagePost)
                .where(MessagePost.thread_id == existing.id)
                .order_by(MessagePost.created_at.asc(), MessagePost.id.asc())
                .limit(1)
            )
        ).scalar_one()
        if (
            existing.subject != payload.subject
            or participants != {current_user.id, recipient.id}
            or first_post.body != payload.body
            or first_post.quick_note_id != payload.quick_note_id
        ):
            raise HTTPException(
                status_code=409,
                detail="Этот идентификатор запроса уже использован для другого письма",
            )
        return await _thread_detail(db, existing.id, current_user.id)

    thread_id = (
        await db.execute(
            insert(MessageThread)
            .values(
                id=uuid.uuid4(),
                subject=payload.subject,
                created_by_id=current_user.id,
                request_id=payload.request_id,
            )
            .on_conflict_do_nothing(
                constraint="uq_message_threads_creator_request"
            )
            .returning(MessageThread.id)
        )
    ).scalar_one_or_none()
    if thread_id is None:
        existing = (
            await db.execute(
                select(MessageThread).where(
                    MessageThread.created_by_id == current_user.id,
                    MessageThread.request_id == payload.request_id,
                )
            )
        ).scalar_one()
        participants = {user.id for _, user in await _thread_users(db, existing.id)}
        first_post = (
            await db.execute(
                select(MessagePost)
                .where(MessagePost.thread_id == existing.id)
                .order_by(MessagePost.created_at.asc(), MessagePost.id.asc())
                .limit(1)
            )
        ).scalar_one()
        if (
            existing.subject != payload.subject
            or participants != {current_user.id, recipient.id}
            or first_post.body != payload.body
            or first_post.quick_note_id != payload.quick_note_id
        ):
            raise HTTPException(
                status_code=409,
                detail="Этот идентификатор запроса уже использован для другого письма",
            )
        return await _thread_detail(db, existing.id, current_user.id)

    thread = (
        await db.execute(select(MessageThread).where(MessageThread.id == thread_id))
    ).scalar_one()
    first_post = MessagePost(
        id=uuid.uuid4(),
        thread_id=thread.id,
        author_id=current_user.id,
        body=payload.body,
        quick_note_id=payload.quick_note_id,
        request_id=payload.request_id,
    )
    db.add_all(
        [
            MessageThreadParticipant(
                thread_id=thread.id,
                user_id=current_user.id,
                unread_count=0,
                last_read_at=datetime.now(timezone.utc),
            ),
            MessageThreadParticipant(
                thread_id=thread.id,
                user_id=recipient.id,
                unread_count=1,
            ),
            first_post,
        ]
    )
    await db.flush()
    activated = await _share_note_without_attention(
        db,
        note=note,
        owner_id=current_user.id,
        recipient_ids=[recipient.id],
    )
    await enqueue_message_notification(
        db,
        post_id=first_post.id,
        thread_id=thread.id,
        recipient=recipient,
        sender_name=current_user.full_name,
    )
    await db.commit()
    await attention_hub.send_to_users(
        [current_user.id, recipient.id],
        {"type": "thread.changed", "thread_id": str(thread.id)},
    )
    await _broadcast_note_access(payload.quick_note_id, activated, current_user.id)
    return await _thread_detail(db, thread.id, current_user.id)


@router.get("/threads/{thread_id}", response_model=MessageThreadDetailRead)
async def get_thread(
    thread_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await _thread_detail(db, thread_id, current_user.id)


@router.post("/threads/{thread_id}/posts", response_model=MessagePostRead)
async def create_post(
    thread_id: UUID,
    payload: MessagePostCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _participant_or_404(db, thread_id, current_user.id)
    participant_rows = await _thread_users(db, thread_id)
    other_users = [user for _, user in participant_rows if user.id != current_user.id]
    if not other_users:
        raise HTTPException(status_code=409, detail="В переписке отсутствует получатель")
    for other_user in other_users:
        if not other_user.is_active or not await _accepted_contact(
            db, current_user.id, other_user.id
        ):
            raise HTTPException(
                status_code=403,
                detail="Контакт больше не активен. История доступна только для чтения",
            )
    note = await _owned_note_or_404(db, payload.quick_note_id, current_user.id)

    existing = (
        await db.execute(
            select(MessagePost).where(
                MessagePost.author_id == current_user.id,
                MessagePost.request_id == payload.request_id,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if (
            existing.thread_id != thread_id
            or existing.body != payload.body
            or existing.quick_note_id != payload.quick_note_id
        ):
            raise HTTPException(
                status_code=409,
                detail="Этот идентификатор запроса уже использован для другого ответа",
            )
        return await _post_read(db, existing, current_user.id)

    now = datetime.now(timezone.utc)
    post_id = (
        await db.execute(
            insert(MessagePost)
            .values(
                id=uuid.uuid4(),
                thread_id=thread_id,
                author_id=current_user.id,
                body=payload.body,
                quick_note_id=payload.quick_note_id,
                request_id=payload.request_id,
                created_at=now,
            )
            .on_conflict_do_nothing(constraint="uq_message_posts_author_request")
            .returning(MessagePost.id)
        )
    ).scalar_one_or_none()
    if post_id is None:
        existing = (
            await db.execute(
                select(MessagePost).where(
                    MessagePost.author_id == current_user.id,
                    MessagePost.request_id == payload.request_id,
                )
            )
        ).scalar_one()
        if (
            existing.thread_id != thread_id
            or existing.body != payload.body
            or existing.quick_note_id != payload.quick_note_id
        ):
            raise HTTPException(
                status_code=409,
                detail="Этот идентификатор запроса уже использован для другого ответа",
            )
        return await _post_read(db, existing, current_user.id)

    post = (
        await db.execute(select(MessagePost).where(MessagePost.id == post_id))
    ).scalar_one()
    await db.execute(
        update(MessageThread)
        .where(MessageThread.id == thread_id)
        .values(updated_at=now)
    )
    await db.execute(
        update(MessageThreadParticipant)
        .where(
            MessageThreadParticipant.thread_id == thread_id,
            MessageThreadParticipant.user_id != current_user.id,
        )
        .values(unread_count=MessageThreadParticipant.unread_count + 1)
    )
    activated = await _share_note_without_attention(
        db,
        note=note,
        owner_id=current_user.id,
        recipient_ids=[user.id for user in other_users],
    )
    for recipient in other_users:
        await enqueue_message_notification(
            db,
            post_id=post.id,
            thread_id=thread_id,
            recipient=recipient,
            sender_name=current_user.full_name,
        )
    await db.commit()
    await attention_hub.send_to_users(
        [user.id for _, user in participant_rows],
        {"type": "thread.changed", "thread_id": str(thread_id)},
    )
    await _broadcast_note_access(payload.quick_note_id, activated, current_user.id)
    return await _post_read(db, post, current_user.id)


@router.post("/threads/{thread_id}/read")
async def read_thread(
    thread_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    participant = await _participant_or_404(
        db, thread_id, current_user.id, for_update=True
    )
    previous = participant.unread_count
    participant.unread_count = 0
    participant.last_read_at = datetime.now(timezone.utc)
    await db.commit()
    if previous:
        await attention_hub.send_to_user(
            current_user.id,
            {"type": "thread.read", "thread_id": str(thread_id)},
        )
    return {"read": True, "thread_id": str(thread_id)}


async def _authenticate_ws_user(token: str, db: AsyncSession) -> User:
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Невалидный токен")
    token_auth_version = payload.get("ver", 0)
    if type(token_auth_version) is not int or token_auth_version < 0:
        raise HTTPException(status_code=401, detail="Невалидный токен")
    sub = payload.get("sub")
    try:
        user_id = UUID(sub) if isinstance(sub, str) else sub
    except (TypeError, ValueError):
        raise HTTPException(status_code=401, detail="Невалидный токен")
    user = (
        await db.execute(select(User).where(User.id == user_id))
    ).scalar_one_or_none()
    if (
        user is None
        or not user.is_active
        or user.auth_version != token_auth_version
        or user.password_change_required
    ):
        raise HTTPException(status_code=401, detail="Сессия недоступна")
    return user


@router.websocket("/live")
async def messages_live(websocket: WebSocket) -> None:
    """User-level resync hints; the JWT is accepted only in the first frame."""
    await websocket.accept()
    try:
        auth_raw = await asyncio.wait_for(websocket.receive_text(), timeout=10)
        auth_message = json.loads(auth_raw)
    except (asyncio.TimeoutError, WebSocketDisconnect, RuntimeError, json.JSONDecodeError):
        await websocket.close(code=1008)
        return
    if (
        not isinstance(auth_message, dict)
        or auth_message.get("type") != "auth"
        or not isinstance(auth_message.get("token"), str)
    ):
        await websocket.close(code=1008)
        return
    async with AsyncSessionLocal() as db:
        try:
            user = await _authenticate_ws_user(auth_message["token"], db)
        except HTTPException:
            await websocket.close(code=1008)
            return

    connection = AttentionConnection(websocket=websocket)
    attention_hub.add(user.id, connection)
    try:
        await websocket.send_text(json.dumps({"type": "ready"}, ensure_ascii=False))
        while True:
            raw = await websocket.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(message, dict) and message.get("type") == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        attention_hub.remove(user.id, connection)
