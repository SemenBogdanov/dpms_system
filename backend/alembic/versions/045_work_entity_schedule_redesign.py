"""Separate project tasks and milestones and add controlled schedule forecasts.

Revision ID: 045_work_entity_schedule
Revises: 044_work_entity_workspace
"""
import os

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "045_work_entity_schedule"
down_revision = "044_work_entity_workspace"
branch_labels = None
depends_on = None

LOSSY_DOWNGRADE_OPT_IN_ENV = (
    "DPMS_ALLOW_LOSSY_WORK_ENTITY_SCHEDULE_DOWNGRADE"
)


WORKSPACE_KB_BODY = """# Проект: задачи, контрольные точки и график

Обновлено: 2026-07-28

Рабочее пространство проекта позволяет сначала сформировать проект, а уже внутри
него создать этапы, задачи, контрольные точки, зависимости, участников и
артефакты. Не требуется заранее заводить элементы в других разделах системы.

## От черновика к активному проекту

Новый проект всегда создается как `Черновик`. До активации руководитель может
свободно менять базовые даты и структуру.

Перед активацией система проверяет готовность:

- указаны начало и срок проекта;
- сформирован непустой scope;
- у задач есть исполнитель, базовые даты и критерии приемки;
- у контрольных точек есть дата, критерий прохождения и ответственный за решение;
- для ключевых и критических точек объяснена критичность;
- в режиме методологии заполнены этапы и их критерии завершения.

Блокирующие замечания не позволяют активировать проект. Предупреждения остаются
видимыми, но не блокируют решение руководителя.

## Задача и контрольная точка — разные сущности

**Задача** — исполняемая работа. У нее есть исполнитель, интервал выполнения,
приоритет, критерии приемки, следующий шаг и рабочий статус: `Запланирована`,
`В работе`, `Ожидание`, `Заблокирована`, `На приемке`, `Выполнена` или `Отменена`.

**Контрольная точка** — значимое событие нулевой длительности. У нее нет даты
начала и длительности. Для нее задаются одна дата, критерий прохождения,
ответственный за подтверждение результата и критичность.

Жизненный статус контрольной точки хранит управленческое решение:

- `Запланирована`;
- `Пройдена`;
- `Отменена`.

Дополнительное состояние вычисляется системой:

- `Перенесена` — прогнозная дата отличается от базовой;
- `Просрочена` — прогнозная дата прошла, а точка не пройдена.

Так перенос не стирает исходное обязательство и не требует вручную поддерживать
два противоречащих друг другу статуса.

## Приоритет задачи и критичность точки

Приоритет отвечает на вопрос, в каком порядке выполнять работу:

- `Низкий`;
- `Средний`;
- `Высокий`;
- `Критический`.

Критичность отвечает на другой вопрос: что произойдет с проектом, если
контрольная точка не будет пройдена:

- `Контрольная` — внутренний рубеж наблюдения;
- `Ключевая` — открывает этап, результат или последующую работу;
- `Критическая` — связана с внешним обязательством, решением органа управления,
  выпуском, регуляторным требованием или сроком завершения проекта.

Для ключевой и критической точки обязательно указывается причина. На диаграмме
цвет показывает состояние, а размер и обводка маркера — критичность.

## Базовый план, прогноз и факт

- `Базовый план` фиксирует первоначально согласованное обязательство.
- `Прогноз` показывает актуальную ожидаемую дату.
- `Факт` сохраняет действительное начало или завершение.

После активации базовый план блокируется. Изменение прогноза не перезаписывает
его, поэтому Gantt показывает исходное положение, актуальное положение и
отклонение в днях.

## Зависимости и управляемый перенос

Перенос контрольной точки выполняется как управленческое решение:

1. Руководитель указывает новую дату и обязательную причину.
2. Система предварительно рассчитывает затронутые задачи и точки.
3. Руководитель видит конфликты и подтверждает или отменяет применение.
4. После подтверждения изменяется прогноз и создается запись в журнале.

Вправо сдвигаются только будущие элементы, соединенные явными зависимостями.
Выполняемые, завершенные и отмененные элементы не меняются молча: они выводятся
как конфликты. В первой версии используется зависимость `окончание → начало` с
неотрицательной задержкой в днях. Автоматическое ускорение графика влево не
выполняется.

Отмена предшественника не считается выполнением зависимости. Руководитель может
заменить предшественника, изменить scope либо явно снять блокировку с обязательным
обоснованием. Такое исключение сохраняет исходную связь и автора решения в журнале.

## Как читать Gantt

- полупрозрачная отметка показывает базовый план;
- цветная полоса или точка показывает прогноз;
- факт отображается отдельно после начала или завершения;
- строки группируются по этапам;
- зависимости показывают, почему следующий элемент не может начаться раньше.

Задача занимает интервал. Контрольная точка всегда отображается одной точкой.

## Этапы и методология

Этап — универсальная группировка задач и контрольных точек. В свободном режиме
этапы создаются вручную. В режиме методологии проект получает snapshot выбранной
версии: этапы, критерии, подсказки, checklist и обязательные результаты.

Модель не зависит от названий и количества этапов. Поэтому новые версии
методологии, включая «Кубики», могут подключаться без изменения базовых сущностей
проекта. Обновление общей методологии не должно молча менять уже активированный
проект: он продолжает работать со своим snapshot.

## Понятность для международной команды

Не полагайтесь на неявный контекст. Для каждого элемента фиксируйте:

- наблюдаемый результат и критерий приемки;
- конкретного ответственного;
- точную дату и часовой пояс, если важно время;
- причину изменения и влияние на график;
- решение, факт и ссылку на артефакт.

Подсказки у полей объясняют, зачем сведения нужны проекту. Формулировки должны
описывать проверяемый результат, а не личные ожидания автора.

## Журнал проекта

Каждая запись отвечает на вопросы:

- кто и когда выполнил действие;
- какой объект, его тип, номер и название изменены;
- что было до изменения и что стало после;
- почему выполнено изменение;
- какие элементы и сроки оно затронуло.

Связанные изменения графика объединяются одним идентификатором операции. Поэтому
каскадный перенос можно прочитать как одно решение, а не как набор безымянных
системных событий.
"""


