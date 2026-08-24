"""Store trusted audit skill archives and document the privacy gate.

Revision ID: 067_audit_skill_privacy
Revises: 066_audit_assignment_workflow
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "067_audit_skill_privacy"
down_revision = "066_audit_assignment_workflow"
branch_labels = None
depends_on = None


ARTICLE = {
    "id": "e717d272-f51c-4ebf-a4bf-5bb6db4587b9",
    "slug": "audit-ai-atomization-skills",
    "title": "Аудит: skill атомизации и безопасная передача в ИИ",
    "summary": "Как установить методику, проверить обезличивание договора и сформировать ИИ-черновик атомов.",
    "section": "audit",
    "body": """Обновлено: 2026-08-23

## Общий принцип
DPMS формирует только проверяемый черновик атомов. Исходное ТЗ остается неизменным, а записи попадают в реестр только после ручного подтверждения ответственного сотрудника.

## Установка методики
Администратор открывает `Админ -> Интеграции -> ИИ -> Skills атомизации аудита` и устанавливает одну из версий:

- декларативный JSON schema 1.0 — проверяется как данные и может быть активирован сразу;
- доверенный архив `.skill` — принимается только при точном совпадении SHA-256 с allowlist DPMS, проверяется как безопасный ZIP и сохраняется неизменяемо вместе с manifest.

Код из `.skill` никогда не исполняется в API-процессе. До подключения отдельного изолированного worker архив имеет состояние `Пакет проверен · runtime ожидается`; активировать его для обработки документов нельзя. Установка такого архива не отключает уже работающую декларативную версию.

## Предпросмотр обезличивания
Перед каждым обращением к внешней модели пользователь:

1. Выбирает неизменяемое ТЗ и активный skill.
2. Вводит номер договора и все допустимые точные варианты написания. Значения используются только в памяти текущего запроса, не записываются в БД и журнал.
3. Нажимает `Проверить обезличивание`.
4. DPMS заменяет найденные варианты единым псевдонимом, например `[ДОГОВОР-A1B2C3D4]`, и повторно сканирует фактический исходящий payload.
5. Если хотя бы один указанный вариант остался либо номер не найден, отправка блокируется.
6. Пользователь видит количество замен, несколько обезличенных фрагментов, провайдера и модель. Подтверждение действует 10 минут и привязано к пользователю, документу, skill и версии ИИ-профиля.

После изменения номера, документа, skill или ИИ-профиля предпросмотр нужно выполнить заново.

## Что уходит внешнему ИИ
Только системный протокол, обезличенное название цифрового продукта, правила активного декларативного skill, идентификаторы фрагментов вида `U000001`, локаторы абзацев/страниц и обезличенный текст фрагментов.

Не передаются: введенный номер договора, исходные имена и пути файлов, внутренние ID карточки, SHA-256 исходного документа, учетные данные интеграций и API key.

## Что сохраняется
DPMS хранит версии документа, skill, модели и конфигурации, технические hash, количество замен, результат проверки покрытия и действия человека. В журнал не записываются введенные номера договора, полный prompt, полный ответ модели и API key.

## Ограничение текущего slice
Полный многоэтапный runtime `audit-tz v0.3.0` (identity gate, primary/challenger, adjudicator, critic, workbook QA и architect) будет подключен отдельным изолированным worker. До этого доверенный архив можно установить и проверить, но нельзя использовать как обычный JSON-skill.
""",
}

PREVIOUS_ARTICLE_BODY = """Обновлено: 2026-08-23

DPMS может взять неизменяемое ТЗ из карточки аудита, применить активный декларативный JSON skill schema 1.0 и подготовить проверяемый черновик атомов. Исходный документ не изменяется, а атомы записываются только после ручного подтверждения ответственного сотрудника.

Администратор настраивает ИИ-провайдера и импортирует новую версию JSON skill в разделе интеграций. Пользователь выбирает ТЗ и активную методику, подтверждает передачу текста, проверяет ссылки на исходные фрагменты и отдельно фиксирует выбранные атомы.

API key, полный prompt и полный ответ модели не отображаются пользователям. Сохраняются версии документа, skill, модели, технические hash и решения человека.
"""


def upgrade() -> None:
    op.add_column(
        "audit_atomization_skill_versions",
        sa.Column("package_format", sa.String(length=40), nullable=False, server_default="declarative_json"),
    )
    op.add_column(
        "audit_atomization_skill_versions",
        sa.Column("package_blob", sa.LargeBinary(), nullable=True),
    )
    op.add_column(
        "audit_atomization_skill_versions",
        sa.Column(
            "package_manifest_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "audit_atomization_skill_versions",
        sa.Column("runtime_status", sa.String(length=40), nullable=False, server_default="ready"),
    )
    op.create_check_constraint(
        "ck_audit_atomization_skill_versions_package_format",
        "audit_atomization_skill_versions",
        "package_format IN ('declarative_json', 'trusted_skill_archive')",
    )
    op.create_check_constraint(
        "ck_audit_atomization_skill_versions_runtime_status",
        "audit_atomization_skill_versions",
        "runtime_status IN ('ready', 'pending_worker')",
    )
    op.create_check_constraint(
        "ck_audit_atomization_skill_versions_package_blob",
        "audit_atomization_skill_versions",
        "(package_format = 'declarative_json' AND package_blob IS NULL) OR "
        "(package_format = 'trusted_skill_archive' AND package_blob IS NOT NULL)",
    )

    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO knowledge_articles (
                id, slug, title, summary, section, body, status, sort_order,
                created_at, updated_at, published_at
            ) VALUES (
                :id, :slug, :title, :summary, :section, :body, 'published', 210,
                now(), now(), now()
            )
            ON CONFLICT (slug) DO UPDATE SET
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                section = EXCLUDED.section,
                body = EXCLUDED.body,
                status = 'published',
                updated_at = now(),
                published_at = COALESCE(knowledge_articles.published_at, now())
            """
        ),
        ARTICLE,
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET title = 'Аудит: атомизация ТЗ с помощью ИИ и skill',
                summary = 'Как установить методику, сформировать проверяемый ИИ-черновик и безопасно записать атомы.',
                body = :body,
                updated_at = now()
            WHERE slug = 'audit-ai-atomization-skills'
            """
        ),
        {"body": PREVIOUS_ARTICLE_BODY},
    )
    # The previous schema cannot represent archive bytes or their trust state.
    # Remove non-runnable archive versions instead of silently reclassifying them as JSON.
    op.get_bind().execute(
        sa.text(
            "DELETE FROM audit_atomization_skill_versions "
            "WHERE package_format = 'trusted_skill_archive'"
        )
    )
    op.get_bind().execute(
        sa.text(
            "DELETE FROM audit_atomization_skills AS skill "
            "WHERE NOT EXISTS ("
            "SELECT 1 FROM audit_atomization_skill_versions AS version "
            "WHERE version.skill_id = skill.id"
            ")"
        )
    )
    op.drop_constraint(
        "ck_audit_atomization_skill_versions_package_blob",
        "audit_atomization_skill_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_audit_atomization_skill_versions_runtime_status",
        "audit_atomization_skill_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_audit_atomization_skill_versions_package_format",
        "audit_atomization_skill_versions",
        type_="check",
    )
    op.drop_column("audit_atomization_skill_versions", "runtime_status")
    op.drop_column("audit_atomization_skill_versions", "package_manifest_json")
    op.drop_column("audit_atomization_skill_versions", "package_blob")
    op.drop_column("audit_atomization_skill_versions", "package_format")
