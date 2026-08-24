"""Add isolated canonical audit-tz runtime and preflight state.

Revision ID: 068_audit_tz_runtime
Revises: 067_audit_skill_privacy
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "068_audit_tz_runtime"
down_revision = "067_audit_skill_privacy"
branch_labels = None
depends_on = None


ARTICLE_BODY = """Обновлено: 2026-08-23

## Что теперь работает
Доверенный архив `audit-tz` запускается не внутри API, а в отдельном изолированном worker. После установки worker повторно проверяет точный SHA-256 пакета и выполняет встроенный self-test. Только успешная версия получает состояние `Runtime готов` и может быть активирована администратором.

Первый этап канонического процесса — `preflight`. Он локально проверяет, что выбранное неизменяемое ТЗ относится к указанному договору, строит identity report и выделяет исходные фрагменты. Внешний ИИ на этом этапе не вызывается.

## Как установить skill
1. Откройте `Админ -> Интеграции -> ИИ -> Skills атомизации аудита`.
2. Загрузите доверенный `.skill`.
3. Дождитесь статуса `Runtime готов`. Статус означает, что отдельный worker проверил пакет и его встроенные тесты.
4. Нажмите `Активировать`.

Если self-test не пройден, версия получает статус `Runtime заблокирован`. Уже активная рабочая версия при этом не отключается.

## Как запустить проверку ТЗ
1. Откройте карточку договора в разделе `Аудит` и вкладку `Атомы`.
2. Нажмите `Сформировать с ИИ`.
3. Выберите неизменяемое ТЗ в формате DOCX и активный доверенный skill.
4. Введите точный номер договора и допустимые варианты написания, по одному в строке.
5. Нажмите `Проверить ТЗ`.

Задание уйдет отдельному worker. Окно покажет состояния `В очереди`, `Проверяем пакет`, `Проверяем принадлежность ТЗ`, затем `Проверка пройдена` либо безопасную причину блокировки. Повторный запуск с теми же документом, skill и вариантами номера возвращает тот же результат и не создает дубликат.

## Какие данные сохраняются
DPMS хранит версии документа и skill, технические hash, состояние этапа, количество извлеченных фрагментов и безопасное резюме identity gate. Точные варианты номера временно сохраняются в зашифрованном виде для worker и удаляются из БД после выполнения. Каноническая привязка к точному номеру остается только во внутреннем рабочем каталоге run с закрытыми правами доступа; через API она не возвращается.

Рабочий каталог canonical run доступен только runtime-контейнеру. API не исполняет код архива и не отдает внутренние пути или сырые артефакты пользователю.

## Конфиденциальность
На этапе preflight сетевого обращения к ИИ нет, поэтому номер договора и текст ТЗ не покидают DPMS. Дочерний процесс skill запускается с очищенным окружением, без API key ИИ и с запретом сетевых вызовов. Перед будущими model-фазами будет отдельный обязательный предпросмотр фактического обезличенного payload.

## Граница текущего этапа
Сейчас canonical runtime выполняет self-test и preflight. Primary/challenger, adjudicator, critic, workbook QA, architect и перенос подтвержденных атомов в реестр будут подключаться следующими проверяемыми этапами. Статус `Проверка пройдена` не означает, что атомы уже сформированы.
"""


PREVIOUS_ARTICLE_BODY = """Обновлено: 2026-08-23

## Общий принцип
DPMS формирует только проверяемый черновик атомов. Исходное ТЗ остается неизменным, а записи попадают в реестр только после ручного подтверждения ответственного сотрудника.

## Установка методики
Администратор открывает `Админ -> Интеграции -> ИИ -> Skills атомизации аудита` и устанавливает одну из версий:

- декларативный JSON schema 1.0 — проверяется как данные и может быть активирован сразу;
- доверенный архив `.skill` — принимается только при точном совпадении SHA-256 с allowlist DPMS, проверяется как безопасный ZIP и сохраняется неизменяемо вместе с manifest.

Код из `.skill` никогда не исполняется в API-процессе. До подключения отдельного изолированного worker архив имеет состояние `Пакет проверен · runtime ожидается`; активировать его для обработки документов нельзя. Установка такого архива не отключает уже работающую декларативную версию.

## Предпросмотр обезличивания
Перед каждым обращением к внешней модели пользователь выбирает неизменяемое ТЗ и активный декларативный skill, вводит точные варианты номера договора и проверяет фактический обезличенный payload. Если номер не найден или хотя бы один вариант остался, отправка блокируется.

