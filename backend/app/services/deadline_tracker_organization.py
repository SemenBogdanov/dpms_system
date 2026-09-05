"""Personal groups/categories and idempotent legacy category seeds."""
import hashlib
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from app.models.deadline_tracker import DeadlineTrackerCategory
from app.models.user import User

LEGACY_CATEGORIES = (
    ("subscription", "Абонемент"), ("system", "Система"), ("password", "Пароль"),
    ("task", "Задача"), ("document", "Документ"), ("payment", "Оплата"), ("other", "Другое"),
)


async def seed_categories(db, owner_id):
    # Serialize first-use seed for newly registered users, without provider-specific UPSERT.
    await db.execute(select(User.id).where(User.id == owner_id).with_for_update())
    rows = list((await db.execute(select(DeadlineTrackerCategory).where(
        DeadlineTrackerCategory.owner_id == owner_id,
    ))).scalars())
    existing = {r.legacy_type for r in rows}
    for order, (kind, name) in enumerate(LEGACY_CATEGORIES):
        if kind not in existing:
            identity = hashlib.md5(f"{owner_id}:tracker-category:{kind}".encode(), usedforsecurity=False).hexdigest()
            row = DeadlineTrackerCategory(id=UUID(identity), owner_id=owner_id, name=name, sort_order=order, legacy_type=kind)
            db.add(row)
            rows.append(row)
    await db.flush()
    return rows


async def owned_organization(db, model, identity, owner_id, *, active=False):
    row = (await db.execute(select(model).where(
        model.id == identity, model.owner_id == owner_id,
    ).with_for_update())).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Группа или категория не найдена")
    if active and row.is_archived:
        raise HTTPException(409, "Группа или категория находится в архиве")
    return row
