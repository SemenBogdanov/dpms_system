"""Store legacy audit workbooks for inspection only, without registry promotion."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "082_audit_legacy_upload"
down_revision = "081_personal_task_form_guide"
branch_labels = None
depends_on = None

ARTICLE = {
    "id": "68575843-a511-41c5-89f5-97fda054e682",
    "slug": "audit-proverka-istoricheskogo-xlsx",
    "title": "Аудит: загрузка исходного XLSX для проверки",
    "summary": "Хранение исходной книги, сопоставление столбцов и отчёт без изменения рабочего реестра.",
    "body": """## Только подготовка и проверка

Файл сохранён для проверки. Рабочий реестр не изменён.

Загрузка исторического XLSX сохраняет исходную книгу и результаты проверки в отдельном хранилище подготовки. Она не создаёт и не изменяет договоры/карточки, атомы, назначения, события или показатели рабочего реестра. Этот этап не включает перенос данных в рабочий реестр. Даже успешная проверка не означает готовность к импорту.

## Доступ и ограничения

Загрузка, просмотр списка, отчёт, скачивание и удаление доступны только администратору с доступом к аудиту. Принимаются книги XLSX размером до 10 МиБ. Одновременно можно хранить не более 20 файлов проверки на всю систему. Повторная загрузка точно таких же байтов возвращает уже сохранённый файл, включая его сопоставление и отчёт, и не расходует ещё одно место.

## Листы и сопоставление

Выберите лист, строку заголовков и вид данных: договоры/карточки, атомы, назначения, события или дневные показатели. Сопоставьте исходные столбцы с полями. Проверка показывает количество строк, ошибки, предупреждения, повторы, ограниченный пример строк и несопоставленные столбцы. Формулы не исполняются; в сопоставленных полях они отмечаются как ошибки, кешированные итоги не принимаются за факты.

Статус «Загружен» означает сохранение книги. Статус «Проверен» означает наличие отчёта; он возможен и при ошибках. Изменение сопоставления запускает повторную проверку. Если другой администратор уже изменил файл проверки, обновите данные перед повторным сохранением или удалением.

## Исходный файл и удаление

Исходные байты хранятся атомарно в базе данных вместе с результатами проверки, а не во внешней временной папке. При скачивании используется нейтральное имя audit-legacy-source.xlsx; имя загруженного файла не сохраняется. Удаление убирает исходную книгу и результаты её проверки, освобождает место и не затрагивает рабочий реестр.

Сохраняются автор загрузки и автор последней проверки. Журнал действий фиксирует загрузку, проверку и удаление с идентификатором файла, SHA-256, размером и счётчиками, без имени файла и содержимого строк. Удаление файла проверки не удаляет эти записи журнала.

Проверка на реальном исходном файле выполняется отдельно после его предоставления пользователем. Обработка синтетических примеров не подтверждает совместимость с ещё не предоставленной книгой.
""",
}


def upgrade() -> None:
    op.create_table(
        "audit_legacy_imports",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="uploaded"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("source_bytes", sa.LargeBinary(), nullable=False),
        sa.Column("inspection", postgresql.JSONB(none_as_null=True), nullable=False),
        sa.Column("mapping", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("report", postgresql.JSONB(none_as_null=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("sha256", name="uq_audit_legacy_imports_sha256"),
        sa.CheckConstraint("status IN ('uploaded', 'checked')", name="ck_audit_legacy_status"),
        sa.CheckConstraint("revision >= 1", name="ck_audit_legacy_revision"),
        sa.CheckConstraint("size_bytes > 0 AND size_bytes <= 10485760", name="ck_audit_legacy_size"),
        sa.CheckConstraint(
            "(status = 'uploaded' AND mapping IS NULL AND report IS NULL) OR "
            "(status = 'checked' AND mapping IS NOT NULL AND report IS NOT NULL)",
            name="ck_audit_legacy_check_state",
        ),
    )
    op.get_bind().execute(sa.text("""
        INSERT INTO knowledge_articles (
            id, slug, title, summary, body, section, status, sort_order,
            created_at, updated_at, published_at
        ) VALUES (
            CAST(:id AS uuid), :slug, :title, :summary, :body, 'audit', 'published', 60,
            now(), now(), now()
        ) ON CONFLICT (slug) DO UPDATE SET
            title = EXCLUDED.title, summary = EXCLUDED.summary, body = EXCLUDED.body,
            status = 'published', updated_at = now()
        WHERE knowledge_articles.id = EXCLUDED.id
    """), ARTICLE)


def downgrade() -> None:
    # Keep the emptiness check and DROP atomic against concurrent uploads.
    op.get_bind().execute(sa.text("LOCK TABLE audit_legacy_imports IN ACCESS EXCLUSIVE MODE"))
    count = op.get_bind().execute(sa.text("SELECT count(*) FROM audit_legacy_imports")).scalar_one()
    if count:
        raise RuntimeError(
            "Cannot downgrade with staged XLSX sources. Export and delete uploaded files first."
        )
    op.get_bind().execute(sa.text(
        "DELETE FROM knowledge_articles WHERE id = CAST(:id AS uuid) AND slug = :slug"
    ), {"id": ARTICLE["id"], "slug": ARTICLE["slug"]})
    op.drop_table("audit_legacy_imports")
