"""Add project operation Q execution contracts and manager capability.

Revision ID: 053_execution_contracts
Revises: 052_admin_user_audit
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "053_execution_contracts"
down_revision = "052_admin_user_audit"
branch_labels = None
depends_on = None


ARTICLE_ID = "bd72a155-4328-4e8c-8b3c-0da2ff3ac57c"
ARTICLE_SLUG = "operaciya-proekta-i-q-zadacha"
ARTICLE_BODY = """# Операция проекта и Q-задача

Проект сначала планируется внутри раздела «Проекты и цели». Атомарная работа в
плане называется **операцией**. Когда для операции нужен ресурс глобальной
очереди, руководитель создает один явный контракт исполнения.

Черновик проекта не публикует задачи в глобальную очередь. Сначала команда
формулирует операции, сроки, контрольные точки и критерии, затем руководитель
нажимает «Активировать» и фиксирует базовый план. Только в активном проекте
можно создать или связать Q-задачу.

## Два способа

1. **Опубликовать новую Q-задачу.** Система берет формулировку операции как
   основу, а руководитель задает цену в Q, срок, сложность, минимальную лигу и
   критерии приемки.
2. **Связать существующую Q-задачу.** Подходит только неназначенная задача со
   сроком, которая еще не начата и не исполняет другую проектную операцию.

Одна операция имеет не более одной активной Q-задачи. Одна Q-задача не может
одновременно исполнять несколько операций. Это защищает команду от двойной
работы и двойной приемки.

## Что фиксирует контракт

- исходную формулировку и срок операции;
- Q, приоритет и срок глобальной задачи;
- критерии приемки на момент публикации;
- автора и источник связи;
- дальнейший статус, исполнителя и результат Q-задачи.

Изменение проектной операции после публикации не переписывает молча уже
выставленную Q-задачу. Руководитель видит обе стороны контракта и принимает
отдельное управленческое решение.

## Исполнение и приемка

Исполнитель берет Q-задачу из глобальной очереди и работает по обычному циклу.
Частичная или полная приемка выполняется в самой Q-задаче. Проект не начисляет Q
повторно и не создает второй процесс приемки.

## Освобождение

Контракт можно освободить только пока Q-задача никому не назначена и не начата.
Причина обязательна и записывается в историю проекта и действий пользователя.
Если задача была создана из операции, при освобождении она отменяется. Если была
связана существующая задача, она остается самостоятельной задачей очереди.

## Права

Действие доступно владельцу или редактору проекта только при наличии отдельного
административного права «Связывать Q-задачи с проектами». Обычный доступ к
разделу задач сам по себе этого права не дает.
"""


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "can_link_queue_tasks_to_projects",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.execute(
        """
        UPDATE users
        SET can_link_queue_tasks_to_projects = TRUE,
            task_workspace_enabled = TRUE
        WHERE role = 'admin'
        """
    )
    op.create_check_constraint(
        "ck_users_queue_project_link_requires_task_workspace",
        "users",
        "NOT can_link_queue_tasks_to_projects OR task_workspace_enabled",
    )

    op.create_table(
        "work_entity_execution_contracts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("operation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("idempotency_key", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "scope_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "acceptance_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("planned_starts_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("planned_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("released_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("release_reason", sa.Text(), nullable=True),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "status IN ('active', 'released')",
            name="ck_work_entity_execution_contracts_status",
        ),
        sa.CheckConstraint(
            "source IN ('linked_existing', 'created_from_operation')",
            name="ck_work_entity_execution_contracts_source",
        ),
        sa.CheckConstraint(
            "planned_starts_at IS NULL OR planned_due_at IS NULL "
            "OR planned_due_at > planned_starts_at",
            name="ck_work_entity_execution_contracts_dates",
        ),
        sa.CheckConstraint(
            "(status = 'active' AND released_at IS NULL AND release_reason IS NULL) "
            "OR (status = 'released' AND released_at IS NOT NULL "
            "AND release_reason IS NOT NULL)",
            name="ck_work_entity_execution_contracts_release_state",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["work_entities.id"],
            name="fk_work_entity_execution_contracts_entity",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id", "operation_id"],
            ["work_entity_tasks.entity_id", "work_entity_tasks.id"],
            name="fk_work_entity_execution_contracts_operation",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name="fk_work_entity_execution_contracts_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_work_entity_execution_contracts_created_by",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["released_by_id"],
            ["users.id"],
            name="fk_work_entity_execution_contracts_released_by",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "idempotency_key",
            name="uq_work_entity_execution_contracts_idempotency_key",
        ),
    )
    op.create_index(
        "ix_work_entity_execution_contracts_entity_id",
        "work_entity_execution_contracts",
        ["entity_id"],
    )
    op.create_index(
        "ix_work_entity_execution_contracts_operation_id",
        "work_entity_execution_contracts",
        ["operation_id"],
    )
    op.create_index(
        "ix_work_entity_execution_contracts_task_id",
        "work_entity_execution_contracts",
        ["task_id"],
    )
    op.create_index(
        "ix_work_entity_execution_contracts_status",
        "work_entity_execution_contracts",
        ["status"],
    )
    op.create_index(
        "uq_work_entity_execution_contracts_active_operation",
        "work_entity_execution_contracts",
        ["entity_id", "operation_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )
    op.create_index(
        "uq_work_entity_execution_contracts_active_task",
        "work_entity_execution_contracts",
        ["task_id"],
        unique=True,
        postgresql_where=sa.text("status = 'active'"),
    )

    op.execute(
        sa.text(
            """
            INSERT INTO knowledge_articles (
                id, slug, title, summary, section, body, status, sort_order,
                created_at, updated_at, published_at
            )
            VALUES (
                CAST(:article_id AS uuid),
                :slug,
                'Операция проекта и Q-задача',
                'Как опубликовать проектную операцию в Q-пул без дублей и повторной приемки.',
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
                body = EXCLUDED.body,
                status = 'published',
                updated_at = now(),
                published_at = now()
            WHERE knowledge_articles.id = EXCLUDED.id
            """
        ).bindparams(
            article_id=ARTICLE_ID,
            slug=ARTICLE_SLUG,
            body=ARTICLE_BODY,
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM knowledge_articles
            WHERE id = CAST(:article_id AS uuid) AND slug = :slug
            """
        ).bindparams(article_id=ARTICLE_ID, slug=ARTICLE_SLUG)
    )
    op.drop_index(
        "uq_work_entity_execution_contracts_active_task",
        table_name="work_entity_execution_contracts",
    )
    op.drop_index(
        "uq_work_entity_execution_contracts_active_operation",
        table_name="work_entity_execution_contracts",
    )
    op.drop_index(
        "ix_work_entity_execution_contracts_status",
        table_name="work_entity_execution_contracts",
    )
    op.drop_index(
        "ix_work_entity_execution_contracts_task_id",
        table_name="work_entity_execution_contracts",
    )
    op.drop_index(
        "ix_work_entity_execution_contracts_operation_id",
        table_name="work_entity_execution_contracts",
    )
    op.drop_index(
        "ix_work_entity_execution_contracts_entity_id",
        table_name="work_entity_execution_contracts",
    )
    op.drop_table("work_entity_execution_contracts")
    op.drop_constraint(
        "ck_users_queue_project_link_requires_task_workspace",
        "users",
        type_="check",
    )
    op.drop_column("users", "can_link_queue_tasks_to_projects")
