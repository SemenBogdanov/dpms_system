"""API каталога операций."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.catalog import CatalogItem, CatalogCategory, Complexity
from app.schemas.catalog import CatalogItemCreate, CatalogItemRead, CatalogItemUpdate

router = APIRouter()


@router.get("", response_model=list[CatalogItemRead])
async def list_catalog(
    category: CatalogCategory | None = Query(None),
    complexity: Complexity | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Справочник операций с фильтрами."""
    stmt = select(CatalogItem).order_by(CatalogItem.category, CatalogItem.name)
    if category is not None:
        stmt = stmt.where(CatalogItem.category == category)
    if complexity is not None:
        stmt = stmt.where(CatalogItem.complexity == complexity)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.post("", response_model=CatalogItemRead)
async def create_catalog_item(
    body: CatalogItemCreate,
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
    db: AsyncSession = Depends(get_db),
):
    """Обновить позицию (base_cost_q, is_active)."""
    result = await db.execute(select(CatalogItem).where(CatalogItem.id == item_id))
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Catalog item not found")
    if body.base_cost_q is not None:
        item.base_cost_q = body.base_cost_q
    if body.is_active is not None:
        item.is_active = body.is_active
    await db.flush()
    await db.refresh(item)
    return item
