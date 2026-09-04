"""SQLite models used by the standalone development module."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


from app.models.competency import (  # noqa: E402
    Competency,
    CompetencyAnswer,
    CompetencyAssignment,
    CompetencyAttempt,
    CompetencyChoice,
    CompetencyInterpretation,
    CompetencyQuestion,
    IndividualDevelopmentPlanItem,
)
from app.models.user import League, User, UserRole  # noqa: E402

__all__ = [
    "Base",
    "Competency",
    "CompetencyAnswer",
    "CompetencyAssignment",
    "CompetencyAttempt",
    "CompetencyChoice",
    "CompetencyInterpretation",
    "CompetencyQuestion",
    "IndividualDevelopmentPlanItem",
    "League",
    "User",
    "UserRole",
]
