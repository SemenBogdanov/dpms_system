"""Transactional smoke test for the guided project cockpit."""
import asyncio
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy import delete, func, or_, select

from app.api.routes.project_cockpit import (
    apply_project_charter_change,
    apply_project_deadline_change,
    create_guided_project,
    create_project_work,
    record_project_decision,
)
from app.api.routes.work_entities import (
    get_work_entity_readiness,
    update_work_entity,
)
from app.api.routes.work_entity_workspace import (
    create_work_entity_artifact,
    create_work_entity_milestone,
    delete_work_entity_dependency,
    preview_work_entity_milestone_reschedule,
    update_work_entity_milestone,
    update_work_entity_task,
)
from app.database import AsyncSessionLocal
from app.models.knowledge import KnowledgeArticle
from app.models.user import User, UserRole
from app.models.work_entity import (
    WorkEntity,
    WorkEntityArtifact,
    WorkEntityEvent,
    WorkEntityMilestone,
    WorkEntityScheduleDependency,
    WorkEntityTask,
)
from app.schemas.project_cockpit import (
    GuidedProjectCreate,
    GuidedProjectMilestone,
    GuidedProjectTask,
    ProjectDeadlineChangeRequest,
    ProjectCharterChangeRequest,
    ProjectDecisionCreate,
    ProjectWorkCreate,
)
from app.schemas.work_entity import (
    WorkEntityArtifactCreate,
    WorkEntityMilestoneCreate,
    WorkEntityMilestoneRescheduleRequest,
    WorkEntityMilestoneUpdate,
    WorkEntityTaskUpdate,
    WorkEntityUpdate,
)


