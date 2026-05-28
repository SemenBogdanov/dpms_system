"""Feedback/change request API."""
from uuid import UUID

from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db, require_role
from app.models.feedback import FeedbackCategory, FeedbackStatus
from app.models.user import User
from app.schemas.feedback import FeedbackRequestCreate, FeedbackRequestListResponse, FeedbackRequestRead, FeedbackRequestUpdate
from app.services.feedback import create_feedback_request, get_feedback_request, list_feedback_requests, update_feedback_request

router = APIRouter()


@router.get("", response_model=FeedbackRequestListResponse)
async def list_feedback(
    status_filter: FeedbackStatus | None = Query(None, alias="status"),
    category: FeedbackCategory | None = Query(None),
    author_id: UUID | None = Query(None),
    reviewer_id: UUID | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List feedback requests. Executors see only their own requests."""
    return await list_feedback_requests(
        db,
        user,
        status_filter=status_filter,
        category=category,
        author_id=author_id,
        reviewer_id=reviewer_id,
        limit=limit,
    )


@router.post("", response_model=FeedbackRequestRead, status_code=status.HTTP_201_CREATED)
async def create_feedback(
    body: FeedbackRequestCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a feedback/change request."""
    return await create_feedback_request(db, user, body)


@router.get("/{feedback_id}", response_model=FeedbackRequestRead)
async def get_feedback(
    feedback_id: UUID,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get one feedback request."""
    return await get_feedback_request(db, user, feedback_id)


@router.patch("/{feedback_id}", response_model=FeedbackRequestRead)
async def update_feedback(
    feedback_id: UUID,
    body: FeedbackRequestUpdate,
    user: User = Depends(require_role("admin", "teamlead")),
    db: AsyncSession = Depends(get_db),
):
    """Manager update: status, reviewer, priority, resolution."""
    return await update_feedback_request(db, user, feedback_id, body)
