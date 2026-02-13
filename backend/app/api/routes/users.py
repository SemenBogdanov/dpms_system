"""API пользователей."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.models.user import User, League, UserRole
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.schemas.dashboard import UserProgress
from app.schemas.transaction import QTransactionRead
from app.services.analytics import get_user_progress

router = APIRouter()


@router.get("", response_model=list[UserRead])
async def list_users(
    league: League | None = Query(None),
    is_active: bool | None = Query(None),
    role: UserRole | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Список сотрудников с фильтрами по лиге, is_active и роли."""
    stmt = select(User).order_by(User.full_name)
    if league is not None:
        stmt = stmt.where(User.league == league)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    if role is not None:
        stmt = stmt.where(User.role == role)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{user_id}", response_model=UserRead)
async def get_user(user_id: UUID, db: AsyncSession = Depends(get_db)):
    """Профиль пользователя."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("", response_model=UserRead)
async def create_user(body: UserCreate, db: AsyncSession = Depends(get_db)):
    """Создать пользователя (admin only — проверка роли в MVP не делаем)."""
    user = User(
        full_name=body.full_name,
        email=body.email,
        league=body.league,
        role=body.role,
        mpw=body.mpw,
        wip_limit=body.wip_limit,
        is_active=body.is_active,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: UUID,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Обновить пользователя (league, mpw, wip_limit)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if body.league is not None:
        user.league = body.league
    if body.mpw is not None:
        user.mpw = body.mpw
    if body.wip_limit is not None:
        user.wip_limit = body.wip_limit
    if body.is_active is not None:
        user.is_active = body.is_active
    await db.flush()
    await db.refresh(user)
    return user


@router.get("/{user_id}/progress", response_model=UserProgress)
async def get_user_progress_route(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Прогресс пользователя: earned/target/karma."""
    progress = await get_user_progress(db, user_id)
    if not progress:
        raise HTTPException(status_code=404, detail="User not found")
    return progress


@router.get("/{user_id}/transactions", response_model=list[QTransactionRead])
async def get_user_transactions(
    user_id: UUID,
    wallet_type: str | None = Query(None, description="main | karma"),
    direction: str | None = Query(None, description="credit | debit"),
    db: AsyncSession = Depends(get_db),
):
    """История операций пользователя. Фильтры: wallet_type, direction (credit=приход, debit=расход)."""
    from app.models.transaction import QTransaction, WalletType

    stmt = select(QTransaction).where(QTransaction.user_id == user_id)
    if wallet_type is not None:
        try:
            wt = WalletType(wallet_type)
            stmt = stmt.where(QTransaction.wallet_type == wt)
        except ValueError:
            pass
    if direction == "credit":
        stmt = stmt.where(QTransaction.amount > 0)
    elif direction == "debit":
        stmt = stmt.where(QTransaction.amount < 0)
    stmt = stmt.order_by(QTransaction.created_at.desc())
    result = await db.execute(stmt)
    return list(result.scalars().all())
