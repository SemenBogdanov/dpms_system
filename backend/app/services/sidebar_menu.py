"""Permission-aware projection for imported sidebar layouts."""

from collections.abc import Iterable

from app.models.user import User, UserRole
from app.schemas.user import (
    SidebarMenuImportGroup,
    SidebarMenuImportLayout,
    SidebarMenuImportPreview,
)


PERSONAL_ITEM_IDS = frozenset(
    {
        "personal-tasks",
        "deadline-trackers",
        "quick-notes",
        "contacts",
        "messages",
    }
)
TASK_WORKSPACE_ITEM_IDS = frozenset(
    {
        "my-tasks",
        "queue",
        "catalog",
        "knowledge",
        "shop",
        "work-entities",
    }
)
TASK_MANAGER_ITEM_IDS = frozenset({"calculator", "dashboard", "reports", "absences"})
TASK_ADMIN_ITEM_IDS = frozenset({"calibration"})
FEATURE_ITEM_IDS = frozenset({"audit", "competencies", "feedback"})

CUSTOMIZABLE_SIDEBAR_ITEM_IDS = frozenset(
    PERSONAL_ITEM_IDS
    | TASK_WORKSPACE_ITEM_IDS
    | TASK_MANAGER_ITEM_IDS
    | TASK_ADMIN_ITEM_IDS
    | FEATURE_ITEM_IDS
)
KNOWN_NON_CUSTOMIZABLE_ITEM_IDS = frozenset({"settings", "admin-users"})
REQUIRED_ITEM_ID = "messages"


def _role_value(user: User) -> str:
    role = user.role
    return role.value if isinstance(role, UserRole) else str(role)


def accessible_sidebar_item_ids(user: User) -> frozenset[str]:
    """Mirror the frontend visibility rules for customizable menu entries."""
    role = _role_value(user)
    allowed = set(PERSONAL_ITEM_IDS)

    has_task_workspace = role == UserRole.admin.value or bool(user.task_workspace_enabled)
    if has_task_workspace:
        allowed.update(TASK_WORKSPACE_ITEM_IDS)
        if role in {UserRole.teamlead.value, UserRole.admin.value}:
            allowed.update(TASK_MANAGER_ITEM_IDS)
        if role == UserRole.admin.value:
            allowed.update(TASK_ADMIN_ITEM_IDS)

    if role == UserRole.admin.value or bool(user.audit_enabled):
        allowed.add("audit")
    if (
        role == UserRole.admin.value
        or bool(user.competency_development_enabled)
        or bool(user.competency_constructor_enabled)
    ):
        allowed.add("competencies")
    if bool(user.feedback_enabled):
        allowed.add("feedback")

    return frozenset(allowed)


def _effective_item_ids(
    group: SidebarMenuImportGroup,
    legacy_items: dict[str, list[str]],
) -> Iterable[str]:
    if group.item_ids is not None:
        return group.item_ids
    return legacy_items.get(group.id, [])


def project_sidebar_menu_import(
    layout: SidebarMenuImportLayout,
    user: User,
) -> SidebarMenuImportPreview:
    """Remove unknown, inaccessible, and duplicate assignments from an import."""
    accessible = accessible_sidebar_item_ids(user)
    seen: set[str] = set()
    accepted_count = 0
    referenced_count = 0
    unknown_count = 0
    inaccessible_count = 0
    duplicate_count = 0
    projected_groups: list[SidebarMenuImportGroup] = []

    for group in layout.groups:
        projected_item_ids: list[str] = []
        for item_id in _effective_item_ids(group, layout.items):
            referenced_count += 1
            if item_id not in CUSTOMIZABLE_SIDEBAR_ITEM_IDS:
                if item_id in KNOWN_NON_CUSTOMIZABLE_ITEM_IDS:
                    inaccessible_count += 1
                else:
                    unknown_count += 1
                continue
            if item_id not in accessible:
                inaccessible_count += 1
                continue
            if item_id in seen:
                duplicate_count += 1
                continue
            seen.add(item_id)
            accepted_count += 1
            projected_item_ids.append(item_id)

        projected_groups.append(
            SidebarMenuImportGroup(
                id=group.id,
                label=group.label,
                item_ids=projected_item_ids,
            )
        )

    required_added_count = 0
    if REQUIRED_ITEM_ID not in seen:
        first_group = projected_groups[0]
        projected_groups[0] = first_group.model_copy(
            update={"item_ids": [*(first_group.item_ids or []), REQUIRED_ITEM_ID]}
        )
        seen.add(REQUIRED_ITEM_ID)
        required_added_count = 1

    projected_items = {
        group.id: list(group.item_ids or [])
        for group in projected_groups
    }
    projected_labels = {
        item_id: label
        for item_id, label in layout.item_labels.items()
        if item_id in seen and item_id in accessible
    }
    projected_layout = SidebarMenuImportLayout(
        version=layout.version,
        groups=projected_groups,
        items=projected_items,
        item_labels=projected_labels,
    )
    return SidebarMenuImportPreview(
        sidebar_menu_order=projected_layout,
        referenced_item_count=referenced_count,
        imported_count=accepted_count,
        skipped_unknown_count=unknown_count,
        skipped_inaccessible_count=inaccessible_count,
        skipped_duplicate_count=duplicate_count,
        required_added_count=required_added_count,
    )
