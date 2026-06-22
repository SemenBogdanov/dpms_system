"""Add competency development module

Revision ID: 025_competency_development
Revises: 024_feedback_access_flag
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "025_competency_development"
down_revision = "024_feedback_access_flag"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("competency_development_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "users",
        sa.Column("competency_constructor_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        "UPDATE users SET competency_development_enabled = true, competency_constructor_enabled = true WHERE role = 'admin'"
    )

    op.create_table(
        "competencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("source", sa.String(length=20), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("department", sa.String(length=255), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("title", "version", name="uq_competencies_title_version"),
    )
    op.create_index(op.f("ix_competencies_title"), "competencies", ["title"])
    op.create_index(op.f("ix_competencies_source"), "competencies", ["source"])

    op.create_table(
        "competency_questions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("competency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("question_type", sa.String(length=40), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["competency_id"], ["competencies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_competency_questions_competency_id"), "competency_questions", ["competency_id"])

    op.create_table(
        "competency_choices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["question_id"], ["competency_questions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_competency_choices_question_id"), "competency_choices", ["question_id"])

    op.create_table(
        "competency_interpretations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("competency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("min_score_ib", sa.Integer(), nullable=False),
        sa.Column("max_score_ib", sa.Integer(), nullable=False),
        sa.Column("min_score_ich", sa.Integer(), nullable=True),
        sa.Column("max_score_ich", sa.Integer(), nullable=True),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("overuse_modifier_text", sa.Text(), nullable=True),
        sa.Column("recommendation_text", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["competency_id"], ["competencies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_competency_interpretations_competency_id"), "competency_interpretations", ["competency_id"])

    op.create_table(
        "competency_assignments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("competency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assigned_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["assigned_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["competency_id"], ["competencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["target_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_competency_assignments_competency_id"), "competency_assignments", ["competency_id"])
    op.create_index(op.f("ix_competency_assignments_target_user_id"), "competency_assignments", ["target_user_id"])
    op.create_index(op.f("ix_competency_assignments_assigned_by_id"), "competency_assignments", ["assigned_by_id"])
    op.create_index(op.f("ix_competency_assignments_status"), "competency_assignments", ["status"])

    op.create_table(
        "competency_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("assignment_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("competency_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("score_ib", sa.Integer(), nullable=True),
        sa.Column("score_ich", sa.Integer(), nullable=True),
        sa.Column("is_overused", sa.Boolean(), nullable=False),
        sa.Column("interpretation_text", sa.Text(), nullable=True),
        sa.Column("avg_time_per_question", sa.Numeric(7, 2), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retake_allowed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["assignment_id"], ["competency_assignments.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["competency_id"], ["competencies.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_competency_attempts_assignment_id"), "competency_attempts", ["assignment_id"])
    op.create_index(op.f("ix_competency_attempts_competency_id"), "competency_attempts", ["competency_id"])
    op.create_index(op.f("ix_competency_attempts_user_id"), "competency_attempts", ["user_id"])
    op.create_index(op.f("ix_competency_attempts_status"), "competency_attempts", ["status"])
    op.create_index(
        "uq_competency_attempt_active",
        "competency_attempts",
        ["user_id", "competency_id"],
        unique=True,
        postgresql_where=sa.text("status = 'in_progress'"),
    )

    op.create_table(
        "competency_answers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("choice_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("time_spent_seconds", sa.Integer(), nullable=True),
        sa.Column("timed_out", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["attempt_id"], ["competency_attempts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["choice_id"], ["competency_choices.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["question_id"], ["competency_questions.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("attempt_id", "question_id", name="uq_competency_answer_attempt_question"),
    )
    op.create_index(op.f("ix_competency_answers_attempt_id"), "competency_answers", ["attempt_id"])
    op.create_index(op.f("ix_competency_answers_question_id"), "competency_answers", ["question_id"])

    op.create_table(
        "individual_development_plan_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("competency_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_attempt_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("goal", sa.String(length=255), nullable=False),
        sa.Column("action_text", sa.Text(), nullable=False),
        sa.Column("expected_result", sa.Text(), nullable=True),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["competency_id"], ["competencies.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_attempt_id"], ["competency_attempts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_individual_development_plan_items_user_id"), "individual_development_plan_items", ["user_id"])
    op.create_index(op.f("ix_individual_development_plan_items_competency_id"), "individual_development_plan_items", ["competency_id"])
    op.create_index(op.f("ix_individual_development_plan_items_status"), "individual_development_plan_items", ["status"])


def downgrade() -> None:
    op.drop_index(op.f("ix_individual_development_plan_items_status"), table_name="individual_development_plan_items")
    op.drop_index(op.f("ix_individual_development_plan_items_competency_id"), table_name="individual_development_plan_items")
    op.drop_index(op.f("ix_individual_development_plan_items_user_id"), table_name="individual_development_plan_items")
    op.drop_table("individual_development_plan_items")

    op.drop_index(op.f("ix_competency_answers_question_id"), table_name="competency_answers")
    op.drop_index(op.f("ix_competency_answers_attempt_id"), table_name="competency_answers")
    op.drop_table("competency_answers")

    op.drop_index("uq_competency_attempt_active", table_name="competency_attempts")
    op.drop_index(op.f("ix_competency_attempts_status"), table_name="competency_attempts")
    op.drop_index(op.f("ix_competency_attempts_user_id"), table_name="competency_attempts")
    op.drop_index(op.f("ix_competency_attempts_competency_id"), table_name="competency_attempts")
    op.drop_index(op.f("ix_competency_attempts_assignment_id"), table_name="competency_attempts")
    op.drop_table("competency_attempts")

    op.drop_index(op.f("ix_competency_assignments_status"), table_name="competency_assignments")
    op.drop_index(op.f("ix_competency_assignments_assigned_by_id"), table_name="competency_assignments")
    op.drop_index(op.f("ix_competency_assignments_target_user_id"), table_name="competency_assignments")
    op.drop_index(op.f("ix_competency_assignments_competency_id"), table_name="competency_assignments")
    op.drop_table("competency_assignments")

    op.drop_index(op.f("ix_competency_interpretations_competency_id"), table_name="competency_interpretations")
    op.drop_table("competency_interpretations")

    op.drop_index(op.f("ix_competency_choices_question_id"), table_name="competency_choices")
    op.drop_table("competency_choices")

    op.drop_index(op.f("ix_competency_questions_competency_id"), table_name="competency_questions")
    op.drop_table("competency_questions")

    op.drop_index(op.f("ix_competencies_source"), table_name="competencies")
    op.drop_index(op.f("ix_competencies_title"), table_name="competencies")
    op.drop_table("competencies")

    op.drop_column("users", "competency_constructor_enabled")
    op.drop_column("users", "competency_development_enabled")
