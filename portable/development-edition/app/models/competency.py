"""Competency assessment models backed by SQLite."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Competency(Base):
    __tablename__ = "competencies"
    __table_args__ = (UniqueConstraint("title", "version", name="uq_competencies_title_version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="builtin", index=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    department: Mapped[str | None] = mapped_column(String(255))
    visibility: Mapped[str] = mapped_column(String(20), nullable=False, default="assigned", index=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )

    questions = relationship("CompetencyQuestion", back_populates="competency", cascade="all, delete-orphan")
    interpretations = relationship(
        "CompetencyInterpretation", back_populates="competency", cascade="all, delete-orphan"
    )


class CompetencyQuestion(Base):
    __tablename__ = "competency_questions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    competency_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("competencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    question_type: Mapped[str] = mapped_column(String(40), nullable=False, default="basic_index")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=100)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)

    competency = relationship("Competency", back_populates="questions")
    choices = relationship("CompetencyChoice", back_populates="question", cascade="all, delete-orphan")


class CompetencyChoice(Base):
    __tablename__ = "competency_choices"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    question_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("competency_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=100)

    question = relationship("CompetencyQuestion", back_populates="choices")


class CompetencyInterpretation(Base):
    __tablename__ = "competency_interpretations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    competency_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("competencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    min_score_ib: Mapped[int] = mapped_column(Integer, nullable=False)
    max_score_ib: Mapped[int] = mapped_column(Integer, nullable=False)
    min_score_ich: Mapped[int | None] = mapped_column(Integer)
    max_score_ich: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    overuse_modifier_text: Mapped[str | None] = mapped_column(Text)
    recommendation_text: Mapped[str | None] = mapped_column(Text)

    competency = relationship("Competency", back_populates="interpretations")


class CompetencyAssignment(Base):
    __tablename__ = "competency_assignments"
    __table_args__ = (
        UniqueConstraint("competency_id", "target_user_id", name="uq_competency_assignment_target"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    competency_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("competencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    assigned_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="assigned", index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)


class CompetencyAttempt(Base):
    __tablename__ = "competency_attempts"
    __table_args__ = (
        Index(
            "uq_active_attempt_per_user_competency",
            "user_id",
            "competency_id",
            unique=True,
            sqlite_where=text("status = 'in_progress'"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    assignment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("competency_assignments.id", ondelete="SET NULL"), index=True
    )
    competency_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("competencies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="in_progress", index=True)
    score_ib: Mapped[int | None] = mapped_column(Integer)
    score_ich: Mapped[int | None] = mapped_column(Integer)
    is_overused: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    interpretation_text: Mapped[str | None] = mapped_column(Text)
    avg_time_per_question: Mapped[float | None] = mapped_column(Numeric(7, 2))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retake_allowed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CompetencyAnswer(Base):
    __tablename__ = "competency_answers"
    __table_args__ = (
        UniqueConstraint("attempt_id", "question_id", name="uq_competency_answer_attempt_question"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    attempt_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("competency_attempts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("competency_questions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    choice_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("competency_choices.id", ondelete="SET NULL")
    )
    time_spent_seconds: Mapped[int | None] = mapped_column(Integer)
    timed_out: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow, index=True
    )


class IndividualDevelopmentPlanItem(Base):
    __tablename__ = "individual_development_plan_items"

    id: Mapped[uuid.UUID] = mapped_column(Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    competency_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("competencies.id", ondelete="SET NULL"), index=True
    )
    source_attempt_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("competency_attempts.id", ondelete="SET NULL")
    )
    goal: Mapped[str] = mapped_column(String(255), nullable=False)
    action_text: Mapped[str] = mapped_column(Text, nullable=False)
    expected_result: Mapped[str | None] = mapped_column(Text)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="planned", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
