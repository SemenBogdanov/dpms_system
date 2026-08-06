from fastapi import APIRouter, Depends, HTTPException, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user, get_current_user_for_password_setup
from app.core.security import (
    create_access_token,
    get_password_hash,
    is_temporary_password_valid,
    validate_password_strength,
    verify_password,
    verify_password_or_dummy,
)
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, SetPasswordRequest, ChangePasswordRequest
from app.schemas.user import AuthenticatedUserRead, SidebarMenuOrderUpdate
from app.services.activity import record_activity_event

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


def _user_to_read(user: User) -> AuthenticatedUserRead:
    return AuthenticatedUserRead(
        id=user.id,
        full_name=user.full_name,
        email=user.email,
        league=user.league,
        role=user.role,
        mpw=user.mpw,
        wip_limit=user.wip_limit,
        is_new_employee=user.is_new_employee,
        task_workspace_enabled=user.task_workspace_enabled,
        can_link_queue_tasks_to_projects=user.can_link_queue_tasks_to_projects,
        feedback_enabled=user.feedback_enabled,
        competency_development_enabled=user.competency_development_enabled,
        competency_constructor_enabled=user.competency_constructor_enabled,
        is_active=user.is_active,
        wallet_main=float(user.wallet_main),
        wallet_karma=float(user.wallet_karma),
        needs_password_change=user.password_change_required,
        plan_started_at=user.plan_started_at,
        onboarding_started_at=user.onboarding_started_at,
        onboarding_until=user.onboarding_until,
        sidebar_menu_order=user.sidebar_menu_order,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


def _access_token_for(user: User) -> str:
    return create_access_token(
        data={
            "sub": str(user.id),
            "ver": user.auth_version,
        }
    )


def _request_metadata(request: Request) -> dict[str, str | None]:
    return {
        "client_host": request.client.host if request.client else None,
        "user_agent": (request.headers.get("user-agent") or "")[:200],
    }


async def _lock_user_for_auth_change(
    request: Request,
    db: AsyncSession,
    user: User,
) -> User:
    result = await db.execute(
        select(User)
        .where(User.id == user.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    locked_user = result.scalar_one_or_none()
    token_auth_version = getattr(request.state, "token_auth_version", None)
    if (
        locked_user is None
        or not locked_user.is_active
        or type(token_auth_version) is not int
        or locked_user.auth_version != token_auth_version
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Сессия завершена. Войдите снова",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return locked_user


def _clean_sidebar_menu_order(value: dict | None) -> dict | None:
    if value is None:
        return None
    groups = value.get("groups") or []
    items = value.get("items") or {}
    item_labels = value.get("item_labels") or value.get("itemLabels") or {}
    if not isinstance(groups, list) or not isinstance(items, dict):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Некорректный формат порядка меню",
        )
    if not isinstance(item_labels, dict):
        item_labels = {}
    cleaned_groups: list[str | dict[str, object]] = []
    for index, group in enumerate(groups):
        if isinstance(group, str):
            cleaned_groups.append(group[:64])
            continue
        if not isinstance(group, dict):
            continue
        group_id = group.get("id") or group.get("key") or f"custom-{index + 1}"
        group_label = group.get("label") or f"Кнопка {index + 1}"
        item_ids = group.get("item_ids") or group.get("itemIds") or []
        if not isinstance(item_ids, list):
            item_ids = []
        cleaned_groups.append(
            {
                "id": str(group_id)[:64],
                "label": str(group_label)[:80],
                "item_ids": [str(item_id)[:64] for item_id in item_ids if isinstance(item_id, str)],
            }
        )
    cleaned_items: dict[str, list[str]] = {}
    for group, item_ids in items.items():
        if not isinstance(group, str) or not isinstance(item_ids, list):
            continue
        cleaned_items[group[:64]] = [str(item_id)[:64] for item_id in item_ids if isinstance(item_id, str)]
    cleaned_item_labels = {
        str(item_id)[:64]: str(label).strip()[:80]
        for item_id, label in item_labels.items()
        if isinstance(item_id, str) and isinstance(label, str) and label.strip()
    }
    return {"groups": cleaned_groups, "items": cleaned_items, "item_labels": cleaned_item_labels}


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
async def login(
    request: Request,
    body: LoginRequest,
    db: AsyncSession = Depends(get_db),
):
    """Вход по email и установленному либо временному паролю."""
    email = str(body.email).strip().lower()
    result = await db.execute(select(User).where(func.lower(User.email) == email))
    user = result.scalar_one_or_none()
    can_authenticate = bool(user and user.is_active and user.password_hash)
    password_hash = user.password_hash if can_authenticate and user else None
    password_valid = verify_password_or_dummy(body.password, password_hash)
    temporary_password_valid = bool(
        user
        and is_temporary_password_valid(
            user.password_change_required,
            user.temporary_password_expires_at,
        )
    )
    if not can_authenticate or not password_valid or not temporary_password_valid or user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный email или пароль",
        )
    token = _access_token_for(user)
    await record_activity_event(
        db,
        user.id,
        "login_success",
        metadata=_request_metadata(request),
    )
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=_user_to_read(user),
    )


@router.post("/set-password")
@limiter.limit("5/minute")
async def set_password(
    request: Request,
    body: SetPasswordRequest,
    user: User = Depends(get_current_user_for_password_setup),
    db: AsyncSession = Depends(get_db),
):
    """Заменить выданный временный пароль и завершить все старые сессии."""
    user = await _lock_user_for_auth_change(request, db, user)
    if not user.password_change_required:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Обязательная смена пароля для пользователя не установлена",
        )
    if user.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Временный пароль не выдан. Обратитесь к администратору",
        )
    if not is_temporary_password_valid(
        user.password_change_required,
        user.temporary_password_expires_at,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Срок действия временного пароля истек. Обратитесь к администратору",
        )
    errors = validate_password_strength(body.new_password)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=errors,
        )
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Новый пароль должен отличаться от временного",
        )
    user.password_hash = get_password_hash(body.new_password)
    user.password_change_required = False
    user.temporary_password_expires_at = None
    user.auth_version += 1
    await record_activity_event(
        db,
        user.id,
        "authn_password_setup",
        metadata=_request_metadata(request),
    )
    await db.commit()
    return {"message": "Пароль установлен. Войдите снова", "reauth_required": True}


