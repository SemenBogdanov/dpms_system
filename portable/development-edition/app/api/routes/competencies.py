"""Competency development API."""
import json
import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import get_db, get_current_user
from app.models.competency import (
    Competency,
    CompetencyAnswer,
    CompetencyAssignment,
    CompetencyAttempt,
    CompetencyChoice,
    CompetencyInterpretation,
    CompetencyQuestion,
    IndividualDevelopmentPlanItem,
)
from app.models.user import User, UserRole
from app.schemas.competency import (
    CompetencyAccess,
    CompetencyAnswerRequest,
    CompetencyAnswerResponse,
    CompetencyAttemptStartResponse,
    CompetencyChoiceRead,
    CompetencyListResponse,
    CompetencyQuestionRead,
    CompetencyResultResponse,
    CompetencySummary,
    ConstructorAssignmentCreate,
    ConstructorAssignmentRead,
    ConstructorAssignmentSet,
    ConstructorChoiceRead,
    ConstructorCompetencyDetail,
    ConstructorCompetencyCreate,
    ConstructorCompetencyUpdate,
    ConstructorInterpretationRead,
    ConstructorQuestionRead,
    ConstructorReportResponse,
    ConstructorReportRow,
    DevelopmentPlanItemCreate,
    DevelopmentPlanItemRead,
    DevelopmentPlanItemUpdate,
    DevelopmentPlanAdminSummaryResponse,
    DevelopmentPlanAdminSummaryUser,
    DevelopmentPlanImportRequest,
    DevelopmentPlanImportResponse,
    DevelopmentPlanPromptResponse,
    DevelopmentPlanReportAssessment,
    DevelopmentPlanReportResponse,
    DevelopmentPlanRoadmapPoint,
)
from app.services.competencies import (
    active_attempt,
    attempt_for_user_or_admin,
    can_use_constructor,
    can_use_development,
    create_or_get_active_attempt,
    ensure_builtin_competencies,
    ensure_constructor_access,
    ensure_development_access,
    ensure_competency_visible_to_user,
    finish_attempt,
    get_competency_or_404,
    latest_attempt,
    questions_for_competency,
    save_answer,
    to_utc,
)

router = APIRouter()


def _question_read(question: CompetencyQuestion) -> CompetencyQuestionRead:
    choices = sorted(question.choices, key=lambda item: item.position)
    return CompetencyQuestionRead(
        id=question.id,
        text=question.text,
        question_type=question.question_type,
        position=question.position,
        choices=[CompetencyChoiceRead(id=choice.id, text=choice.text) for choice in choices],
    )


def _result_response(attempt: CompetencyAttempt, competency: Competency) -> CompetencyResultResponse:
    return CompetencyResultResponse(
        attempt_id=attempt.id,
        competency_id=competency.id,
        competency_title=competency.title,
        status=attempt.status,
        score_ib=attempt.score_ib,
        score_ich=attempt.score_ich,
        is_overused=attempt.is_overused,
        interpretation_text=attempt.interpretation_text,
        avg_time_per_question=float(attempt.avg_time_per_question) if attempt.avg_time_per_question is not None else None,
        completed_at=attempt.completed_at,
        retake_allowed_at=attempt.retake_allowed_at,
    )


async def _attempt_maps_for_user(
    db: AsyncSession,
    user_id: UUID,
    competency_ids: list[UUID],
) -> tuple[dict[UUID, CompetencyAttempt], dict[UUID, CompetencyAttempt]]:
    """Вернуть latest/active attempts без отдельных запросов по каждой компетенции."""
    if not competency_ids:
        return {}, {}
    result = await db.execute(
        select(CompetencyAttempt)
        .where(
            CompetencyAttempt.user_id == user_id,
            CompetencyAttempt.competency_id.in_(competency_ids),
        )
        .order_by(CompetencyAttempt.competency_id, CompetencyAttempt.started_at.desc())
    )
    latest_by_competency: dict[UUID, CompetencyAttempt] = {}
    active_by_competency: dict[UUID, CompetencyAttempt] = {}
    for attempt in result.scalars().all():
        latest_by_competency.setdefault(attempt.competency_id, attempt)
        if attempt.status == "in_progress":
            active_by_competency.setdefault(attempt.competency_id, attempt)
    return latest_by_competency, active_by_competency


async def _constructor_counts(db: AsyncSession, competency_id: UUID) -> tuple[int, int, int]:
    assignments_result = await db.execute(
        select(CompetencyAssignment).where(CompetencyAssignment.competency_id == competency_id)
    )
    attempts_result = await db.execute(
        select(CompetencyAttempt).where(CompetencyAttempt.competency_id == competency_id)
    )
    assignments = list(assignments_result.scalars().all())
    attempts = list(attempts_result.scalars().all())
    completed_count = len([attempt for attempt in attempts if attempt.status == "completed"])
    return len(assignments), len(attempts), completed_count


async def _constructor_summary(db: AsyncSession, competency: Competency, status: str = "content") -> CompetencySummary:
    assigned_count, attempts_count, completed_count = await _constructor_counts(db, competency.id)
    active_questions = [question for question in competency.questions if question.is_active]
    return CompetencySummary(
        id=competency.id,
        title=competency.title,
        description=competency.description,
        source=competency.source,
        department=competency.department,
        visibility=competency.visibility,
        created_by_id=competency.created_by_id,
        questions_count=len(active_questions),
        status=status,
        is_required_builtin=competency.source == "builtin",
        assigned_count=assigned_count,
        attempts_count=attempts_count,
        completed_count=completed_count,
        can_edit_content=attempts_count == 0,
    )


