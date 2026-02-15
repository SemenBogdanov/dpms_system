"""Модели SQLAlchemy. Импорт всех моделей для Alembic и Base.metadata."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Базовый класс для всех моделей."""
    pass


from app.models.user import User
from app.models.catalog import CatalogItem
from app.models.task import Task
from app.models.transaction import QTransaction
from app.models.shop import ShopItem, Purchase, PeriodSnapshot
from app.models.notification import Notification


__all__ = [
    "Base",
    "User",
    "CatalogItem",
    "Task",
    "QTransaction",
    "ShopItem",
    "Purchase",
    "PeriodSnapshot",
    "Notification",
]