async def run() -> None:
    async with AsyncSessionLocal() as db:
        user = (
            await db.execute(
                select(User)
                .where(
                    User.is_active.is_(True),
                    or_(
                        User.role == UserRole.admin,
                        User.task_workspace_enabled.is_(True),
                    ),
                )
                .order_by(User.created_at)
                .limit(1)
            )
        ).scalar_one()
        starts_at = datetime.now(timezone.utc) + timedelta(days=1)
        concept_at = starts_at + timedelta(days=7)
        final_at = starts_at + timedelta(days=30)
        created = await create_guided_project(
            GuidedProjectCreate(
                title="SMOKE: сигнал не беспокоить",
                outcome_statement=(
                    "На рабочих местах действует согласованный визуальный "
                    "сигнал «не беспокоить»."
                ),
                success_criteria=(
                    "Образец принят, флажки размещены, инструкция опубликована."
                ),
                constraints="Тестовый проект должен быть удален после проверки.",
                starts_at=starts_at,
                due_at=final_at,
                milestones=[
                    GuidedProjectMilestone(
                        title="Концепция и образец приняты",
                        acceptance_criteria="Есть решение о приемке образца.",
                        baseline_at=concept_at,
                        decision_owner_id=user.id,
                    ),
                    GuidedProjectMilestone(
                        title="Развертывание принято",
                        acceptance_criteria="100 мест оснащены и правило опубликовано.",
                        baseline_at=final_at,
                        decision_owner_id=user.id,
                    ),
                ],
                tasks=[
                    GuidedProjectTask(
                        title="Подготовить образец флажка",
                        acceptance_criteria="Изготовлен физический образец.",
                        baseline_starts_at=starts_at,
                        baseline_due_at=concept_at - timedelta(days=1),
                        assignee_id=user.id,
                        target_milestone_index=0,
                    ),
                    GuidedProjectTask(
                        title="Закупить и разместить флажки",
                        acceptance_criteria="Флажки размещены на 100 местах.",
                        baseline_starts_at=concept_at,
                        baseline_due_at=final_at - timedelta(days=1),
                        assignee_id=user.id,
                        target_milestone_index=1,
                    ),
                ],
            ),
            user,
            db,
        )
        entity_id = created.entity_id
        try:
            milestone_ids = list(
                (
                    await db.execute(
                        select(WorkEntityMilestone.id)
                        .where(WorkEntityMilestone.entity_id == entity_id)
                        .order_by(WorkEntityMilestone.position)
                    )
                ).scalars().all()
            )
            first_milestone_id, second_milestone_id = milestone_ids
            initial_work = await create_project_work(
                entity_id,
                ProjectWorkCreate(
                    title="Проверить понятность правила",
                    acceptance_criteria="Пять пользователей верно поняли сигнал.",
                    baseline_starts_at=starts_at + timedelta(days=1),
                    baseline_due_at=starts_at + timedelta(days=3),
                    assignee_id=user.id,
                    target_milestone_id=first_milestone_id,
                ),
                user,
                db,
            )
            readiness = await get_work_entity_readiness(entity_id, user, db)
            assert readiness.can_activate, readiness.model_dump(mode="json")
            activated = await update_work_entity(
                entity_id,
                WorkEntityUpdate(status="active"),
                user,
                db,
            )
            assert activated.baseline_locked_at is not None
            try:
                await update_work_entity(
                    entity_id,
                    WorkEntityUpdate(status="draft"),
                    user,
                    db,
                )
            except HTTPException as error:
                assert error.status_code == 409
            else:
                raise AssertionError("Active project returned to draft")
            try:
                await update_work_entity(
                    entity_id,
                    WorkEntityUpdate(entity_type="goal"),
                    user,
                    db,
                )
            except HTTPException as error:
                assert error.status_code == 409
            else:
                raise AssertionError("Active project type was changed")
            target_dependency_id = (
                await db.execute(
                    select(WorkEntityScheduleDependency.id).where(
                        WorkEntityScheduleDependency.entity_id == entity_id,
                        WorkEntityScheduleDependency.predecessor_task_id
                        == initial_work.task_id,
                        WorkEntityScheduleDependency.successor_milestone_id
                        == first_milestone_id,
                        WorkEntityScheduleDependency.status == "active",
                    )
                )
            ).scalar_one()
            try:
                await delete_work_entity_dependency(
                    entity_id,
                    target_dependency_id,
                    user,
                    db,
                )
            except HTTPException as error:
                assert error.status_code == 409
            else:
                raise AssertionError("Last task target dependency was deleted")
            try:
                await update_work_entity_milestone(
                    entity_id,
                    first_milestone_id,
                    WorkEntityMilestoneUpdate(
                        status="cancelled",
                        change_reason="Проверка защиты маршрута.",
                    ),
                    user,
                    db,
                )
            except HTTPException as error:
                assert error.status_code == 409
            else:
                raise AssertionError("Milestone with linked work was cancelled")
            retargeted = await update_work_entity_task(
                entity_id,
                initial_work.task_id,
                WorkEntityTaskUpdate(
                    target_milestone_id=second_milestone_id,
                    change_reason="Комитет перенес итоговую проверку работы.",
                ),
                user,
                db,
            )
            assert retargeted.target_milestone_id == second_milestone_id
            current_revision = (
                await db.execute(
                    select(WorkEntity.schedule_revision).where(
                        WorkEntity.id == entity_id
                    )
                )
            ).scalar_one()
            extended = await apply_project_deadline_change(
                entity_id,
                ProjectDeadlineChangeRequest(
                    target_due_at=starts_at + timedelta(days=40),
                    reason="Комитет проверяет сценарий более поздней цели.",
                    expected_revision=current_revision,
                ),
                user,
                db,
            )
            assert extended.forecast_due_at == final_at
            post_launch_milestone = await create_work_entity_milestone(
                entity_id,
                WorkEntityMilestoneCreate(
                    title="Расширенный пилот принят",
                    acceptance_criteria=(
                        "Расширение пилота принято отдельным решением."
                    ),
                    baseline_at=starts_at + timedelta(days=38),
                    decision_owner_id=user.id,
                ),
                user,
                db,
            )
            assert post_launch_milestone.introduced_after_baseline is True
            assert post_launch_milestone.introduced_at_revision is not None
            post_launch = await create_project_work(
                entity_id,
                ProjectWorkCreate(
                    title="Проверить пилот после запуска",
                    acceptance_criteria="Пилот подтвержден пятью пользователями.",
                    baseline_starts_at=starts_at + timedelta(days=31),
                    baseline_due_at=starts_at + timedelta(days=35),
                    assignee_id=user.id,
                    target_milestone_id=post_launch_milestone.id,
                ),
                user,
                db,
            )
            post_launch_task = (
                await db.execute(
                    select(WorkEntityTask).where(
                        WorkEntityTask.id == post_launch.task_id
                    )
                )
            ).scalar_one()
            assert post_launch_task.introduced_after_baseline is True
            assert (
                post_launch_task.introduced_at_revision
                == post_launch.schedule_revision
            )
            forecast_after_new_work = (
                await db.execute(
                    select(WorkEntity.forecast_due_at).where(
                        WorkEntity.id == entity_id
                    )
                )
            ).scalar_one()
            assert forecast_after_new_work == starts_at + timedelta(days=38)
            target_due_at = starts_at + timedelta(days=20)
            applied = await apply_project_deadline_change(
                entity_id,
                ProjectDeadlineChangeRequest(
                    target_due_at=target_due_at,
                    reason="Комитет сократил обязательный срок проекта.",
                    expected_revision=post_launch.schedule_revision,
                ),
                user,
                db,
            )
            assert applied.conflicts, "Shortened target must expose schedule conflicts"
            acceleration = await preview_work_entity_milestone_reschedule(
                entity_id,
                first_milestone_id,
                WorkEntityMilestoneRescheduleRequest(
                    forecast_at=starts_at + timedelta(days=5),
                    reason="Комитет просит пройти проверку раньше.",
                    cascade=True,
                    expected_revision=applied.schedule_revision,
                ),
                user,
                db,
            )
            assert acceleration.shift_days < 0
            assert acceleration.conflicts
            await create_work_entity_artifact(
                entity_id,
                WorkEntityArtifactCreate(
                    artifact_type="evidence",
                    title="Подтверждение проверки концепции",
                    body="Протокол проверки концепции приложен к точке.",
                    milestone_id=first_milestone_id,
                ),
                user,
                db,
            )
            amended = await apply_project_charter_change(
                entity_id,
                ProjectCharterChangeRequest(
                    constraints=(
                        "Тестовый проект удаляется после проверки; "
                        "пилот ограничен одним этажом."
                    ),
                    reason="Комитет уточнил границы пилота.",
                    expected_revision=applied.schedule_revision,
                ),
                user,
                db,
            )
            assert amended.baseline_constraints == (
                "Тестовый проект должен быть удален после проверки."
            )
            await record_project_decision(
                entity_id,
                ProjectDecisionCreate(
                    decided_at=datetime.now(timezone.utc),
                    title="Срок сокращен",
                    decision="Подготовить варианты ускорения и сокращения scope.",
                    reason="Решение проектного комитета.",
                    participants="Проектный комитет",
                    follow_up="Представить обновленный прогноз.",
                    owner_id=user.id,
                    due_at=starts_at + timedelta(days=3),
                ),
                user,
                db,
            )
            amended_entity = (
                await db.execute(
                    select(WorkEntity).where(WorkEntity.id == entity_id)
                )
            ).scalar_one()
            assert amended_entity.baseline_outcome_statement == (
                "На рабочих местах действует согласованный визуальный "
                "сигнал «не беспокоить»."
            )
            assert amended_entity.constraints == (
                "Тестовый проект удаляется после проверки; "
                "пилот ограничен одним этажом."
            )
            binding_to_corrupt = (
                await db.execute(
                    select(WorkEntityScheduleDependency).where(
                        WorkEntityScheduleDependency.entity_id == entity_id,
                        WorkEntityScheduleDependency.predecessor_task_id
                        == initial_work.task_id,
                        WorkEntityScheduleDependency.successor_milestone_id
                        == second_milestone_id,
                        WorkEntityScheduleDependency.status == "active",
                    )
                )
            ).scalar_one()
            await db.delete(binding_to_corrupt)
            await db.flush()
            try:
                await update_work_entity(
                    entity_id,
                    WorkEntityUpdate(status="done"),
                    user,
                    db,
                )
            except HTTPException as error:
                assert error.status_code == 409
                assert error.detail["code"] == "project_completion_blocked"
                assert error.detail["tasks_without_target"] >= 1
            else:
                raise AssertionError("Incomplete project was marked done")
            await db.rollback()
            await db.refresh(user)
            counts = {
                "tasks": int(
                    (
                        await db.execute(
                            select(func.count(WorkEntityTask.id)).where(
                                WorkEntityTask.entity_id == entity_id
                            )
                        )
                    ).scalar_one()
                ),
                "milestones": int(
                    (
                        await db.execute(
                            select(func.count(WorkEntityMilestone.id)).where(
                                WorkEntityMilestone.entity_id == entity_id
                            )
                        )
                    ).scalar_one()
                ),
                "events": int(
                    (
                        await db.execute(
                            select(func.count(WorkEntityEvent.id)).where(
                                WorkEntityEvent.entity_id == entity_id
                            )
                        )
                    ).scalar_one()
                ),
                "decisions": int(
                    (
                        await db.execute(
                            select(func.count(WorkEntityArtifact.id)).where(
                                WorkEntityArtifact.entity_id == entity_id,
                                WorkEntityArtifact.artifact_type == "decision",
                            )
                        )
                    ).scalar_one()
                ),
                "evidence": int(
                    (
                        await db.execute(
                            select(func.count(WorkEntityArtifact.id)).where(
                                WorkEntityArtifact.entity_id == entity_id,
                                WorkEntityArtifact.artifact_type == "evidence",
                            )
                        )
                    ).scalar_one()
                ),
            }
            assert counts["tasks"] == 4
            assert counts["milestones"] == 3
            assert counts["events"] >= 6
            assert counts["decisions"] == 1
            assert counts["evidence"] == 1
            article = (
                await db.execute(
                    select(KnowledgeArticle).where(
                        KnowledgeArticle.slug == "rabochee-prostranstvo-proekta"
                    )
                )
            ).scalar_one()
            assert "Пульт проекта" in article.title
            assert "планирование от результата" in article.body.lower()
            assert "артефактом типа «подтверждение»" in article.body.lower()
            await update_work_entity(
                entity_id,
                WorkEntityUpdate(status="archived"),
                user,
                db,
            )
            try:
                await update_work_entity(
                    entity_id,
                    WorkEntityUpdate(status="active"),
                    user,
                    db,
                )
            except HTTPException as error:
                assert error.status_code == 409
            else:
                raise AssertionError("Archived project was reactivated")
            done_fixture = WorkEntity(
                owner_id=user.id,
                entity_type="goal",
                title="SMOKE: завершенная цель",
                status="done",
                actual_due_at=datetime.now(timezone.utc),
            )
            db.add(done_fixture)
            await db.flush()
            try:
                await update_work_entity(
                    done_fixture.id,
                    WorkEntityUpdate(status="active"),
                    user,
                    db,
                )
            except HTTPException as error:
                assert error.status_code == 409
            else:
                raise AssertionError("Completed entity was reactivated")
            await db.delete(done_fixture)
            await db.flush()
            try:
                await create_project_work(
                    entity_id,
                    ProjectWorkCreate(
                        title="Недопустимая работа в архиве",
                        acceptance_criteria="Эта запись не должна создаться.",
                        baseline_starts_at=starts_at + timedelta(days=1),
                        baseline_due_at=starts_at + timedelta(days=2),
                        assignee_id=user.id,
                        target_milestone_id=first_milestone_id,
                    ),
                    user,
                    db,
                )
            except HTTPException as error:
                assert error.status_code == 409
            else:
                raise AssertionError("Archived project accepted new work")
            print(
                "project_cockpit_smoke=ok "
                f"tasks={counts['tasks']} milestones={counts['milestones']} "
                f"events={counts['events']} deadline_conflicts={len(applied.conflicts)} "
                "forecast_target_separated=ok post_launch_scope=ok "
                "acceleration_preview=ok "
                "evidence_artifact=ok "
                "charter_revision=ok route_integrity=ok "
                "completion_guard=ok "
                "lifecycle_transitions=ok archived_write_blocked=ok "
                "knowledge_article=ok"
            )
        finally:
            await db.execute(delete(WorkEntity).where(WorkEntity.id == entity_id))
            await db.commit()


if __name__ == "__main__":
    asyncio.run(run())
