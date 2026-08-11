"""Transactional smoke test for the personal-task/Q single-execution guard."""
import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from app.api.routes.personal_tasks import update_personal_task
from app.database import AsyncSessionLocal
from app.models.catalog import Complexity
from app.models.personal_task import PersonalTask, PersonalTaskEvent
from app.models.task import Task, TaskPriority, TaskStatus, TaskType
from app.models.user import League, User, UserRole
from app.schemas.personal_task import PersonalTaskUpdate


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


def queue_task(owner: User, assignee: User | None, status: TaskStatus, label: str) -> Task:
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


def personal_task(owner: User, label: str, **links) -> PersonalTask:
    return PersonalTask(
        owner_id=owner.id,
        title=f"SMOKE: {label}",
        status="planned",
        priority="medium",
        category="work",
        start_at=datetime.now(timezone.utc),
        **links,
    )


async def expect_blocked(db, task: PersonalTask, owner: User, message: str) -> None:
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


async def run() -> None:
    async with AsyncSessionLocal() as db:
        owner = smoke_user("owner")
        executor = smoke_user("executor")
        db.add_all([owner, executor])
        await db.flush()

        promoted_q = queue_task(owner, executor, TaskStatus.in_progress, "promoted conflict")
        linked_q = queue_task(owner, executor, TaskStatus.review, "linked conflict")
        second_q = queue_task(owner, None, TaskStatus.in_queue, "ambiguous link")
        self_q = queue_task(owner, owner, TaskStatus.in_progress, "owner execution")
        queued_q = queue_task(owner, executor, TaskStatus.in_queue, "future execution")
        unassigned_review_q = queue_task(owner, None, TaskStatus.review, "unassigned review")
        db.add_all([promoted_q, linked_q, second_q, self_q, queued_q, unassigned_review_q])
        await db.flush()

        promoted_pt = personal_task(
            owner,
            "promoted conflict",
            promoted_task_id=promoted_q.id,
            linked_task_id=promoted_q.id,
        )
        linked_pt = personal_task(owner, "linked conflict", linked_task_id=linked_q.id)
        ambiguous_pt = personal_task(
            owner,
            "ambiguous conflict",
            promoted_task_id=promoted_q.id,
            linked_task_id=second_q.id,
        )
        self_pt = personal_task(owner, "owner execution", linked_task_id=self_q.id)
        queued_pt = personal_task(owner, "future execution", linked_task_id=queued_q.id)
        unassigned_review_pt = personal_task(
            owner,
            "unassigned review",
            linked_task_id=unassigned_review_q.id,
        )
        atomic_link_pt = personal_task(owner, "atomic active link")
        db.add_all([
            promoted_pt,
            linked_pt,
            ambiguous_pt,
            self_pt,
            queued_pt,
            unassigned_review_pt,
            atomic_link_pt,
        ])
        await db.flush()

        try:
            await update_personal_task(
                promoted_pt.id,
                PersonalTaskUpdate(linked_task_id=second_q.id),
                owner,
                db,
            )
        except HTTPException as error:
            assert error.status_code == 409, error.detail
            assert "уже связана" in str(error.detail)
        else:
            raise AssertionError("A promoted personal task cannot acquire a second Q link")
        await db.refresh(promoted_pt)
        assert promoted_pt.linked_task_id == promoted_q.id

        await expect_blocked(db, promoted_pt, owner, "параллельный старт")
        await expect_blocked(db, linked_pt, owner, "параллельный старт")
        await expect_blocked(db, ambiguous_pt, owner, "две разные Q-задачи")
        await expect_blocked(db, unassigned_review_pt, owner, "параллельный старт")

        try:
            await update_personal_task(
                atomic_link_pt.id,
                PersonalTaskUpdate(
                    linked_task_id=linked_q.id,
                    status="in_progress",
                ),
                owner,
                db,
            )
        except HTTPException as error:
            assert error.status_code == 409, error.detail
            assert "параллельный старт" in str(error.detail), error.detail
        else:
            raise AssertionError("Atomic link-and-start must enforce the Q execution guard")
        await db.refresh(atomic_link_pt)
        assert atomic_link_pt.status == "planned"
        assert atomic_link_pt.linked_task_id is None

        await update_personal_task(
            self_pt.id,
            PersonalTaskUpdate(status="in_progress"),
            owner,
            db,
        )
        await update_personal_task(
            queued_pt.id,
            PersonalTaskUpdate(status="in_progress"),
            owner,
            db,
        )
        await db.refresh(self_pt)
        await db.refresh(queued_pt)
        assert self_pt.status == "in_progress"
        assert queued_pt.status == "in_progress"

        await db.rollback()

    print("personal task execution guard smoke: OK")


if __name__ == "__main__":
    asyncio.run(run())