@router.post("/change-password")
@limiter.limit("5/minute")
async def change_password(
    request: Request,
    body: ChangePasswordRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сменить пароль и завершить все ранее выданные сессии."""
    user = await _lock_user_for_auth_change(request, db, user)
    if user.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Сначала установите пароль через форму первого входа.",
        )
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Неверный текущий пароль",
        )
    errors = validate_password_strength(body.new_password)
    if errors:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=errors,
        )
    if verify_password(body.new_password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Новый пароль должен отличаться от текущего",
        )
    user.password_hash = get_password_hash(body.new_password)
    user.password_change_required = False
    user.temporary_password_expires_at = None
    user.auth_version += 1
    await record_activity_event(
        db,
        user.id,
        "authn_password_change",
        metadata=_request_metadata(request),
    )
    await db.commit()
    return {"message": "Пароль успешно изменён. Войдите снова", "reauth_required": True}


@router.get("/me", response_model=AuthenticatedUserRead)
async def me(
    user: User = Depends(get_current_user_for_password_setup),
):
    """Текущий пользователь по JWT."""
    return _user_to_read(user)


@router.patch("/me/sidebar-menu", response_model=AuthenticatedUserRead)
async def update_sidebar_menu_order(
    body: SidebarMenuOrderUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Сохранить персональный порядок левого меню."""
    merged = await db.merge(user)
    merged.sidebar_menu_order = _clean_sidebar_menu_order(body.sidebar_menu_order)
    await db.commit()
    await db.refresh(merged)
    return _user_to_read(merged)
