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
from app.models.task import Task, TaskReviewEvent
from app.models.attachment import TaskAttachment
from app.models.knowledge import KnowledgeArticle
from app.models.absence import GlobalHoliday, UserAbsence
from app.models.transaction import QTransaction
from app.models.shop import ShopItem, Purchase, PeriodSnapshot, PeriodClosure
from app.models.notification import Notification
from app.models.activity import ActivityEvent
from app.models.feedback import FeedbackRequest
from app.models.contact import Contact
from app.models.quick_note import QuickNote
from app.models.quick_note_attachment import QuickNoteAttachment
from app.models.quick_note_share import QuickNoteComment, QuickNoteShare
from app.models.personal_task import PersonalTask, PersonalTaskCheckpoint, PersonalTaskEvent
from app.models.deadline_tracker import DeadlineTracker
from app.models.work_track import WorkMethodology, WorkTrack, WorkTrackItem
from app.models.audit import (
    AuditAIAtomDraft,
    AuditAIAtomizationAttempt,
    AuditAssignment,
    AuditAtom,
    AuditCase,
    AuditDocument,
    AuditEvent,
    AuditImportBatch,
    AuditSynologyConnection,
    AuditSynologyEvent,
    AuditSynologyImport,
    AuditSynologyImportBatch,
    AuditTeamMember,
)
from app.models.ai_provider import (
    AIProviderConfig,
    AIProviderEvent,
    AuditAtomizationSkill,
    AuditAtomizationSkillVersion,
)
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
    "TaskReviewEvent",
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
    "Contact",
    "QuickNote",
    "QuickNoteAttachment",
    "QuickNoteComment",
    "QuickNoteShare",
    "PersonalTask",
    "PersonalTaskEvent",
    "PersonalTaskCheckpoint",
    "DeadlineTracker",
    "WorkMethodology",
    "WorkTrack",
    "WorkTrackItem",
    "AuditCase",
    "AuditAIAtomDraft",
    "AuditAIAtomizationAttempt",
    "AuditAssignment",
    "AuditAtom",
    "AuditImportBatch",
    "AuditDocument",
    "AuditSynologyConnection",
    "AuditSynologyEvent",
    "AuditSynologyImport",
    "AuditSynologyImportBatch",
    "AuditTeamMember",
    "AuditEvent",
    "AIProviderConfig",
    "AIProviderEvent",
    "AuditAtomizationSkill",
    "AuditAtomizationSkillVersion",
    "Competency",
    "CompetencyQuestion",
    "CompetencyChoice",
    "CompetencyInterpretation",
    "CompetencyAssignment",
    "CompetencyAttempt",
    "CompetencyAnswer",
    "IndividualDevelopmentPlanItem",
]
