"""Isolated migration smoke for the redesigned project schedule."""
import asyncio
import os
import re
import uuid
from datetime import datetime, timedelta, timezone

from alembic import command
from alembic.config import Config
from sqlalchemy import text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings


OPT_IN_ENV = "DPMS_MIGRATION_SMOKE_ALLOW_CREATE_DATABASE"
LOSSY_DOWNGRADE_OPT_IN_ENV = (
    "DPMS_ALLOW_LOSSY_WORK_ENTITY_SCHEDULE_DOWNGRADE"
)
SAFE_DATABASE_HOSTS = {"localhost", "127.0.0.1", "::1", "db"}
TEMPORARY_DATABASE_RE = re.compile(r"^dpms_migration_smoke_[0-9a-f]{12}$")


def ensure_safe_target(database_url: URL) -> None:
    if os.environ.get(OPT_IN_ENV) != "1":
        raise RuntimeError(
            f"Migration smoke is disabled. Set {OPT_IN_ENV}=1 only "
            "for a disposable local database."
        )
    if database_url.get_backend_name() != "postgresql":
        raise RuntimeError("Migration smoke supports only PostgreSQL")
    if (database_url.host or "") not in SAFE_DATABASE_HOSTS:
        raise RuntimeError("Migration smoke refuses a non-local database host")
    if database_url.database in {None, "postgres", "template0", "template1"}:
        raise RuntimeError("Migration smoke requires a non-system source database")


def ensure_temporary_database_name(database_name: str) -> None:
    if not TEMPORARY_DATABASE_RE.fullmatch(database_name):
        raise RuntimeError("Refusing an unexpected temporary database name")


async def create_database(admin_url: URL, database_name: str) -> None:
    ensure_temporary_database_name(database_name)
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(text(f'CREATE DATABASE "{database_name}"'))
    finally:
        await engine.dispose()


async def drop_database(admin_url: URL, database_name: str) -> None:
    ensure_temporary_database_name(database_name)
    engine = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with engine.connect() as connection:
            await connection.execute(
                text(
                    "SELECT pg_terminate_backend(pid) "
                    "FROM pg_stat_activity "
                    "WHERE datname = :database_name AND pid <> pg_backend_pid()"
                ),
                {"database_name": database_name},
            )
            await connection.execute(
                text(f'DROP DATABASE IF EXISTS "{database_name}"')
            )
    finally:
        await engine.dispose()


async def run_alembic(
    database_url: URL,
    direction: str,
    revision: str,
) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            def invoke(sync_connection) -> None:
                config = Config("alembic.ini")
                config.attributes["connection"] = sync_connection
                if direction == "upgrade":
                    command.upgrade(config, revision)
                else:
                    command.downgrade(config, revision)

            await connection.run_sync(invoke)
    finally:
        await engine.dispose()


