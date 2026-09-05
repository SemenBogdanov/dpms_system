"""Document the default start screen and personal workspace layout.

Revision ID: 078_start_menu_knowledge_layout
Revises: 077_user_storage_quota
"""

from alembic import op
import sqlalchemy as sa


revision = "078_start_menu_knowledge_layout"
down_revision = "077_user_storage_quota"
branch_labels = None
depends_on = None


ARTICLE = {
    "id": "fe4b5111-df61-4905-90c0-ceeeff8a8f08",
    "slug": "soobshcheniya-perenos-menyu-i-chtenie-bazy-znanij",
    "title": "Сообщения, перенос меню и чтение базы знаний",
    "summary": "Как устроен первый экран, как перенести свое меню и настроить ширину списка статей.",
    "section": "start",
    "body": """Обновлено: 2026-09-03

## Первый экран

После входа система открывает раздел «Сообщения». Здесь собраны адресные обращения и важные рабочие события. Остальные разделы остаются доступны через личное меню.

## Экспорт меню

Откройте «Настройки» и найдите блок «Меню». Команда «Экспорт» сохраняет JSON-файл с текущим порядком кнопок, составом разделов и личными названиями. Файл не содержит пароль или данные рабочих сущностей.

## Импорт меню

Команда «Импортировать» загружает конфигурацию в черновик. Система пропускает неизвестные разделы и разделы, к которым администратор не предоставил доступ. «Сообщения» остаются обязательным системным разделом и при необходимости добавляются автоматически.

Перед применением показывается результат фильтрации. Проверьте расположение кнопок и нажмите «Сохранить». До сохранения профиль пользователя не изменяется.

## Область чтения

На широком экране границу между списком статей и текстом можно перетаскивать мышью. Когда разделитель выбран с клавиатуры, используйте стрелки влево и вправо; двойное нажатие мышью возвращает стандартную ширину. Выбранная ширина сохраняется в текущем браузере. На телефоне список и статья располагаются последовательно.
""",
}


def upgrade() -> None:
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO knowledge_articles (
                id, slug, title, summary, section, body, status, sort_order,
                created_at, updated_at, published_at
            )
            VALUES (
                CAST(:id AS uuid), :slug, :title, :summary, :section, :body,
                'published', 15, now(), now(), now()
            )
            ON CONFLICT (slug) DO UPDATE SET
                title = EXCLUDED.title,
                summary = EXCLUDED.summary,
                section = EXCLUDED.section,
                body = EXCLUDED.body,
                status = 'published',
                sort_order = EXCLUDED.sort_order,
                updated_at = now(),
                published_at = COALESCE(knowledge_articles.published_at, now())
            WHERE knowledge_articles.id = EXCLUDED.id
            """
        ),
        ARTICLE,
    )


def downgrade() -> None:
    op.get_bind().execute(
        sa.text(
            "DELETE FROM knowledge_articles WHERE id = CAST(:id AS uuid) AND slug = :slug"
        ),
        {"id": ARTICLE["id"], "slug": ARTICLE["slug"]},
    )
