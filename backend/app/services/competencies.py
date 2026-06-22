"""Competency development business logic."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.competency import (
    Competency,
    CompetencyAssignment,
    CompetencyAnswer,
    CompetencyAttempt,
    CompetencyChoice,
    CompetencyInterpretation,
    CompetencyQuestion,
)
from app.models.user import User, UserRole

BUILTIN_CONTENT_PATH = Path(__file__).resolve().parents[1] / "data" / "competency_content.json"
OVERUSE_THRESHOLD = 14
QUESTION_TIMEOUT_SECONDS = 60


def can_use_development(user: User) -> bool:
    return user.role == UserRole.admin or user.competency_development_enabled


def can_use_constructor(user: User) -> bool:
    return user.role == UserRole.admin or user.competency_constructor_enabled


def ensure_development_access(user: User) -> None:
    if not can_use_development(user):
        raise HTTPException(status_code=403, detail="Нет доступа к разделу развития компетенций")


def ensure_constructor_access(user: User) -> None:
    if not can_use_constructor(user):
        raise HTTPException(status_code=403, detail="Нет доступа к конструктору компетенций")


def _clean_text(value: str | None) -> str | None:
    if value is None:
        return None
    return value.replace("\r", "").strip()


def to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def ensure_builtin_competencies(db: AsyncSession) -> None:
    """Idempotently import builtin competency content."""
    data = json.loads(BUILTIN_CONTENT_PATH.read_text(encoding="utf-8"))
    for competency_index, item in enumerate(data, start=1):
        title = _clean_text(item.get("title")) or f"Компетенция {competency_index}"
        existing_result = await db.execute(
            select(Competency)
            .options(
                selectinload(Competency.questions).selectinload(CompetencyQuestion.choices),
                selectinload(Competency.interpretations),
            )
            .where(Competency.title == title, Competency.version == 1, Competency.source == "builtin")
        )
        competency = existing_result.scalar_one_or_none()
        if not competency:
            competency = Competency(
                title=title,
                description=_clean_text(item.get("description")),
                source="builtin",
                visibility="all",
                version=1,
                is_active=True,
            )
            db.add(competency)
            await db.flush()
            existing_questions: list[CompetencyQuestion] = []
            existing_interpretations: list[CompetencyInterpretation] = []
        else:
            competency.description = _clean_text(item.get("description"))
            competency.visibility = "all"
            competency.is_active = True
            existing_questions = list(competency.questions)
            existing_interpretations = list(competency.interpretations)

        existing_question_positions = {question.position for question in existing_questions}
        for question_index, question_data in enumerate(item.get("questions", []), start=1):
            if question_index in existing_question_positions:
                continue
            question = CompetencyQuestion(
                competency_id=competency.id,
                text=_clean_text(question_data.get("text")) or "",
                question_type=question_data.get("question_type") or "basic_index",
                position=question_index,
                is_active=True,
            )
            db.add(question)
            await db.flush()
            for choice_index, choice_data in enumerate(question_data.get("choices", []), start=1):
                db.add(
                    CompetencyChoice(
                        question_id=question.id,
                        text=_clean_text(choice_data.get("text")) or "",
                        value=int(choice_data.get("value") or 0),
                        position=choice_index,
                    )
                )

        existing_interpretation_ranges = {
            (interpretation.min_score_ib, interpretation.max_score_ib)
            for interpretation in existing_interpretations
        }
        for interpretation_data in item.get("interpretations", []):
            min_score_ib = int(interpretation_data.get("min_score_ib") or 0)
            max_score_ib = int(interpretation_data.get("max_score_ib") or 0)
            if (min_score_ib, max_score_ib) in existing_interpretation_ranges:
                continue
            db.add(
                CompetencyInterpretation(
                    competency_id=competency.id,
                    min_score_ib=min_score_ib,
                    max_score_ib=max_score_ib,
                    text=_clean_text(interpretation_data.get("base_text") or interpretation_data.get("text")) or "",
                    overuse_modifier_text=_clean_text(interpretation_data.get("overuse_modifier_text")),
                )
            )
    await db.flush()


async def get_competency_or_404(db: AsyncSession, competency_id: UUID) -> Competency:
    result = await db.execute(
        select(Competency)
        .options(
            selectinload(Competency.questions).selectinload(CompetencyQuestion.choices),
            selectinload(Competency.interpretations),
        )
        .where(Competency.id == competency_id, Competency.is_active.is_(True))
    )
    competency = result.scalar_one_or_none()
    if not competency:
        raise HTTPException(status_code=404, detail="Компетенция не найдена")
    return competency


async def latest_attempt(db: AsyncSession, user_id: UUID, competency_id: UUID) -> CompetencyAttempt | None:
    result = await db.execute(
        select(CompetencyAttempt)
        .where(CompetencyAttempt.user_id == user_id, CompetencyAttempt.competency_id == competency_id)
        .order_by(CompetencyAttempt.started_at.desc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def active_attempt(db: AsyncSession, user_id: UUID, competency_id: UUID) -> CompetencyAttempt | None:
    result = await db.execute(
        select(CompetencyAttempt).where(
            CompetencyAttempt.user_id == user_id,
            CompetencyAttempt.competency_id == competency_id,
            CompetencyAttempt.status == "in_progress",
        )
    )
    return result.scalar_one_or_none()

async def create_or_get_active_attempt(db: AsyncSession, user_id: UUID, competency_id: UUID) -> CompetencyAttempt:
    """Create active attempt atomically or return the one created by a concurrent request."""
    insert_stmt = (
        pg_insert(CompetencyAttempt.__table__)
        .values(
            id=uuid4(),
            user_id=user_id,
            competency_id=competency_id,
            status="in_progress",
            is_overused=False,
            started_at=datetime.now(timezone.utc),
        )
        .on_conflict_do_nothing(
            index_elements=[CompetencyAttempt.user_id, CompetencyAttempt.competency_id],
            index_where=text("status = 'in_progress'"),
        )
        .returning(CompetencyAttempt.id)
    )
    inserted_id = (await db.execute(insert_stmt)).scalar_one_or_none()
    if inserted_id:
        result = await db.execute(select(CompetencyAttempt).where(CompetencyAttempt.id == inserted_id))
        attempt = result.scalar_one()
    else:
        attempt = await active_attempt(db, user_id, competency_id)
    if not attempt:
        raise HTTPException(status_code=500, detail="Не удалось создать попытку")
    return attempt


async def ensure_competency_visible_to_user(db: AsyncSession, competency: Competency, user: User) -> None:
    """Builtin/global competencies are open to enabled users; assigned custom ones require assignment."""
    if user.role == UserRole.admin or competency.source == "builtin" or competency.visibility == "all":
        return
    result = await db.execute(
        select(CompetencyAssignment).where(
            CompetencyAssignment.competency_id == competency.id,
            CompetencyAssignment.target_user_id == user.id,
        )
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=403, detail="Компетенция не назначена сотруднику")


async def attempt_for_user_or_admin(db: AsyncSession, attempt_id: UUID, user: User) -> CompetencyAttempt:
    result = await db.execute(select(CompetencyAttempt).where(CompetencyAttempt.id == attempt_id))
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Попытка не найдена")
    if attempt.user_id != user.id and user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Нет доступа к попытке")
    return attempt


async def questions_for_competency(db: AsyncSession, competency_id: UUID) -> list[CompetencyQuestion]:
    result = await db.execute(
        select(CompetencyQuestion)
        .options(selectinload(CompetencyQuestion.choices))
        .where(CompetencyQuestion.competency_id == competency_id, CompetencyQuestion.is_active.is_(True))
        .order_by(CompetencyQuestion.position)
    )
    return list(result.scalars().all())


async def answers_for_attempt(db: AsyncSession, attempt_id: UUID) -> list[CompetencyAnswer]:
    result = await db.execute(select(CompetencyAnswer).where(CompetencyAnswer.attempt_id == attempt_id))
    return list(result.scalars().all())


async def save_answer(
    db: AsyncSession,
    attempt: CompetencyAttempt,
    question_id: UUID,
    choice_id: UUID | None,
    time_spent_seconds: int | None,
    timed_out: bool,
) -> tuple[int, int]:
    if attempt.status != "in_progress":
        raise HTTPException(status_code=400, detail="Попытка уже завершена")

    question_result = await db.execute(
        select(CompetencyQuestion).where(
            CompetencyQuestion.id == question_id,
            CompetencyQuestion.competency_id == attempt.competency_id,
            CompetencyQuestion.is_active.is_(True),
        )
    )
    question = question_result.scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=400, detail="Вопрос не относится к этой компетенции")

    if choice_id is not None:
        choice_result = await db.execute(
            select(CompetencyChoice).where(
                CompetencyChoice.id == choice_id,
                CompetencyChoice.question_id == question_id,
            )
        )
        if not choice_result.scalar_one_or_none():
            raise HTTPException(status_code=400, detail="Вариант ответа не относится к вопросу")

    saved_at = datetime.now(timezone.utc)
    insert_stmt = pg_insert(CompetencyAnswer.__table__).values(
        id=uuid4(),
        attempt_id=attempt.id,
        question_id=question_id,
        choice_id=choice_id,
        time_spent_seconds=time_spent_seconds,
        timed_out=timed_out,
        created_at=saved_at,
        updated_at=saved_at,
    )
    if timed_out:
        insert_stmt = insert_stmt.on_conflict_do_nothing(constraint="uq_competency_answer_attempt_question")
    else:
        insert_stmt = insert_stmt.on_conflict_do_update(
            constraint="uq_competency_answer_attempt_question",
            set_={
                "choice_id": choice_id,
                "time_spent_seconds": time_spent_seconds,
                "timed_out": False,
                "updated_at": saved_at,
            },
        )
    await db.execute(insert_stmt)
    questions = await questions_for_competency(db, attempt.competency_id)
    answers = await answers_for_attempt(db, attempt.id)
    return len(answers), len(questions)


async def finish_attempt(db: AsyncSession, attempt: CompetencyAttempt) -> CompetencyAttempt:
    if attempt.status != "in_progress":
        return attempt

    questions = await questions_for_competency(db, attempt.competency_id)
    answers = await answers_for_attempt(db, attempt.id)
    answer_by_question = {answer.question_id: answer for answer in answers}
    missing = [question.id for question in questions if question.id not in answer_by_question]
    if missing:
        raise HTTPException(status_code=400, detail="Не все вопросы имеют ответ или таймаут")

    choice_ids = [answer.choice_id for answer in answers if answer.choice_id is not None]
    choices_by_id: dict[UUID, CompetencyChoice] = {}
    if choice_ids:
        choices_result = await db.execute(select(CompetencyChoice).where(CompetencyChoice.id.in_(choice_ids)))
        choices_by_id = {choice.id: choice for choice in choices_result.scalars().all()}

    question_by_id = {question.id: question for question in questions}
    score_ib = 0
    score_ich = 0
    total_time = 0
    counted_time = 0
    for answer in answers:
        if answer.time_spent_seconds is not None:
            total_time += answer.time_spent_seconds
            counted_time += 1
        if answer.timed_out or answer.choice_id is None:
            continue
        if answer.time_spent_seconds is not None and answer.time_spent_seconds >= QUESTION_TIMEOUT_SECONDS:
            continue
        choice = choices_by_id.get(answer.choice_id)
        question = question_by_id.get(answer.question_id)
        if not choice or not question:
            continue
        if question.question_type == "overuse_index":
            score_ich += choice.value
        else:
            score_ib += choice.value

    interpretation = await resolve_interpretation(db, attempt.competency_id, score_ib, score_ich)
    now = datetime.now(timezone.utc)
    attempt.status = "completed"
    attempt.score_ib = score_ib
    attempt.score_ich = score_ich
    attempt.is_overused = score_ich > OVERUSE_THRESHOLD
    attempt.interpretation_text = interpretation
    attempt.avg_time_per_question = round(total_time / counted_time, 2) if counted_time else None
    attempt.completed_at = now
    attempt.retake_allowed_at = now + timedelta(days=365 if score_ib >= 38 else 90)
    await db.flush()
    return attempt


async def resolve_interpretation(db: AsyncSession, competency_id: UUID, score_ib: int, score_ich: int) -> str:
    result = await db.execute(
        select(CompetencyInterpretation)
        .where(
            CompetencyInterpretation.competency_id == competency_id,
            CompetencyInterpretation.min_score_ib <= score_ib,
            CompetencyInterpretation.max_score_ib >= score_ib,
        )
        .order_by(CompetencyInterpretation.min_score_ib)
    )
    item = result.scalars().first()
    if not item:
        return "Для полученного результата пока не задана интерпретация."
    parts = [item.text]
    if score_ich > OVERUSE_THRESHOLD and item.overuse_modifier_text:
        parts.append(item.overuse_modifier_text)
    if item.recommendation_text:
        parts.append(item.recommendation_text)
    return "\n\n".join(part for part in parts if part)
