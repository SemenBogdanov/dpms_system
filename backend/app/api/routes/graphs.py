"""Private server storage for graph documents."""
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.models.user import User
from app.schemas.graph import (
    CLIENT_ID_PATTERN,
    GraphDeleteRead,
    GraphDocumentRead,
    GraphDocumentWrite,
    GraphMetadataRead,
)
from app.services import graph_documents as service


router = APIRouter()
ClientId = Annotated[str, Path(pattern=CLIENT_ID_PATTERN)]


@router.get("", response_model=list[GraphMetadataRead])
async def list_graphs(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.list_graphs(db, user.id)


@router.get("/{client_id}", response_model=GraphDocumentRead)
async def get_graph(
    client_id: ClientId,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.read_graph(db, user.id, client_id)


@router.put("/{client_id}", response_model=GraphDocumentRead)
async def put_graph(
    client_id: ClientId,
    body: GraphDocumentWrite,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    return await service.save_graph(db, user.id, client_id, body)


@router.delete("/{client_id}", response_model=GraphDeleteRead)
async def remove_graph(
    client_id: ClientId,
    base_revision: int = Query(ge=1),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await service.delete_graph(db, user.id, client_id, base_revision)
    return GraphDeleteRead(client_id=client_id)
