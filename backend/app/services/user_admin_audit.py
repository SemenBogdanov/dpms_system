"""Sanitized append-only audit for administrative user changes."""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import ActivityEvent
from app.models.email_change_request import EmailChangeRequest
from app.models.user import User
from app.schemas.user import (
    AdminUserAuditChangeRead,
    AdminUserAuditEventRead,
    AdminUserAuditHistoryRead,
)
from app.services.activity import record_activity_event


USER_CREATED_EVENT = "authn_user_created"
USER_UPDATED_EVENT = "admin_user_updated"
TEMPORARY_PASSWORD_EVENT = "authn_temporary_password_issued"
EMAIL_CHANGE_REQUESTED_EVENT = "authn_email_change_requested"
EMAIL_CHANGE_CONFIRMED_EVENT = "authn_email_change_confirmed"
EMAIL_CHANGE_CANCELLED_EVENT = "authn_email_change_cancelled"
EMAIL_CHANGE_EXPIRED_EVENT = "authn_email_change_expired"
EMAIL_CHANGE_SUPERSEDED_EVENT = "authn_email_change_superseded"
ADMIN_USER_EVENT_TYPES = (
    USER_CREATED_EVENT,
    USER_UPDATED_EVENT,
    TEMPORARY_PASSWORD_EVENT,
    EMAIL_CHANGE_REQUESTED_EVENT,
    EMAIL_CHANGE_CONFIRMED_EVENT,
    EMAIL_CHANGE_CANCELLED_EVENT,
    EMAIL_CHANGE_EXPIRED_EVENT,
    EMAIL_CHANGE_SUPERSEDED_EVENT,
)

AUDITED_USER_FIELDS = (
    "full_name",
    "email",
    "role",
    "league",
    "mpw",
    "is_active",
    "is_new_employee",
    "task_workspace_enabled",
    "can_link_queue_tasks_to_projects",
    "feedback_enabled",
    "competency_development_enabled",
    "competency_constructor_enabled",
    "plan_started_at",
    "onboarding_started_at",
    "onboarding_until",
)
AUDITED_USER_FIELD_SET = frozenset(AUDITED_USER_FIELDS)


def _audit_value(value: Any) -> Any:
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, datetime):
        return value.isoformat()
    return value


def admin_user_snapshot(user: User) -> dict[str, Any]:
    """Return a strict whitelist; auth secrets can never enter audit metadata."""
    return {
        field: _audit_value(getattr(user, field))
        for field in AUDITED_USER_FIELDS
    }


