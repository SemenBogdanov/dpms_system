"""Minimal local participant management for competency assignments."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, require_admin
from app.core.security import get_password_hash, validate_password_strength
from app.models.user import League, User, UserRole
from app.schemas.user import UserCreate, UserRead, UserUpdate


router = APIRouter()


@router.get("", response_model=list[UserRead])
async def list_users(
    is_active: bool | None = Query(default=None),
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    query = select(User).order_by(User.full_name, User.email)
    if is_active is not None:
        query = query.where(User.is_active.is_(is_active))
    return list((await db.execute(query)).scalars().all())


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    body: UserCreate,
    _admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    password_errors = validate_password_strength(body.password)
    if password_errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=password_errors)
    email = str(body.email).strip().lower()
    existing = await db.execute(select(User.id).where(func.lower(User.email) == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Пользователь с такой почтой уже существует")
    user = User(
        full_name=body.full_name.strip(),
        email=email,
        password_hash=get_password_hash(body.password),
        role=body.role,
        league=League.A if body.role == UserRole.admin else League.C,
        competency_development_enabled=True,
        competency_constructor_enabled=body.competency_constructor_enabled or body.role == UserRole.admin,
        is_active=True,
    )
    db.add(user)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Пользователь уже существует") from exc
    return user


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: UUID,
    body: UserUpdate,
    admin: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    fields = body.model_fields_set
    if "full_name" in fields and body.full_name:
        user.full_name = body.full_name.strip()
    if "email" in fields and body.email:
        user.email = str(body.email).strip().lower()
    if "role" in fields and body.role is not None:
        if user.id == admin.id and body.role != UserRole.admin:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Нельзя снять роль администратора с собственной учетной записи",
            )
        user.role = body.role
    if "competency_constructor_enabled" in fields and body.competency_constructor_enabled is not None:
        user.competency_constructor_enabled = body.competency_constructor_enabled
    if "is_active" in fields and body.is_active is not None:
        if user.id == admin.id and not body.is_active:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Нельзя отключить собственную учетную запись")
        user.is_active = body.is_active
        if not body.is_active:
            user.auth_version += 1
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Пользователь с такой почтой уже существует") from exc
    return user
