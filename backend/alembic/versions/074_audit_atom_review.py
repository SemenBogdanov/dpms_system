"""Add sequential atom review support.

Revision ID: 074_audit_atom_review
Revises: 073_audit_workflow_polish
"""

from alembic import op
import sqlalchemy as sa


revision = "074_audit_atom_review"
down_revision = "073_audit_workflow_polish"
branch_labels = None
depends_on = None


ARTICLE = {
    "id": "b381c747-d1b5-4b65-8fcc-d2e441b0f506",
    "slug": "audit-sequential-atom-review",
    "title": "Аудит: быстрая проверка атомов",
    "summary": "Как последовательно принять черновики, исключить лишнее и провести альфа-проверку.",
    "section": "audit",
    "body": """Обновлено: 2026-08-24

## Проверка черновиков
После формирования генерального реестра откройте `Атомы` и нажмите `Проверить черновики`. DPMS показывает по одному атому: название, пункт ТЗ и текстовое основание. Положительное решение переводит атом в `Принят`, исключение оставляет его в реестре со статусом `Исключен`.

Для поточной проверки используйте `Пробел` или `Стрелку вправо`, чтобы принять атом и перейти дальше. `Стрелка вниз` исключает черновик, `E` открывает быстрое редактирование, `Стрелка влево` возвращает к предыдущему атому. Последнее сохраненное решение можно отменить прямо в окне проверки.

Каждое решение сначала сохраняется на сервере и только затем открывается следующий атом. Если атом уже изменил другой сотрудник, DPMS оставит текущий экран открытым и попросит обновить данные.

## Альфа-проверка
Когда черновиков не осталось, запустите `Альфа-проверку`. В ней проверяется уже не формулировка, а наличие принятого атома в реальной системе. Для каждого атома фиксируются результат, дата, комментарий и при необходимости ссылка.

`Пробел` или `Стрелка вправо` подтверждают наличие элемента. `Стрелка вниз` открывает отрицательное решение: `Нет в системе` или `Нужно уточнить`. Для такого решения комментарий обязателен. Отрицательный результат не исключает атом из реестра.

Если после запуска альфа-проверки меняется формулировка или состав атомов, аудит автоматически возвращается к этапу атомизации. Это защищает комиссию от проверки устаревшего реестра.
""",
}


def upgrade() -> None:
    op.add_column("audit_atoms", sa.Column("alpha_comment", sa.Text(), nullable=True))
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            INSERT INTO knowledge_articles (
                id, slug, title, summary, section, body, status, sort_order,
                created_at, updated_at, published_at
            )
            VALUES (
                :id, :slug, :title, :summary, :section, :body, 'published', 214,
                now(), now(), now()
            )
            ON CONFLICT (slug) DO NOTHING
            """
        ),
        ARTICLE,
    )


def downgrade() -> None:
    bind = op.get_bind()
    bind.execute(
        sa.text(
            """
            DELETE FROM knowledge_articles
            WHERE id = :id AND slug = :slug
            """
        ),
        {"id": ARTICLE["id"], "slug": ARTICLE["slug"]},
    )
    op.drop_column("audit_atoms", "alpha_comment")