def upgrade() -> None:
    op.execute("SET LOCAL lock_timeout = '15s'")
    op.execute("SET LOCAL statement_timeout = '10min'")

    op.add_column(
        "work_entities",
        sa.Column("forecast_starts_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "work_entities",
        sa.Column("forecast_due_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "work_entities",
        sa.Column("actual_starts_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "work_entities",
        sa.Column("actual_due_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "work_entities",
        sa.Column(
            "planning_mode",
            sa.String(length=30),
            nullable=False,
            server_default="free",
        ),
    )
    op.add_column(
        "work_entities",
        sa.Column("methodology_title", sa.String(length=240), nullable=True),
    )
    op.add_column(
        "work_entities",
        sa.Column("methodology_version", sa.String(length=80), nullable=True),
    )
    op.add_column(
        "work_entities",
        sa.Column(
            "methodology_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "work_entities",
        sa.Column("baseline_locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "work_entities",
        sa.Column(
            "baseline_locked_by_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.add_column(
        "work_entities",
        sa.Column(
            "schedule_revision",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.execute(
        """
        UPDATE work_entities
        SET forecast_starts_at = starts_at,
            forecast_due_at = due_at,
            baseline_locked_at = CASE
                WHEN status IN ('active', 'paused', 'done') THEN updated_at
                ELSE NULL
            END,
            baseline_locked_by_id = CASE
                WHEN status IN ('active', 'paused', 'done') THEN owner_id
                ELSE NULL
            END
        """
    )
    op.create_foreign_key(
        "fk_work_entities_baseline_locked_by",
        "work_entities",
        "users",
        ["baseline_locked_by_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_check_constraint(
        "ck_work_entities_forecast_dates",
        "work_entities",
        (
            "forecast_starts_at IS NULL OR forecast_due_at IS NULL "
            "OR forecast_due_at > forecast_starts_at"
        ),
    )
    op.create_check_constraint(
        "ck_work_entities_planning_mode",
        "work_entities",
        "planning_mode IN ('free', 'methodology')",
    )
    op.create_index(
        "ix_work_entities_forecast_due_at",
        "work_entities",
        ["forecast_due_at"],
    )
    op.create_index(
        "ix_work_entities_planning_mode",
        "work_entities",
        ["planning_mode"],
    )

    op.create_table(
        "work_entity_stages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("completion_criteria", sa.Text(), nullable=True),
        sa.Column("guidance", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="planned",
        ),
        sa.Column(
            "source_type",
            sa.String(length=30),
            nullable=False,
            server_default="manual",
        ),
        sa.Column("source_key", sa.String(length=120), nullable=True),
        sa.Column(
            "source_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'active', 'done', 'cancelled')",
            name="ck_work_entity_stages_status",
        ),
        sa.CheckConstraint(
            "source_type IN ('manual', 'methodology')",
            name="ck_work_entity_stages_source_type",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["work_entities.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "entity_id",
            "id",
            name="uq_work_entity_stages_entity_id_id",
        ),
        sa.UniqueConstraint(
            "entity_id",
            "source_key",
            name="uq_work_entity_stages_entity_source_key",
        ),
    )
    op.create_index(
        "ix_work_entity_stages_entity_id",
        "work_entity_stages",
        ["entity_id"],
    )
    op.create_index(
        "ix_work_entity_stages_status",
        "work_entity_stages",
        ["status"],
    )
    op.create_index(
        "ix_work_entity_stages_source_type",
        "work_entity_stages",
        ["source_type"],
    )
    op.create_index(
        "ix_work_entity_stages_entity_position",
        "work_entity_stages",
        ["entity_id", "position"],
    )

    op.execute("CREATE SEQUENCE work_entity_milestones_number_seq START WITH 1")
    op.create_table(
        "work_entity_milestones",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "milestone_number",
            sa.Integer(),
            nullable=False,
            server_default=sa.text(
                "nextval('work_entity_milestones_number_seq'::regclass)"
            ),
        ),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=30),
            nullable=False,
            server_default="planned",
        ),
        sa.Column(
            "criticality",
            sa.String(length=20),
            nullable=False,
            server_default="control",
        ),
        sa.Column("criticality_reason", sa.Text(), nullable=True),
        sa.Column("acceptance_criteria", sa.Text(), nullable=False),
        sa.Column("decision_owner_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("baseline_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("forecast_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("actual_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reschedule_reason", sa.Text(), nullable=True),
        sa.Column(
            "reschedule_count",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "status IN ('planned', 'achieved', 'cancelled')",
            name="ck_work_entity_milestones_status",
        ),
        sa.CheckConstraint(
            "criticality IN ('control', 'key', 'critical')",
            name="ck_work_entity_milestones_criticality",
        ),
        sa.CheckConstraint(
            "criticality = 'control' OR criticality_reason IS NOT NULL",
            name="ck_work_entity_milestones_criticality_reason",
        ),
        sa.CheckConstraint(
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
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["decision_owner_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["work_entities.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id", "stage_id"],
            ["work_entity_stages.entity_id", "work_entity_stages.id"],
            ondelete="RESTRICT",
            name="fk_work_entity_milestones_stage_entity",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "milestone_number",
            name="uq_work_entity_milestones_number",
        ),
        sa.UniqueConstraint(
            "entity_id",
            "id",
            name="uq_work_entity_milestones_entity_id_id",
        ),
    )
    op.execute(
        """
        INSERT INTO work_entity_milestones (
            id, milestone_number, entity_id, title, description, status,
            criticality, criticality_reason, acceptance_criteria,
            decision_owner_id, created_by_id, baseline_at, forecast_at,
            actual_at, cancelled_at, position, created_at, updated_at
        )
        SELECT
            id,
            nextval('work_entity_milestones_number_seq'::regclass),
            entity_id,
            title,
            description,
            CASE
                WHEN status = 'done' THEN 'achieved'
                WHEN status = 'cancelled' THEN 'cancelled'
                ELSE 'planned'
            END,
            CASE
                WHEN priority = 'critical' THEN 'critical'
                WHEN priority = 'high' THEN 'key'
                ELSE 'control'
            END,
            CASE
                WHEN priority IN ('critical', 'high')
                THEN 'Перенесено из локального прототипа; требуется уточнение.'
                ELSE NULL
            END,
            COALESCE(
                acceptance_criteria,
                'Критерий перенесен из прототипа и требует уточнения.'
            ),
            assignee_id,
            created_by_id,
            COALESCE(due_at, starts_at, created_at),
            COALESCE(due_at, starts_at, created_at),
            CASE
                WHEN status = 'done'
                THEN COALESCE(
                    completed_at, updated_at, due_at, starts_at, created_at
                )
                ELSE NULL
            END,
            CASE
                WHEN status = 'cancelled'
                THEN COALESCE(
                    updated_at, completed_at, due_at, starts_at, created_at
                )
                ELSE NULL
            END,
            position,
            created_at,
            updated_at
        FROM work_entity_tasks
        WHERE item_type = 'milestone'
        """
    )
    op.create_index(
        "ix_work_entity_milestones_entity_id",
        "work_entity_milestones",
        ["entity_id"],
    )
    op.create_index(
        "ix_work_entity_milestones_stage_id",
        "work_entity_milestones",
        ["stage_id"],
    )
    op.create_index(
        "ix_work_entity_milestones_status",
        "work_entity_milestones",
        ["status"],
    )
    op.create_index(
        "ix_work_entity_milestones_criticality",
        "work_entity_milestones",
        ["criticality"],
    )
    op.create_index(
        "ix_work_entity_milestones_decision_owner_id",
        "work_entity_milestones",
        ["decision_owner_id"],
    )
    op.create_index(
        "ix_work_entity_milestones_baseline_at",
        "work_entity_milestones",
        ["baseline_at"],
    )
    op.create_index(
        "ix_work_entity_milestones_forecast_at",
        "work_entity_milestones",
        ["forecast_at"],
    )

    op.add_column(
        "work_entity_tasks",
        sa.Column("stage_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "work_entity_tasks",
        sa.Column("baseline_starts_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "work_entity_tasks",
        sa.Column("baseline_due_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "work_entity_tasks",
        sa.Column("forecast_starts_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "work_entity_tasks",
        sa.Column("forecast_due_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "work_entity_tasks",
        sa.Column("actual_starts_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "work_entity_tasks",
        sa.Column("actual_due_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE work_entity_tasks
        SET baseline_starts_at = starts_at,
            baseline_due_at = due_at,
            forecast_starts_at = starts_at,
            forecast_due_at = due_at,
            actual_starts_at = CASE
                WHEN status IN ('in_progress', 'review', 'done')
                THEN updated_at
                ELSE NULL
            END,
            actual_due_at = completed_at
        WHERE item_type = 'task'
        """
    )
    op.create_foreign_key(
        "fk_work_entity_tasks_stage_entity",
        "work_entity_tasks",
        "work_entity_stages",
        ["entity_id", "stage_id"],
        ["entity_id", "id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "work_entity_schedule_dependencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "predecessor_task_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "predecessor_milestone_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "successor_task_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "successor_milestone_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "dependency_type",
            sa.String(length=30),
            nullable=False,
            server_default="finish_to_start",
        ),
        sa.Column("lag_days", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "cascade_on_shift",
            sa.Boolean(),
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "status",
            sa.String(length=20),
            nullable=False,
            server_default="active",
        ),
        sa.Column("waiver_reason", sa.Text(), nullable=True),
        sa.Column("waived_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "waived_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "num_nonnulls(predecessor_task_id, predecessor_milestone_id) = 1",
            name="ck_work_entity_schedule_dependencies_one_predecessor",
        ),
        sa.CheckConstraint(
            "num_nonnulls(successor_task_id, successor_milestone_id) = 1",
            name="ck_work_entity_schedule_dependencies_one_successor",
        ),
        sa.CheckConstraint(
            "NOT (predecessor_task_id IS NOT NULL "
            "AND predecessor_task_id = successor_task_id)",
            name="ck_work_entity_schedule_dependencies_no_self_task",
        ),
        sa.CheckConstraint(
            "NOT (predecessor_milestone_id IS NOT NULL "
            "AND predecessor_milestone_id = successor_milestone_id)",
            name="ck_work_entity_schedule_dependencies_no_self_milestone",
        ),
        sa.CheckConstraint(
            "dependency_type = 'finish_to_start'",
            name="ck_work_entity_schedule_dependencies_type",
        ),
        sa.CheckConstraint(
            "lag_days BETWEEN 0 AND 3650",
            name="ck_work_entity_schedule_dependencies_lag",
        ),
        sa.CheckConstraint(
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
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["waived_by_id"],
            ["users.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["work_entities.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id", "predecessor_task_id"],
            ["work_entity_tasks.entity_id", "work_entity_tasks.id"],
            ondelete="CASCADE",
            name="fk_work_entity_schedule_predecessor_task",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id", "successor_task_id"],
            ["work_entity_tasks.entity_id", "work_entity_tasks.id"],
            ondelete="CASCADE",
            name="fk_work_entity_schedule_successor_task",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id", "predecessor_milestone_id"],
            ["work_entity_milestones.entity_id", "work_entity_milestones.id"],
            ondelete="CASCADE",
            name="fk_work_entity_schedule_predecessor_milestone",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id", "successor_milestone_id"],
            ["work_entity_milestones.entity_id", "work_entity_milestones.id"],
            ondelete="CASCADE",
            name="fk_work_entity_schedule_successor_milestone",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.execute(
        """
        INSERT INTO work_entity_schedule_dependencies (
            id, entity_id,
            predecessor_task_id, predecessor_milestone_id,
            successor_task_id, successor_milestone_id,
            dependency_type, lag_days, cascade_on_shift, status,
            created_by_id, created_at
        )
        SELECT
            d.id,
            d.entity_id,
            CASE WHEN predecessor.item_type = 'task'
                THEN d.depends_on_task_id ELSE NULL END,
            CASE WHEN predecessor.item_type = 'milestone'
                THEN d.depends_on_task_id ELSE NULL END,
            CASE WHEN successor.item_type = 'task'
                THEN d.task_id ELSE NULL END,
            CASE WHEN successor.item_type = 'milestone'
                THEN d.task_id ELSE NULL END,
            'finish_to_start',
            0,
            true,
            'active',
            d.created_by_id,
            d.created_at
        FROM work_entity_task_dependencies d
        JOIN work_entity_tasks predecessor
          ON predecessor.id = d.depends_on_task_id
        JOIN work_entity_tasks successor
          ON successor.id = d.task_id
        """
    )
    op.create_index(
        "ix_work_entity_schedule_dependencies_entity_id",
        "work_entity_schedule_dependencies",
        ["entity_id"],
    )
    op.create_index(
        "ix_work_entity_schedule_dependencies_status",
        "work_entity_schedule_dependencies",
        ["status"],
    )
    for column in (
        "predecessor_task_id",
        "predecessor_milestone_id",
        "successor_task_id",
        "successor_milestone_id",
    ):
        op.create_index(
            f"ix_work_entity_schedule_dependencies_{column}",
            "work_entity_schedule_dependencies",
            [column],
        )
    op.create_index(
        "uq_work_entity_schedule_dependencies_tt",
        "work_entity_schedule_dependencies",
        ["entity_id", "predecessor_task_id", "successor_task_id"],
        unique=True,
        postgresql_where=sa.text(
            "predecessor_task_id IS NOT NULL "
            "AND successor_task_id IS NOT NULL"
        ),
    )
    op.create_index(
        "uq_work_entity_schedule_dependencies_tm",
        "work_entity_schedule_dependencies",
        ["entity_id", "predecessor_task_id", "successor_milestone_id"],
        unique=True,
        postgresql_where=sa.text(
            "predecessor_task_id IS NOT NULL "
            "AND successor_milestone_id IS NOT NULL"
        ),
    )
    op.create_index(
        "uq_work_entity_schedule_dependencies_mt",
        "work_entity_schedule_dependencies",
        ["entity_id", "predecessor_milestone_id", "successor_task_id"],
        unique=True,
        postgresql_where=sa.text(
            "predecessor_milestone_id IS NOT NULL "
            "AND successor_task_id IS NOT NULL"
        ),
    )
    op.create_index(
        "uq_work_entity_schedule_dependencies_mm",
        "work_entity_schedule_dependencies",
        ["entity_id", "predecessor_milestone_id", "successor_milestone_id"],
        unique=True,
        postgresql_where=sa.text(
            "predecessor_milestone_id IS NOT NULL "
            "AND successor_milestone_id IS NOT NULL"
        ),
    )
    op.drop_table("work_entity_task_dependencies")

    op.add_column(
        "work_entity_artifacts",
        sa.Column("milestone_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        """
        UPDATE work_entity_artifacts a
        SET milestone_id = a.task_id
        FROM work_entity_tasks t
        WHERE t.id = a.task_id
          AND t.item_type = 'milestone'
        """
    )
    op.drop_constraint(
        "fk_work_entity_artifacts_task_entity",
        "work_entity_artifacts",
        type_="foreignkey",
    )
    op.drop_constraint(
        "work_entity_artifacts_task_id_fkey",
        "work_entity_artifacts",
        type_="foreignkey",
    )
    op.execute(
        """
        UPDATE work_entity_artifacts
        SET task_id = NULL
        WHERE milestone_id IS NOT NULL
        """
    )
    op.create_foreign_key(
        "work_entity_artifacts_task_id_fkey",
        "work_entity_artifacts",
        "work_entity_tasks",
        ["task_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_work_entity_artifacts_task_entity",
        "work_entity_artifacts",
        "work_entity_tasks",
        ["entity_id", "task_id"],
        ["entity_id", "id"],
    )
    op.create_foreign_key(
        "work_entity_artifacts_milestone_id_fkey",
        "work_entity_artifacts",
        "work_entity_milestones",
        ["milestone_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_work_entity_artifacts_milestone_entity",
        "work_entity_artifacts",
        "work_entity_milestones",
        ["entity_id", "milestone_id"],
        ["entity_id", "id"],
    )
    op.create_check_constraint(
        "ck_work_entity_artifacts_one_parent",
        "work_entity_artifacts",
        "num_nonnulls(task_id, milestone_id) <= 1",
    )
    op.create_index(
        "ix_work_entity_artifacts_milestone_id",
        "work_entity_artifacts",
        ["milestone_id"],
    )

    op.execute("DELETE FROM work_entity_tasks WHERE item_type = 'milestone'")
    op.drop_index(
        "ix_work_entity_tasks_entity_status_due",
        table_name="work_entity_tasks",
    )
    op.drop_index("ix_work_entity_tasks_due_at", table_name="work_entity_tasks")
    op.drop_index("ix_work_entity_tasks_starts_at", table_name="work_entity_tasks")
    op.drop_index("ix_work_entity_tasks_item_type", table_name="work_entity_tasks")
    op.drop_constraint(
        "ck_work_entity_tasks_dates",
        "work_entity_tasks",
        type_="check",
    )
    op.drop_constraint(
        "ck_work_entity_tasks_item_type",
        "work_entity_tasks",
        type_="check",
    )
    op.drop_column("work_entity_tasks", "completed_at")
    op.drop_column("work_entity_tasks", "due_at")
    op.drop_column("work_entity_tasks", "starts_at")
    op.drop_column("work_entity_tasks", "item_type")
    op.create_check_constraint(
        "ck_work_entity_tasks_baseline_dates",
        "work_entity_tasks",
        (
            "baseline_starts_at IS NULL OR baseline_due_at IS NULL "
            "OR baseline_due_at > baseline_starts_at"
        ),
    )
    op.create_check_constraint(
        "ck_work_entity_tasks_forecast_dates",
        "work_entity_tasks",
        (
            "forecast_starts_at IS NULL OR forecast_due_at IS NULL "
            "OR forecast_due_at > forecast_starts_at"
        ),
    )
    for column in (
        "stage_id",
        "baseline_starts_at",
        "baseline_due_at",
        "forecast_starts_at",
        "forecast_due_at",
    ):
        op.create_index(
            f"ix_work_entity_tasks_{column}",
            "work_entity_tasks",
            [column],
        )
    op.create_index(
        "ix_work_entity_tasks_entity_status_forecast_due",
        "work_entity_tasks",
        ["entity_id", "status", "forecast_due_at"],
    )

    for column, column_type in (
        ("object_type", sa.String(length=40)),
        ("object_id", postgresql.UUID(as_uuid=True)),
        ("object_ref", sa.String(length=80)),
        ("object_title", sa.String(length=240)),
        ("action", sa.String(length=40)),
        ("reason", sa.Text()),
        ("correlation_id", postgresql.UUID(as_uuid=True)),
    ):
        op.add_column(
            "work_entity_events",
            sa.Column(column, column_type, nullable=True),
        )
    op.create_index(
        "ix_work_entity_events_object_type",
        "work_entity_events",
        ["object_type"],
    )
    op.create_index(
        "ix_work_entity_events_correlation_id",
        "work_entity_events",
        ["correlation_id"],
    )

    op.execute(
        sa.text(
            """
            INSERT INTO knowledge_articles (
                id, slug, title, summary, section, body, status, sort_order,
                created_at, updated_at, published_at
            )
            VALUES (
                '126876f6-a052-4483-93b3-fd2cbc0f8de0',
                'rabochee-prostranstvo-proekta',
                'Проект: задачи, контрольные точки и график',
                'Как устроены задачи, milestones, baseline, forecast, зависимости и управляемый перенос.',
                'tasks',
                :body,
                'published',
                37,
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
            """
        ).bindparams(body=WORKSPACE_KB_BODY)
    )


def downgrade() -> None:
    if os.environ.get(LOSSY_DOWNGRADE_OPT_IN_ENV) != "1":
        raise RuntimeError(
            "Downgrade 045 collapses the typed project schedule and is "
            "disabled by default. Restore a verified pre-migration backup, "
            f"or set {LOSSY_DOWNGRADE_OPT_IN_ENV}=1 only for a disposable "
            "local database."
        )
    op.execute(
        """
        UPDATE knowledge_articles
        SET title = 'Рабочее пространство проекта',
            summary = 'Проектные задачи, участники, артефакты, зависимости, карта и журнал.',
            updated_at = now(),
            published_at = now()
        WHERE slug = 'rabochee-prostranstvo-proekta'
        """
    )

    op.drop_index(
        "ix_work_entity_events_correlation_id",
        table_name="work_entity_events",
    )
    op.drop_index(
        "ix_work_entity_events_object_type",
        table_name="work_entity_events",
    )
    for column in (
        "correlation_id",
        "reason",
        "action",
        "object_title",
        "object_ref",
        "object_id",
        "object_type",
    ):
        op.drop_column("work_entity_events", column)

    op.add_column(
        "work_entity_tasks",
        sa.Column(
            "item_type",
            sa.String(length=30),
            nullable=False,
            server_default="task",
        ),
    )
    op.add_column(
        "work_entity_tasks",
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "work_entity_tasks",
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "work_entity_tasks",
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(
        """
        UPDATE work_entity_tasks
        SET starts_at = forecast_starts_at,
            due_at = forecast_due_at,
            completed_at = actual_due_at
        """
    )
    op.execute(
        """
        SELECT setval(
            'work_entity_tasks_task_number_seq',
            GREATEST(COALESCE(MAX(task_number), 1000), 1000),
            true
        )
        FROM work_entity_tasks
        """
    )
    op.execute(
        """
        INSERT INTO work_entity_tasks (
            id, task_number, entity_id, item_type, title, description, status,
            priority, assignee_id, created_by_id, acceptance_criteria,
            starts_at, due_at, completed_at, position, created_at, updated_at
        )
        SELECT
            id,
            nextval('work_entity_tasks_task_number_seq'::regclass),
            entity_id,
            'milestone',
            title,
            description,
            CASE
                WHEN status = 'achieved' THEN 'done'
                WHEN status = 'cancelled' THEN 'cancelled'
                ELSE 'planned'
            END,
            CASE
                WHEN criticality = 'critical' THEN 'critical'
                WHEN criticality = 'key' THEN 'high'
                ELSE 'medium'
            END,
            decision_owner_id,
            created_by_id,
            acceptance_criteria,
            NULL,
            forecast_at,
            actual_at,
            position,
            created_at,
            updated_at
        FROM work_entity_milestones
        """
    )

    op.create_table(
        "work_entity_task_dependencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("depends_on_task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "task_id <> depends_on_task_id",
            name="ck_work_entity_task_dependencies_no_self",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id"],
            ["work_entities.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id", "task_id"],
            ["work_entity_tasks.entity_id", "work_entity_tasks.id"],
            ondelete="CASCADE",
            name="fk_work_entity_dependencies_task_entity",
        ),
        sa.ForeignKeyConstraint(
            ["entity_id", "depends_on_task_id"],
            ["work_entity_tasks.entity_id", "work_entity_tasks.id"],
            ondelete="CASCADE",
            name="fk_work_entity_dependencies_prerequisite_entity",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "task_id",
            "depends_on_task_id",
            name="uq_work_entity_task_dependencies_pair",
        ),
    )
    op.create_index(
        "ix_work_entity_task_dependencies_entity_id",
        "work_entity_task_dependencies",
        ["entity_id"],
    )
    op.create_index(
        "ix_work_entity_task_dependencies_task_id",
        "work_entity_task_dependencies",
        ["task_id"],
    )
    op.create_index(
        "ix_work_entity_task_dependencies_depends_on_task_id",
        "work_entity_task_dependencies",
        ["depends_on_task_id"],
    )
    op.execute(
        """
        INSERT INTO work_entity_task_dependencies (
            id, entity_id, task_id, depends_on_task_id, created_by_id, created_at
        )
        SELECT
            id,
            entity_id,
            COALESCE(successor_task_id, successor_milestone_id),
            COALESCE(predecessor_task_id, predecessor_milestone_id),
            created_by_id,
            created_at
        FROM work_entity_schedule_dependencies
        """
    )
    op.drop_table("work_entity_schedule_dependencies")

    op.drop_constraint(
        "ck_work_entity_artifacts_one_parent",
        "work_entity_artifacts",
        type_="check",
    )
    op.drop_constraint(
        "fk_work_entity_artifacts_milestone_entity",
        "work_entity_artifacts",
        type_="foreignkey",
    )
    op.drop_constraint(
        "work_entity_artifacts_milestone_id_fkey",
        "work_entity_artifacts",
        type_="foreignkey",
    )
    op.execute(
        """
        UPDATE work_entity_artifacts
        SET task_id = milestone_id
        WHERE milestone_id IS NOT NULL
        """
    )
    op.drop_index(
        "ix_work_entity_artifacts_milestone_id",
        table_name="work_entity_artifacts",
    )
    op.drop_column("work_entity_artifacts", "milestone_id")

    op.drop_constraint(
        "ck_work_entity_tasks_forecast_dates",
        "work_entity_tasks",
        type_="check",
    )
    op.drop_constraint(
        "ck_work_entity_tasks_baseline_dates",
        "work_entity_tasks",
        type_="check",
    )
    op.create_check_constraint(
        "ck_work_entity_tasks_item_type",
        "work_entity_tasks",
        "item_type IN ('task', 'milestone')",
    )
    op.create_check_constraint(
        "ck_work_entity_tasks_dates",
        "work_entity_tasks",
        "starts_at IS NULL OR due_at IS NULL OR due_at > starts_at",
    )
    op.drop_index(
        "ix_work_entity_tasks_entity_status_forecast_due",
        table_name="work_entity_tasks",
    )
    for column in (
        "forecast_due_at",
        "forecast_starts_at",
        "baseline_due_at",
        "baseline_starts_at",
        "stage_id",
    ):
        op.drop_index(
            f"ix_work_entity_tasks_{column}",
            table_name="work_entity_tasks",
        )
    op.create_index(
        "ix_work_entity_tasks_item_type",
        "work_entity_tasks",
        ["item_type"],
    )
    op.create_index(
        "ix_work_entity_tasks_starts_at",
        "work_entity_tasks",
        ["starts_at"],
    )
    op.create_index(
        "ix_work_entity_tasks_due_at",
        "work_entity_tasks",
        ["due_at"],
    )
    op.create_index(
        "ix_work_entity_tasks_entity_status_due",
        "work_entity_tasks",
        ["entity_id", "status", "due_at"],
    )
    op.drop_constraint(
        "fk_work_entity_tasks_stage_entity",
        "work_entity_tasks",
        type_="foreignkey",
    )
    for column in (
        "actual_due_at",
        "actual_starts_at",
        "forecast_due_at",
        "forecast_starts_at",
        "baseline_due_at",
        "baseline_starts_at",
        "stage_id",
    ):
        op.drop_column("work_entity_tasks", column)

    op.drop_table("work_entity_milestones")
    op.execute("DROP SEQUENCE work_entity_milestones_number_seq")
    op.drop_table("work_entity_stages")

    op.drop_index(
        "ix_work_entities_planning_mode",
        table_name="work_entities",
    )
    op.drop_index(
        "ix_work_entities_forecast_due_at",
        table_name="work_entities",
    )
    op.drop_constraint(
        "ck_work_entities_planning_mode",
        "work_entities",
        type_="check",
    )
    op.drop_constraint(
        "ck_work_entities_forecast_dates",
        "work_entities",
        type_="check",
    )
    op.drop_constraint(
        "fk_work_entities_baseline_locked_by",
        "work_entities",
        type_="foreignkey",
    )
    for column in (
        "schedule_revision",
        "baseline_locked_by_id",
        "baseline_locked_at",
        "methodology_snapshot",
        "methodology_version",
        "methodology_title",
        "planning_mode",
        "actual_due_at",
        "actual_starts_at",
        "forecast_due_at",
        "forecast_starts_at",
    ):
        op.drop_column("work_entities", column)
