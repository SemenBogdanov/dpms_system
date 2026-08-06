"""API пользователей."""
from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db, get_current_user, require_role, ensure_task_workspace_access
from app.core.security import get_password_hash, validate_password_strength, verify_password
from app.models.user import User, League, UserRole
from app.schemas.user import (
    AdminUserAuditHistoryRead,
    AdminUserRead,
    TemporaryPasswordRequest,
    UserCreate,
    UserRead,
    UserUpdate,
)
from app.schemas.dashboard import UserProgress, RunRate
from app.schemas.transaction import QTransactionRead
from app.schemas.leagues import LeagueProgress
from app.services.analytics import get_user_progress, get_run_rate
from app.services.planning import add_months
from app.services.leagues import get_league_progress as get_league_progress_svc
from app.services.user_admin_audit import (
    TEMPORARY_PASSWORD_EVENT,
    USER_CREATED_EVENT,
    USER_UPDATED_EVENT,
    admin_user_snapshot,
    list_admin_user_audit_history,
    record_admin_user_audit_event,
)

router = APIRouter()
TEMPORARY_PASSWORD_TTL = timedelta(days=7)


@router.get("", response_model=list[UserRead])
async def list_users(
    league: League | None = Query(None),
    is_active: bool | None = Query(None),
    role: UserRole | None = Query(None),
    current_user: User = Depends(get_current_user),
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


@router.get("/admin", response_model=list[AdminUserRead])
async def list_users_for_admin(
    league: League | None = Query(None),
    is_active: bool | None = Query(None),
    role: UserRole | None = Query(None),
    _: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Список сотрудников с состоянием учетных записей (только admin)."""
    stmt = select(User).order_by(User.full_name)
    if league is not None:
        stmt = stmt.where(User.league == league)
    if is_active is not None:
        stmt = stmt.where(User.is_active == is_active)
    if role is not None:
        stmt = stmt.where(User.role == role)
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{user_id}/admin-history", response_model=AdminUserAuditHistoryRead)
async def get_user_admin_history(
    user_id: UUID,
    limit: int = Query(50, ge=1, le=200),
    _: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    """Безопасная история административных изменений сотрудника."""
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return await list_admin_user_audit_history(
        db,
        target_user_id=user_id,
        limit=limit,
    )


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Профиль пользователя."""
    if current_user.id != user_id and current_user.role not in (UserRole.admin, UserRole.teamlead):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    ensure_task_workspace_access(current_user)
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user


@router.post("", response_model=AdminUserRead)
async def create_user(
    body: UserCreate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    """Создать сотрудника с временным паролем (только admin)."""
    email = str(body.email).strip().lower()
    existing = await db.execute(select(User).where(func.lower(User.email) == email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")
    password_errors = validate_password_strength(body.password)
    if password_errors:
        raise HTTPException(status_code=400, detail=password_errors)
    now = datetime.now(timezone.utc)
    onboarding_until = add_months(now, 3) if body.is_new_employee else None
    user = User(
        full_name=body.full_name.strip(),
        email=email,
        league=body.league,
        role=body.role,
        mpw=body.mpw,
        wip_limit=2,
        is_active=True,
        is_new_employee=body.is_new_employee,
        task_workspace_enabled=body.task_workspace_enabled,
        can_link_queue_tasks_to_projects=body.can_link_queue_tasks_to_projects,
        feedback_enabled=body.feedback_enabled,
        competency_development_enabled=body.competency_development_enabled,
        competency_constructor_enabled=body.competency_constructor_enabled,
        plan_started_at=now,
        onboarding_started_at=now if body.is_new_employee else None,
        onboarding_until=onboarding_until,
        password_hash=get_password_hash(body.password),
        password_change_required=True,
        temporary_password_expires_at=now + TEMPORARY_PASSWORD_TTL,
    )
    db.add(user)
    try:
        await db.flush()
        await record_admin_user_audit_event(
            db,
            actor_id=admin.id,
            target=user,
            event_type=USER_CREATED_EVENT,
            after=admin_user_snapshot(user),
        )
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует") from error
    await db.refresh(user)
    return user


@router.post("/{user_id}/temporary-password", response_model=AdminUserRead)
async def issue_temporary_password(
    user_id: UUID,
    body: TemporaryPasswordRequest,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    """Выдать новый временный пароль и завершить текущие сессии пользователя."""
    if user_id == admin.id:
        raise HTTPException(
            status_code=400,
            detail="Для собственной учетной записи используйте смену пароля в настройках",
        )
    result = await db.execute(select(User).where(User.id == user_id).with_for_update())
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    password_errors = validate_password_strength(body.temporary_password)
    if password_errors:
        raise HTTPException(status_code=400, detail=password_errors)
    if user.password_hash and verify_password(body.temporary_password, user.password_hash):
        raise HTTPException(
            status_code=400,
            detail="Временный пароль должен отличаться от текущего",
        )
    user.password_hash = get_password_hash(body.temporary_password)
    user.password_change_required = True
    user.temporary_password_expires_at = datetime.now(timezone.utc) + TEMPORARY_PASSWORD_TTL
    user.auth_version += 1
    await record_admin_user_audit_event(
        db,
        actor_id=admin.id,
        target=user,
        event_type=TEMPORARY_PASSWORD_EVENT,
        sessions_revoked=True,
    )
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/{user_id}", response_model=AdminUserRead)
async def update_user(
    user_id: UUID,
    body: UserUpdate,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_role("admin")),
):
    """Обновить сотрудника (только admin)."""
    result = await db.execute(select(User).where(User.id == user_id).with_for_update())
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    before = admin_user_snapshot(user)
    revoke_sessions = False
    if body.full_name is not None:
        user.full_name = body.full_name
    if body.email is not None:
        email = str(body.email).strip().lower()
        other = await db.execute(select(User).where(func.lower(User.email) == email, User.id != user_id))
        if other.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")
        revoke_sessions = revoke_sessions or email != user.email
        user.email = email
    if body.role is not None:
        revoke_sessions = revoke_sessions or body.role != user.role
        user.role = body.role
    if body.league is not None:
        user.league = body.league
    if body.mpw is not None:
        user.mpw = body.mpw
    if body.is_active is not None and body.is_active != user.is_active:
        user.is_active = body.is_active
        revoke_sessions = True
    if body.feedback_enabled is not None:
        revoke_sessions = revoke_sessions or body.feedback_enabled != user.feedback_enabled
        user.feedback_enabled = body.feedback_enabled
    if body.competency_development_enabled is not None:
        revoke_sessions = (
            revoke_sessions
            or body.competency_development_enabled != user.competency_development_enabled
        )
        user.competency_development_enabled = body.competency_development_enabled
    if body.competency_constructor_enabled is not None:
        revoke_sessions = (
            revoke_sessions
            or body.competency_constructor_enabled != user.competency_constructor_enabled
        )
        user.competency_constructor_enabled = body.competency_constructor_enabled
    if body.is_new_employee is not None:
        now = datetime.now(timezone.utc)
        if body.is_new_employee:
            if not user.is_new_employee or user.onboarding_started_at is None:
                user.plan_started_at = now
                user.onboarding_started_at = now
                user.onboarding_until = add_months(now, 3)
            elif user.onboarding_until is None:
                user.onboarding_until = add_months(user.onboarding_started_at, 3)
            user.is_new_employee = True
        else:
            user.is_new_employee = False
            user.onboarding_started_at = None
            user.onboarding_until = None
    if body.task_workspace_enabled is not None:
        revoke_sessions = (
            revoke_sessions
            or body.task_workspace_enabled != user.task_workspace_enabled
        )
        user.task_workspace_enabled = body.task_workspace_enabled
        if not body.task_workspace_enabled:
            user.can_link_queue_tasks_to_projects = False
    if body.can_link_queue_tasks_to_projects is not None:
        if body.can_link_queue_tasks_to_projects and not user.task_workspace_enabled:
            raise HTTPException(
                status_code=400,
                detail="Привязка Q-задач к проектам требует доступа к разделу задач",
            )
        revoke_sessions = (
            revoke_sessions
            or body.can_link_queue_tasks_to_projects
            != user.can_link_queue_tasks_to_projects
        )
        user.can_link_queue_tasks_to_projects = body.can_link_queue_tasks_to_projects
    if revoke_sessions:
        user.auth_version += 1
    await record_admin_user_audit_event(
        db,
        actor_id=admin.id,
        target=user,
        event_type=USER_UPDATED_EVENT,
        before=before,
        after=admin_user_snapshot(user),
        sessions_revoked=revoke_sessions,
    )
    try:
        await db.commit()
    except IntegrityError as error:
        await db.rollback()
        raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует") from error
    await db.refresh(user)
    return user


@router.get("/{user_id}/progress", response_model=UserProgress)
async def get_user_progress_route(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Прогресс пользователя: earned/target/karma."""
    if current_user.id != user_id and current_user.role not in (UserRole.admin, UserRole.teamlead):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    ensure_task_workspace_access(current_user)
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
    ensure_task_workspace_access(current_user)
    progress = await get_league_progress_svc(db, user_id)
    if not progress:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return progress


@router.get("/{user_id}/run-rate", response_model=RunRate)
async def get_user_run_rate(
    user_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Run Rate — прогноз выполнения плана. Свои данные — всегда; чужие — admin/teamlead."""
    if current_user.id != user_id and current_user.role not in (UserRole.admin, UserRole.teamlead):
        raise HTTPException(status_code=403, detail="Недостаточно прав")
    ensure_task_workspace_access(current_user)
    run_rate = await get_run_rate(db, user_id)
    if not run_rate:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    return run_rate


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
    ensure_task_workspace_access(current_user)
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
