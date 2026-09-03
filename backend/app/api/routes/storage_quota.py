"""Personal storage quota and administrator approval API."""
from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_role
from app.models.storage_quota import StorageQuotaRequest, UserStorageQuota
from app.models.user import User
from app.schemas.storage_quota import (
    AdminStorageQuotaRequestRead,
    StorageQuotaRequestCreate,
    StorageQuotaRequestDecision,
    StorageQuotaRequestRead,
    StorageQuotaSummaryRead,
)
from app.services.activity import record_activity_event
from app.services.storage_quota import get_storage_account, quota_state


router = APIRouter()
REQUEST_STATUSES = {"pending", "approved", "rejected", "cancelled"}


async def _pending_request(
    db: AsyncSession,
    user_id: UUID,
) -> StorageQuotaRequest | None:
    return (
        await db.execute(
            select(StorageQuotaRequest)
            .where(
                StorageQuotaRequest.user_id == user_id,
                StorageQuotaRequest.status == "pending",
            )
            .order_by(StorageQuotaRequest.created_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()


def _summary(
    account: UserStorageQuota,
    pending: StorageQuotaRequest | None,
) -> StorageQuotaSummaryRead:
    available, percent, warning_level, warning_message = quota_state(account)
    return StorageQuotaSummaryRead(
        quota_bytes=account.limit_bytes,
        used_bytes=account.used_bytes,
        reserved_bytes=account.reserved_bytes,
        available_bytes=available,
        usage_percent=percent,
        warning_level=warning_level,
        warning_message=warning_message,
        pending_request=(
            StorageQuotaRequestRead.model_validate(pending) if pending is not None else None
        ),
    )


@router.get("/me", response_model=StorageQuotaSummaryRead)
async def get_my_storage_quota(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return current personal storage usage and the active increase request."""
    account = await get_storage_account(db, current_user.id)
    pending = await _pending_request(db, current_user.id)
    return _summary(account, pending)


@router.get("/me/requests", response_model=list[StorageQuotaRequestRead])
async def list_my_storage_quota_requests(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    requests = list(
        (
            await db.execute(
                select(StorageQuotaRequest)
                .where(StorageQuotaRequest.user_id == current_user.id)
                .order_by(
                    StorageQuotaRequest.created_at.desc(),
                    StorageQuotaRequest.id.desc(),
                )
                .limit(50)
            )
        ).scalars()
    )
    return requests


@router.post(
    "/me/requests",
    response_model=StorageQuotaRequestRead,
    status_code=201,
)
async def create_storage_quota_request(
    body: StorageQuotaRequestCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    account = await get_storage_account(db, current_user.id)
    existing = await _pending_request(db, current_user.id)
    if existing is not None:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "storage_quota_request_pending",
                "message": "Предыдущая заявка на увеличение хранилища еще рассматривается.",
            },
        )
    reason = body.reason.strip()
    if len(reason) < 10:
        raise HTTPException(status_code=422, detail="Опишите причину минимум в 10 символах")
    if body.requested_limit_bytes <= account.limit_bytes:
        raise HTTPException(
            status_code=422,
            detail="Новый лимит должен быть больше текущего",
        )
    request = StorageQuotaRequest(
        user_id=current_user.id,
        current_limit_bytes=account.limit_bytes,
        requested_limit_bytes=body.requested_limit_bytes,
        reason=reason,
        status="pending",
    )
    db.add(request)
    await db.flush()
    await record_activity_event(
        db,
        current_user.id,
        "storage_quota_increase_requested",
        metadata={
            "request_id": request.id,
            "current_limit_bytes": request.current_limit_bytes,
            "requested_limit_bytes": request.requested_limit_bytes,
        },
    )
    return request


@router.delete("/me/requests/{request_id}", response_model=StorageQuotaRequestRead)
async def cancel_storage_quota_request(
    request_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    request = (
        await db.execute(
            select(StorageQuotaRequest)
            .where(
                StorageQuotaRequest.id == request_id,
                StorageQuotaRequest.user_id == current_user.id,
            )
            .with_for_update()
        )
    ).scalar_one_or_none()
    if request is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if request.status != "pending":
        raise HTTPException(status_code=409, detail="Решение по заявке уже зафиксировано")
    now = datetime.now(timezone.utc)
    request.status = "cancelled"
    request.updated_at = now
    await record_activity_event(
        db,
        current_user.id,
        "storage_quota_increase_cancelled",
        metadata={"request_id": request.id},
    )
    await db.flush()
    return request


@router.get("/admin/requests", response_model=list[AdminStorageQuotaRequestRead])
async def list_storage_quota_requests_for_admin(
    status: str = Query("pending"),
    _: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    if status not in REQUEST_STATUSES:
        raise HTTPException(status_code=422, detail="Некорректный статус заявки")
    rows = (
        await db.execute(
            select(StorageQuotaRequest, User, UserStorageQuota)
            .join(User, User.id == StorageQuotaRequest.user_id)
            .join(UserStorageQuota, UserStorageQuota.user_id == User.id)
            .where(StorageQuotaRequest.status == status)
            .order_by(
                StorageQuotaRequest.created_at.asc(),
                StorageQuotaRequest.id.asc(),
            )
            .limit(200)
        )
    ).all()
    return [
        AdminStorageQuotaRequestRead(
            **StorageQuotaRequestRead.model_validate(request).model_dump(),
            user_name=user.full_name,
            user_email=user.email,
            used_bytes=account.used_bytes,
            reserved_bytes=account.reserved_bytes,
        )
        for request, user, account in rows
    ]


@router.post(
    "/admin/requests/{request_id}/decision",
    response_model=AdminStorageQuotaRequestRead,
)
async def decide_storage_quota_request(
    request_id: UUID,
    body: StorageQuotaRequestDecision,
    admin: User = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
):
    request = (
        await db.execute(
            select(StorageQuotaRequest)
            .where(StorageQuotaRequest.id == request_id)
            .with_for_update()
        )
    ).scalar_one_or_none()
    if request is None:
        raise HTTPException(status_code=404, detail="Заявка не найдена")
    if request.status != "pending":
        raise HTTPException(
            status_code=409,
            detail={
                "code": "storage_quota_request_already_decided",
                "message": "Другой администратор уже обработал эту заявку.",
            },
        )
    account = await get_storage_account(db, request.user_id)
    user = (
        await db.execute(select(User).where(User.id == request.user_id))
    ).scalar_one()
    now = datetime.now(timezone.utc)
    comment = body.comment.strip()
    approved_limit: int | None = None
    if body.decision == "approved":
        approved_limit = body.approved_limit_bytes or request.requested_limit_bytes
        if approved_limit <= account.limit_bytes:
            raise HTTPException(
                status_code=422,
                detail="Одобренный лимит должен быть больше текущего",
            )
        if approved_limit > request.requested_limit_bytes:
            raise HTTPException(
                status_code=422,
                detail="Одобренный лимит не может превышать запрошенный",
            )
        account.limit_bytes = approved_limit
        account.updated_at = now
    request.status = body.decision
    request.approved_limit_bytes = approved_limit
    request.decision_comment = comment
    request.decided_by_id = admin.id
    request.decided_at = now
    request.updated_at = now
    await record_activity_event(
        db,
        admin.id,
        f"storage_quota_increase_{body.decision}",
        metadata={
            "request_id": request.id,
            "target_user_id": request.user_id,
            "current_limit_bytes": request.current_limit_bytes,
            "requested_limit_bytes": request.requested_limit_bytes,
            "approved_limit_bytes": approved_limit,
            "decision_comment": comment,
        },
    )
    await db.flush()
    return AdminStorageQuotaRequestRead(
        **StorageQuotaRequestRead.model_validate(request).model_dump(),
        user_name=user.full_name,
        user_email=user.email,
        used_bytes=account.used_bytes,
        reserved_bytes=account.reserved_bytes,
    )
