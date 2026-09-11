"""Read-only release verification; prints aggregate checks, never user content."""
import asyncio
import json

from sqlalchemy import text

from app.database import engine


async def main():
    async with engine.connect() as db:
        await db.execute(text("SET TRANSACTION READ ONLY"))
        revision = await db.scalar(text("SELECT version_num FROM alembic_version"))
        article_count = await db.scalar(text("""
            SELECT count(*) FROM knowledge_articles WHERE status = 'published' AND slug IN (
                'soobshcheniya-perenos-menyu-i-chtenie-bazy-znanij',
                'trekery-gruppy-povtoreniya-napominaniya',
                'lichnye-gruppy-zametok-i-kontekst',
                'lichnaya-zadacha-bystroe-sozdanie',
                'audit-proverka-istoricheskogo-xlsx',
                'audit-metodiki-i-istochniki-atomov'
            )
        """))
        transfer_guide_ready = await db.scalar(text("""
            SELECT EXISTS (
                SELECT 1 FROM knowledge_articles
                WHERE slug = 'audit-proverka-istoricheskogo-xlsx'
                  AND status = 'published'
                  AND title = 'Аудит: проверка и перенос исторического XLSX'
                  AND body LIKE '%## Предварительный просмотр%'
                  AND body LIKE '%## Отмена%'
            )
        """))
        invalid_note_groups = await db.scalar(text("""
            SELECT count(*) FROM quick_notes n JOIN note_groups g ON g.id = n.group_id
            WHERE n.owner_id <> g.owner_id
        """))
        invalid_tracker_groups = await db.scalar(text("""
            SELECT count(*) FROM deadline_trackers t
            LEFT JOIN deadline_tracker_groups g ON g.id = t.group_id
            LEFT JOIN deadline_tracker_categories c ON c.id = t.category_id
            WHERE t.owner_id <> g.owner_id OR t.owner_id <> c.owner_id
        """))
        invalid_series = await db.scalar(text("""
            SELECT count(*) FROM deadline_trackers WHERE recurrence IS NOT NULL
            AND (personal_task_id IS NOT NULL OR linked_task_id IS NOT NULL)
        """))
        checks = {
            "migration_head": revision == "086_audit_skills_registry_guide",
            "knowledge_articles": article_count == 6,
            "legacy_transfer_guide": bool(transfer_guide_ready),
            "note_group_owner_isolation": invalid_note_groups == 0,
            "tracker_organization_owner_isolation": invalid_tracker_groups == 0,
            "linked_trackers_one_time": invalid_series == 0,
        }
        print(json.dumps({"checks": checks, "status": "ok" if all(checks.values()) else "failed"}))
        if not all(checks.values()):
            raise SystemExit(1)
    await engine.dispose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except Exception as exc:
        print(json.dumps({"status": "failed", "error_type": type(exc).__name__}))
        raise SystemExit(1) from None
