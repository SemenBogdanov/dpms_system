"""Admin-only, read-only server boot journal."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.schemas.server_boot import ServerBootListRead
from app.services.server_boot import MAX_OFFSET, list_server_boots


router = APIRouter(dependencies=[Depends(require_role("admin"))])


@router.get("", response_model=ServerBootListRead)
async def get_server_boots(
    days: int = Query(default=0, ge=0, le=366),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=MAX_OFFSET),
    db: AsyncSession = Depends(get_db),
):
    return await list_server_boots(db, days=days, limit=limit, offset=offset)