def admin_user_changes(
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> tuple[list[str], dict[str, Any], dict[str, Any]]:
    before_values = {
        field: _audit_value(value)
        for field, value in (before or {}).items()
        if field in AUDITED_USER_FIELD_SET
    }
    after_values = {
        field: _audit_value(value)
        for field, value in (after or {}).items()
        if field in AUDITED_USER_FIELD_SET
    }
    changed_fields = [
        field
        for field in AUDITED_USER_FIELDS
        if before_values.get(field) != after_values.get(field)
    ]
    return (
        changed_fields,
        {field: before_values.get(field) for field in changed_fields},
        {field: after_values.get(field) for field in changed_fields},
    )


async def record_admin_user_audit_event(
    db: AsyncSession,
    *,
    actor_id: UUID,
    target: User,
    event_type: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    sessions_revoked: bool = False,
) -> ActivityEvent | None:
    if event_type not in ADMIN_USER_EVENT_TYPES:
        raise ValueError("unsupported_admin_user_audit_event")

    changed_fields, safe_before, safe_after = admin_user_changes(before, after)
    if event_type == USER_UPDATED_EVENT and not changed_fields:
        return None

    return await record_activity_event(
        db,
        actor_id,
        event_type,
        metadata={
            "schema_version": 1,
            "target_user_id": target.id,
            "target_user_name": target.full_name,
            "changed_fields": changed_fields,
            "before": safe_before,
            "after": safe_after,
            "sessions_revoked": sessions_revoked,
        },
    )


async def record_email_change_audit_event(
    db: AsyncSession,
    *,
    actor_id: UUID,
    target: User,
    request: EmailChangeRequest,
    event_type: str,
    sessions_revoked: bool = False,
) -> ActivityEvent:
    """Record email-change lifecycle metadata without action tokens or passwords."""
    if event_type not in {
        EMAIL_CHANGE_REQUESTED_EVENT,
        EMAIL_CHANGE_CONFIRMED_EVENT,
        EMAIL_CHANGE_CANCELLED_EVENT,
        EMAIL_CHANGE_EXPIRED_EVENT,
        EMAIL_CHANGE_SUPERSEDED_EVENT,
    }:
        raise ValueError("unsupported_email_change_audit_event")
    changed_fields = ["email"] if event_type == EMAIL_CHANGE_CONFIRMED_EVENT else []
    before = {"email": request.old_email} if changed_fields else {}
    after = {"email": request.new_email} if changed_fields else {}
    reason = (request.reason or "").strip()[:500] or None
    return await record_activity_event(
        db,
        actor_id,
        event_type,
        metadata={
            "schema_version": 1,
            "target_user_id": target.id,
            "target_user_name": target.full_name,
            "changed_fields": changed_fields,
            "before": before,
            "after": after,
            "sessions_revoked": sessions_revoked,
            "email_change": {
                "request_id": str(request.id),
                "request_kind": request.request_kind,
                "status": request.status,
                "new_email": request.new_email,
                "reason": reason,
            },
        },
    )


def _event_action(event_type: str) -> str:
    if event_type == USER_CREATED_EVENT:
        return "created"
    if event_type == TEMPORARY_PASSWORD_EVENT:
        return "temporary_password_issued"
    if event_type == EMAIL_CHANGE_REQUESTED_EVENT:
        return "email_change_requested"
    if event_type == EMAIL_CHANGE_CONFIRMED_EVENT:
        return "email_change_confirmed"
    if event_type == EMAIL_CHANGE_CANCELLED_EVENT:
        return "email_change_cancelled"
    if event_type == EMAIL_CHANGE_EXPIRED_EVENT:
        return "email_change_expired"
    if event_type == EMAIL_CHANGE_SUPERSEDED_EVENT:
        return "email_change_superseded"
    return "updated"


def _event_note(event_type: str, metadata: dict[str, Any]) -> str | None:
    if not event_type.startswith("authn_email_change_"):
        return None
    detail = metadata.get("email_change")
    if not isinstance(detail, dict):
        return None
    new_email = str(detail.get("new_email") or "").strip()[:255]
    reason = str(detail.get("reason") or "").strip()[:500]
    parts = [f"Новый email: {new_email}" if new_email else ""]
    if reason:
        parts.append(f"Причина: {reason}")
    return ". ".join(part for part in parts if part) or None


async def list_admin_user_audit_history(
    db: AsyncSession,
    *,
    target_user_id: UUID,
    limit: int,
) -> AdminUserAuditHistoryRead:
    limit = min(max(limit, 1), 200)
    target_id_text = str(target_user_id)
    target_filter = ActivityEvent.event_data.op("->>")("target_user_id") == target_id_text
    event_filter = ActivityEvent.event_type.in_(ADMIN_USER_EVENT_TYPES)

    stmt = (
        select(ActivityEvent, User.full_name)
        .join(User, User.id == ActivityEvent.actor_id)
        .where(event_filter, target_filter)
        .order_by(ActivityEvent.occurred_at.desc(), ActivityEvent.id.desc())
        .limit(limit)
    )
    count_stmt = select(func.count(ActivityEvent.id)).where(event_filter, target_filter)
    rows = (await db.execute(stmt)).all()
    total = int((await db.execute(count_stmt)).scalar() or 0)

    items: list[AdminUserAuditEventRead] = []
    for event, actor_name in rows:
        metadata = event.event_data or {}
        raw_fields = metadata.get("changed_fields")
        before = metadata.get("before") if isinstance(metadata.get("before"), dict) else {}
        after = metadata.get("after") if isinstance(metadata.get("after"), dict) else {}
        changed_fields = raw_fields if isinstance(raw_fields, list) else []
        changes = [
            AdminUserAuditChangeRead(
                field=field,
                before=before.get(field),
                after=after.get(field),
            )
            for field in changed_fields
            if isinstance(field, str) and field in AUDITED_USER_FIELD_SET
        ]
        items.append(
            AdminUserAuditEventRead(
                id=event.id,
                actor_id=event.actor_id,
                actor_name=actor_name,
                target_user_id=target_user_id,
                action=_event_action(event.event_type),
                changes=changes,
                note=_event_note(event.event_type, metadata),
                sessions_revoked=metadata.get("sessions_revoked") is True,
                occurred_at=event.occurred_at,
            )
        )

    return AdminUserAuditHistoryRead(items=items, total=total, limit=limit)
