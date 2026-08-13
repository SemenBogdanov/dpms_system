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
from app.models.task import (
    Task,
    TaskAcceptanceCriterion,
    TaskAcceptanceCriterionEvent,
    TaskReviewEvent,
)
from app.models.attachment import TaskAttachment
from app.models.knowledge import KnowledgeArticle
from app.models.absence import GlobalHoliday, UserAbsence
from app.models.transaction import QTransaction
from app.models.shop import ShopItem, Purchase, PeriodSnapshot, PeriodClosure
from app.models.notification import Notification
from app.models.messages import (
    CommunicationEvent,
    MessagePost,
    MessageThread,
    MessageThreadParticipant,
    UserAttentionItem,
)
from app.models.activity import ActivityEvent
from app.models.feedback import FeedbackRequest
from app.models.contact import Contact
from app.models.quick_note import QuickNote
from app.models.quick_note_attachment import QuickNoteAttachment
from app.models.quick_note_share import QuickNoteComment, QuickNoteShare
from app.models.personal_task import PersonalTask, PersonalTaskCheckpoint, PersonalTaskEvent
from app.models.personal_task_artifact import (
    PersonalTaskArtifact,
    PersonalTaskArtifactVersion,
)
from app.models.deadline_tracker import DeadlineTracker
from app.models.execution_contract import WorkEntityExecutionContract
from app.models.work_entity import (
    WorkEntity,
    WorkEntityArtifact,
    WorkEntityEvent,
    WorkEntityLink,
    WorkEntityMember,
    WorkEntityMilestone,
    WorkEntityScheduleDependency,
    WorkEntityStage,
    WorkEntityTask,
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
    "TaskAcceptanceCriterion",
    "TaskAcceptanceCriterionEvent",
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
    "CommunicationEvent",
    "UserAttentionItem",
    "MessageThread",
    "MessageThreadParticipant",
    "MessagePost",
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
    "PersonalTaskArtifact",
    "PersonalTaskArtifactVersion",
    "DeadlineTracker",
    "WorkEntityExecutionContract",
    "WorkEntity",
    "WorkEntityMember",
    "WorkEntityLink",
    "WorkEntityEvent",
    "WorkEntityStage",
    "WorkEntityTask",
    "WorkEntityMilestone",
    "WorkEntityScheduleDependency",
    "WorkEntityArtifact",
    "Competency",
    "CompetencyQuestion",
    "CompetencyChoice",
    "CompetencyInterpretation",
    "CompetencyAssignment",
    "CompetencyAttempt",
    "CompetencyAnswer",
    "IndividualDevelopmentPlanItem",
]
