"""Shared task permission checks."""

from fastapi import HTTPException

from app.models.task import TaskPriority
from app.models.user import User, UserRole


def ensure_critical_priority_allowed(user: User, priority: TaskPriority | str | None) -> None:
    """Only admins can create or change tasks with critical priority."""
    if priority is None:
        return

    try:
        priority_enum = priority if isinstance(priority, TaskPriority) else TaskPriority(priority)
    except ValueError:
        return

    if priority_enum == TaskPriority.critical and user.role != UserRole.admin:
        raise HTTPException(
            status_code=403,
            detail="Критический приоритет может установить только администратор",
        )
