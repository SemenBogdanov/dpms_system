"""Transactional smoke test for criterion-level task acceptance and Q payout."""
import asyncio
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import func, select

from app.database import AsyncSessionLocal
from app.models.catalog import Complexity
from app.models.knowledge import KnowledgeArticle
from app.models.task import (
    Task,
    TaskAcceptanceCriterion,
    TaskPriority,
    TaskStatus,
    TaskType,
)
from app.models.transaction import QTransaction
from app.models.user import League, User, UserRole
from app.schemas.task_acceptance import (
    AcceptanceCriteriaReviewRequest,
    AcceptanceCriteriaSubmitRequest,
    AcceptanceCriterionCreate,
    AcceptanceCriterionDecision,
    AcceptanceCriterionEvidence,
    AcceptanceCriterionRevisionRequest,
    AcceptancePlanUpdate,
)
from app.schemas.task import TaskCreate
from app.services.queue import submit_for_review, validate_task
from app.services.task_acceptance import (
    initialize_acceptance_plan,
    replace_acceptance_plan,
    review_acceptance_criteria,
    revise_acceptance_decision,
    submit_acceptance_criteria,
)
from app.services.wallet import credit_q


async def expect_http_error(awaitable, status_code: int) -> None:
    try:
        await awaitable
    except HTTPException as error:
        assert error.status_code == status_code, error.detail
    else:
        raise AssertionError(f"Expected HTTP {status_code}")


def smoke_user(role: UserRole, label: str) -> User:
    return User(
        full_name=f"Acceptance smoke {label}",
        email=f"acceptance-smoke-{label}-{uuid.uuid4()}@dpms-demo.ru",
        league=League.A,
        role=role,
        mpw=0,
        wip_limit=10,
        task_workspace_enabled=True,
        is_active=True,
    )


