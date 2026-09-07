"""Transactional legacy transfer, provenance, historical dates and aggregate metrics."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "083_audit_legacy_transfer"
down_revision = "082_audit_legacy_upload"
branch_labels = None
depends_on = None

ARTICLE = {
    "id": "68575843-a511-41c5-89f5-97fda054e682",
    "slug": "audit-proverka-istoricheskogo-xlsx",
    "title": "Аудит: проверка и перенос исторического XLSX",
    "summary": "Исходная книга, сопоставления, предварительный просмотр, атомарный перенос и защищённая отмена.",
    "body": """## Как перенести исторический аудит

1. Откройте «Аудит», раздел исторического XLSX, и загрузите исходную книгу.
2. Создайте перенос и выберите наборы данных: нужные листы, диапазоны строк и сопоставления столбцов. Для атома occurred_at означает подтверждённую дату верификации, а не произвольную дату снимка или загрузки. Неизвестную дату оставьте пустой.
3. Для каждой исходной карточки выберите существующую карточку или создание новой. Сопоставьте сотрудников с пользователями либо историческими именами; текущие назначения разрешаются отдельно.
4. Сохраните настройки и запустите предварительную проверку. Просмотрите все страницы результатов, устраните ошибки и явно решите, какие существующие записи использовать или дополнить.
5. Подтвердите перенос. При изменении исходника или целевых данных выполните проверку заново.
6. Откройте перенесённые карточки и проверьте атомы, назначения, историю и статистику за исторический период.
7. При необходимости отмените перенос с указанием причины. Отмена возможна только пока данные не изменены и не используются живыми событиями, документами или другим переносом. Исходник и журнал сохраняются.

## Исходник и перенос

Загрузка XLSX сама по себе не меняет рабочий реестр. Администратор создаёт отдельную конфигурацию переноса: namespace, наборы данных, сопоставления полей, значения по умолчанию и словари исходных обозначений. Можно обработать несколько листов и диапазонов совместно: карточки, атомы, назначения, события и дневные показатели. Формулы не исполняются. Ограничения загрузки остаются прежними: XLSX до 10 МиБ, не более 20 сохранённых исходников.

## Явные решения

Для каждой исходной карточки выбирается существующая цель или создание новой. Для сотрудников задаётся существующий пользователь либо неизменяемое историческое имя. Перенос никогда не создаёт учётные записи. Совпадение имени или кода не разрешает автоматическую перезапись: существующий атом можно явно использовать или заполнить выбранные пустые поля; конфликт непустых значений блокирует перенос. В предварительном просмотре используются непрозрачные ключи карточек, а не исходные номера договоров.

Исторические назначения сохраняются как история. Создание текущих назначений требует отдельного флага, исходного признака текущего назначения и активного участника команды аудита с включённым доступом. Назначение с датой завершения никогда не становится текущим.

## Предварительный просмотр и подтверждение

Сохранение конфигурации увеличивает revision и аннулирует прошлый preview. Preview проверяет все строки, показывает итоговые счётчики, ошибки и результаты каждой строки; результаты доступны постранично. Ошибки за пределами первых 500 сообщений также блокируют перенос. Неизвестная дата снимка остаётся неизвестной, дата загрузки не подставляется вместо исторической даты.

Commit требует явного подтверждения, текущей revision и preview_hash. Под блокировками повторно проверяются исходник, целевые данные, сотрудники и provenance. Изменения, события, показатели и журнал сохраняются одной транзакцией либо не сохраняются вовсе. Повтор того же запроса не дублирует данные. Одинаковые семантические ключи в одном namespace дедуплицируются независимо от имени файла, листа и номера строки; изменённые данные под прежним ключом блокируются.

## История и показатели

Историческое событие использует реального сопоставленного пользователя либо историческое имя без приписывания действий администратору переноса. Снимок атома записывается как legacy_atom_snapshot, а не как переход статуса. Переход atom_status_changed содержит previous_state и state. Дневные агрегаты разных сотрудников могут суммироваться, но общий итог и персональные итоги одного дня/карточки/типа не смешиваются. Пересечение агрегатов с детальными атомами или событиями по карточке, дате и типу запрещено независимо от автора.

