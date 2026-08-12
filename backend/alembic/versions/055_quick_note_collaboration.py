"""Add quick note realtime collaboration (revision guard) and KB article.

Revision ID: 055_quick_note_collaboration
Revises: 054_personal_task_artifacts
"""
from alembic import op
import sqlalchemy as sa


revision = "055_quick_note_collaboration"
down_revision = "054_personal_task_artifacts"
branch_labels = None
depends_on = None


ARTICLE_ID = "7d8c2e1a-3f5b-4d6a-9c7e-1b2c3d4e5f60"
ARTICLE_SLUG = "sovmestnaya-rabota-i-realtime-v-zametkah"
ARTICLE_BODY = """# Совместная работа и realtime в заметках

## Кто что может

Заметка принадлежит одному сотруднику — её **создателю**. Только создатель
изменяет содержимое заметки: заголовок, текст, контекст и теги. Статус заметки,
загрузку вложений, доступ, связи с проектами и удаление настраивает тоже только
создатель.

Пользователи, которым заметка **открыта**, получают доступ только на чтение и
комментирование в панели **Обсуждение**. Изменять текст заметки или её тегов
они не могут.

## Ревизии и защита от конфликтов

Каждое изменение заметки увеличивает числовую **ревизию** на
единицу. При сохранении редактор отправляет ревизию, на основе которой работал.
Если за это время создатель уже сохранил новую версию в другой вкладке или на
другом устройстве, сервер отклоняет изменение с ошибкой **409** и просит
загрузить актуальную версию.

Это защищает от потери правок, когда создатель правит заметку с
нескольких вкладок или устройств одновременно.

## Обновления без перезагрузки страницы

Пока заметка открыта, сохранённая правка создателя, новый комментарий, файл или
изменение доступа появляются у участников автоматически. Индикатор в верхней
части заметки показывает, работает ли живая синхронизация. Если соединение
прервалось, система переподключается и повторно загружает актуальные данные.

## Отзыв доступа

Если создатель закрывает доступ, пользователь, потерявший доступ, получает
событие об отзыве, после чего его realtime-соединение по этой заметке
закрывается.
"""


def upgrade() -> None:
    op.add_column(
        "quick_notes",
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )
    op.create_check_constraint(
        "ck_quick_notes_revision_positive",
        "quick_notes",
        "revision >= 1",
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
                :title,
                :summary,
                :section,
                :body,
                'published',
                42,
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
            WHERE knowledge_articles.id = CAST(:article_id AS uuid)
            """
        ).bindparams(
            article_id=ARTICLE_ID,
            slug=ARTICLE_SLUG,
            title="Совместная работа и realtime в заметках",
            summary="Кто редактирует заметку, защита ревизий от конфликтов и realtime события.",
            section="tasks",
            body=ARTICLE_BODY,
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM knowledge_articles WHERE id = CAST(:article_id AS uuid)"
        ).bindparams(article_id=ARTICLE_ID)
    )

    op.drop_constraint("ck_quick_notes_revision_positive", "quick_notes", type_="check")
    op.drop_column("quick_notes", "revision")