## Что сохраняется
DPMS хранит версии документа, skill, модели и конфигурации, технические hash, количество замен, результат проверки покрытия и действия человека. В журнал не записываются введенные номера договора, полный prompt, полный ответ модели и API key.

## Ограничение текущего slice
Полный многоэтапный runtime `audit-tz v0.3.0` (identity gate, primary/challenger, adjudicator, critic, workbook QA и architect) будет подключен отдельным изолированным worker. До этого доверенный архив можно установить и проверить, но нельзя использовать как обычный JSON-skill.
"""


def upgrade() -> None:
    op.drop_constraint(
        "ck_audit_atomization_skill_versions_runtime_status",
        "audit_atomization_skill_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_audit_atomization_skill_versions_runtime_status",
        "audit_atomization_skill_versions",
        "runtime_status IN ('ready', 'pending_worker', 'runtime_failed')",
    )
    op.add_column(
        "audit_atomization_skill_versions",
        sa.Column("runtime_checked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "audit_atomization_skill_versions",
        sa.Column("runtime_error_code", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "audit_atomization_skill_versions",
        sa.Column(
            "runtime_selftest_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )

    op.create_table(
        "audit_tz_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("case_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skill_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("requested_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("mode", sa.String(length=20), nullable=False, server_default="audit-only"),
        sa.Column("run_key_hash", sa.String(length=64), nullable=False),
        sa.Column("identifier_digest", sa.String(length=64), nullable=False),
        sa.Column("identifier_ciphertext", sa.Text(), nullable=True),
        sa.Column("identifiers_purged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("source_sha256", sa.String(length=64), nullable=False),
        sa.Column("skill_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="queued"),
        sa.Column("current_phase", sa.String(length=40), nullable=False, server_default="queued"),
        sa.Column("source_unit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("warning_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "safe_summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("mode = 'audit-only'", name="ck_audit_tz_runs_mode"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'preflight_pass', 'blocked', 'failed')",
            name="ck_audit_tz_runs_status",
        ),
        sa.CheckConstraint("source_unit_count >= 0", name="ck_audit_tz_runs_source_units"),
        sa.CheckConstraint("warning_count >= 0", name="ck_audit_tz_runs_warnings"),
        sa.ForeignKeyConstraint(["case_id"], ["audit_cases.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["document_id"], ["audit_documents.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(
            ["skill_version_id"],
            ["audit_atomization_skill_versions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(["requested_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_key_hash", name="uq_audit_tz_runs_key"),
    )
    op.create_index("ix_audit_tz_runs_case_id", "audit_tz_runs", ["case_id"])
    op.create_index("ix_audit_tz_runs_document_id", "audit_tz_runs", ["document_id"])
    op.create_index("ix_audit_tz_runs_skill_version_id", "audit_tz_runs", ["skill_version_id"])
    op.create_index("ix_audit_tz_runs_requested_by_id", "audit_tz_runs", ["requested_by_id"])
    op.create_index("ix_audit_tz_runs_status", "audit_tz_runs", ["status"])
    op.create_index("ix_audit_tz_runs_case_created_at", "audit_tz_runs", ["case_id", "created_at"])

    op.create_table(
        "audit_tz_runtime_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("skill_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="queued"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("lease_token", sa.String(length=36), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("worker_id", sa.String(length=80), nullable=True),
        sa.Column("error_code", sa.String(length=100), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "kind IN ('skill_selftest', 'preflight')",
            name="ck_audit_tz_runtime_jobs_kind",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'blocked', 'failed')",
            name="ck_audit_tz_runtime_jobs_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_audit_tz_runtime_jobs_attempts"),
        sa.CheckConstraint(
            "max_attempts BETWEEN 1 AND 10",
            name="ck_audit_tz_runtime_jobs_max_attempts",
        ),
        sa.CheckConstraint(
            "(kind = 'skill_selftest' AND run_id IS NULL) OR "
            "(kind = 'preflight' AND run_id IS NOT NULL)",
            name="ck_audit_tz_runtime_jobs_target",
        ),
        sa.ForeignKeyConstraint(
            ["skill_version_id"],
            ["audit_atomization_skill_versions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["audit_tz_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_tz_runtime_jobs_skill_version_id", "audit_tz_runtime_jobs", ["skill_version_id"])
    op.create_index("ix_audit_tz_runtime_jobs_run_id", "audit_tz_runtime_jobs", ["run_id"])
    op.create_index(
        "ix_audit_tz_runtime_jobs_claim",
        "audit_tz_runtime_jobs",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "uq_audit_tz_runtime_jobs_selftest",
        "audit_tz_runtime_jobs",
        ["skill_version_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'skill_selftest'"),
    )
    op.create_index(
        "uq_audit_tz_runtime_jobs_preflight",
        "audit_tz_runtime_jobs",
        ["run_id"],
        unique=True,
        postgresql_where=sa.text("kind = 'preflight'"),
    )

    op.create_table(
        "audit_tz_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("phase", sa.String(length=40), nullable=False, server_default="PREFLIGHT"),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("path_rel", sa.String(length=500), nullable=False),
        sa.Column(
            "safe_summary_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("visible_to_user", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint(
            "kind IN ('identity_report', 'gated_evidence_bundle', 'source_units')",
            name="ck_audit_tz_artifacts_kind",
        ),
        sa.ForeignKeyConstraint(["run_id"], ["audit_tz_runs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("run_id", "kind", name="uq_audit_tz_artifacts_run_kind"),
    )
    op.create_index("ix_audit_tz_artifacts_run_id", "audit_tz_artifacts", ["run_id"])
    op.create_index(
        "ix_audit_tz_artifacts_run_created_at",
        "audit_tz_artifacts",
        ["run_id", "created_at"],
    )

    op.execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET body = :body,
                summary = 'Как проверить доверенный skill, выполнить локальный preflight ТЗ и прочитать результат.',
                updated_at = now()
            WHERE slug = 'audit-ai-atomization-skills'
            """
        ).bindparams(body=ARTICLE_BODY)
    )


