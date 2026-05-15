"""API базы знаний. Чтение требует JWT; редактирование доступно admin/teamlead."""
import re
from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_role
from app.models.knowledge import KnowledgeArticle, KnowledgeStatus
from app.models.user import User
from app.schemas.knowledge import (
    KnowledgeArticleCreate,
    KnowledgeArticleRead,
    KnowledgeArticleUpdate,
)

router = APIRouter()


def _can_manage(user: User) -> bool:
    return user.role.value in {"admin", "teamlead"}


def _normalize_slug(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-zА-Яа-яЁё]+", "-", value.strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:160] or "article"


def _required_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail=f"Поле {field_name} не может быть пустым")
    return cleaned


async def _ensure_unique_slug(
    db: AsyncSession,
    slug: str,
    current_id: UUID | None = None,
) -> None:
    stmt = select(KnowledgeArticle.id).where(KnowledgeArticle.slug == slug)
    if current_id is not None:
        stmt = stmt.where(KnowledgeArticle.id != current_id)
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Статья с таким slug уже существует",
        )


async def _get_article_by_id_or_404(db: AsyncSession, article_id: UUID) -> KnowledgeArticle:
    result = await db.execute(select(KnowledgeArticle).where(KnowledgeArticle.id == article_id))
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return article


@router.get("", response_model=list[KnowledgeArticleRead])
async def list_knowledge_articles(
    section: str | None = Query(None),
    status_filter: KnowledgeStatus | None = Query(None, alias="status"),
    search: str | None = Query(None),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Список статей базы знаний."""
    manager = _can_manage(user)
    stmt = select(KnowledgeArticle)
    if manager:
        if status_filter is not None:
            stmt = stmt.where(KnowledgeArticle.status == status_filter)
    else:
        stmt = stmt.where(KnowledgeArticle.status == KnowledgeStatus.published)
    if section and section.strip():
        stmt = stmt.where(KnowledgeArticle.section == section.strip())
    if search and search.strip():
        pattern = f"%{search.strip()}%"
        stmt = stmt.where(
            or_(
                KnowledgeArticle.title.ilike(pattern),
                KnowledgeArticle.summary.ilike(pattern),
                KnowledgeArticle.body.ilike(pattern),
            )
        )
    stmt = stmt.order_by(KnowledgeArticle.sort_order.asc(), KnowledgeArticle.title.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


@router.get("/{slug}", response_model=KnowledgeArticleRead)
async def get_knowledge_article(
    slug: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Одна статья базы знаний по slug."""
    result = await db.execute(select(KnowledgeArticle).where(KnowledgeArticle.slug == slug))
    article = result.scalar_one_or_none()
    if not article:
        raise HTTPException(status_code=404, detail="Статья не найдена")
    if article.status != KnowledgeStatus.published and not _can_manage(user):
        raise HTTPException(status_code=404, detail="Статья не найдена")
    return article


@router.post("", response_model=KnowledgeArticleRead)
async def create_knowledge_article(
    body: KnowledgeArticleCreate,
    user: User = Depends(require_role("admin", "teamlead")),
    db: AsyncSession = Depends(get_db),
):
    """Создать статью базы знаний."""
    slug = _normalize_slug(body.slug or body.title)
    await _ensure_unique_slug(db, slug)
    now = datetime.now(timezone.utc)
    article = KnowledgeArticle(
        slug=slug,
        title=_required_text(body.title, "title"),
        summary=body.summary.strip(),
        section=body.section.strip() or "general",
        body=_required_text(body.body, "body"),
        status=body.status,
        sort_order=body.sort_order,
        created_by_id=user.id,
        updated_by_id=user.id,
        published_at=now if body.status == KnowledgeStatus.published else None,
    )
    db.add(article)
    await db.flush()
    await db.refresh(article)
    return article


@router.patch("/{article_id}", response_model=KnowledgeArticleRead)
async def update_knowledge_article(
    article_id: UUID,
    body: KnowledgeArticleUpdate,
    user: User = Depends(require_role("admin", "teamlead")),
    db: AsyncSession = Depends(get_db),
):
    """Частично обновить статью базы знаний."""
    article = await _get_article_by_id_or_404(db, article_id)
    if body.slug is not None:
        slug = _normalize_slug(body.slug)
        await _ensure_unique_slug(db, slug, current_id=article.id)
        article.slug = slug
    if body.title is not None:
        article.title = _required_text(body.title, "title")
    if body.summary is not None:
        article.summary = body.summary.strip()
    if body.section is not None:
        article.section = body.section.strip() or "general"
    if body.body is not None:
        article.body = _required_text(body.body, "body")
    if body.sort_order is not None:
        article.sort_order = body.sort_order
    if body.status is not None and body.status != article.status:
        article.status = body.status
        if body.status == KnowledgeStatus.published and article.published_at is None:
            article.published_at = datetime.now(timezone.utc)
    article.updated_by_id = user.id
    await db.flush()
    await db.refresh(article)
    return article
