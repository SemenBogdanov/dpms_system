"""Add structured task acceptance criteria and idempotent Q payout.

Revision ID: 050_task_acceptance_criteria
Revises: 049_project_route_integrity
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "050_task_acceptance_criteria"
down_revision = "049_project_route_integrity"
branch_labels = None
depends_on = None


ARTICLE_BODY = """# Приемка задач по критериям

Обновлено: 2026-08-03

При создании задачи в калькуляторе можно выбрать один из двух режимов приемки.

## Приемка целиком

Исполнитель сдает единый результат. Ответственный за приемку принимает всю задачу
или возвращает ее с обязательным комментарием.

## Приемка по критериям

Постановщик заранее формулирует проверяемые условия результата:

- обязательный критерий — без него задача не может быть принята;
- quality gate — обязательная проверка качества или безопасности;
- дополнительный критерий — полезен для контроля, но не блокирует итоговую приемку.

После назначения исполнителя план приемки фиксируется. Это защищает договоренность:
критерии нельзя незаметно заменить уже в ходе работы.

Исполнитель отправляет готовые критерии с пояснением или ссылкой на подтверждение.
Ответственный принимает каждый пункт либо возвращает его с конкретным комментарием.
Принятые пункты сохраняются, поэтому повторно выполняется только возвращенная часть.

## Как начисляются Q

В текущей версии проверка по критериям не означает пропорциональную оплату. Например,
шесть принятых пунктов из десяти не равны автоматически 60% стоимости задачи.
Полная сумма Q начисляется один раз после принятия всех обязательных критериев и всей
задачи. Для независимых оплачиваемых результатов следует создавать отдельные задачи.

## Кто принимает задачу

При создании назначается ответственный за приемку. Он не может быть исполнителем той
же задачи. Администратор может выполнить аварийную приемку вместо ответственного,
но обязан указать причину. Все сдачи, возвраты и решения сохраняются в истории.

## Рекомендуемый порядок

