"""Persistence rules for owner-only graph snapshots."""
from __future__ import annotations

import hashlib
import json
from uuid import UUID

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.graph_document import GraphDocument, utc_now
from app.models.user import User
from app.schemas.graph import GraphDocumentRead, GraphDocumentWrite, GraphMetadataRead


MAX_GRAPHS_PER_USER = 100
MAX_GRAPH_BYTES = 5 * 1024 * 1024
MAX_TOTAL_BYTES_PER_USER = 50 * 1024 * 1024


def graph_error(status_code: int, code: str, message: str, **details) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={"code": code, "message": message, **details},
    )


def canonical_payload(body: GraphDocumentWrite) -> tuple[dict, bytes, str]:
    payload = body.payload.model_dump(mode="json")
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return payload, encoded, hashlib.sha256(encoded).hexdigest()


async def lock_owner(db: AsyncSession, owner_id: UUID) -> None:
    await db.execute(select(User.id).where(User.id == owner_id).with_for_update())


async def owned_graph(
    db: AsyncSession,
    owner_id: UUID,
    client_id: str,
    *,
    lock: bool = False,
) -> GraphDocument | None:
    query = select(GraphDocument).where(
        GraphDocument.owner_id == owner_id,
        GraphDocument.client_id == client_id,
    )
    if lock:
        query = query.with_for_update()
    return (await db.execute(query)).scalar_one_or_none()


def metadata_read(document: GraphDocument) -> GraphMetadataRead:
    return GraphMetadataRead.model_validate(document)


def document_read(document: GraphDocument) -> GraphDocumentRead:
    return GraphDocumentRead.model_validate(document)


async def list_graphs(db: AsyncSession, owner_id: UUID) -> list[GraphMetadataRead]:
    documents = (
        await db.execute(
            select(GraphDocument)
            .where(GraphDocument.owner_id == owner_id)
            .order_by(GraphDocument.updated_at.desc(), GraphDocument.client_id)
        )
    ).scalars().all()
    return [metadata_read(document) for document in documents]


async def read_graph(db: AsyncSession, owner_id: UUID, client_id: str) -> GraphDocumentRead:
    document = await owned_graph(db, owner_id, client_id)
    if document is None:
        raise graph_error(status.HTTP_404_NOT_FOUND, "graph_not_found", "Граф не найден")
    return document_read(document)


async def save_graph(
    db: AsyncSession,
    owner_id: UUID,
    client_id: str,
    body: GraphDocumentWrite,
) -> GraphDocumentRead:
    if client_id != body.payload.id:
        raise graph_error(
            status.HTTP_409_CONFLICT,
            "graph_id_mismatch",
            "ID графа в адресе и документе не совпадают",
        )

    payload, encoded, content_hash = canonical_payload(body)
    payload_bytes = len(encoded)
    if payload_bytes > MAX_GRAPH_BYTES:
        raise graph_error(
            413,
            "graph_too_large",
            "Размер одного графа не должен превышать 5 МБ",
            limit_bytes=MAX_GRAPH_BYTES,
            actual_bytes=payload_bytes,
        )

    await lock_owner(db, owner_id)
    document = await owned_graph(db, owner_id, client_id, lock=True)

    if document is not None and document.content_hash == content_hash:
        return document_read(document)

    if document is None and body.base_revision is not None:
        raise graph_error(status.HTTP_404_NOT_FOUND, "graph_not_found", "Граф не найден")
    if document is not None and body.base_revision is None:
        raise graph_error(
            status.HTTP_409_CONFLICT,
            "graph_already_exists",
            "Граф с таким ID уже сохранён в системе",
            server_revision=document.revision,
        )
    if document is not None and body.base_revision != document.revision:
        raise graph_error(
            status.HTTP_409_CONFLICT,
            "graph_revision_conflict",
            "Граф изменился в другой вкладке или на другом устройстве",
            server_revision=document.revision,
        )

    count = (
        await db.execute(
            select(func.count()).select_from(GraphDocument).where(GraphDocument.owner_id == owner_id)
        )
    ).scalar_one()
    if document is None and count >= MAX_GRAPHS_PER_USER:
        raise graph_error(
            status.HTTP_409_CONFLICT,
            "graph_count_limit",
            "Достигнут лимит: 100 графов в системе",
            limit=MAX_GRAPHS_PER_USER,
        )

    total_bytes = (
        await db.execute(
            select(func.coalesce(func.sum(GraphDocument.payload_bytes), 0)).where(
                GraphDocument.owner_id == owner_id
            )
        )
    ).scalar_one()
    projected_bytes = int(total_bytes) - (document.payload_bytes if document else 0) + payload_bytes
    if projected_bytes > MAX_TOTAL_BYTES_PER_USER:
        raise graph_error(
            413,
            "graph_storage_limit",
            "Достигнут лимит серверного хранения графов: 50 МБ",
            limit_bytes=MAX_TOTAL_BYTES_PER_USER,
            projected_bytes=projected_bytes,
        )

    now = utc_now()
    if document is None:
        document = GraphDocument(
            owner_id=owner_id,
            client_id=client_id,
            revision=1,
            created_at=now,
        )
        db.add(document)
    else:
        document.revision += 1

    document.title = body.payload.title
    document.payload = payload
    document.content_hash = content_hash
    document.payload_bytes = payload_bytes
    document.node_count = len(body.payload.nodes)
    document.edge_count = len(body.payload.edges)
    document.updated_at = now
    await db.flush()
    return document_read(document)


async def delete_graph(
    db: AsyncSession,
    owner_id: UUID,
    client_id: str,
    base_revision: int,
) -> None:
    await lock_owner(db, owner_id)
    document = await owned_graph(db, owner_id, client_id, lock=True)
    if document is None:
        raise graph_error(status.HTTP_404_NOT_FOUND, "graph_not_found", "Граф не найден")
    if document.revision != base_revision:
        raise graph_error(
            status.HTTP_409_CONFLICT,
            "graph_revision_conflict",
            "Граф изменился в другой вкладке или на другом устройстве",
            server_revision=document.revision,
        )
    await db.delete(document)
    await db.flush()