async def run() -> None:
    try:
        TaskCreate(
            title="Invalid completed task",
            task_type=TaskType.docs,
            complexity=Complexity.S,
            estimated_q=Decimal("1.0"),
            priority=TaskPriority.medium,
            min_league=League.C,
            status=TaskStatus.done,
            estimator_id=uuid.uuid4(),
            acceptance_mode="criteria",
            acceptance_criteria=[
                AcceptanceCriterionCreate(title="Pending result", kind="required")
            ],
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("Direct task creation must not bypass the acceptance workflow")

    try:
        AcceptanceCriterionRevisionRequest(
            criterion_id=uuid.uuid4(),
            approved=False,
            comment=" ",
        )
    except ValidationError:
        pass
    else:
        raise AssertionError("Acceptance decision revision requires a reason")

    async with AsyncSessionLocal() as db:
        owner = smoke_user(UserRole.teamlead, "owner")
        executor = smoke_user(UserRole.executor, "executor")
        outsider = smoke_user(UserRole.teamlead, "outsider")
        admin = smoke_user(UserRole.admin, "admin")
        db.add_all([owner, executor, outsider, admin])
        await db.flush()

        task = Task(
            title="SMOKE: criterion acceptance",
            description="Disposable acceptance workflow test.",
            task_type=TaskType.docs,
            complexity=Complexity.S,
            estimated_q=Decimal("12.5"),
            priority=TaskPriority.medium,
            status=TaskStatus.in_progress,
            min_league=League.C,
            assignee_id=executor.id,
            estimator_id=owner.id,
            acceptance_owner_id=owner.id,
            started_at=datetime.now(timezone.utc),
        )
        db.add(task)
        await db.flush()
        await initialize_acceptance_plan(
            db,
            task,
            owner_id=owner.id,
            mode="criteria",
            criteria=[
                AcceptanceCriterionCreate(
                    title="Result is attached",
                    kind="required",
                ),
                AcceptanceCriterionCreate(
                    title="Quality check passed",
                    kind="quality_gate",
                ),
            ],
        )
        criteria = list(
            (
                await db.execute(
                    select(TaskAcceptanceCriterion)
                    .where(TaskAcceptanceCriterion.task_id == task.id)
                    .order_by(TaskAcceptanceCriterion.position)
                )
            ).scalars().all()
        )
        first, second = criteria

        await expect_http_error(
            replace_acceptance_plan(
                db,
                task.id,
                AcceptancePlanUpdate(
                    expected_revision=task.acceptance_revision,
                    mode="full",
                    criteria=[],
                ),
                owner,
            ),
            409,
        )

        await submit_acceptance_criteria(
            db,
            task.id,
            AcceptanceCriteriaSubmitRequest(
                items=[
                    AcceptanceCriterionEvidence(
                        criterion_id=first.id,
                        evidence_comment="Result verified in the attached report.",
                    )
                ]
            ),
            executor,
        )
        await expect_http_error(
            review_acceptance_criteria(
                db,
                task.id,
                AcceptanceCriteriaReviewRequest(
                    decisions=[
                        AcceptanceCriterionDecision(
                            criterion_id=first.id,
                            approved=True,
                        )
                    ]
                ),
                outsider,
            ),
            403,
        )
        await expect_http_error(
            review_acceptance_criteria(
                db,
                task.id,
                AcceptanceCriteriaReviewRequest(
                    decisions=[
                        AcceptanceCriterionDecision(
                            criterion_id=first.id,
                            approved=True,
                        )
                    ]
                ),
                admin,
            ),
            400,
        )
        partial = await review_acceptance_criteria(
            db,
            task.id,
            AcceptanceCriteriaReviewRequest(
                decisions=[
                    AcceptanceCriterionDecision(
                        criterion_id=first.id,
                        approved=True,
                    )
                ]
            ),
            owner,
        )
        assert partial.state == "partially_accepted"
        assert sum(item.status == "accepted" for item in partial.criteria) == 1

        await expect_http_error(
            revise_acceptance_decision(
                db,
                task.id,
                AcceptanceCriterionRevisionRequest(
                    criterion_id=first.id,
                    approved=False,
                    comment="Outsider must not revise the decision.",
                ),
                outsider,
            ),
            403,
        )
        await expect_http_error(
            revise_acceptance_decision(
                db,
                task.id,
                AcceptanceCriterionRevisionRequest(
                    criterion_id=first.id,
                    approved=False,
                    comment="Executor must not revise own acceptance.",
                ),
                executor,
            ),
            403,
        )

        revised_to_returned = await revise_acceptance_decision(
            db,
            task.id,
            AcceptanceCriterionRevisionRequest(
                criterion_id=first.id,
                approved=False,
                comment="Accepted by mistake; inspect the report again.",
            ),
            owner,
        )
        first_after_return = revised_to_returned.criteria[0]
        assert first_after_return.status == "returned"
        assert first_after_return.decision_change_count == 1

        revised_to_accepted = await revise_acceptance_decision(
            db,
            task.id,
            AcceptanceCriterionRevisionRequest(
                criterion_id=first.id,
                approved=True,
                comment="Second review confirms the submitted evidence.",
            ),
            owner,
        )
        first_after_accept = revised_to_accepted.criteria[0]
        assert first_after_accept.status == "accepted"
        assert first_after_accept.decision_change_count == 2
        assert [event.event_type for event in first_after_accept.events] == [
            "submitted",
            "accepted",
            "decision_changed",
            "decision_changed",
        ]
        await expect_http_error(
            revise_acceptance_decision(
                db,
                task.id,
                AcceptanceCriterionRevisionRequest(
                    criterion_id=first.id,
                    approved=False,
                    comment="Third change must be rejected.",
                ),
                owner,
            ),
            409,
        )

        await expect_http_error(
            submit_for_review(db, executor.id, task.id, brief_rating=5),
            409,
        )

        await submit_acceptance_criteria(
            db,
            task.id,
            AcceptanceCriteriaSubmitRequest(
                items=[
                    AcceptanceCriterionEvidence(
                        criterion_id=second.id,
                        evidence_comment="Initial quality report.",
                    )
                ]
            ),
            executor,
        )
        returned = await review_acceptance_criteria(
            db,
            task.id,
            AcceptanceCriteriaReviewRequest(
                decisions=[
                    AcceptanceCriterionDecision(
                        criterion_id=second.id,
                        approved=False,
                        comment="Add the missing control sample.",
                    )
                ]
            ),
            owner,
        )
        assert returned.criteria[0].status == "accepted"
        assert returned.criteria[1].status == "returned"

        await submit_acceptance_criteria(
            db,
            task.id,
            AcceptanceCriteriaSubmitRequest(
                items=[
                    AcceptanceCriterionEvidence(
                        criterion_id=second.id,
                        evidence_comment="Control sample added.",
                    )
                ]
            ),
            executor,
        )
        complete = await review_acceptance_criteria(
            db,
            task.id,
            AcceptanceCriteriaReviewRequest(
                decisions=[
                    AcceptanceCriterionDecision(
                        criterion_id=second.id,
                        approved=True,
                    )
                ]
            ),
            owner,
        )
        assert all(item.status == "accepted" for item in complete.criteria)
        assert [event.event_type for event in complete.criteria[1].events] == [
            "submitted",
            "returned",
            "submitted",
            "accepted",
        ]

        submitted_task = await submit_for_review(
            db,
            executor.id,
            task.id,
            comment="All acceptance criteria are complete.",
            brief_rating=5,
        )
        assert submitted_task.acceptance_state == "submitted"

        reopened_by_revision = await revise_acceptance_decision(
            db,
            task.id,
            AcceptanceCriterionRevisionRequest(
                criterion_id=second.id,
                approved=False,
                comment="Final review exposed an incorrect criterion decision.",
            ),
            owner,
        )
        await db.refresh(task)
        assert task.status == TaskStatus.in_progress
        assert task.completed_at is None
        assert reopened_by_revision.criteria[1].status == "returned"
        assert reopened_by_revision.criteria[1].decision_change_count == 1
        assert executor.wallet_main == Decimal("0")

        reaccepted_after_revision = await revise_acceptance_decision(
            db,
            task.id,
            AcceptanceCriterionRevisionRequest(
                criterion_id=second.id,
                approved=True,
                comment="Repeated review confirms the original evidence.",
            ),
            owner,
        )
        assert reaccepted_after_revision.criteria[1].status == "accepted"
        assert reaccepted_after_revision.criteria[1].decision_change_count == 2
        assert [
            event.event_type for event in reaccepted_after_revision.criteria[1].events
        ] == [
            "submitted",
            "returned",
            "submitted",
            "accepted",
            "decision_changed",
            "decision_changed",
        ]
        await submit_for_review(
            db,
            executor.id,
            task.id,
            comment="Criteria decisions were reconciled.",
            brief_rating=5,
        )

        returned_task = await validate_task(
            db,
            owner.id,
            task.id,
            approved=False,
            comment="Clarify the final summary without changing accepted criteria.",
        )
        assert returned_task.status == TaskStatus.in_progress
        assert returned_task.acceptance_state == "returned"
        unchanged_criteria = list(
            (
                await db.execute(
                    select(TaskAcceptanceCriterion)
                    .where(TaskAcceptanceCriterion.task_id == task.id)
                    .order_by(TaskAcceptanceCriterion.position)
                )
            ).scalars().all()
        )
        assert all(item.status == "accepted" for item in unchanged_criteria)
        resubmitted_task = await submit_for_review(
            db,
            executor.id,
            task.id,
            comment="Final summary clarified.",
            brief_rating=5,
        )
        assert resubmitted_task.acceptance_state == "submitted"
        await expect_http_error(
            validate_task(db, outsider.id, task.id, approved=True),
            403,
        )
        await expect_http_error(
            validate_task(db, admin.id, task.id, approved=True),
            400,
        )
        accepted = await validate_task(db, owner.id, task.id, approved=True)
        assert accepted.status == TaskStatus.done
        assert accepted.acceptance_state == "accepted"
        await expect_http_error(
            revise_acceptance_decision(
                db,
                task.id,
                AcceptanceCriterionRevisionRequest(
                    criterion_id=second.id,
                    approved=False,
                    comment="Final payout must make decisions immutable.",
                ),
                owner,
            ),
            409,
        )

        payout_prefix = f"task:{task.id}:acceptance:{task.acceptance_revision}"
        wallet_after_acceptance = executor.wallet_main
        assert wallet_after_acceptance == Decimal("12.5")
        payout_count = (
            await db.execute(
                select(func.count(QTransaction.id)).where(
                    QTransaction.idempotency_key.in_(
                        [f"{payout_prefix}:main", f"{payout_prefix}:karma"]
                    )
                )
            )
        ).scalar_one()
        assert payout_count == 1

        await credit_q(
            db,
            executor.id,
            task.estimated_q,
            reason="Idempotency replay",
            task_id=task.id,
            idempotency_prefix=payout_prefix,
        )
        assert executor.wallet_main == wallet_after_acceptance
        replay_count = (
            await db.execute(
                select(func.count(QTransaction.id)).where(
                    QTransaction.idempotency_key.in_(
                        [f"{payout_prefix}:main", f"{payout_prefix}:karma"]
                    )
                )
            )
        ).scalar_one()
        assert replay_count == 1

        article_exists = (
            await db.execute(
                select(func.count(KnowledgeArticle.id)).where(
                    KnowledgeArticle.slug == "priemka-zadach-po-kriteriyam"
                )
            )
        ).scalar_one()
        assert article_exists == 1

        await db.rollback()
        print("Task acceptance smoke OK: criteria, two audited decision changes, final lock, and Q idempotency.")


if __name__ == "__main__":
    asyncio.run(run())
