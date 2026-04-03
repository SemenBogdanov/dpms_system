"""Модели SQLAlchemy. Импорт всех моделей для Alembic и Base.metadata."""
from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

from app.config import settings

_metadata_kwargs = {}
if settings.DB_SCHEMA:
    _metadata_kwargs["schema"] = settings.DB_SCHEMA

class Base(DeclarativeBase):
    metadata = MetaData(**_metadata_kwargs)


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
