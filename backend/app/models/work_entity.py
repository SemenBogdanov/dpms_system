"""Projects, goals, and typed links to existing DPMS objects."""
import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkEntity(Base):
    """A user-owned context such as a project, goal, system, or initiative."""

    __tablename__ = "work_entities"
    __table_args__ = (
        CheckConstraint(
            "entity_type IN ('project', 'initiative', 'goal', 'system', 'kpi', 'other')",
            name="ck_work_entities_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'active', 'paused', 'done', 'archived')",
            name="ck_work_entities_status",
        ),
        CheckConstraint(
            "visibility IN ('private', 'shared')",
            name="ck_work_entities_visibility",
        ),
        CheckConstraint(
            "(starts_at IS NULL OR due_at IS NULL OR due_at > starts_at)",
            name="ck_work_entities_dates",
        ),
        CheckConstraint(
            "(forecast_starts_at IS NULL OR forecast_due_at IS NULL "
            "OR forecast_due_at > forecast_starts_at)",
            name="ck_work_entities_forecast_dates",
        ),
        CheckConstraint(
            "(starts_at IS NULL OR target_due_at IS NULL "
            "OR target_due_at > starts_at)",
            name="ck_work_entities_target_dates",
        ),
        CheckConstraint(
            "planning_mode IN ('free', 'methodology')",
            name="ck_work_entities_planning_mode",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome_statement: Mapped[str | None] = mapped_column(Text, nullable=True)
    success_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    constraints: Mapped[str | None] = mapped_column(Text, nullable=True)
    baseline_outcome_statement: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    baseline_success_criteria: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    baseline_constraints: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", index=True)
    visibility: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="private",
        index=True,
    )
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    target_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    forecast_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    forecast_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    actual_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    actual_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    planning_mode: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="free",
        index=True,
    )
    methodology_title: Mapped[str | None] = mapped_column(String(240), nullable=True)
    methodology_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    methodology_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    baseline_locked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    baseline_locked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    schedule_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tags: Mapped[list[str]] = mapped_column(ARRAY(String), nullable=False, default=list)
    details_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class WorkEntityMember(Base):
    """Explicit viewer, participant, or editor access to a shared entity."""

    __tablename__ = "work_entity_members"
    __table_args__ = (
        UniqueConstraint("entity_id", "user_id", name="uq_work_entity_members_entity_user"),
        CheckConstraint(
            "role IN ('viewer', 'participant', 'editor')",
            name="ck_work_entity_members_role",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False, default="viewer", index=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class WorkEntityStage(Base):
    """A methodology-neutral planning stage inside a project."""

    __tablename__ = "work_entity_stages"
    __table_args__ = (
        CheckConstraint(
            "status IN ('planned', 'active', 'done', 'cancelled')",
            name="ck_work_entity_stages_status",
        ),
        CheckConstraint(
            "source_type IN ('manual', 'methodology')",
            name="ck_work_entity_stages_source_type",
        ),
        UniqueConstraint(
            "entity_id",
            "id",
            name="uq_work_entity_stages_entity_id_id",
        ),
        UniqueConstraint(
            "entity_id",
            "source_key",
            name="uq_work_entity_stages_entity_source_key",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    completion_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    guidance: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="planned",
        index=True,
    )
    source_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="manual",
        index=True,
    )
    source_key: Mapped[str | None] = mapped_column(String(120), nullable=True)
    source_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class WorkEntityTask(Base):
    """An executable project activity with an assignee and duration."""

    __tablename__ = "work_entity_tasks"
    __table_args__ = (
        CheckConstraint(
            "status IN ('planned', 'in_progress', 'waiting', 'blocked', "
            "'review', 'done', 'cancelled')",
            name="ck_work_entity_tasks_status",
        ),
        CheckConstraint(
            "priority IN ('low', 'medium', 'high', 'critical')",
            name="ck_work_entity_tasks_priority",
        ),
        CheckConstraint(
            "(baseline_starts_at IS NULL OR baseline_due_at IS NULL "
            "OR baseline_due_at > baseline_starts_at)",
            name="ck_work_entity_tasks_baseline_dates",
        ),
        CheckConstraint(
            "(forecast_starts_at IS NULL OR forecast_due_at IS NULL "
            "OR forecast_due_at > forecast_starts_at)",
            name="ck_work_entity_tasks_forecast_dates",
        ),
        ForeignKeyConstraint(
            ["entity_id", "stage_id"],
            ["work_entity_stages.entity_id", "work_entity_stages.id"],
            ondelete="RESTRICT",
            name="fk_work_entity_tasks_stage_entity",
        ),
        UniqueConstraint(
            "entity_id",
            "id",
            name="uq_work_entity_tasks_entity_id_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    task_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        unique=True,
        server_default=text(
            "nextval('work_entity_tasks_task_number_seq'::regclass)"
        ),
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="planned",
        index=True,
    )
    priority: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="medium",
        index=True,
    )
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    acceptance_criteria: Mapped[str | None] = mapped_column(Text, nullable=True)
    next_step: Mapped[str | None] = mapped_column(String(500), nullable=True)
    waiting_for: Mapped[str | None] = mapped_column(String(240), nullable=True)
    baseline_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    baseline_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    forecast_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    forecast_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    actual_starts_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    actual_due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    introduced_after_baseline: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    introduced_at_revision: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class WorkEntityMilestone(Base):
    """A zero-duration project checkpoint with one target date."""

    __tablename__ = "work_entity_milestones"
    __table_args__ = (
        CheckConstraint(
            "status IN ('planned', 'achieved', 'cancelled')",
            name="ck_work_entity_milestones_status",
        ),
        CheckConstraint(
            "criticality IN ('control', 'key', 'critical')",
            name="ck_work_entity_milestones_criticality",
        ),
        CheckConstraint(
            "(criticality = 'control' OR criticality_reason IS NOT NULL)",
            name="ck_work_entity_milestones_criticality_reason",
        ),
        CheckConstraint(
            """
            (
                status = 'planned'
                AND actual_at IS NULL
                AND cancelled_at IS NULL
            )
            OR (
                status = 'achieved'
                AND actual_at IS NOT NULL
                AND cancelled_at IS NULL
            )
            OR (
                status = 'cancelled'
                AND actual_at IS NULL
                AND cancelled_at IS NOT NULL
            )
            """,
            name="ck_work_entity_milestones_lifecycle_dates",
        ),
        ForeignKeyConstraint(
            ["entity_id", "stage_id"],
            ["work_entity_stages.entity_id", "work_entity_stages.id"],
            ondelete="RESTRICT",
            name="fk_work_entity_milestones_stage_entity",
        ),
        UniqueConstraint(
            "entity_id",
            "id",
            name="uq_work_entity_milestones_entity_id_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    milestone_number: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        unique=True,
        server_default=text(
            "nextval('work_entity_milestones_number_seq'::regclass)"
        ),
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stage_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="planned",
        index=True,
    )
    criticality: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="control",
        index=True,
    )
    criticality_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    acceptance_criteria: Mapped[str] = mapped_column(Text, nullable=False)
    decision_owner_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    baseline_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    forecast_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        index=True,
    )
    actual_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    reschedule_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reschedule_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    introduced_after_baseline: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    introduced_at_revision: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class WorkEntityScheduleDependency(Base):
    """A typed schedule edge between tasks and/or milestones."""

    __tablename__ = "work_entity_schedule_dependencies"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(predecessor_task_id, predecessor_milestone_id) = 1",
            name="ck_work_entity_schedule_dependencies_one_predecessor",
        ),
        CheckConstraint(
            "num_nonnulls(successor_task_id, successor_milestone_id) = 1",
            name="ck_work_entity_schedule_dependencies_one_successor",
        ),
        CheckConstraint(
            "NOT (predecessor_task_id IS NOT NULL "
            "AND predecessor_task_id = successor_task_id)",
            name="ck_work_entity_schedule_dependencies_no_self_task",
        ),
        CheckConstraint(
            "NOT (predecessor_milestone_id IS NOT NULL "
            "AND predecessor_milestone_id = successor_milestone_id)",
            name="ck_work_entity_schedule_dependencies_no_self_milestone",
        ),
        CheckConstraint(
            "dependency_type = 'finish_to_start'",
            name="ck_work_entity_schedule_dependencies_type",
        ),
        CheckConstraint(
            "lag_days BETWEEN 0 AND 3650",
            name="ck_work_entity_schedule_dependencies_lag",
        ),
        CheckConstraint(
            """
            (
                status = 'active'
                AND waived_at IS NULL
                AND waived_by_id IS NULL
                AND waiver_reason IS NULL
            )
            OR (
                status = 'waived'
                AND waived_at IS NOT NULL
                AND waived_by_id IS NOT NULL
                AND waiver_reason IS NOT NULL
            )
            """,
            name="ck_work_entity_schedule_dependencies_waiver",
        ),
        ForeignKeyConstraint(
            ["entity_id", "predecessor_task_id"],
            ["work_entity_tasks.entity_id", "work_entity_tasks.id"],
            ondelete="CASCADE",
            name="fk_work_entity_schedule_predecessor_task",
        ),
        ForeignKeyConstraint(
            ["entity_id", "successor_task_id"],
            ["work_entity_tasks.entity_id", "work_entity_tasks.id"],
            ondelete="CASCADE",
            name="fk_work_entity_schedule_successor_task",
        ),
        ForeignKeyConstraint(
            ["entity_id", "predecessor_milestone_id"],
            ["work_entity_milestones.entity_id", "work_entity_milestones.id"],
            ondelete="CASCADE",
            name="fk_work_entity_schedule_predecessor_milestone",
        ),
        ForeignKeyConstraint(
            ["entity_id", "successor_milestone_id"],
            ["work_entity_milestones.entity_id", "work_entity_milestones.id"],
            ondelete="CASCADE",
            name="fk_work_entity_schedule_successor_milestone",
        ),
        Index(
            "uq_work_entity_schedule_active_task_target",
            "entity_id",
            "predecessor_task_id",
            unique=True,
            postgresql_where=text(
                "predecessor_task_id IS NOT NULL "
                "AND successor_milestone_id IS NOT NULL "
                "AND status = 'active'"
            ),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    predecessor_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    predecessor_milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    successor_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    successor_milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    dependency_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="finish_to_start",
    )
    lag_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cascade_on_shift: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        index=True,
    )
    waiver_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    waived_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    waived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )


