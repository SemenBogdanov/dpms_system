"""API каталога операций. GET — публичный; POST/PATCH/DELETE — admin/teamlead."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_role
from app.models.user import User
from app.models.catalog import CatalogItem, CatalogCategory, Complexity
from app.schemas.catalog import CatalogItemCreate, CatalogItemRead, CatalogItemUpdate

router = APIRouter()


@router.get("", response_model=list[CatalogItemRead])
async def list_catalog(
    category: CatalogCategory | None = Query(None),
    complexity: Complexity | None = Query(None),
    is_active: bool | None = Query(None),
    search: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Справочник операций с фильтрами."""
    stmt = select(CatalogItem).order_by(CatalogItem.category, CatalogItem.name)
    if category is not None:
        stmt = stmt.where(CatalogItem.category == category)
    if complexity is not None:
        stmt = stmt.where(CatalogItem.complexity == complexity)
    if is_active is not None:
        stmt = stmt.where(CatalogItem.is_active == is_active)
    if search and search.strip():
        stmt = stmt.where(CatalogItem.name.ilike(f"%{search.strip()}%"))
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=CatalogItemRead)
async def create_catalog_item(
    body: CatalogItemCreate,
    user: User = Depends(require_role("admin", "teamlead")),
    db: AsyncSession = Depends(get_db),
):
    """Добавить позицию в каталог."""
    item = CatalogItem(
        category=body.category,
        name=body.name,
        complexity=body.complexity,
        base_cost_q=body.base_cost_q,
        description=body.description,
        min_league=body.min_league,
        is_active=body.is_active,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    return item


@router.get("/{item_id}", response_model=CatalogItemRead)
async def get_catalog_item(
    item_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Одна позиция каталога."""
    result = await db.execute(select(CatalogItem).where(CatalogItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    return item


@router.patch("/{item_id}", response_model=CatalogItemRead)
async def update_catalog_item(
    item_id: UUID,
    body: CatalogItemUpdate,
    user: User = Depends(require_role("admin", "teamlead")),
    db: AsyncSession = Depends(get_db),
):
    """Обновить позицию (частично)."""
    result = await db.execute(select(CatalogItem).where(CatalogItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Позиция каталога не найдена")
    if body.name is not None:
        item.name = body.name
    if body.category is not None:
        item.category = body.category
    if body.complexity is not None:
        item.complexity = body.complexity
    if body.base_cost_q is not None:
        item.base_cost_q = body.base_cost_q
    if body.min_league is not None:
        item.min_league = body.min_league
    if body.description is not None:
        item.description = body.description
    if body.is_active is not None:
        item.is_active = body.is_active
    await db.flush()
    await db.refresh(item)
    return item


@router.delete("/{item_id}", response_model=CatalogItemRead)
async def deactivate_catalog_item(
    item_id: UUID,
    user: User = Depends(require_role("admin", "teamlead")),
    db: AsyncSession = Depends(get_db),
):
    """Деактивировать позицию (is_active=false), не удаляя из БД."""
    result = await db.execute(select(CatalogItem).where(CatalogItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Позиция каталога не найдена")
    item.is_active = False
    await db.flush()
    await db.refresh(item)
    return item
