"""Transactional smoke test for the personal-task/Q single-execution guard.

Expresses the corrected PersonalTask -> Q handoff semantics:

1. A PersonalTask linked/promoted to any non-cancelled Q task
   (in_queue, in_progress assigned to owner, review unassigned, done)
   cannot transition to local in_progress. The in_queue/done conflict
   reports "локальный старт"; an active in_progress/review
   conflict reports "параллельный старт".
2. A cancelled Q relation permits returning the PersonalTask to local
   in_progress.
3. The promote endpoint rejects initial publication from non-publishable
   personal-task states (in_progress/done/archived) and when a manual
   linked_task_id is already present; a planned publication succeeds,
   immediately prevents the PersonalTask from local start while the
   created Q task waits in_queue, and repeated promotion is idempotent.
   Manual linked_task_id changes are rejected with "Ручное изменение
   связи"; an unchanged echo from a cached client remains compatible.
4. A PersonalTask cannot acquire a conflicting second Q link, and an
   atomic link-and-start payload must be rejected by the execution guard.

All assertions run inside a single transaction that is rolled back at the
end, so the smoke test never persists data.
"""
import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.routes.personal_tasks import (
    create_personal_task,
    promote_personal_task,
    update_personal_task,
)
from app.database import AsyncSessionLocal
from app.models.catalog import Complexity
from app.models.personal_task import PersonalTask, PersonalTaskEvent
from app.models.task import Task, TaskPriority, TaskStatus, TaskType
from app.models.user import League, User, UserRole
from app.schemas.personal_task import (
    PersonalTaskCreate,
    PersonalTaskPromoteRequest,
    PersonalTaskUpdate,
)


def smoke_user(label: str) -> User:
    return User(
        full_name=f"Execution guard {label}",
        email=f"execution-guard-{label}-{uuid.uuid4()}@example.invalid",
        league=League.A,
        role=UserRole.executor,
        mpw=0,
        wip_limit=10,
        task_workspace_enabled=True,
        is_active=True,
    )


def queue_task(
    owner: User,
    assignee: User | None,
    status: TaskStatus,
    label: str,
) -> Task:
    return Task(
        title=f"SMOKE: {label}",
        task_type=TaskType.docs,
        complexity=Complexity.S,
        estimated_q=Decimal("1.0"),
        priority=TaskPriority.medium,
        status=status,
        min_league=League.C,
        assignee_id=assignee.id if assignee else None,
        estimator_id=owner.id,
        acceptance_owner_id=owner.id,
        started_at=datetime.now(timezone.utc) if status == TaskStatus.in_progress else None,
    )


def personal_task(owner: User, label: str, *, status: str = "planned", **links) -> PersonalTask:
    return PersonalTask(
        owner_id=owner.id,
        title=f"SMOKE: {label}",
        status=status,
        priority="medium",
        category="work",
        start_at=datetime.now(timezone.utc),
        **links,
    )


async def expect_blocked(
    db,
    task: PersonalTask,
    owner: User,
    *,
    message: str = "",
) -> None:
    """A non-cancelled Q relation must forbid the local in_progress transition."""
    try:
        PersonalTaskUpdate.model_validate(
            {"status": "in_progress", "allow_parallel_execution": True}
        )
    except ValidationError as error:
        assert "allow_parallel_execution" in str(error)
    else:
        raise AssertionError("Legacy parallel-execution override must be rejected")

    try:
        await update_personal_task(
            task.id,
            PersonalTaskUpdate(status="in_progress"),
            owner,
            db,
        )
    except HTTPException as error:
        assert error.status_code == 409, error.detail
        if message:
            assert message in str(error.detail), error.detail
    else:
        raise AssertionError("Conflicting execution must return HTTP 409")

    await db.refresh(task)
    assert task.status == "planned"
    event_count = (
        await db.execute(
            select(func.count(PersonalTaskEvent.id)).where(
                PersonalTaskEvent.task_id == task.id,
                PersonalTaskEvent.event_type == "status_changed",
            )
        )
    ).scalar_one()
    assert event_count == 0


async def expect_allowed(db, task: PersonalTask, owner: User, *, from_status: str = "planned") -> None:
    """A cancelled (or absent) Q relation must permit the local in_progress transition."""
    await update_personal_task(
        task.id,
        PersonalTaskUpdate(status="in_progress"),
        owner,
        db,
    )
    await db.refresh(task)
    assert task.status == "in_progress"
    assert task.status != from_status


async def expect_promote_rejected(
    db,
    task: PersonalTask,
    owner: User,
    *,
    message: str = "",
) -> None:
    """Initial publication must be rejected for non-publishable states or stale links."""
    try:
        await promote_personal_task(
            task.id,
            PersonalTaskPromoteRequest(),
            owner,
            db,
        )
    except HTTPException as error:
        assert error.status_code == 409, error.detail
        if message:
            assert message in str(error.detail), error.detail
    else:
        raise AssertionError("Promotion from a non-publishable state must return HTTP 409")
    await db.refresh(task)
    assert task.promoted_task_id is None


