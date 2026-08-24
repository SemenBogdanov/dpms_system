"""Document attachments and guarded audit case deletion guidance.

Revision ID: 069_audit_case_materials
Revises: 068_audit_tz_runtime
"""

from alembic import op
import sqlalchemy as sa


revision = "069_audit_case_materials"
down_revision = "068_audit_tz_runtime"
branch_labels = None
depends_on = None


ARTICLE_APPENDIX = """

## Дополнительные материалы договора
Во вкладке `Материалы` нажмите `Добавить документ`. Файл добавляется в уже выбранный договор и не создает вторую карточку. Перед загрузкой выберите категорию: техническое задание, реестр атомов, результат аудита, протокол или другой материал. PDF, DOCX и XLSX сохраняются как неизменяемые версии; одинаковый файл нельзя повторно прикрепить к тому же договору.

## Если preflight не подтвердил договор
Код `BLOCKED_SOURCE_ID_UNCONFIRMED` означает, что система не нашла надежный признак принадлежности DOCX указанному договору. Свободного упоминания номера внутри текста недостаточно. Проверьте полный номер и выполните одно из действий:

1. добавьте точный номер договора в имя DOCX;
2. либо разместите на титульной странице отдельную строку `Договор № ...`;
3. загрузите исправленный DOCX в `Материалы` как новую версию и повторите preflight.

Identity gate нельзя обходить приблизительным номером: это защита от атомизации чужого ТЗ.

## Удаление ошибочно загруженного договора
Рабочую карточку нельзя удалить сразу. Сначала откройте `Редактировать договор` и переведите ее в `Архив`. После этого в панели управления появится `Удалить договор`. Для окончательного удаления нужно ввести код вида `AUD-0001`. Удаляются карточка, документы, атомы и связанная история; в системном журнале остается обезличенный факт удаления. Активная проверка или атомизация временно блокирует удаление.
"""


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET body = CASE
                    WHEN strpos(body, :appendix) = 0 THEN body || :appendix
                    ELSE body
                END,
                summary = 'Как вести реестр аудита, добавлять материалы, проверять привязку ТЗ и безопасно удалять ошибочные карточки.',
                updated_at = now()
            WHERE slug = 'audit-workspace-registry-team-documents'
            """
        ).bindparams(appendix=ARTICLE_APPENDIX)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE knowledge_articles
            SET body = replace(body, :appendix, ''),
                summary = 'Как создать карточку договора, назначить ответственного и загрузить реестр атомов именно в выбранный аудит.',
                updated_at = now()
            WHERE slug = 'audit-workspace-registry-team-documents'
            """
        ).bindparams(appendix=ARTICLE_APPENDIX)
    )
