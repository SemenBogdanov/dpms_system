"""API аутентификации: login, set-password, me."""
from fastapi import APIRouter, Depends, HTTPException, status

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user
from app.core.security import verify_password, get_password_hash, create_access_token
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, SetPasswordRequest
from app.schemas.user import UserRead

router = APIRouter()


def _user_to_read(user: User) -> UserRead:
    return UserRead(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        league=user.league,
        role=user.role,
        mpw=user.mpw,
        wip_limit=user.wip_limit,
        is_active=user.is_active,
        wallet_main=float(user.wallet_main),
        wallet_karma=float(user.wallet_karma),
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Вход по email и паролю.
    Если у пользователя password_hash is NULL — принять любой пароль и вернуть токен
    (фронт покажет форму установки пароля).
    """
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь деактивирован",
        )
    if user.password_hash:
        if not verify_password(body.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Неверный email или пароль",
            )
    # Если password_hash пустой — первый вход, пароль не проверяем
    token = create_access_token(data={"sub": str(user.id)})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=_user_to_read(user),
    )


@router.post("/set-password")
async def set_password(
    body: SetPasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Установить пароль (для пользователей с password_hash=NULL или смена пароля)."""
    user.password_hash = get_password_hash(body.new_password)
    db.add(user)
    await db.flush()
    return {"message": "Пароль установлен"}


@router.get("/me", response_model=UserRead)
async def me(
    user: User = Depends(get_current_user),
):
    """Текущий пользователь по JWT."""
    return _user_to_read(user)