## Отмена и сохранность

Rollback требует revision, подтверждения и причины. Он разрешён только для неизменённых созданных переносом данных или неизменённых явно заполненных полей. Живые события, документы, внешние ссылки и использование другим подтверждённым переносом блокируют автоматическую отмену. Сначала отменяется зависимый перенос. Исходная книга, конфигурация, provenance и журнал остаются после отмены; отменённые исходные ключи не используются повторно в том же namespace.

Исходник, связанный с конфигурацией переноса, удалить нельзя. Он доступен только через административные маршруты и не прикрепляется как публичный документ карточки. Миграцию нельзя откатить при наличии записей переноса или исторических данных. Проверка синтетической книги не заменяет отдельную проверку реального файла пользователя.
""",
}


def uuid_column(name, target=None, *, nullable=False, primary_key=False, ondelete="RESTRICT"):
    args = [sa.ForeignKey(target, ondelete=ondelete)] if target else []
    return sa.Column(name, postgresql.UUID(as_uuid=True), *args, nullable=nullable, primary_key=primary_key)


def upgrade():
    op.create_table(
        "audit_legacy_transfers",
        uuid_column("id", primary_key=True),
        uuid_column("source_id", "audit_legacy_imports.id"),
        sa.Column("namespace", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("config", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("preview", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("preview_hash", sa.String(64), nullable=True),
        sa.Column("commit_key", sa.String(64), nullable=True),
        sa.Column("committed_revision", sa.Integer(), nullable=True),
        sa.Column("summary", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        uuid_column("created_by_id", "users.id", nullable=True, ondelete="SET NULL"),
        uuid_column("committed_by_id", "users.id", nullable=True, ondelete="SET NULL"),
        uuid_column("rolled_back_by_id", "users.id", nullable=True, ondelete="SET NULL"),
        sa.Column("rollback_reason", sa.Text(), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rolled_back_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("status IN ('draft', 'previewed', 'committed', 'rolled_back')", name="ck_audit_legacy_transfers_status"),
        sa.CheckConstraint("revision >= 1", name="ck_audit_legacy_transfers_revision"),
        sa.UniqueConstraint("commit_key", name="uq_audit_legacy_transfers_commit_key"),
    )
    op.create_index("ix_audit_legacy_transfers_source_id", "audit_legacy_transfers", ["source_id"])
    op.create_table(
        "audit_legacy_provenance",
        uuid_column("id", primary_key=True), uuid_column("transfer_id", "audit_legacy_transfers.id"),
        sa.Column("namespace", sa.String(120), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("source_key", sa.Text(), nullable=False),
        sa.Column("source_key_hash", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("target_table", sa.String(80), nullable=False), uuid_column("target_id"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.UniqueConstraint("namespace", "kind", "source_key_hash", name="uq_audit_legacy_provenance_source"),
    )
    op.create_index("ix_audit_legacy_provenance_transfer_id", "audit_legacy_provenance", ["transfer_id"])
    op.create_table(
        "audit_legacy_transfer_rows",
        uuid_column("id", primary_key=True), uuid_column("transfer_id", "audit_legacy_transfers.id"),
        sa.Column("row_key", sa.String(100), nullable=False),
        uuid_column("provenance_id", "audit_legacy_provenance.id", nullable=True),
        sa.Column("target_table", sa.String(80), nullable=True), uuid_column("target_id", nullable=True),
        sa.Column("outcome", sa.String(20), nullable=False),
        sa.Column("owned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("before", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("after", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.UniqueConstraint("transfer_id", "row_key", name="uq_audit_legacy_transfer_rows_key"),
    )
    for column in ("transfer_id", "provenance_id", "target_id"):
        op.create_index("ix_audit_legacy_transfer_rows_" + column, "audit_legacy_transfer_rows", [column])
    op.create_table(
        "audit_legacy_metrics",
        uuid_column("id", primary_key=True), uuid_column("transfer_id", "audit_legacy_transfers.id"),
        uuid_column("case_id", "audit_cases.id"),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("metric_type", sa.String(30), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.Column("actor_name", sa.String(255), nullable=True),
        sa.Column("actor_scope", sa.String(64), nullable=False, server_default=""),
        sa.UniqueConstraint("case_id", "metric_date", "metric_type", "actor_scope", name="uq_audit_legacy_metrics_coverage"),
        sa.CheckConstraint("metric_type IN ('verified', 'alpha_reviewed', 'commission_reviewed')", name="ck_audit_legacy_metrics_type"),
        sa.CheckConstraint("value >= 0", name="ck_audit_legacy_metrics_value"),
    )
    for column in ("transfer_id", "case_id"):
        op.create_index("ix_audit_legacy_metrics_" + column, "audit_legacy_metrics", [column])
    for table in ("audit_atoms", "audit_events"):
        op.add_column(table, uuid_column("legacy_transfer_id", nullable=True))
        op.create_foreign_key("fk_" + table + "_legacy_transfer", table, "audit_legacy_transfers", ["legacy_transfer_id"], ["id"], ondelete="RESTRICT")
    op.add_column("audit_atoms", sa.Column("legacy_effective_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("audit_events", sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("audit_events", sa.Column("historical_actor_name", sa.String(255), nullable=True))
    op.execute("UPDATE audit_events SET occurred_at = created_at WHERE occurred_at IS NULL")
    op.get_bind().execute(sa.text("""
        UPDATE knowledge_articles SET title=:title, summary=:summary, body=:body,
            status='published', updated_at=now()
        WHERE id=CAST(:id AS uuid) AND slug=:slug
    """), ARTICLE)


def downgrade():
    bind = op.get_bind()
    bind.execute(sa.text("LOCK TABLE audit_legacy_transfers, audit_legacy_provenance, audit_legacy_transfer_rows, audit_legacy_metrics, audit_atoms, audit_events IN ACCESS EXCLUSIVE MODE"))
    nonempty = bind.execute(sa.text("""
        SELECT (SELECT count(*) FROM audit_legacy_transfers)
            + (SELECT count(*) FROM audit_legacy_provenance)
            + (SELECT count(*) FROM audit_legacy_transfer_rows)
            + (SELECT count(*) FROM audit_legacy_metrics)
            + (SELECT count(*) FROM audit_atoms WHERE legacy_transfer_id IS NOT NULL OR legacy_effective_at IS NOT NULL)
            + (SELECT count(*) FROM audit_events WHERE legacy_transfer_id IS NOT NULL OR historical_actor_name IS NOT NULL)
    """)).scalar_one()
    if nonempty:
        raise RuntimeError("Cannot downgrade nonempty legacy transfer journal or historical data. Preserve the journal and sources.")
    for table in ("audit_atoms", "audit_events"):
        op.drop_constraint("fk_" + table + "_legacy_transfer", table, type_="foreignkey")
        op.drop_column(table, "legacy_transfer_id")
    op.drop_column("audit_atoms", "legacy_effective_at")
    op.drop_column("audit_events", "historical_actor_name")
    op.drop_column("audit_events", "occurred_at")
    for table in ("audit_legacy_metrics", "audit_legacy_transfer_rows", "audit_legacy_provenance", "audit_legacy_transfers"):
        op.drop_table(table)
    bind.execute(sa.text("""
        UPDATE knowledge_articles SET title=:title, summary=:summary, body=:body, updated_at=now()
        WHERE id=CAST(:id AS uuid) AND slug=:slug
    """), {**ARTICLE, "title": "Аудит: загрузка исходного XLSX для проверки",
           "summary": "Хранение исходной книги, сопоставление столбцов и отчёт без изменения рабочего реестра.",
           "body": "## Только подготовка и проверка\n\nФайл сохранён для проверки. Рабочий реестр не изменён.\n\nЗагрузка, сопоставление, просмотр, скачивание и удаление XLSX доступны только администратору. Подтверждение переноса в рабочий реестр в этой версии недоступно. Проверка не создаёт карточки, атомы, назначения, события и показатели. Формулы не исполняются. Исходные байты хранятся в БД. XLSX до 10 МиБ; не более 20 исходников. Повторная загрузка тех же байтов возвращает сохранённый исходник. Удаление исходника сохраняет журнал действий.\n"})