async def _constructor_detail(db: AsyncSession, competency: Competency) -> ConstructorCompetencyDetail:
    summary = await _constructor_summary(db, competency)
    questions = []
    for question in sorted([item for item in competency.questions if item.is_active], key=lambda item: item.position):
        questions.append(
            ConstructorQuestionRead(
                id=question.id,
                text=question.text,
                question_type=question.question_type,
                position=question.position,
                choices=[
                    ConstructorChoiceRead(
                        id=choice.id,
                        text=choice.text,
                        value=choice.value,
                        position=choice.position,
                    )
                    for choice in sorted(question.choices, key=lambda item: item.position)
                ],
            )
        )
    interpretations = [
        ConstructorInterpretationRead(
            id=item.id,
            min_score_ib=item.min_score_ib,
            max_score_ib=item.max_score_ib,
            text=item.text,
            overuse_modifier_text=item.overuse_modifier_text,
            recommendation_text=item.recommendation_text,
        )
        for item in sorted(competency.interpretations, key=lambda item: (item.min_score_ib, item.max_score_ib))
    ]
    return ConstructorCompetencyDetail(**summary.model_dump(), questions=questions, interpretations=interpretations)


def _ensure_constructor_owner(competency: Competency, user: User) -> None:
    if competency.source != "custom":
        raise HTTPException(status_code=400, detail="Базовые компетенции нельзя менять через конструктор")
    if user.role != UserRole.admin and competency.created_by_id != user.id:
        raise HTTPException(status_code=403, detail="Можно управлять только своими компетенциями")


async def _replace_constructor_content(
    db: AsyncSession,
    competency: Competency,
    questions: list,
    interpretations: list,
) -> None:
    question_ids_result = await db.execute(
        select(CompetencyQuestion.id).where(CompetencyQuestion.competency_id == competency.id)
    )
    question_ids = list(question_ids_result.scalars().all())
    if question_ids:
        await db.execute(delete(CompetencyChoice).where(CompetencyChoice.question_id.in_(question_ids)))
    await db.execute(delete(CompetencyQuestion).where(CompetencyQuestion.competency_id == competency.id))
    await db.execute(delete(CompetencyInterpretation).where(CompetencyInterpretation.competency_id == competency.id))

    for q_index, question_data in enumerate(questions, start=1):
        question = CompetencyQuestion(
            competency_id=competency.id,
            text=question_data.text.strip(),
            question_type=question_data.question_type or "custom",
            position=q_index,
            is_active=True,
        )
        db.add(question)
        await db.flush()
        for c_index, choice_data in enumerate(question_data.choices, start=1):
            db.add(
                CompetencyChoice(
                    question_id=question.id,
                    text=choice_data.text.strip(),
                    value=choice_data.value,
                    position=c_index,
                )
            )
    for item in interpretations:
        db.add(
            CompetencyInterpretation(
                competency_id=competency.id,
                min_score_ib=item.min_score_ib,
                max_score_ib=item.max_score_ib,
                text=item.text.strip(),
                overuse_modifier_text=item.overuse_modifier_text.strip() if item.overuse_modifier_text else None,
                recommendation_text=item.recommendation_text.strip() if item.recommendation_text else None,
            )
        )


def _attention_points(attempt: CompetencyAttempt | None, questions_count: int) -> list[str]:
    if not attempt:
        return ["Опрос не пройден"]
    if attempt.status != "completed":
        return ["Оценка начата, но не завершена"]

    points: list[str] = []
    if attempt.score_ib is not None and attempt.score_ib <= max(1, questions_count * 2):
        points.append("Низкий ИБ относительно числа вопросов")
    if attempt.is_overused:
        points.append("Есть риск чрезмерного развития: ИЧ выше порога")
    if attempt.interpretation_text:
        text = attempt.interpretation_text.replace("\n", " ").strip()
        if text:
            points.append(text[:220])
    return points or ["Критических маркеров для разговора не выделено"]


