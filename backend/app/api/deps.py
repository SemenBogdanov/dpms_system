"""Зависимости API: get_db, get_current_user, require_role."""
from collections.abc import AsyncGenerator
from typing import Callable
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import AsyncSessionLocal
from app.models.user import User, UserRole
from app.core.security import decode_access_token, is_temporary_password_valid

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login", auto_error=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Сессия БД для эндпоинтов."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def get_current_user(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Вернуть пользователя с полноценной активной сессией."""
    user = await _get_authenticated_user(request, token, db)
    if user.password_change_required:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Сначала смените временный пароль",
        )
    return user


async def get_current_user_for_password_setup(
    request: Request,
    token: str | None = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Вернуть пользователя, разрешая ограниченную сессию первого входа."""
    user = await _get_authenticated_user(request, token, db)
    if not is_temporary_password_valid(
        user.password_change_required,
        user.temporary_password_expires_at,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Срок действия временного пароля истек. Обратитесь к администратору",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


async def _get_authenticated_user(
    request: Request,
    token: str | None,
    db: AsyncSession,
) -> User:
    """
    Декодировать JWT и проверить пользователя вместе с auth_version.

    Токены, выданные до появления claim ver, считаются версией 0. Это
    сохраняет текущие сессии до первой смены или административного сброса
    пароля, после чего auth_version инвалидирует все старые токены.
    """
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Требуется авторизация",
            headers={"WWW-Authenticate": "Bearer"},
        )
    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный или истёкший токен",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token_auth_version = payload.get("ver", 0)
    if type(token_auth_version) is not int or token_auth_version < 0:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный токен",
            headers={"WWW-Authenticate": "Bearer"},
        )
    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный токен",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        user_id = UUID(sub) if isinstance(sub, str) else sub
    except (ValueError, TypeError):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Невалидный токен",
            headers={"WWW-Authenticate": "Bearer"},
        )
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь не найден",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Пользователь деактивирован",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if user.auth_version != token_auth_version:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия завершена. Войдите снова",
            headers={"WWW-Authenticate": "Bearer"},
        )
    request.state.token_auth_version = token_auth_version
    return user


def require_role(*allowed_roles: str) -> Callable:
    """
    Dependency factory: require_role("admin", "teamlead").
    Проверяет роль текущего пользователя. Если роль не подходит → 403.
    """

    async def _require_role(
        user: User = Depends(get_current_user),
    ) -> User:
        if user.role.value not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав",
            )
        return user

    return _require_role


def ensure_task_workspace_access(user: User) -> User:
    """Allow task workspace APIs only for admins or users enabled by admin."""
    if user.role == UserRole.admin or user.task_workspace_enabled:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Раздел работы с задачами недоступен",
    )


async def require_task_workspace_access(
    user: User = Depends(get_current_user),
) -> User:
    """Dependency: current user must have the task workspace feature enabled."""
    return ensure_task_workspace_access(user)


def require_task_workspace_role(*allowed_roles: str) -> Callable:
    """Dependency factory: feature gate + role gate for task workspace APIs."""

    async def _require_task_workspace_role(
        user: User = Depends(get_current_user),
    ) -> User:
        ensure_task_workspace_access(user)
        if user.role.value not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав",
            )
        return user

    return _require_task_workspace_role


def ensure_audit_access(user: User) -> User:
    """Allow audit APIs only for admins or users explicitly enabled by admin."""
    if user.role == UserRole.admin or user.audit_enabled:
        return user
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Раздел аудита недоступен",
    )


async def require_audit_access(
    user: User = Depends(get_current_user),
) -> User:
    """Dependency: current user must have the audit feature enabled."""
    return ensure_audit_access(user)


def require_audit_role(*allowed_roles: str) -> Callable:
    """Dependency factory: audit feature gate plus role gate."""

    async def _require_audit_role(
        user: User = Depends(get_current_user),
    ) -> User:
        ensure_audit_access(user)
        if user.role.value not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Недостаточно прав",
            )
        return user

    return _require_audit_role
