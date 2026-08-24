"""Bind canonical audit processing to the selected immutable document.

Revision ID: 070_audit_document_binding
Revises: 069_audit_case_materials
"""

from alembic import op
import sqlalchemy as sa


revision = "070_audit_document_binding"
down_revision = "069_audit_case_materials"
branch_labels = None
depends_on = None


ARTICLE_REPLACEMENTS = (
    (
        "Первый этап канонического процесса — `preflight`. Он локально проверяет, что выбранное неизменяемое ТЗ относится к указанному договору, строит identity report и выделяет исходные фрагменты. Внешний ИИ на этом этапе не вызывается.",
        "Первый этап канонического процесса — локальная подготовка выбранного неизменяемого ТЗ. DPMS фиксирует документ по SHA-256, проверяет его структуру и выделяет исходные фрагменты. Номер договора не вводится и не проверяется. Внешний ИИ на этом этапе не вызывается.",
    ),
    (
        "3. Выберите неизменяемое ТЗ в формате DOCX и активный доверенный skill.\n4. Введите точный номер договора и допустимые варианты написания, по одному в строке.\n5. Нажмите `Проверить ТЗ`.",
        "3. Выберите неизменяемое ТЗ в формате DOCX и активный доверенный skill.\n4. Нажмите `Подготовить документ`.",
    ),
    (
        "Задание уйдет отдельному worker. Окно покажет состояния `В очереди`, `Проверяем пакет`, `Проверяем принадлежность ТЗ`, затем `Проверка пройдена` либо безопасную причину блокировки. Повторный запуск с теми же документом, skill и вариантами номера возвращает тот же результат и не создает дубликат.",
        "Задание уйдет отдельному worker. Окно покажет состояния `В очереди`, `Подготавливаем документ`, затем `Документ подготовлен` либо безопасную техническую причину остановки. Повторный запуск с теми же документом и skill возвращает тот же результат и не создает дубликат.",
    ),
    (
        "DPMS хранит версии документа и skill, технические hash, состояние этапа, количество извлеченных фрагментов и безопасное резюме identity gate. Точные варианты номера временно сохраняются в зашифрованном виде для worker и удаляются из БД после выполнения. Каноническая привязка к точному номеру остается только во внутреннем рабочем каталоге run с закрытыми правами доступа; через API она не возвращается.",
        "DPMS хранит версии документа и skill, технические hash, состояние этапа и количество извлеченных фрагментов. Запуск привязан к выбранной карточке и неизменяемому SHA-256 файла. Бизнес-номер договора в runtime не передается и не используется.",
    ),
    (
        "На этапе preflight сетевого обращения к ИИ нет, поэтому номер договора и текст ТЗ не покидают DPMS. Дочерний процесс skill запускается с очищенным окружением, без API key ИИ и с запретом сетевых вызовов. Перед будущими model-фазами будет отдельный обязательный предпросмотр фактического обезличенного payload.",
        "На этапе подготовки сетевого обращения к ИИ нет, поэтому текст ТЗ не покидает DPMS. Дочерний процесс skill запускается с очищенным окружением, без API key ИИ и с запретом сетевых вызовов. Перед будущими model-фазами остается отдельный обязательный предпросмотр фактического обезличенного payload.",
    ),
)


OLD_WORKSPACE_SECTION = """## Если preflight не подтвердил договор
Код `BLOCKED_SOURCE_ID_UNCONFIRMED` означает, что система не нашла надежный признак принадлежности DOCX указанному договору. Свободного упоминания номера внутри текста недостаточно. Проверьте полный номер и выполните одно из действий:

1. добавьте точный номер договора в имя DOCX;
2. либо разместите на титульной странице отдельную строку `Договор № ...`;
3. загрузите исправленный DOCX в `Материалы` как новую версию и повторите preflight.

Identity gate нельзя обходить приблизительным номером: это защита от атомизации чужого ТЗ.
"""


NEW_WORKSPACE_SECTION = """## Как документ выбирается для обработки
Откройте нужную карточку, перейдите в `Атомы`, нажмите `Сформировать с ИИ` и выберите загруженный DOCX. Номер договора вводить, искать в тексте или добавлять в имя файла не нужно. DPMS привязывает запуск к выбранной карточке, ID документа и его неизменяемому SHA-256.

Если файл заменить, изменится SHA-256 и потребуется новый запуск. Такая привязка защищает от незаметной подмены документа без проверки бизнес-номера.
"""


def _replace_article_text(old: str, new: str, slug: str) -> None:
    op.execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET body = replace(body, :old, :new),
                updated_at = now()
            WHERE slug = :slug
            """
        ).bindparams(old=old, new=new, slug=slug)
    )


def upgrade() -> None:
    op.add_column(
        "audit_tz_runs",
        sa.Column("source_binding", sa.String(length=24), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE audit_tz_runs SET source_binding = 'contract_identifier' WHERE source_binding IS NULL"
        )
    )
    op.alter_column(
        "audit_tz_runs",
        "source_binding",
        nullable=False,
        server_default="document_hash",
    )
    op.create_check_constraint(
        "ck_audit_tz_runs_source_binding",
        "audit_tz_runs",
        "source_binding IN ('contract_identifier', 'document_hash')",
    )

    for old, new in ARTICLE_REPLACEMENTS:
        _replace_article_text(old, new, "audit-ai-atomization-skills")
    _replace_article_text(
        OLD_WORKSPACE_SECTION,
        NEW_WORKSPACE_SECTION,
        "audit-workspace-registry-team-documents",
    )
    op.execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET summary = 'Как локально подготовить выбранный DOCX по hash без проверки номера договора.',
                updated_at = now()
            WHERE slug = 'audit-ai-atomization-skills'
            """
        )
    )


def downgrade() -> None:
    for old, new in reversed(ARTICLE_REPLACEMENTS):
        _replace_article_text(new, old, "audit-ai-atomization-skills")
    _replace_article_text(
        NEW_WORKSPACE_SECTION,
        OLD_WORKSPACE_SECTION,
        "audit-workspace-registry-team-documents",
    )
    op.execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET summary = 'Как проверить доверенный skill, выполнить локальный preflight ТЗ и прочитать результат.',
                updated_at = now()
            WHERE slug = 'audit-ai-atomization-skills'
            """
        )
    )
    op.drop_constraint(
        "ck_audit_tz_runs_source_binding",
        "audit_tz_runs",
        type_="check",
    )
    op.drop_column("audit_tz_runs", "source_binding")