async def seed_conflicting_article(database_url: URL, slug: str) -> uuid.UUID:
    article_id = uuid.uuid4()
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO knowledge_articles (
                        id, slug, title, summary, section, body, status, sort_order,
                        created_at, updated_at, published_at
                    )
                    VALUES (
                        :id,
                        :slug,
                        'Пользовательская статья',
                        'Не принадлежит миграции DPMS.',
                        'tasks',
                        'Эта запись должна пережить upgrade и downgrade.',
                        'published',
                        999,
                        now(),
                        now(),
                        now()
                    )
                    """
                ),
                {"id": article_id, "slug": slug},
            )
    finally:
        await engine.dispose()
    return article_id


async def verify_conflicting_article(
    database_url: URL,
    article_id: uuid.UUID,
    slug: str,
) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            article = (
                await connection.execute(
                    text(
                        """
                        SELECT id, title, body
                        FROM knowledge_articles
                        WHERE slug = :slug
                        """
                    ),
                    {"slug": slug},
                )
            ).one()
            assert article.id == article_id
            assert article.title == "Пользовательская статья"
            assert article.body == "Эта запись должна пережить upgrade и downgrade."
    finally:
        await engine.dispose()


async def seed_acceptance_revision_event(database_url: URL) -> uuid.UUID:
    from app.models.catalog import Complexity
    from app.models.task import (
        Task,
        TaskAcceptanceCriterion,
        TaskAcceptanceCriterionEvent,
        TaskPriority,
        TaskStatus,
        TaskType,
    )
    from app.models.user import League, User, UserRole

    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    event_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    try:
        async with session_factory() as db:
            owner = User(
                full_name="Acceptance downgrade owner",
                email=f"acceptance-downgrade-{uuid.uuid4()}@dpms-demo.ru",
                league=League.A,
                role=UserRole.teamlead,
                mpw=0,
                wip_limit=10,
                task_workspace_enabled=True,
                is_active=True,
            )
            db.add(owner)
            await db.flush()
            task = Task(
                title="Acceptance downgrade fixture",
                task_type=TaskType.docs,
                complexity=Complexity.S,
                estimated_q=1,
                priority=TaskPriority.medium,
                status=TaskStatus.in_progress,
                min_league=League.C,
                estimator_id=owner.id,
                acceptance_owner_id=owner.id,
                acceptance_mode="criteria",
            )
            db.add(task)
            await db.flush()
            criterion = TaskAcceptanceCriterion(
                task_id=task.id,
                position=0,
                title="Downgrade keeps audit data",
                kind="required",
                status="returned",
                baseline_revision=1,
                reviewer_comment="Decision corrected during review.",
                reviewed_by_id=owner.id,
                reviewed_at=now,
                return_count=1,
                decision_change_count=1,
            )
            db.add(criterion)
            await db.flush()
            db.add(
                TaskAcceptanceCriterionEvent(
                    id=event_id,
                    task_id=task.id,
                    criterion_id=criterion.id,
                    actor_id=owner.id,
                    event_type="decision_changed",
                    from_status="accepted",
                    to_status="returned",
                    comment="Decision corrected during review.",
                    acceptance_revision=1,
                    created_at=now,
                )
            )
            await db.commit()
        return event_id
    finally:
        await engine.dispose()


async def verify_downgraded_acceptance_revision_event(
    database_url: URL,
    event_id: uuid.UUID,
) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            event = (
                await connection.execute(
                    text(
                        """
                        SELECT event_type, from_status, to_status, comment
                        FROM task_acceptance_criterion_events
                        WHERE id = :event_id
                        """
                    ),
                    {"event_id": event_id},
                )
            ).one()
            assert event.event_type == "returned"
            assert event.from_status == "accepted"
            assert event.to_status == "returned"
            assert event.comment == "Decision corrected during review."
    finally:
        await engine.dispose()


async def verify_head_schema(database_url: URL) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            revision = (
                await connection.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            ).scalar_one()
            assert revision == "053_execution_contracts"
            admin_audit_index = (
                await connection.execute(
                    text(
                        """
                        SELECT indexname
                        FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND indexname = 'ix_activity_events_admin_target_occurred'
                        """
                    )
                )
            ).scalar_one_or_none()
            assert admin_audit_index == "ix_activity_events_admin_target_occurred"
            tables = set(
                (
                    await connection.execute(
                        text(
                            """
                            SELECT tablename
                            FROM pg_tables
                            WHERE schemaname = 'public'
                              AND tablename IN (
                                'work_entity_stages',
                                'work_entity_tasks',
                                'work_entity_milestones',
                                'work_entity_schedule_dependencies',
                                'work_entity_artifacts',
                                'work_entity_execution_contracts'
                              )
                            """
                        )
                    )
                ).scalars()
            )
            assert tables == {
                "work_entity_stages",
                "work_entity_tasks",
                "work_entity_milestones",
                "work_entity_schedule_dependencies",
                "work_entity_artifacts",
                "work_entity_execution_contracts",
            }
            user_columns = set(
                (
                    await connection.execute(
                        text(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_name = 'users'
                            """
                        )
                    )
                ).scalars()
            )
            assert "can_link_queue_tasks_to_projects" in user_columns
            contract_indexes = set(
                (
                    await connection.execute(
                        text(
                            """
                            SELECT indexname
                            FROM pg_indexes
                            WHERE schemaname = 'public'
                              AND tablename = 'work_entity_execution_contracts'
                            """
                        )
                    )
                ).scalars()
            )
            assert {
                "uq_work_entity_execution_contracts_active_operation",
                "uq_work_entity_execution_contracts_active_task",
            }.issubset(contract_indexes)
            execution_article = (
                await connection.execute(
                    text(
                        """
                        SELECT status
                        FROM knowledge_articles
                        WHERE slug = 'operaciya-proekta-i-q-zadacha'
                        """
                    )
                )
            ).scalar_one_or_none()
            assert execution_article == "published"
            task_columns = set(
                (
                    await connection.execute(
                        text(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_name = 'work_entity_tasks'
                            """
                        )
                    )
                ).scalars()
            )
            assert "item_type" not in task_columns
            assert {
                "baseline_starts_at",
                "baseline_due_at",
                "forecast_starts_at",
                "forecast_due_at",
                "actual_starts_at",
                "actual_due_at",
            }.issubset(task_columns)
            entity_columns = set(
                (
                    await connection.execute(
                        text(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_name = 'work_entities'
                            """
                        )
                    )
                ).scalars()
            )
            assert {
                "outcome_statement",
                "success_criteria",
                "constraints",
                "baseline_outcome_statement",
                "baseline_success_criteria",
                "baseline_constraints",
                "target_due_at",
                "forecast_due_at",
                "baseline_locked_at",
                "schedule_revision",
            }.issubset(entity_columns)
            article = (
                await connection.execute(
                    text(
                        """
                        SELECT title, body
                        FROM knowledge_articles
                        WHERE slug = 'rabochee-prostranstvo-proekta'
                        """
                    )
                )
            ).one()
            assert article.title == "Пульт проекта: от результата к плану"
            assert "Пульт проекта" in article.body
            assert "Подтверждение результата" in article.body
            assert "Связь работы с контрольной точкой" in article.body
            assert "AI-помощник не входит в текущую версию" in article.body
            target_index = (
                await connection.execute(
                    text(
                        """
                        SELECT indexdef
                        FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND tablename = 'work_entity_schedule_dependencies'
                          AND indexname =
                              'uq_work_entity_schedule_active_task_target'
                        """
                    )
                )
            ).scalar_one()
            assert "UNIQUE INDEX" in target_index
            assert "WHERE" in target_index
            assert "status" in target_index
            assert "active" in target_index
            acceptance_tables = set(
                (
                    await connection.execute(
                        text(
                            """
                            SELECT tablename
                            FROM pg_tables
                            WHERE schemaname = 'public'
                              AND tablename IN (
                                'task_acceptance_criteria',
                                'task_acceptance_criterion_events'
                              )
                            """
                        )
                    )
                ).scalars()
            )
            assert acceptance_tables == {
                "task_acceptance_criteria",
                "task_acceptance_criterion_events",
            }
            acceptance_columns = set(
                (
                    await connection.execute(
                        text(
                            """
                            SELECT column_name
                            FROM information_schema.columns
                            WHERE table_name = 'task_acceptance_criteria'
                            """
                        )
                    )
                ).scalars()
            )
            assert "decision_change_count" in acceptance_columns
            acceptance_article = (
                await connection.execute(
                    text(
                        """
                        SELECT title, body
                        FROM knowledge_articles
                        WHERE slug = 'priemka-zadach-po-kriteriyam'
                        """
                    )
                )
            ).one()
            assert acceptance_article.title == "Приемка задач по критериям"
            assert "не означает пропорциональную оплату" in acceptance_article.body
            assert "не более двух раз" in acceptance_article.body
    finally:
        await engine.dispose()