def downgrade() -> None:
    op.drop_index("ix_audit_tz_artifacts_run_created_at", table_name="audit_tz_artifacts")
    op.drop_index("ix_audit_tz_artifacts_run_id", table_name="audit_tz_artifacts")
    op.drop_table("audit_tz_artifacts")
    op.drop_index("uq_audit_tz_runtime_jobs_preflight", table_name="audit_tz_runtime_jobs")
    op.drop_index("uq_audit_tz_runtime_jobs_selftest", table_name="audit_tz_runtime_jobs")
    op.drop_index("ix_audit_tz_runtime_jobs_claim", table_name="audit_tz_runtime_jobs")
    op.drop_index("ix_audit_tz_runtime_jobs_run_id", table_name="audit_tz_runtime_jobs")
    op.drop_index("ix_audit_tz_runtime_jobs_skill_version_id", table_name="audit_tz_runtime_jobs")
    op.drop_table("audit_tz_runtime_jobs")
    op.drop_index("ix_audit_tz_runs_case_created_at", table_name="audit_tz_runs")
    op.drop_index("ix_audit_tz_runs_status", table_name="audit_tz_runs")
    op.drop_index("ix_audit_tz_runs_requested_by_id", table_name="audit_tz_runs")
    op.drop_index("ix_audit_tz_runs_skill_version_id", table_name="audit_tz_runs")
    op.drop_index("ix_audit_tz_runs_document_id", table_name="audit_tz_runs")
    op.drop_index("ix_audit_tz_runs_case_id", table_name="audit_tz_runs")
    op.drop_table("audit_tz_runs")

    op.drop_column("audit_atomization_skill_versions", "runtime_selftest_json")
    op.drop_column("audit_atomization_skill_versions", "runtime_error_code")
    op.drop_column("audit_atomization_skill_versions", "runtime_checked_at")
    op.drop_constraint(
        "ck_audit_atomization_skill_versions_runtime_status",
        "audit_atomization_skill_versions",
        type_="check",
    )
    op.execute(
        "UPDATE audit_atomization_skill_versions "
        "SET runtime_status = 'pending_worker' WHERE runtime_status = 'runtime_failed'"
    )
    op.create_check_constraint(
        "ck_audit_atomization_skill_versions_runtime_status",
        "audit_atomization_skill_versions",
        "runtime_status IN ('ready', 'pending_worker')",
    )

    op.execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET body = :body,
                summary = 'Как установить методику, проверить обезличивание договора и сформировать ИИ-черновик атомов.',
                updated_at = now()
            WHERE slug = 'audit-ai-atomization-skills'
            """
        ).bindparams(body=PREVIOUS_ARTICLE_BODY)
    )
