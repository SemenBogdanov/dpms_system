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
from app.models.attachment import TaskAttachment
from app.models.knowledge import KnowledgeArticle
from app.models.absence import GlobalHoliday, UserAbsence
from app.models.transaction import QTransaction
from app.models.shop import ShopItem, Purchase, PeriodSnapshot, PeriodClosure
from app.models.notification import Notification
from app.models.activity import ActivityEvent
from app.models.feedback import FeedbackRequest
from app.models.quick_note import QuickNote
from app.models.personal_task import PersonalTask, PersonalTaskCheckpoint, PersonalTaskEvent
from app.models.deadline_tracker import DeadlineTracker
from app.models.competency import (
    Competency,
    CompetencyQuestion,
    CompetencyChoice,
    CompetencyInterpretation,
    CompetencyAssignment,
    CompetencyAttempt,
    CompetencyAnswer,
    IndividualDevelopmentPlanItem,
)


__all__ = [
    "Base",
    "User",
    "CatalogItem",
    "Task",
    "TaskAttachment",
    "KnowledgeArticle",
    "UserAbsence",
    "GlobalHoliday",
    "QTransaction",
    "ShopItem",
    "Purchase",
    "PeriodSnapshot",
    "PeriodClosure",
    "Notification",
    "ActivityEvent",
    "FeedbackRequest",
    "QuickNote",
    "PersonalTask",
    "PersonalTaskEvent",
    "PersonalTaskCheckpoint",
    "DeadlineTracker",
    "Competency",
    "CompetencyQuestion",
    "CompetencyChoice",
    "CompetencyInterpretation",
    "CompetencyAssignment",
    "CompetencyAttempt",
    "CompetencyAnswer",
    "IndividualDevelopmentPlanItem",
]
