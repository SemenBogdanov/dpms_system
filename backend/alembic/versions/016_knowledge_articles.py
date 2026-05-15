"""Add knowledge base articles

Revision ID: 016_knowledge_articles
Revises: 015_task_attachments
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "016_knowledge_articles"
down_revision = "015_task_attachments"
branch_labels = None
depends_on = None


STARTER_ARTICLES = [
    {
        "id": "59c74be7-fec1-4ce9-890e-516323fc21aa",
        "slug": "vhodnoy-brif-novichka",
        "title": "Входной бриф новичка",
        "summary": "Короткая рамка работы в системе: где брать задачи, как быть на связи и как сдавать результат.",
        "section": "start",
        "sort_order": 10,
        "body": """Обновлено: 2026-05-15

## Кратко
DPMS помогает команде видеть очередь задач, брать работу по правилам приоритета и фиксировать результат в Q.

## Первый день
- Откройте очередь и проверьте задачи, доступные вашей лиге.
- Возьмите задачу только после того, как поняли цель, срок и ожидаемый результат.
- Если формулировка неполная, задайте вопрос тимлиду до начала работы.
- В рабочее время оставайтесь доступны для оперативной связи.

## Базовый порядок
1. Проверьте приоритет задачи.
2. Возьмите задачу в работу.
3. Запустите focus timer, когда реально начали выполнять задачу.
4. Приложите результат и детальное описание при сдаче.
5. Дождитесь проверки или комментария на доработку.

## Доступность
Если сотрудник работает, он должен быть на связи. Телефон нужно брать не позднее чем через три гудка, чтобы вопросы по задаче решались без ожидания.""",
    },
    {
        "id": "58359c4c-c1b9-40c2-bc43-4e323ffc3184",
        "slug": "kak-rabotat-s-zadachami",
        "title": "Как работать с задачами",
        "summary": "Жизненный цикл задачи от очереди до проверки результата.",
        "section": "tasks",
        "sort_order": 20,
        "body": """Обновлено: 2026-05-15

## Очередь
В очереди находятся задачи, которые можно взять в работу. Доступность зависит от лиги, WIP-лимита, приоритета и текущих ограничений системы.

## В работе
- Берите задачу только тогда, когда готовы начать.
- Не держите задачу без движения.
- Если появилась блокировка, напишите тимлиду и зафиксируйте, что мешает продолжить.

## Сдача результата
При завершении заполните детальное описание и ссылки на результат. Эти данные нужны проверяющему и сохраняют историю выполнения.

## Доработка
Если задача возвращена, сначала разберите комментарий, затем продолжайте работу в той же задаче.""",
    },
    {
        "id": "4b25d2f4-3cfd-4e7e-8bc6-21b352afff42",
        "slug": "pravilo-dostupnosti-v-rabochie-chasy",
        "title": "Правило доступности в рабочие часы",
        "summary": "Ожидания по связи во время выполнения задач.",
        "section": "rules",
        "sort_order": 30,
        "body": """Обновлено: 2026-05-15

## Главное правило
В рабочие часы сотрудник должен быть доступен для связи по текущим задачам.

## Практический стандарт
- Телефон берется не позднее чем через три гудка.
- Сообщения по активной задаче проверяются регулярно.
- Если нужно отойти, предупредите тимлида или команду заранее.
- Если вопрос требует созвона, подключайтесь без затяжной переписки.

## Зачем это нужно
Цель правила — стопроцентная доступность для решения рабочих вопросов, чтобы задача не простаивала из-за ожидания ответа.""",
    },
    {
        "id": "b5195a85-6029-4c13-b016-d0a9acf8694f",
        "slug": "kritichnye-zadachi-i-dedlayny",
        "title": "Критичные задачи и дедлайны",
        "summary": "Что делать, если в очереди появляется критичная задача или задача со сроком.",
        "section": "tasks",
        "sort_order": 40,
        "body": """Обновлено: 2026-05-15

## Критичный приоритет
Критичная задача имеет приоритет над обычной очередью. Если такая задача доступна, следующая работа должна начинаться с нее или назначаться вручную ответственным.

## Дедлайны
- Задача без срока не считается просроченной сама по себе.
- Просрочка относится к незавершенным задачам в очереди или в работе.
- Если срок выглядит нереалистичным, сообщите тимлиду до начала выполнения.

## Поведение исполнителя
Не обходите критичную задачу ради более простой работы. Если не можете взять ее из-за лиги, доступа или контекста, сразу сообщите ответственному.""",
    },
    {
        "id": "ad66a416-e925-40f7-8bbc-cdf553f4c81f",
        "slug": "focus-timer-i-sdacha-rezultata",
        "title": "Focus timer и сдача результата",
        "summary": "Как фиксировать активную работу и корректно завершать задачу.",
        "section": "tasks",
        "sort_order": 50,
        "body": """Обновлено: 2026-05-15

## Focus timer
Запускайте таймер только на реальную активную работу. Если переключились на другую задачу или ушли на перерыв, остановите таймер.

## Ограничение
Один фокус-сегмент не должен превращаться в бесконтрольный многочасовой таймер. Если таймер не остановился автоматически, сообщите тимлиду или администратору.

## Сдача результата
- Заполните детальное описание того, что сделано.
- Добавьте ссылку на результат, если он находится во внешней системе.
- Укажите важные ограничения, проверки и договоренности.
- Отправляйте задачу на проверку только после самопроверки результата.""",
    },
]


def upgrade() -> None:
    knowledge_status_enum = postgresql.ENUM(
        "draft",
        "published",
        name="knowledgestatus",
        create_type=True,
    )
    knowledge_status_enum.create(op.get_bind(), checkfirst=True)
    knowledge_status_t = postgresql.ENUM(
        "draft",
        "published",
        name="knowledgestatus",
        create_type=False,
    )

    op.create_table(
        "knowledge_articles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=160), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("summary", sa.String(length=500), nullable=False, server_default=""),
        sa.Column("section", sa.String(length=80), nullable=False, server_default="general"),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("status", knowledge_status_t, nullable=False, server_default="draft"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("created_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("updated_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["updated_by_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug", name="uq_knowledge_articles_slug"),
    )
    op.create_index("ix_knowledge_articles_section", "knowledge_articles", ["section"])
    op.create_index("ix_knowledge_articles_status", "knowledge_articles", ["status"])

    bind = op.get_bind()
    for article in STARTER_ARTICLES:
        bind.execute(
            sa.text(
                """
                INSERT INTO knowledge_articles (
                    id, slug, title, summary, section, body, status, sort_order,
                    created_at, updated_at, published_at
                )
                VALUES (
                    :id, :slug, :title, :summary, :section, :body, 'published', :sort_order,
                    now(), now(), now()
                )
                ON CONFLICT (slug) DO NOTHING
                """
            ),
            article,
        )


def downgrade() -> None:
    op.drop_index("ix_knowledge_articles_status", table_name="knowledge_articles")
    op.drop_index("ix_knowledge_articles_section", table_name="knowledge_articles")
    op.drop_table("knowledge_articles")
    postgresql.ENUM(name="knowledgestatus").drop(op.get_bind(), checkfirst=True)