1. Рассчитайте задачу и выберите режим приемки.
2. Сформулируйте короткие, наблюдаемые критерии результата.
3. Опубликуйте задачу в глобальной очереди.
4. Исполнитель берет задачу и по мере готовности отправляет критерии.
5. Ответственный принимает или возвращает каждый критерий.
6. После принятия обязательных критериев исполнитель сдает задачу целиком.
7. Ответственный выполняет финальную приемку; только после нее начисляются Q.
"""


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("acceptance_owner_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("acceptance_mode", sa.String(length=20), nullable=False, server_default="full"),
    )
    op.add_column(
        "tasks",
        sa.Column("acceptance_state", sa.String(length=30), nullable=False, server_default="none"),
    )
    op.add_column(
        "tasks",
        sa.Column("acceptance_revision", sa.Integer(), nullable=False, server_default="1"),
    )
    for column_name in (
        "acceptance_total_count",
        "acceptance_required_count",
        "acceptance_accepted_count",
        "acceptance_required_accepted_count",
        "acceptance_submitted_count",
        "acceptance_returned_count",
    ):
        op.add_column(
            "tasks",
            sa.Column(column_name, sa.Integer(), nullable=False, server_default="0"),
        )

    op.create_foreign_key(
        "fk_tasks_acceptance_owner_id_users",
        "tasks",
        "users",
        ["acceptance_owner_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_tasks_acceptance_owner_id", "tasks", ["acceptance_owner_id"])
    op.create_check_constraint(
        "ck_tasks_acceptance_mode",
        "tasks",
        "acceptance_mode IN ('full', 'criteria')",
    )
    op.create_check_constraint(
        "ck_tasks_acceptance_state",
        "tasks",
        "acceptance_state IN ('none', 'submitted', 'partially_accepted', 'returned', 'accepted')",
    )
    op.create_check_constraint(
        "ck_tasks_acceptance_counters_nonnegative",
        "tasks",
        "acceptance_revision >= 1 AND acceptance_total_count >= 0 "
        "AND acceptance_required_count >= 0 AND acceptance_accepted_count >= 0 "
        "AND acceptance_required_accepted_count >= 0 AND acceptance_submitted_count >= 0 "
        "AND acceptance_returned_count >= 0",
    )
    op.create_check_constraint(
        "ck_tasks_acceptance_counter_bounds",
        "tasks",
        "acceptance_required_count <= acceptance_total_count "
        "AND acceptance_accepted_count <= acceptance_total_count "
        "AND acceptance_required_accepted_count <= acceptance_required_count "
        "AND acceptance_submitted_count <= acceptance_total_count "
        "AND acceptance_returned_count <= acceptance_total_count",
    )
    op.execute(
        """
        UPDATE tasks
        SET acceptance_owner_id = estimator_id,
            acceptance_state = CASE
                WHEN status = 'done' THEN 'accepted'
                WHEN status = 'review' THEN 'submitted'
                WHEN rejection_comment IS NOT NULL THEN 'returned'
                ELSE 'none'
            END
        """
    )

    op.create_table(
        "task_acceptance_criteria",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("kind", sa.String(length=30), nullable=False, server_default="required"),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("baseline_revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("evidence_comment", sa.Text(), nullable=True),
        sa.Column("evidence_url", sa.String(length=1000), nullable=True),
        sa.Column("reviewer_comment", sa.Text(), nullable=True),
        sa.Column("submitted_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("return_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "kind IN ('required', 'optional', 'quality_gate')",
            name="ck_task_acceptance_criteria_kind",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'submitted', 'accepted', 'returned', 'not_applicable')",
            name="ck_task_acceptance_criteria_status",
        ),
        sa.CheckConstraint("position >= 0", name="ck_task_acceptance_criteria_position"),
        sa.CheckConstraint("baseline_revision >= 1", name="ck_task_acceptance_criteria_revision"),
        sa.CheckConstraint("return_count >= 0", name="ck_task_acceptance_criteria_return_count"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["submitted_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "position", name="uq_task_acceptance_criteria_task_position"),
    )
    op.create_index("ix_task_acceptance_criteria_task_id", "task_acceptance_criteria", ["task_id"])
    op.create_index("ix_task_acceptance_criteria_status", "task_acceptance_criteria", ["status"])

    op.create_table(
        "task_acceptance_criterion_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("criterion_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(length=30), nullable=False),
        sa.Column("from_status", sa.String(length=30), nullable=True),
        sa.Column("to_status", sa.String(length=30), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("evidence_url", sa.String(length=1000), nullable=True),
        sa.Column("acceptance_revision", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "event_type IN ('submitted', 'accepted', 'returned', 'not_applicable')",
            name="ck_task_acceptance_criterion_events_type",
        ),
        sa.CheckConstraint("acceptance_revision >= 1", name="ck_task_acceptance_criterion_events_revision"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["criterion_id"], ["task_acceptance_criteria.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_task_acceptance_criterion_events_task_id",
        "task_acceptance_criterion_events",
        ["task_id"],
    )
    op.create_index(
        "ix_task_acceptance_criterion_events_criterion_id",
        "task_acceptance_criterion_events",
        ["criterion_id"],
    )
    op.create_index(
        "ix_task_acceptance_criterion_events_actor_id",
        "task_acceptance_criterion_events",
        ["actor_id"],
    )
    op.create_index(
        "ix_task_acceptance_criterion_events_event_type",
        "task_acceptance_criterion_events",
        ["event_type"],
    )

    op.add_column(
        "q_transactions",
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
    )
    op.create_index(
        "ix_q_transactions_idempotency_key",
        "q_transactions",
        ["idempotency_key"],
        unique=True,
    )

    op.execute(
        sa.text(
            """
            INSERT INTO knowledge_articles (
                id, slug, title, summary, section, body, status, sort_order,
                created_at, updated_at, published_at
            )
            VALUES (
                '5072e1f7-ec75-4ac9-9c0d-f7e743684a76',
                'priemka-zadach-po-kriteriyam',
                'Приемка задач по критериям',
                'Как задать проверяемый результат, принять отдельные критерии и корректно начислить Q.',
                'tasks',
                :body,
                'published',
                39,
                now(),
                now(),
                now()
            )
            ON CONFLICT (slug) DO UPDATE
            SET title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                section = EXCLUDED.section,
                body = EXCLUDED.body,
                status = 'published',
                sort_order = EXCLUDED.sort_order,
                updated_at = now(),
                published_at = now()
            WHERE knowledge_articles.id = EXCLUDED.id
            """
        ).bindparams(body=ARTICLE_BODY)
    )


def downgrade() -> None:
    op.execute(
        "DELETE FROM knowledge_articles "
        "WHERE id = '5072e1f7-ec75-4ac9-9c0d-f7e743684a76' "
        "AND slug = 'priemka-zadach-po-kriteriyam'"
    )

    op.drop_index("ix_q_transactions_idempotency_key", table_name="q_transactions")
    op.drop_column("q_transactions", "idempotency_key")

    op.drop_index(
        "ix_task_acceptance_criterion_events_event_type",
        table_name="task_acceptance_criterion_events",
    )
    op.drop_index(
        "ix_task_acceptance_criterion_events_actor_id",
        table_name="task_acceptance_criterion_events",
    )
    op.drop_index(
        "ix_task_acceptance_criterion_events_criterion_id",
        table_name="task_acceptance_criterion_events",
    )
    op.drop_index(
        "ix_task_acceptance_criterion_events_task_id",
        table_name="task_acceptance_criterion_events",
    )
    op.drop_table("task_acceptance_criterion_events")

    op.drop_index("ix_task_acceptance_criteria_status", table_name="task_acceptance_criteria")
    op.drop_index("ix_task_acceptance_criteria_task_id", table_name="task_acceptance_criteria")
    op.drop_table("task_acceptance_criteria")

    op.drop_constraint("ck_tasks_acceptance_counter_bounds", "tasks", type_="check")
    op.drop_constraint("ck_tasks_acceptance_counters_nonnegative", "tasks", type_="check")
    op.drop_constraint("ck_tasks_acceptance_state", "tasks", type_="check")
    op.drop_constraint("ck_tasks_acceptance_mode", "tasks", type_="check")
    op.drop_index("ix_tasks_acceptance_owner_id", table_name="tasks")
    op.drop_constraint("fk_tasks_acceptance_owner_id_users", "tasks", type_="foreignkey")
    for column_name in (
        "acceptance_returned_count",
        "acceptance_submitted_count",
        "acceptance_required_accepted_count",
        "acceptance_accepted_count",
        "acceptance_required_count",
        "acceptance_total_count",
        "acceptance_revision",
        "acceptance_state",
        "acceptance_mode",
        "acceptance_owner_id",
    ):
        op.drop_column("tasks", column_name)