async def run() -> None:
    async with AsyncSessionLocal() as db:
        owner = smoke_user("owner")
        executor = smoke_user("executor")
        db.add_all([owner, executor])
        await db.flush()

        in_queue_q = queue_task(owner, None, TaskStatus.in_queue, "queued wait")
        owner_progress_q = queue_task(owner, owner, TaskStatus.in_progress, "owner execution")
        unassigned_review_q = queue_task(owner, None, TaskStatus.review, "unassigned review")
        done_q = queue_task(owner, executor, TaskStatus.done, "completed by executor")
        cancelled_q = queue_task(owner, executor, TaskStatus.cancelled, "cancelled relation")
        second_q = queue_task(owner, None, TaskStatus.in_queue, "ambiguous second link")
        db.add_all([
            in_queue_q,
            owner_progress_q,
            unassigned_review_q,
            done_q,
            cancelled_q,
            second_q,
        ])
        await db.flush()

        try:
            await create_personal_task(
                PersonalTaskCreate(
                    title="SMOKE: forbidden manual Q link",
                    linked_task_id=in_queue_q.id,
                ),
                owner,
                db,
            )
        except HTTPException as error:
            assert error.status_code == 409, error.detail
            assert "Ручная связь" in str(error.detail), error.detail
        else:
            raise AssertionError("Creating a manual PersonalTask/Q link must be rejected")

        in_queue_pt = personal_task(owner, "queued wait", linked_task_id=in_queue_q.id)
        owner_progress_pt = personal_task(
            owner,
            "owner execution",
            linked_task_id=owner_progress_q.id,
        )
        unassigned_review_pt = personal_task(
            owner,
            "unassigned review",
            linked_task_id=unassigned_review_q.id,
        )
        done_pt = personal_task(owner, "completed by executor", linked_task_id=done_q.id)
        ambiguous_pt = personal_task(
            owner,
            "ambiguous conflict",
            promoted_task_id=in_queue_q.id,
            linked_task_id=second_q.id,
        )
        cancelled_pt = personal_task(owner, "cancelled relation", linked_task_id=cancelled_q.id)
        atomic_link_pt = personal_task(owner, "atomic active link")
        db.add_all([
            in_queue_pt,
            owner_progress_pt,
            unassigned_review_pt,
            done_pt,
            ambiguous_pt,
            cancelled_pt,
            atomic_link_pt,
        ])
        await db.flush()

        await expect_blocked(db, in_queue_pt, owner, message="локальный старт")
        await expect_blocked(db, owner_progress_pt, owner, message="параллельный старт")
        await expect_blocked(db, unassigned_review_pt, owner, message="параллельный старт")
        await expect_blocked(db, done_pt, owner, message="локальный старт")
        await expect_blocked(db, ambiguous_pt, owner, message="две разные Q-задачи")

        try:
            await update_personal_task(
                atomic_link_pt.id,
                PersonalTaskUpdate(
                    linked_task_id=done_q.id,
                    status="in_progress",
                ),
                owner,
                db,
            )
        except HTTPException as error:
            assert error.status_code == 409, error.detail
            assert "Ручное изменение связи" in str(error.detail), error.detail
        else:
            raise AssertionError("Atomic link-and-start must enforce the manual-link guard")
        await db.refresh(atomic_link_pt)
        assert atomic_link_pt.status == "planned"
        assert atomic_link_pt.linked_task_id is None

        echoed_pt = await update_personal_task(
            in_queue_pt.id,
            PersonalTaskUpdate(linked_task_id=in_queue_q.id),
            owner,
            db,
        )
        assert echoed_pt.linked_task_id == in_queue_q.id
        await db.refresh(in_queue_pt)
        assert in_queue_pt.status == "planned"

        await expect_allowed(db, cancelled_pt, owner)

        for blocked_status in ("in_progress", "done", "archived"):
            blocked_pt = personal_task(
                owner,
                f"blocked promote {blocked_status}",
                status=blocked_status,
            )
            db.add(blocked_pt)
            await db.flush()
            await expect_promote_rejected(db, blocked_pt, owner)

        stale_link_pt = personal_task(
            owner,
            "stale manual link",
            status="planned",
            linked_task_id=second_q.id,
        )
        db.add(stale_link_pt)
        await db.flush()
        await expect_promote_rejected(
            db,
            stale_link_pt,
            owner,
            message="уже имеет прежнюю Q-связь",
        )

        planned_pt = personal_task(owner, "planned promotion", status="planned")
        db.add(planned_pt)
        await db.flush()

        promoted_task = await promote_personal_task(
            planned_pt.id,
            PersonalTaskPromoteRequest(),
            owner,
            db,
        )
        await db.flush()
        await db.refresh(promoted_task)
        await db.refresh(planned_pt)
        assert promoted_task.status == TaskStatus.in_queue
        assert promoted_task.assignee_id is None
        assert planned_pt.promoted_task_id == promoted_task.id
        assert planned_pt.linked_task_id == promoted_task.id
        assert planned_pt.promoted_at is not None

        await expect_blocked(
            db,
            planned_pt,
            owner,
            message="локальный старт",
        )

        try:
            await update_personal_task(
                planned_pt.id,
                PersonalTaskUpdate(linked_task_id=second_q.id),
                owner,
                db,
            )
        except HTTPException as error:
            assert error.status_code == 409, error.detail
            assert "Ручное изменение связи" in str(error.detail)
        else:
            raise AssertionError("A promoted personal task cannot acquire a second Q link")
        await db.refresh(planned_pt)
        assert planned_pt.linked_task_id == promoted_task.id

        repeat_task = await promote_personal_task(
            planned_pt.id,
            PersonalTaskPromoteRequest(),
            owner,
            db,
        )
        await db.flush()
        assert repeat_task.id == promoted_task.id
        promoted_q_count = (
            await db.execute(
                select(func.count(Task.id)).where(Task.id == promoted_task.id)
            )
        ).scalar_one()
        assert promoted_q_count == 1

        await db.rollback()

    print("personal task execution guard smoke: OK")


if __name__ == "__main__":
    asyncio.run(run())
