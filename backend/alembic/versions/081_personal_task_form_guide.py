"""Document the personal task editor without changing task data."""

from alembic import op
import sqlalchemy as sa

revision = "081_personal_task_form_guide"
down_revision = "080_note_groups"
branch_labels = None
depends_on = None

ARTICLE = {
    "id": "4e54a5a6-d2b8-45fb-a4b9-70a1d27d8c77",
    "slug": "lichnaya-zadacha-bystroe-sozdanie",
    "title": "Личная задача: создание и дополнительные параметры",
    "summary": "Основные поля, дополнительные настройки и сохранение черновика при заполнении задачи.",
    "body": """## Создание задачи

Откройте «Личные задачи» и нажмите «Новая задача». Заполните название, следующий шаг и срок. Новая задача попадает во «Входящие». На компьютере форма открывается сбоку, на телефоне занимает экран.

## Дополнительные поля

В блоке «Дополнительно» доступны дата начала, приоритет, проект или контекст, критерии и другие параметры задачи. Их можно заполнить сразу или вернуться к ним при редактировании.

Статусы «Ожидание» и «Блокировка» требуют пояснения: кого или чего ожидаете, либо что препятствует выполнению. Эти поля появляются для соответствующего статуса.

## Сохранение и ошибки

Клик снаружи формы и Escape не стирают введенные данные. При закрытии заполненной формы нужно подтвердить отказ от несохраненных изменений. Если сохранение завершилось ошибкой, введенные значения остаются в форме; исправьте указанное поле и повторите отправку.

## Приватность

Личная задача остается приватной. Связь с проектом, целью или заметками сама по себе не передает задачу другому исполнителю. Публикация в глобальную очередь выполняется отдельным действием с оценкой в Q и подтверждением.
""",
}


def upgrade() -> None:
    op.get_bind().execute(sa.text("""
        INSERT INTO knowledge_articles (
            id, slug, title, summary, body, section, status, sort_order,
            created_at, updated_at, published_at
        ) VALUES (
            CAST(:id AS uuid), :slug, :title, :summary, :body, 'tasks', 'published', 36,
            now(), now(), now()
        ) ON CONFLICT (slug) DO UPDATE SET
            title = EXCLUDED.title, summary = EXCLUDED.summary, body = EXCLUDED.body,
            status = 'published', updated_at = now()
        WHERE knowledge_articles.id = EXCLUDED.id
    """), ARTICLE)


def downgrade() -> None:
    op.get_bind().execute(sa.text(
        "DELETE FROM knowledge_articles WHERE id = CAST(:id AS uuid) AND slug = :slug"
    ), {"id": ARTICLE["id"], "slug": ARTICLE["slug"]})