async def verify_head_integrity(database_url: URL) -> None:
    from app.models.user import League, User, UserRole
    from app.models.work_entity import (
        WorkEntity,
        WorkEntityArtifact,
        WorkEntityMilestone,
        WorkEntityScheduleDependency,
        WorkEntityStage,
        WorkEntityTask,
    )

    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    owner_id = uuid.uuid4()
    first_entity_id = uuid.uuid4()
    second_entity_id = uuid.uuid4()
    first_task_id = uuid.uuid4()
    second_task_id = uuid.uuid4()
    milestone_id = uuid.uuid4()
    stage_id = uuid.uuid4()
    now = datetime.now(timezone.utc)
    try:
        async with session_factory() as db:
            db.add(
                User(
                    id=owner_id,
                    full_name="Migration smoke owner",
                    email=f"migration-smoke-{uuid.uuid4()}@example.invalid",
                    league=League.C,
                    role=UserRole.executor,
                )
            )
            db.add_all(
                [
                    WorkEntity(
                        id=first_entity_id,
                        owner_id=owner_id,
                        entity_type="project",
                        title="First project",
                        starts_at=now,
                        due_at=now + timedelta(days=30),
                        forecast_starts_at=now,
                        forecast_due_at=now + timedelta(days=30),
                    ),
                    WorkEntity(
                        id=second_entity_id,
                        owner_id=owner_id,
                        entity_type="project",
                        title="Second project",
                    ),
                ]
            )
            db.add_all(
                [
                    WorkEntityStage(
                        id=stage_id,
                        entity_id=first_entity_id,
                        title="First project stage",
                    ),
                    WorkEntityTask(
                        id=first_task_id,
                        entity_id=first_entity_id,
                        title="First task",
                    ),
                    WorkEntityTask(
                        id=second_task_id,
                        entity_id=second_entity_id,
                        title="Second task",
                    ),
                    WorkEntityMilestone(
                        id=milestone_id,
                        entity_id=first_entity_id,
                        title="Decision",
                        acceptance_criteria="Protocol signed.",
                        baseline_at=now + timedelta(days=5),
                        forecast_at=now + timedelta(days=5),
                    ),
                ]
            )
            await db.commit()

        async with session_factory() as db:
            db.add(
                WorkEntityTask(
                    entity_id=second_entity_id,
                    stage_id=stage_id,
                    title="Cross-project stage task",
                )
            )
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
            else:
                raise AssertionError("Cross-project stage reference was accepted")

        async with session_factory() as db:
            db.add(
                WorkEntityScheduleDependency(
                    entity_id=first_entity_id,
                    predecessor_milestone_id=milestone_id,
                    successor_task_id=second_task_id,
                )
            )
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
            else:
                raise AssertionError("Cross-project schedule edge was accepted")

        async with session_factory() as db:
            db.add(
                WorkEntityArtifact(
                    entity_id=first_entity_id,
                    task_id=second_task_id,
                    title="Cross-project artifact",
                    body="Must be rejected",
                )
            )
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
            else:
                raise AssertionError("Cross-project artifact was accepted")

        async with session_factory() as db:
            db.add(
                WorkEntityArtifact(
                    entity_id=first_entity_id,
                    task_id=first_task_id,
                    artifact_type="evidence",
                    title="Evidence attached to task",
                    body="Evidence must belong to a milestone.",
                )
            )
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
            else:
                raise AssertionError(
                    "Evidence artifact without milestone parent was accepted"
                )

        async with session_factory() as db:
            db.add(
                WorkEntityMilestone(
                    entity_id=first_entity_id,
                    title="Invalid planned milestone with actual date",
                    acceptance_criteria="Must be rejected.",
                    baseline_at=now + timedelta(days=6),
                    forecast_at=now + timedelta(days=6),
                    actual_at=now,
                )
            )
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
            else:
                raise AssertionError(
                    "Planned milestone with actual date was accepted"
                )

        async with session_factory() as db:
            db.add(
                WorkEntityScheduleDependency(
                    entity_id=first_entity_id,
                    predecessor_milestone_id=milestone_id,
                    successor_task_id=first_task_id,
                    status="waived",
                    waived_at=now,
                )
            )
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
            else:
                raise AssertionError(
                    "Dependency waiver without a reason was accepted"
                )

        async with session_factory() as db:
            db.add(
                WorkEntityScheduleDependency(
                    entity_id=first_entity_id,
                    predecessor_milestone_id=milestone_id,
                    successor_task_id=first_task_id,
                    status="waived",
                    waiver_reason="Imported exception without actor.",
                    waived_at=now,
                )
            )
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
            else:
                raise AssertionError(
                    "Dependency waiver without an actor was accepted"
                )
    finally:
        await engine.dispose()


