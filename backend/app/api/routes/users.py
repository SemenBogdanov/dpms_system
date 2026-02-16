"""API пользователей."""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user, require_role
from app.models.user import User, League, UserRole
from app.schemas.user import UserCreate, UserRead, UserUpdate
from app.schemas.dashboard import UserProgress
from app.schemas.transaction import QTransactionRead
from app.schemas.leagues import LeagueProgress
from app.services.analytics import get_user_progress
from app.services.leagues import get_league_progress as get_league_progress_svc

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
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_role("admin")),
):
    """Создать сотрудника (только admin). Проверка уникальности email."""
    from app.core.security import get_password_hash

    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")
    user = User(
        full_name=body.full_name,
        email=body.email,
        league=body.league,
        role=body.role,
        mpw=body.mpw,
        wip_limit=2,
        is_active=True,
        password_hash=get_password_hash(body.password),
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
    _: User = Depends(require_role("admin")),
):
    """Обновить сотрудника (только admin)."""
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.email is not None:
        other = await db.execute(select(User).where(User.email == body.email, User.id != user_id))
        if other.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")
        user.email = body.email
    if body.role is not None:
        user.role = body.role
    if body.league is not None:
        user.league = body.league
    if body.mpw is not None:
        user.mpw = body.mpw
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


@router.get("/{user_id}/league-progress", response_model=LeagueProgress)
async def get_league_progress_route(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Прогресс к следующей лиге. Свои данные — всегда; чужие — admin/teamlead."""
    if current_user.id != user_id and current_user.role not in (UserRole.admin, UserRole.teamlead):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    progress = await get_league_progress_svc(db, user_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return progress


@router.get("/{user_id}/transactions", response_model=list[QTransactionRead])
async def get_user_transactions(
    user_id: UUID,
    wallet_type: str | None = Query(None, description="main | karma"),
    direction: str | None = Query(None, description="credit | debit"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """История операций. Свои — всегда; чужие — только admin/teamlead."""
    from app.api.deps import get_current_user

    if current_user.id != user_id and current_user.role.value not in ("admin", "teamlead"):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
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