def _parse_import_due_at(value: str | None) -> datetime | None:
    if not value:
        return None
    text_value = str(value).strip()
    if not text_value:
        return None
    try:
        if len(text_value) == 10:
            return datetime.fromisoformat(text_value).replace(tzinfo=timezone.utc)
        return to_utc(datetime.fromisoformat(text_value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _repair_json_newlines_in_strings(value: str) -> str:
    """GPT sometimes returns raw line breaks inside JSON strings; JSON requires escaped ones."""
    chars: list[str] = []
    in_string = False
    escaped = False
    for char in value:
        if char == '"' and not escaped:
            in_string = not in_string
            chars.append(char)
            continue
        if char in "\r\n" and in_string:
            chars.append(" ")
            escaped = False
            continue
        chars.append(char)
        if char == "\\" and not escaped:
            escaped = True
        else:
            escaped = False
    return "".join(chars)


def _extract_json_object(raw_text: str) -> dict:
    text_value = raw_text.strip()
    first_brace = text_value.find("{")
    last_brace = text_value.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        text_value = text_value[first_brace : last_brace + 1]
    try:
        data = json.loads(text_value)
    except json.JSONDecodeError as exc:
        try:
            data = json.loads(_repair_json_newlines_in_strings(text_value))
        except json.JSONDecodeError as repaired_exc:
            raise HTTPException(
                status_code=400,
                detail="Ответ должен быть валидным JSON по формату dpms_ipr_v1. Проверьте кавычки, запятые и переносы строк внутри значений.",
            ) from repaired_exc
    if not isinstance(data, dict):
        raise HTTPException(status_code=400, detail="JSON должен быть объектом")
    return data


def _normalize_competency_title(value: str) -> str:
    text_value = value.strip().lower().replace("ё", "е")
    text_value = re.sub(r"^\d+[\).\s-]*", "", text_value)
    text_value = re.sub(r"\s+", " ", text_value)
    return text_value


async def _competency_titles(db: AsyncSession, competency_ids: set[UUID]) -> dict[UUID, str]:
    if not competency_ids:
        return {}
    comp_result = await db.execute(select(Competency).where(Competency.id.in_(competency_ids)))
    return {item.id: item.title for item in comp_result.scalars().all()}


def _plan_item_read(item: IndividualDevelopmentPlanItem, competency_titles: dict[UUID, str]) -> DevelopmentPlanItemRead:
    return DevelopmentPlanItemRead(
        id=item.id,
        competency_id=item.competency_id,
        source_attempt_id=item.source_attempt_id,
        competency_title=competency_titles.get(item.competency_id) if item.competency_id else None,
        goal=item.goal,
        action_text=item.action_text,
        expected_result=item.expected_result,
        due_at=item.due_at,
        status=item.status,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


async def _plan_items_for_user(db: AsyncSession, user_id: UUID) -> list[IndividualDevelopmentPlanItem]:
    result = await db.execute(
        select(IndividualDevelopmentPlanItem)
        .where(IndividualDevelopmentPlanItem.user_id == user_id)
        .order_by(IndividualDevelopmentPlanItem.created_at.desc())
    )
    return list(result.scalars().all())


async def _latest_completed_attempts_for_user(db: AsyncSession, user_id: UUID) -> list[tuple[CompetencyAttempt, Competency]]:
    result = await db.execute(
        select(CompetencyAttempt, Competency)
        .join(Competency, Competency.id == CompetencyAttempt.competency_id)
        .where(
            CompetencyAttempt.user_id == user_id,
            CompetencyAttempt.status == "completed",
            Competency.is_active.is_(True),
        )
        .order_by(CompetencyAttempt.completed_at.desc().nullslast(), CompetencyAttempt.started_at.desc())
    )
    latest_by_competency: dict[UUID, tuple[CompetencyAttempt, Competency]] = {}
    for attempt, competency in result.all():
        latest_by_competency.setdefault(competency.id, (attempt, competency))
    return list(latest_by_competency.values())


def _build_development_prompt(user: User, attempts: list[tuple[CompetencyAttempt, Competency]]) -> str:
    assessment_lines = []
    for attempt, competency in attempts:
        interpretation = (attempt.interpretation_text or "Интерпретация отсутствует").replace("\n", " ")
        assessment_lines.append(
            f"- {competency.title}: source={competency.source}, ИБ={attempt.score_ib}, ИЧ={attempt.score_ich}, "
            f"чрезмерное развитие={attempt.is_overused}, дата={attempt.completed_at.isoformat() if attempt.completed_at else 'нет'}, "
            f"интерпретация={interpretation}"
        )
    if not assessment_lines:
        assessment_lines.append("- Завершенных оценок пока нет. Сформируй только общую структуру ИПР и попроси пройти базовые оценки.")

    return "\n".join(
        [
            "Ты GPT-5. Сформируй индивидуальный план развития сотрудника для DPMS.",
            "",
            "Контекст методологии:",
            "- Используется модель компетенций Lominger: компетенция описывается наблюдаемыми поведенческими маркерами.",
            "- Оценка связана с Learning Agility: способность быстро учиться, переносить опыт, действовать в неопределенности и менять поведение по обратной связи.",
            "- Базовые компетенции являются обязательным организационным контуром. Они связаны с целевыми функциями подразделения и требованиями постановления 171.",
            "- ИБ показывает выраженность компетенции. ИЧ показывает риск чрезмерного развития: сильная сторона может стать блокером других компетенций.",
            "",
            f"Сотрудник: {user.full_name} ({user.email})",
            "Результаты пройденных оценок:",
            *assessment_lines,
            "",
            "Задача:",
            "1. Выдели 2-4 приоритетные зоны развития.",
            "2. Сформируй конкретные действия на 3 месяца: рабочие практики, наблюдаемые маркеры результата, сроки.",
            "3. Добавь книги или материалы, которые можно включить в ИПР как отдельные мероприятия. Книги должны быть преимущественно на русском языке или иметь доступный русский перевод. Не выдумывай несуществующие книги и авторов.",
            "4. Не придумывай оценки, используй только переданные ИБ/ИЧ и интерпретации.",
            "",
            "Верни строго JSON без Markdown по формату:",
            "{",
            '  "version": "dpms_ipr_v1",',
            '  "summary": "короткий вывод по развитию",',
            '  "items": [',
            "    {",
            '      "competency_title": "точное название компетенции или null",',
            '      "goal": "цель развития до 255 символов",',
            '      "action_text": "конкретное действие/мероприятие",',
            '      "expected_result": "наблюдаемый результат",',
            '      "due_at": "YYYY-MM-DD или null"',
            "    }",
            "  ],",
            '  "books": [',
            "    {",
            '      "competency_title": "точное название компетенции или null",',
            '      "title": "название книги",',
            '      "author": "автор",',
            '      "why": "зачем читать и какой навык развивает"',
            "    }",
            "  ],",
            '  "roadmap": [',
            '    {"month": 1, "focus": "фокус месяца", "milestone": "проверяемая отметка"}',
            "  ]",
            "}",
        ]
    )


async def _development_report_for_user(db: AsyncSession, user: User) -> DevelopmentPlanReportResponse:
    attempts = await _latest_completed_attempts_for_user(db, user.id)
    items = await _plan_items_for_user(db, user.id)
    competency_titles = await _competency_titles(db, {item.competency_id for item in items if item.competency_id})

    status_counts = {status: 0 for status in ("planned", "in_progress", "done", "cancelled")}
    for item in items:
        status_counts[item.status] = status_counts.get(item.status, 0) + 1
    active_total = len([item for item in items if item.status != "cancelled"])
    progress_percent = round(status_counts.get("done", 0) / active_total * 100) if active_total else 0

    assessments = [
        DevelopmentPlanReportAssessment(
            attempt_id=attempt.id,
            competency_id=competency.id,
            competency_title=competency.title,
            source=competency.source,
            score_ib=attempt.score_ib,
            score_ich=attempt.score_ich,
            is_overused=attempt.is_overused,
            interpretation_text=attempt.interpretation_text,
            completed_at=attempt.completed_at,
            retake_allowed_at=attempt.retake_allowed_at,
        )
        for attempt, competency in attempts
    ]
    roadmap: list[DevelopmentPlanRoadmapPoint] = [
        DevelopmentPlanRoadmapPoint(
            title=f"Оценка: {assessment.competency_title}",
            description=f"ИБ {assessment.score_ib or '—'}, ИЧ {assessment.score_ich or '—'}",
            status="assessment_completed",
            completed_at=assessment.completed_at,
        )
        for assessment in assessments
    ]
    roadmap.extend(
        DevelopmentPlanRoadmapPoint(
            id=item.id,
            title=item.goal,
            description=item.action_text,
            status=item.status,
            due_at=item.due_at,
            completed_at=item.updated_at if item.status == "done" else None,
        )
        for item in sorted(items, key=lambda item: (item.due_at or item.created_at, item.created_at))
    )

    return DevelopmentPlanReportResponse(
        user_id=user.id,
        full_name=user.full_name,
        email=user.email,
        completed_assessments_count=len(assessments),
        plan_total=len(items),
        plan_planned=status_counts.get("planned", 0),
        plan_in_progress=status_counts.get("in_progress", 0),
        plan_done=status_counts.get("done", 0),
        plan_cancelled=status_counts.get("cancelled", 0),
        progress_percent=progress_percent,
        assessments=assessments,
        roadmap=roadmap,
    )


@router.get("/access", response_model=CompetencyAccess)
async def access(current_user: User = Depends(get_current_user)):
    """Current user's competency feature access."""
    return CompetencyAccess(
        development_enabled=can_use_development(current_user),
        constructor_enabled=can_use_constructor(current_user),
        is_admin=current_user.role == UserRole.admin,
    )


@router.get("/my", response_model=CompetencyListResponse)
async def my_competencies(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List builtin competencies and user-visible custom assignments."""
    ensure_development_access(current_user)

    competencies_result = await db.execute(
        select(Competency)
        .options(selectinload(Competency.questions))
        .where(Competency.is_active.is_(True), Competency.source == "builtin")
        .order_by(Competency.title)
    )
    competencies = list(competencies_result.scalars().all())

    public_custom_result = await db.execute(
        select(Competency)
        .options(selectinload(Competency.questions))
        .where(
            Competency.is_active.is_(True),
            Competency.source == "custom",
            Competency.visibility == "all",
        )
        .order_by(Competency.created_at.desc())
    )
    competencies.extend(list(public_custom_result.scalars().all()))

    assignments_result = await db.execute(
        select(CompetencyAssignment)
        .where(CompetencyAssignment.target_user_id == current_user.id)
        .order_by(CompetencyAssignment.created_at.desc())
    )
    assignments = list(assignments_result.scalars().all())
    custom_ids = {assignment.competency_id for assignment in assignments}
    if custom_ids:
        custom_result = await db.execute(
            select(Competency)
            .options(selectinload(Competency.questions))
            .where(Competency.id.in_(custom_ids), Competency.is_active.is_(True))
        )
        competencies.extend(list(custom_result.scalars().all()))

    items: list[CompetencySummary] = []
    seen: set[UUID] = set()
    latest_by_competency, active_by_competency = await _attempt_maps_for_user(
        db,
        current_user.id,
        [competency.id for competency in competencies],
    )
    for competency in competencies:
        if competency.id in seen:
            continue
        seen.add(competency.id)
        latest = latest_by_competency.get(competency.id)
        active = active_by_competency.get(competency.id)
        status = "not_started"
        if active:
            status = "in_progress"
        elif latest and latest.status == "completed":
            status = "completed"
        items.append(
            CompetencySummary(
                id=competency.id,
                title=competency.title,
                description=competency.description,
                source=competency.source,
                department=competency.department,
                visibility=competency.visibility,
                created_by_id=competency.created_by_id,
                questions_count=len([q for q in competency.questions if q.is_active]),
                status=status,
                is_required_builtin=competency.source == "builtin",
                active_attempt_id=active.id if active else None,
                latest_attempt_id=latest.id if latest else None,
                score_ib=latest.score_ib if latest else None,
                score_ich=latest.score_ich if latest else None,
                is_overused=latest.is_overused if latest else False,
                completed_at=latest.completed_at if latest else None,
                retake_allowed_at=latest.retake_allowed_at if latest else None,
            )
        )
    return CompetencyListResponse(competencies=items)


@router.post("/my/{competency_id}/start", response_model=CompetencyAttemptStartResponse)
async def start_attempt(
    competency_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start or continue a competency attempt."""
    ensure_development_access(current_user)
    await ensure_builtin_competencies(db)
    competency = await get_competency_or_404(db, competency_id)
    await ensure_competency_visible_to_user(db, competency, current_user)

    active = await active_attempt(db, current_user.id, competency.id)
    if active:
        attempt = active
    else:
        latest = await latest_attempt(db, current_user.id, competency.id)
        if latest and latest.status == "completed" and latest.retake_allowed_at and to_utc(latest.retake_allowed_at) > datetime.now(timezone.utc):
            raise HTTPException(status_code=409, detail="Повторное прохождение пока недоступно")
        attempt = await create_or_get_active_attempt(db, current_user.id, competency.id)

    questions = await questions_for_competency(db, competency.id)
    return CompetencyAttemptStartResponse(
        attempt_id=attempt.id,
        competency_id=competency.id,
        competency_title=competency.title,
        competency_description=competency.description,
        status=attempt.status,
        questions=[_question_read(question) for question in questions],
    )


@router.post("/attempts/{attempt_id}/answer", response_model=CompetencyAnswerResponse)
async def answer_attempt(
    attempt_id: UUID,
    body: CompetencyAnswerRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Save answer. Validates question and choice ownership."""
    ensure_development_access(current_user)
    attempt = await attempt_for_user_or_admin(db, attempt_id, current_user)
    if attempt.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Отвечать может только владелец попытки")
    answered_count, total_questions = await save_answer(
        db,
        attempt,
        body.question_id,
        body.choice_id,
        body.time_spent_seconds,
        body.timed_out,
    )
    return CompetencyAnswerResponse(saved=True, answered_count=answered_count, total_questions=total_questions)


@router.post("/attempts/{attempt_id}/finish", response_model=CompetencyResultResponse)
async def finish_attempt_route(
    attempt_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Finish attempt and calculate IB/ICH."""
    ensure_development_access(current_user)
    attempt = await attempt_for_user_or_admin(db, attempt_id, current_user)
    if attempt.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="Завершить попытку может только владелец")
    attempt = await finish_attempt(db, attempt)
    competency = await get_competency_or_404(db, attempt.competency_id)
    return _result_response(attempt, competency)


@router.get("/attempts/{attempt_id}/result", response_model=CompetencyResultResponse)
async def attempt_result(
    attempt_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Read attempt result."""
    ensure_development_access(current_user)
    attempt = await attempt_for_user_or_admin(db, attempt_id, current_user)
    competency = await get_competency_or_404(db, attempt.competency_id)
    return _result_response(attempt, competency)


@router.delete("/attempts/{attempt_id}")
async def delete_attempt(
    attempt_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin-only deletion of an assessment attempt, used to allow exceptional retake."""
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Удаление результатов доступно только администратору")
    result = await db.execute(select(CompetencyAttempt).where(CompetencyAttempt.id == attempt_id))
    attempt = result.scalar_one_or_none()
    if not attempt:
        raise HTTPException(status_code=404, detail="Результат оценки не найден")
    await db.delete(attempt)
    await db.flush()
    return {"deleted": True, "attempt_id": str(attempt_id)}


@router.get("/development-plan/my", response_model=list[DevelopmentPlanItemRead])
async def list_plan_items(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Current user's individual development plan items."""
    ensure_development_access(current_user)
    items = await _plan_items_for_user(db, current_user.id)
    competency_titles = await _competency_titles(db, {item.competency_id for item in items if item.competency_id})
    return [_plan_item_read(item, competency_titles) for item in items]


@router.get("/development-plan/my/ai-prompt", response_model=DevelopmentPlanPromptResponse)
async def development_plan_ai_prompt(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Build standardized prompt for cloud LLM-based IPR planning."""
    ensure_development_access(current_user)
    attempts = await _latest_completed_attempts_for_user(db, current_user.id)
    return DevelopmentPlanPromptResponse(
        prompt=_build_development_prompt(current_user, attempts),
        completed_assessments_count=len(attempts),
        generated_at=datetime.now(timezone.utc),
    )


@router.post("/development-plan/my/import-ai", response_model=DevelopmentPlanImportResponse)
async def import_ai_development_plan(
    body: DevelopmentPlanImportRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Import standardized dpms_ipr_v1 JSON into user's IPR."""
    ensure_development_access(current_user)
    data = _extract_json_object(body.raw_text)
    warnings: list[str] = []
    if data.get("version") != "dpms_ipr_v1":
        warnings.append("Версия JSON отличается от dpms_ipr_v1, импорт выполнен по совместимым полям")

    competency_stmt = select(Competency).where(Competency.is_active.is_(True))
    if current_user.role != UserRole.admin:
        assignments_result = await db.execute(
            select(CompetencyAssignment.competency_id).where(CompetencyAssignment.target_user_id == current_user.id)
        )
        assigned_ids = set(assignments_result.scalars().all())
        visibility_clauses = [Competency.source == "builtin", Competency.visibility == "all"]
        if assigned_ids:
            visibility_clauses.append(Competency.id.in_(assigned_ids))
        competency_stmt = competency_stmt.where(or_(*visibility_clauses))
    competencies_result = await db.execute(competency_stmt)
    competencies = list(competencies_result.scalars().all())
    competency_by_title: dict[str, Competency] = {}
    for competency in competencies:
        competency_by_title[competency.title.strip().lower()] = competency
        competency_by_title[_normalize_competency_title(competency.title)] = competency
    latest_attempts = {
        competency.id: attempt
        for attempt, competency in await _latest_completed_attempts_for_user(db, current_user.id)
    }

    source_items = data.get("items") or []
    if not isinstance(source_items, list):
        raise HTTPException(status_code=400, detail="Поле items должно быть массивом")
    import_items = list(source_items)

    books = data.get("books") or []
    if isinstance(books, list):
        for book in books:
            if not isinstance(book, dict):
                continue
            title = str(book.get("title") or "").strip()
            if not title:
                continue
            author = str(book.get("author") or "").strip()
            why = str(book.get("why") or "").strip()
            import_items.append(
                {
                    "competency_title": book.get("competency_title"),
                    "goal": f"Прочитать: {title}"[:255],
                    "action_text": f"Книга: {title}{f' — {author}' if author else ''}. {why}".strip(),
                    "expected_result": why or "Зафиксировать выводы и применить один прием в рабочей практике.",
                    "due_at": None,
                }
            )

    if len(import_items) > 30:
        warnings.append("Импорт ограничен первыми 30 мероприятиями")
        import_items = import_items[:30]

    imported: list[IndividualDevelopmentPlanItem] = []
    skipped_count = 0
    for index, raw_item in enumerate(import_items, start=1):
        if not isinstance(raw_item, dict):
            skipped_count += 1
            warnings.append(f"Пункт {index} пропущен: ожидается объект")
            continue
        goal = str(raw_item.get("goal") or "").strip()
        action_text = str(raw_item.get("action_text") or "").strip()
        if len(goal) < 3 or len(action_text) < 3:
            skipped_count += 1
            warnings.append(f"Пункт {index} пропущен: нет цели или действия")
            continue
        competency = None
        competency_title = raw_item.get("competency_title")
        if competency_title:
            title_key = str(competency_title).strip()
            competency = competency_by_title.get(title_key.lower()) or competency_by_title.get(_normalize_competency_title(title_key))
            if not competency:
                warnings.append(f"Пункт {index}: компетенция не найдена, добавлено без привязки")
        due_at = _parse_import_due_at(raw_item.get("due_at"))
        item = IndividualDevelopmentPlanItem(
            user_id=current_user.id,
            competency_id=competency.id if competency else None,
            source_attempt_id=latest_attempts.get(competency.id).id if competency and competency.id in latest_attempts else None,
            goal=goal[:255],
            action_text=action_text,
            expected_result=str(raw_item.get("expected_result") or "").strip() or None,
            due_at=due_at,
        )
        db.add(item)
        imported.append(item)

    await db.flush()
    for item in imported:
        await db.refresh(item)
    competency_titles = await _competency_titles(db, {item.competency_id for item in imported if item.competency_id})
    return DevelopmentPlanImportResponse(
        imported_count=len(imported),
        skipped_count=skipped_count,
        warnings=warnings,
        items=[_plan_item_read(item, competency_titles) for item in imported],
    )


@router.get("/development-plan/my/report", response_model=DevelopmentPlanReportResponse)
async def my_development_plan_report(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Current user's development roadmap report."""
    ensure_development_access(current_user)
    return await _development_report_for_user(db, current_user)


@router.get("/development-plan/admin/report", response_model=DevelopmentPlanAdminSummaryResponse | DevelopmentPlanReportResponse)
async def admin_development_plan_report(
    user_id: UUID | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Admin aggregate report or selected employee roadmap."""
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=403, detail="Доступно только администратору")
    if user_id:
        user_result = await db.execute(select(User).where(User.id == user_id, User.is_active.is_(True)))
        user = user_result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=404, detail="Сотрудник не найден")
        return await _development_report_for_user(db, user)

    users_result = await db.execute(select(User).where(User.is_active.is_(True)).order_by(User.full_name))
    users = [user for user in users_result.scalars().all() if can_use_development(user)]
    if not users:
        return DevelopmentPlanAdminSummaryResponse(
            total_enabled_users=0,
            users_with_completed_assessments=0,
            completed_assessments_count=0,
            users_with_plan=0,
            plan_total=0,
            plan_planned=0,
            plan_in_progress=0,
            plan_done=0,
            plan_cancelled=0,
            users=[],
        )
    attempts_result = await db.execute(
        select(CompetencyAttempt).where(
            CompetencyAttempt.user_id.in_([user.id for user in users]),
            CompetencyAttempt.status == "completed",
        )
    )
    attempts = list(attempts_result.scalars().all())
    items_result = await db.execute(
        select(IndividualDevelopmentPlanItem).where(
            IndividualDevelopmentPlanItem.user_id.in_([user.id for user in users])
        )
    )
    items = list(items_result.scalars().all())

    attempts_by_user: dict[UUID, list[CompetencyAttempt]] = {}
    for attempt in attempts:
        attempts_by_user.setdefault(attempt.user_id, []).append(attempt)
    items_by_user: dict[UUID, list[IndividualDevelopmentPlanItem]] = {}
    for item in items:
        items_by_user.setdefault(item.user_id, []).append(item)

    status_totals = {status: 0 for status in ("planned", "in_progress", "done", "cancelled")}
    user_rows: list[DevelopmentPlanAdminSummaryUser] = []
    for user in users:
        user_items = items_by_user.get(user.id, [])
        done_count = len([item for item in user_items if item.status == "done"])
        in_progress_count = len([item for item in user_items if item.status == "in_progress"])
        active_total = len([item for item in user_items if item.status != "cancelled"])
        progress_percent = round(done_count / active_total * 100) if active_total else 0
        for item in user_items:
            status_totals[item.status] = status_totals.get(item.status, 0) + 1
        activity_values = [attempt.completed_at for attempt in attempts_by_user.get(user.id, []) if attempt.completed_at]
        activity_values.extend([item.updated_at for item in user_items if item.updated_at])
        user_rows.append(
            DevelopmentPlanAdminSummaryUser(
                user_id=user.id,
                full_name=user.full_name,
                email=user.email,
                completed_assessments_count=len(attempts_by_user.get(user.id, [])),
                plan_total=len(user_items),
                plan_done=done_count,
                plan_in_progress=in_progress_count,
                progress_percent=progress_percent,
                last_activity_at=max(activity_values) if activity_values else None,
            )
        )

    return DevelopmentPlanAdminSummaryResponse(
        total_enabled_users=len(users),
        users_with_completed_assessments=len([user for user in users if attempts_by_user.get(user.id)]),
        completed_assessments_count=len(attempts),
        users_with_plan=len([user for user in users if items_by_user.get(user.id)]),
        plan_total=len(items),
        plan_planned=status_totals.get("planned", 0),
        plan_in_progress=status_totals.get("in_progress", 0),
        plan_done=status_totals.get("done", 0),
        plan_cancelled=status_totals.get("cancelled", 0),
        users=user_rows,
    )


@router.post("/development-plan/my", response_model=DevelopmentPlanItemRead)
async def create_plan_item(
    body: DevelopmentPlanItemCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create current user's IPR item."""
    ensure_development_access(current_user)
    item = IndividualDevelopmentPlanItem(
        user_id=current_user.id,
        competency_id=body.competency_id,
        source_attempt_id=body.source_attempt_id,
        goal=body.goal.strip(),
        action_text=body.action_text.strip(),
        expected_result=body.expected_result.strip() if body.expected_result else None,
        due_at=body.due_at,
    )
    db.add(item)
    await db.flush()
    await db.refresh(item)
    competency_title = None
    if item.competency_id:
        comp = await db.execute(select(Competency).where(Competency.id == item.competency_id))
        competency = comp.scalar_one_or_none()
        competency_title = competency.title if competency else None
    return DevelopmentPlanItemRead(
        id=item.id,
        competency_id=item.competency_id,
        source_attempt_id=item.source_attempt_id,
        competency_title=competency_title,
        goal=item.goal,
        action_text=item.action_text,
        expected_result=item.expected_result,
        due_at=item.due_at,
        status=item.status,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.patch("/development-plan/my/{item_id}", response_model=DevelopmentPlanItemRead)
async def update_plan_item(
    item_id: UUID,
    body: DevelopmentPlanItemUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update current user's IPR item."""
    ensure_development_access(current_user)
    result = await db.execute(
        select(IndividualDevelopmentPlanItem).where(
            IndividualDevelopmentPlanItem.id == item_id,
            IndividualDevelopmentPlanItem.user_id == current_user.id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Пункт ИПР не найден")
    if body.competency_id is not None:
        item.competency_id = body.competency_id
    if body.source_attempt_id is not None:
        item.source_attempt_id = body.source_attempt_id
    if body.goal is not None:
        item.goal = body.goal.strip()
    if body.action_text is not None:
        item.action_text = body.action_text.strip()
    if body.expected_result is not None:
        item.expected_result = body.expected_result.strip() or None
    if body.due_at is not None:
        item.due_at = body.due_at
    if body.status is not None:
        if body.status not in {"planned", "in_progress", "done", "cancelled"}:
            raise HTTPException(status_code=400, detail="Некорректный статус")
        item.status = body.status
    await db.flush()
    await db.refresh(item)
    return DevelopmentPlanItemRead(
        id=item.id,
        competency_id=item.competency_id,
        source_attempt_id=item.source_attempt_id,
        competency_title=None,
        goal=item.goal,
        action_text=item.action_text,
        expected_result=item.expected_result,
        due_at=item.due_at,
        status=item.status,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


@router.delete("/development-plan/my/{item_id}")
async def delete_plan_item(
    item_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Delete current user's IPR item."""
    ensure_development_access(current_user)
    result = await db.execute(
        select(IndividualDevelopmentPlanItem).where(
            IndividualDevelopmentPlanItem.id == item_id,
            IndividualDevelopmentPlanItem.user_id == current_user.id,
        )
    )
    item = result.scalar_one_or_none()
    if not item:
        raise HTTPException(status_code=404, detail="Пункт ИПР не найден")
    await db.delete(item)
    await db.flush()
    return {"deleted": True, "item_id": str(item_id)}


@router.get("/constructor", response_model=list[CompetencySummary])
async def constructor_list(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List competencies available for constructor owner/admin."""
    ensure_constructor_access(current_user)
    stmt = (
        select(Competency)
        .options(selectinload(Competency.questions))
        .where(Competency.source == "custom", Competency.is_active.is_(True))
        .order_by(Competency.created_at.desc())
    )
    if current_user.role != UserRole.admin:
        stmt = stmt.where(Competency.created_by_id == current_user.id)
    result = await db.execute(stmt)
    return [await _constructor_summary(db, item) for item in result.scalars().all()]


@router.get("/constructor/{competency_id}", response_model=ConstructorCompetencyDetail)
async def constructor_detail(
    competency_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Return custom competency content for editing."""
    ensure_constructor_access(current_user)
    competency = await get_competency_or_404(db, competency_id)
    _ensure_constructor_owner(competency, current_user)
    return await _constructor_detail(db, competency)


@router.patch("/constructor/{competency_id}", response_model=ConstructorCompetencyDetail)
async def constructor_update(
    competency_id: UUID,
    body: ConstructorCompetencyUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update custom competency metadata and, before attempts exist, content."""
    ensure_constructor_access(current_user)
    competency = await get_competency_or_404(db, competency_id)
    _ensure_constructor_owner(competency, current_user)
    _, attempts_count, _ = await _constructor_counts(db, competency.id)

    fields_set = body.model_fields_set

    if "title" in fields_set and body.title is not None:
        competency.title = body.title.strip()
    if "description" in fields_set:
        competency.description = body.description.strip() if body.description else None
    if "department" in fields_set:
        competency.department = body.department.strip() if body.department else None
    if "visibility" in fields_set and body.visibility is not None:
        competency.visibility = body.visibility

    content_update_requested = body.questions is not None or body.interpretations is not None
    if content_update_requested:
        if attempts_count > 0:
            raise HTTPException(status_code=400, detail="Нельзя менять вопросы после начала прохождений")
        if body.questions is None or body.interpretations is None:
            raise HTTPException(status_code=400, detail="Для обновления содержания нужны вопросы и интерпретации")
        await _replace_constructor_content(db, competency, body.questions, body.interpretations)

    await db.flush()
    refreshed = await get_competency_or_404(db, competency.id)
    return await _constructor_detail(db, refreshed)


@router.delete("/constructor/{competency_id}", response_model=CompetencySummary)
async def constructor_delete(
    competency_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete custom competency."""
    ensure_constructor_access(current_user)
    competency = await get_competency_or_404(db, competency_id)
    _ensure_constructor_owner(competency, current_user)
    competency.is_active = False
    await db.flush()
    return await _constructor_summary(db, competency, status="deleted")


@router.put("/constructor/{competency_id}/assignments", response_model=CompetencySummary)
async def constructor_set_assignments(
    competency_id: UUID,
    body: ConstructorAssignmentSet,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Replace target user assignment list and optionally update visibility."""
    ensure_constructor_access(current_user)
    competency = await get_competency_or_404(db, competency_id)
    _ensure_constructor_owner(competency, current_user)

    if body.visibility is not None:
        competency.visibility = body.visibility

    target_user_ids = list(dict.fromkeys(body.target_user_ids))
    if target_user_ids:
        users_result = await db.execute(
            select(User).where(User.id.in_(target_user_ids), User.is_active.is_(True))
        )
        users = list(users_result.scalars().all())
        found_ids = {user.id for user in users}
        missing = [user_id for user_id in target_user_ids if user_id not in found_ids]
        if missing:
            raise HTTPException(status_code=404, detail="Один или несколько сотрудников не найдены")

    existing_result = await db.execute(
        select(CompetencyAssignment).where(CompetencyAssignment.competency_id == competency.id)
    )
    existing = list(existing_result.scalars().all())
    existing_by_user = {item.target_user_id: item for item in existing}
    target_set = set(target_user_ids)
    remove_ids = [item.id for item in existing if item.target_user_id not in target_set]
    if remove_ids:
        await db.execute(delete(CompetencyAssignment).where(CompetencyAssignment.id.in_(remove_ids)))
    for user_id in target_user_ids:
        if user_id not in existing_by_user:
            db.add(
                CompetencyAssignment(
                    competency_id=competency.id,
                    target_user_id=user_id,
                    assigned_by_id=current_user.id,
                    status="assigned",
                )
            )

    await db.flush()
    refreshed = await get_competency_or_404(db, competency.id)
    return await _constructor_summary(db, refreshed)


@router.get("/constructor/{competency_id}/report", response_model=ConstructorReportResponse)
async def constructor_report(
    competency_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Report custom competency completion facts for owner/admin."""
    ensure_constructor_access(current_user)
    competency = await get_competency_or_404(db, competency_id)
    _ensure_constructor_owner(competency, current_user)

    assignments_result = await db.execute(
        select(CompetencyAssignment).where(CompetencyAssignment.competency_id == competency.id)
    )
    assignments = list(assignments_result.scalars().all())
    assignment_by_user = {assignment.target_user_id: assignment for assignment in assignments}

    attempts_result = await db.execute(
        select(CompetencyAttempt)
        .where(CompetencyAttempt.competency_id == competency.id)
        .order_by(CompetencyAttempt.started_at.desc())
    )
    attempts_by_user: dict[UUID, CompetencyAttempt] = {}
    for attempt in attempts_result.scalars().all():
        attempts_by_user.setdefault(attempt.user_id, attempt)

    if competency.visibility == "all":
        users_result = await db.execute(select(User).where(User.is_active.is_(True)).order_by(User.full_name))
        target_users = [user for user in users_result.scalars().all() if can_use_development(user)]
    else:
        target_ids = set(assignment_by_user.keys()) | set(attempts_by_user.keys())
        if target_ids:
            users_result = await db.execute(select(User).where(User.id.in_(target_ids)).order_by(User.full_name))
            target_users = list(users_result.scalars().all())
        else:
            target_users = []

    questions_count = len([question for question in competency.questions if question.is_active])
    rows: list[ConstructorReportRow] = []
    for user in target_users:
        assignment = assignment_by_user.get(user.id)
        attempt = attempts_by_user.get(user.id)
        rows.append(
            ConstructorReportRow(
                user_id=user.id,
                full_name=user.full_name,
                email=user.email,
                assignment_status=assignment.status if assignment else None,
                attempt_status=attempt.status if attempt else "not_started",
                score_ib=attempt.score_ib if attempt else None,
                score_ich=attempt.score_ich if attempt else None,
                is_overused=attempt.is_overused if attempt else False,
                completed_at=attempt.completed_at if attempt else None,
                retake_allowed_at=attempt.retake_allowed_at if attempt else None,
                attention_points=_attention_points(attempt, questions_count),
                interpretation_text=attempt.interpretation_text if attempt else None,
            )
        )

    completed_count = len([row for row in rows if row.attempt_status == "completed"])
    return ConstructorReportResponse(
        competency_id=competency.id,
        title=competency.title,
        visibility=competency.visibility,
        assigned_count=len(assignments),
        completed_count=completed_count,
        rows=rows,
    )


@router.get("/assignments/{assignment_id}", response_model=CompetencySummary)
async def assignment_detail(
    assignment_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resolve authenticated assignment link."""
    ensure_development_access(current_user)
    result = await db.execute(
        select(CompetencyAssignment).where(
            CompetencyAssignment.id == assignment_id,
            CompetencyAssignment.target_user_id == current_user.id,
        )
    )
    assignment = result.scalar_one_or_none()
    if not assignment and current_user.role != UserRole.admin:
        raise HTTPException(status_code=404, detail="Назначение не найдено")
    if not assignment:
        admin_result = await db.execute(select(CompetencyAssignment).where(CompetencyAssignment.id == assignment_id))
        assignment = admin_result.scalar_one_or_none()
    if not assignment:
        raise HTTPException(status_code=404, detail="Назначение не найдено")
    competency = await get_competency_or_404(db, assignment.competency_id)
    latest = await latest_attempt(db, assignment.target_user_id, competency.id)
    return CompetencySummary(
        id=competency.id,
        title=competency.title,
        description=competency.description,
        source=competency.source,
        department=competency.department,
        visibility=competency.visibility,
        created_by_id=competency.created_by_id,
        questions_count=len([q for q in competency.questions if q.is_active]),
        status=assignment.status if not latest else latest.status,
        is_required_builtin=competency.source == "builtin",
        latest_attempt_id=latest.id if latest else None,
        score_ib=latest.score_ib if latest else None,
        score_ich=latest.score_ich if latest else None,
        is_overused=latest.is_overused if latest else False,
        completed_at=latest.completed_at if latest else None,
        retake_allowed_at=latest.retake_allowed_at if latest else None,
    )


@router.post("/constructor", response_model=CompetencySummary)
async def constructor_create(
    body: ConstructorCompetencyCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create custom competency with questions and interpretations."""
    ensure_constructor_access(current_user)
    competency = Competency(
        title=body.title.strip(),
        description=body.description.strip() if body.description else None,
        source="custom",
        created_by_id=current_user.id,
        department=body.department.strip() if body.department else None,
        visibility=body.visibility,
        version=1,
        is_active=True,
    )
    db.add(competency)
    await db.flush()
    for q_index, question_data in enumerate(body.questions, start=1):
        question = CompetencyQuestion(
            competency_id=competency.id,
            text=question_data.text.strip(),
            question_type=question_data.question_type or "custom",
            position=q_index,
            is_active=True,
        )
        db.add(question)
        await db.flush()
        for c_index, choice_data in enumerate(question_data.choices, start=1):
            db.add(
                CompetencyChoice(
                    question_id=question.id,
                    text=choice_data.text.strip(),
                    value=choice_data.value,
                    position=c_index,
                )
            )
    for item in body.interpretations:
        db.add(
            CompetencyInterpretation(
                competency_id=competency.id,
                min_score_ib=item.min_score_ib,
                max_score_ib=item.max_score_ib,
                text=item.text.strip(),
                overuse_modifier_text=item.overuse_modifier_text.strip() if item.overuse_modifier_text else None,
                recommendation_text=item.recommendation_text.strip() if item.recommendation_text else None,
            )
        )
    await db.flush()
    refreshed = await get_competency_or_404(db, competency.id)
    return await _constructor_summary(db, refreshed)


@router.post("/constructor/{competency_id}/assign", response_model=ConstructorAssignmentRead)
async def constructor_assign(
    competency_id: UUID,
    body: ConstructorAssignmentCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Assign competency to a DPMS user and return internal route."""
    ensure_constructor_access(current_user)
    competency = await get_competency_or_404(db, competency_id)
    if current_user.role != UserRole.admin and competency.created_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="Можно назначать только свои компетенции")
    target = await db.execute(select(User).where(User.id == body.target_user_id, User.is_active.is_(True)))
    if not target.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Сотрудник не найден")
    assignment = CompetencyAssignment(
        competency_id=competency.id,
        target_user_id=body.target_user_id,
        assigned_by_id=current_user.id,
        status="assigned",
        due_at=body.due_at,
    )
    db.add(assignment)
    await db.flush()
    return ConstructorAssignmentRead(
        id=assignment.id,
        competency_id=assignment.competency_id,
        target_user_id=assignment.target_user_id,
        status=assignment.status,
        link=f"/competencies/assignments/{assignment.id}",
        due_at=assignment.due_at,
        created_at=assignment.created_at,
    )