async def verify_044_schema(database_url: URL) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            constraints = set(
                (
                    await connection.execute(
                        text(
                            """
                            SELECT conname
                            FROM pg_constraint
                            WHERE conrelid =
                                'work_entity_task_dependencies'::regclass
                            """
                        )
                    )
                ).scalars()
            )
            assert "ck_work_entity_task_dependencies_no_self" in constraints

            indexes = set(
                (
                    await connection.execute(
                        text(
                            """
                            SELECT indexname
                            FROM pg_indexes
                            WHERE schemaname = 'public'
                              AND tablename =
                                  'work_entity_task_dependencies'
                            """
                        )
                    )
                ).scalars()
            )
            assert {
                "ix_work_entity_task_dependencies_entity_id",
                "ix_work_entity_task_dependencies_task_id",
                "ix_work_entity_task_dependencies_depends_on_task_id",
            }.issubset(indexes)
    finally:
        await engine.dispose()


async def seed_legacy_044(database_url: URL) -> dict[str, uuid.UUID]:
    values = {
        "owner": uuid.uuid4(),
        "entity": uuid.uuid4(),
        "task": uuid.uuid4(),
        "milestone": uuid.uuid4(),
        "done_milestone": uuid.uuid4(),
        "cancelled_milestone": uuid.uuid4(),
        "planned_with_fact_milestone": uuid.uuid4(),
        "dependency": uuid.uuid4(),
        "artifact": uuid.uuid4(),
    }
    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    INSERT INTO users (
                        id, email, full_name, role, league, password_hash,
                        mpw, wip_limit, wallet_main, wallet_karma,
                        quality_score, is_active, is_new_employee,
                        task_workspace_enabled, feedback_enabled,
                        competency_development_enabled,
                        competency_constructor_enabled, auth_version,
                        password_change_required, created_at, updated_at
                    )
                    VALUES (
                        :owner, :email, 'Legacy owner', 'executor', 'C', '',
                        0, 2, 0, 0, 100, true, false, true, false,
                        false, false, 0, false, now(), now()
                    )
                    """
                ),
                {
                    "owner": values["owner"],
                    "email": f"legacy-{uuid.uuid4()}@example.invalid",
                },
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO work_entities (
                        id, owner_id, entity_type, title, status, visibility,
                        starts_at, due_at, tags, created_at, updated_at
                    )
                    VALUES (
                        :entity, :owner, 'project', 'Legacy project',
                        'active', 'private', now(), now() + interval '30 days',
                        '{}', now(), now()
                    )
                    """
                ),
                values,
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO work_entity_tasks (
                        id, task_number, entity_id, item_type, title, status,
                        priority, starts_at, due_at, completed_at, position,
                        created_at, updated_at
                    )
                    VALUES
                    (
                        :task, 910001, :entity, 'task', 'Legacy task',
                        'planned', 'medium', now() + interval '6 days',
                        now() + interval '10 days', NULL, 1, now(), now()
                    ),
                    (
                        :milestone, 910002, :entity, 'milestone',
                        'Legacy milestone', 'planned', 'high', NULL,
                        now() + interval '5 days', NULL, 0, now(), now()
                    ),
                    (
                        :done_milestone, 910003, :entity, 'milestone',
                        'Legacy done milestone without fact', 'done', 'medium',
                        NULL, now() + interval '4 days', NULL, 2, now(), now()
                    ),
                    (
                        :cancelled_milestone, 910004, :entity, 'milestone',
                        'Legacy cancelled milestone with fact', 'cancelled',
                        'medium', NULL, now() + interval '3 days',
                        now() - interval '1 day', 3, now(), now()
                    ),
                    (
                        :planned_with_fact_milestone, 910005, :entity,
                        'milestone', 'Legacy planned milestone with fact',
                        'planned', 'low', NULL, now() + interval '2 days',
                        now() - interval '2 days', 4, now(), now()
                    )
                    """
                ),
                values,
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO work_entity_task_dependencies (
                        id, entity_id, task_id, depends_on_task_id,
                        created_by_id, created_at
                    )
                    VALUES (
                        :dependency, :entity, :task, :milestone, :owner, now()
                    )
                    """
                ),
                values,
            )
            await connection.execute(
                text(
                    """
                    INSERT INTO work_entity_artifacts (
                        id, entity_id, task_id, artifact_type, title, body,
                        status, created_by_id, updated_by_id, created_at,
                        updated_at
                    )
                    VALUES (
                        :artifact, :entity, :milestone, 'decision',
                        'Legacy protocol', 'Legacy body', 'active',
                        :owner, :owner, now(), now()
                    )
                    """
                ),
                values,
            )
    finally:
        await engine.dispose()
    return values


