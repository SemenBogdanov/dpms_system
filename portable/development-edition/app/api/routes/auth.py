"""Local authentication endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse
from app.schemas.user import AuthenticatedUserRead


router = APIRouter()
DUMMY_HASH = get_password_hash("Portable-development-dummy-2026")


def user_read(user: User) -> AuthenticatedUserRead:
    return AuthenticatedUserRead.model_validate(user)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    email = str(body.email).strip().lower()
    result = await db.execute(select(User).where(func.lower(User.email) == email))
    user = result.scalar_one_or_none()
    password_valid = verify_password(body.password, user.password_hash if user else DUMMY_HASH)
    if user is None or not user.is_active or not password_valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный email или пароль")
    return TokenResponse(
        access_token=create_access_token(user.id, user.auth_version),
        user=user_read(user),
    )


@router.get("/me", response_model=AuthenticatedUserRead)
async def me(user: User = Depends(get_current_user)):
    return user_read(user)