class WorkEntityArtifact(Base):
    """A shared project note, decision, document reference, or other artifact."""

    __tablename__ = "work_entity_artifacts"
    __table_args__ = (
        CheckConstraint(
            "artifact_type IN "
            "('note', 'decision', 'evidence', 'document', 'reference', 'other')",
            name="ck_work_entity_artifacts_type",
        ),
        CheckConstraint(
            "status IN ('active', 'archived')",
            name="ck_work_entity_artifacts_status",
        ),
        CheckConstraint(
            "(body IS NOT NULL OR url IS NOT NULL)",
            name="ck_work_entity_artifacts_content",
        ),
        CheckConstraint(
            "(artifact_type != 'evidence' "
            "OR (milestone_id IS NOT NULL AND task_id IS NULL))",
            name="ck_work_entity_artifacts_evidence_parent",
        ),
        ForeignKeyConstraint(
            ["entity_id", "task_id"],
            ["work_entity_tasks.entity_id", "work_entity_tasks.id"],
            name="fk_work_entity_artifacts_task_entity",
        ),
        ForeignKeyConstraint(
            ["entity_id", "milestone_id"],
            ["work_entity_milestones.entity_id", "work_entity_milestones.id"],
            name="fk_work_entity_artifacts_milestone_entity",
        ),
        CheckConstraint(
            "num_nonnulls(task_id, milestone_id) <= 1",
            name="ck_work_entity_artifacts_one_parent",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_entity_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    milestone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_entity_milestones.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    artifact_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="note",
        index=True,
    )
    title: Mapped[str] = mapped_column(String(240), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="active",
        index=True,
    )
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    archived_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class WorkEntityLink(Base):
    """A typed, referentially safe link from one entity to exactly one target."""

    __tablename__ = "work_entity_links"
    __table_args__ = (
        UniqueConstraint("entity_id", "target_entity_id", name="uq_work_entity_links_entity_target_entity"),
        UniqueConstraint("entity_id", "task_id", name="uq_work_entity_links_entity_task"),
        UniqueConstraint(
            "entity_id",
            "personal_task_id",
            name="uq_work_entity_links_entity_personal_task",
        ),
        UniqueConstraint(
            "entity_id",
            "quick_note_id",
            name="uq_work_entity_links_entity_quick_note",
        ),
        UniqueConstraint(
            "entity_id",
            "deadline_tracker_id",
            name="uq_work_entity_links_entity_deadline_tracker",
        ),
        CheckConstraint(
            "num_nonnulls(target_entity_id, task_id, personal_task_id, quick_note_id, "
            "deadline_tracker_id) = 1",
            name="ck_work_entity_links_exactly_one_target",
        ),
        CheckConstraint(
            "(target_entity_id IS NULL OR target_entity_id <> entity_id)",
            name="ck_work_entity_links_no_self_link",
        ),
        CheckConstraint(
            "relation_type IN ('contains', 'contributes_to', 'depends_on', 'measures', 'related')",
            name="ck_work_entity_links_relation_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    target_entity_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_entities.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    personal_task_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("personal_tasks.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    quick_note_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("quick_notes.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    deadline_tracker_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("deadline_trackers.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    relation_type: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        default="contains",
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        onupdate=utc_now,
    )


class WorkEntityEvent(Base):
    """Audit trail for entity, member, and link changes."""

    __tablename__ = "work_entity_events"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    entity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("work_entities.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    object_type: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    object_ref: Mapped[str | None] = mapped_column(String(80), nullable=True)
    object_title: Mapped[str | None] = mapped_column(String(240), nullable=True)
    action: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    correlation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        nullable=True,
        index=True,
    )
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=utc_now,
        index=True,
    )