async def verify_legacy_conversion(
    database_url: URL,
    values: dict[str, uuid.UUID],
) -> None:
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as connection:
            milestone = (
                await connection.execute(
                    text(
                        """
                        SELECT id, title, criticality, baseline_at, forecast_at
                        FROM work_entity_milestones
                        WHERE id = :milestone
                        """
                    ),
                    values,
                )
            ).one()
            assert milestone.title == "Legacy milestone"
            assert milestone.criticality == "key"
            assert milestone.baseline_at == milestone.forecast_at

            lifecycle_rows = {
                row.id: row
                for row in (
                    await connection.execute(
                        text(
                            """
                            SELECT id, status, actual_at, cancelled_at
                            FROM work_entity_milestones
                            WHERE id IN (
                                :done_milestone,
                                :cancelled_milestone,
                                :planned_with_fact_milestone
                            )
                            """
                        ),
                        values,
                    )
                )
            }
            done = lifecycle_rows[values["done_milestone"]]
            assert done.status == "achieved"
            assert done.actual_at is not None
            assert done.cancelled_at is None

            cancelled = lifecycle_rows[values["cancelled_milestone"]]
            assert cancelled.status == "cancelled"
            assert cancelled.actual_at is None
            assert cancelled.cancelled_at is not None

            planned = lifecycle_rows[values["planned_with_fact_milestone"]]
            assert planned.status == "planned"
            assert planned.actual_at is None
            assert planned.cancelled_at is None

            assert (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM work_entity_tasks "
                        "WHERE id = :milestone"
                    ),
                    values,
                )
            ).scalar_one() == 0
            dependency = (
                await connection.execute(
                    text(
                        """
                        SELECT predecessor_milestone_id, successor_task_id
                        FROM work_entity_schedule_dependencies
                        WHERE id = :dependency
                        """
                    ),
                    values,
                )
            ).one()
            assert dependency.predecessor_milestone_id == values["milestone"]
            assert dependency.successor_task_id == values["task"]
            artifact = (
                await connection.execute(
                    text(
                        """
                        SELECT task_id, milestone_id
                        FROM work_entity_artifacts
                        WHERE id = :artifact
                        """
                    ),
                    values,
                )
            ).one()
            assert artifact.task_id is None
            assert artifact.milestone_id == values["milestone"]
    finally:
        await engine.dispose()


def run() -> None:
    original_url = make_url(settings.DATABASE_URL)
    ensure_safe_target(original_url)
    database_name = f"dpms_migration_smoke_{uuid.uuid4().hex[:12]}"
    admin_url = original_url.set(database="postgres")
    temporary_url = original_url.set(database=database_name)
    created = False
    try:
        asyncio.run(create_database(admin_url, database_name))
        created = True
        asyncio.run(run_alembic(temporary_url, "upgrade", "head"))
        asyncio.run(verify_head_schema(temporary_url))
        asyncio.run(verify_head_integrity(temporary_url))

        revision_event_id = asyncio.run(
            seed_acceptance_revision_event(temporary_url)
        )
        asyncio.run(
            run_alembic(
                temporary_url,
                "downgrade",
                "050_task_acceptance_criteria",
            )
        )
        asyncio.run(
            verify_downgraded_acceptance_revision_event(
                temporary_url,
                revision_event_id,
            )
        )
        asyncio.run(run_alembic(temporary_url, "upgrade", "head"))
        asyncio.run(verify_head_schema(temporary_url))

        previous_downgrade_opt_in = os.environ.get(LOSSY_DOWNGRADE_OPT_IN_ENV)
        os.environ[LOSSY_DOWNGRADE_OPT_IN_ENV] = "1"
        try:
            asyncio.run(
                run_alembic(
                    temporary_url,
                    "downgrade",
                    "044_work_entity_workspace",
                )
            )
        finally:
            if previous_downgrade_opt_in is None:
                os.environ.pop(LOSSY_DOWNGRADE_OPT_IN_ENV, None)
            else:
                os.environ[LOSSY_DOWNGRADE_OPT_IN_ENV] = (
                    previous_downgrade_opt_in
                )
        asyncio.run(verify_044_schema(temporary_url))
        legacy_values = asyncio.run(seed_legacy_044(temporary_url))
        asyncio.run(run_alembic(temporary_url, "upgrade", "head"))
        asyncio.run(verify_head_schema(temporary_url))
        asyncio.run(verify_legacy_conversion(temporary_url, legacy_values))

        asyncio.run(
            run_alembic(
                temporary_url,
                "downgrade",
                "049_project_route_integrity",
            )
        )
        conflicting_article_id = asyncio.run(
            seed_conflicting_article(
                temporary_url,
                "priemka-zadach-po-kriteriyam",
            )
        )
        asyncio.run(run_alembic(temporary_url, "upgrade", "head"))
        asyncio.run(
            verify_conflicting_article(
                temporary_url,
                conflicting_article_id,
                "priemka-zadach-po-kriteriyam",
            )
        )
        asyncio.run(
            run_alembic(
                temporary_url,
                "downgrade",
                "049_project_route_integrity",
            )
        )
        asyncio.run(
            verify_conflicting_article(
                temporary_url,
                conflicting_article_id,
                "priemka-zadach-po-kriteriyam",
            )
        )
        asyncio.run(run_alembic(temporary_url, "upgrade", "head"))
        asyncio.run(
            verify_conflicting_article(
                temporary_url,
                conflicting_article_id,
                "priemka-zadach-po-kriteriyam",
            )
        )

        asyncio.run(
            run_alembic(
                temporary_url,
                "downgrade",
                "052_admin_user_audit",
            )
        )
        execution_article_id = asyncio.run(
            seed_conflicting_article(
                temporary_url,
                "operaciya-proekta-i-q-zadacha",
            )
        )
        asyncio.run(run_alembic(temporary_url, "upgrade", "head"))
        asyncio.run(
            verify_conflicting_article(
                temporary_url,
                execution_article_id,
                "operaciya-proekta-i-q-zadacha",
            )
        )
        asyncio.run(
            run_alembic(
                temporary_url,
                "downgrade",
                "052_admin_user_audit",
            )
        )
        asyncio.run(
            verify_conflicting_article(
                temporary_url,
                execution_article_id,
                "operaciya-proekta-i-q-zadacha",
            )
        )
        asyncio.run(run_alembic(temporary_url, "upgrade", "head"))
        asyncio.run(
            verify_conflicting_article(
                temporary_url,
                execution_article_id,
                "operaciya-proekta-i-q-zadacha",
            )
        )

        print(
            "Work entity migration smoke OK: fresh head, DB constraints, "
            "044 schema restoration, legacy lifecycle normalization, and "
            "task/milestone/dependency/artifact conversion; knowledge article "
            "conflicts survive acceptance and execution-contract upgrade/downgrade"
        )
    finally:
        if created:
            asyncio.run(drop_database(admin_url, database_name))


if __name__ == "__main__":
    run()
