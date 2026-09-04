"""First-run bootstrap without bundled credentials."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.core.security import create_access_token, get_password_hash, validate_password_strength
from app.models.competency import Competency, CompetencyQuestion
from app.models.user import League, User, UserRole
from app.schemas.auth import TokenResponse
from app.schemas.user import AuthenticatedUserRead, SetupAdminRequest, SetupStatus


router = APIRouter()


def user_read(user: User) -> AuthenticatedUserRead:
    return AuthenticatedUserRead.model_validate(user)


@router.get("/status", response_model=SetupStatus)
async def setup_status(db: AsyncSession = Depends(get_db)):
    users = int((await db.execute(select(func.count(User.id)))).scalar_one())
    competencies = int((await db.execute(select(func.count(Competency.id)))).scalar_one())
    questions = int((await db.execute(select(func.count(CompetencyQuestion.id)))).scalar_one())
    return SetupStatus(
        setup_required=users == 0,
        catalog_competencies=competencies,
        catalog_questions=questions,
    )


@router.post("/admin", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def create_first_admin(body: SetupAdminRequest, db: AsyncSession = Depends(get_db)):
    # Serialize the one-time bootstrap check on SQLite so two first requests
    # cannot create independent administrators.
    await db.execute(text("BEGIN IMMEDIATE"))
    users = int((await db.execute(select(func.count(User.id)))).scalar_one())
    if users:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Первичная настройка уже завершена")
    password_errors = validate_password_strength(body.password)
    if password_errors:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=password_errors)
    admin = User(
        full_name=body.full_name.strip(),
        email=str(body.email).strip().lower(),
        password_hash=get_password_hash(body.password),
        role=UserRole.admin,
        league=League.A,
        competency_development_enabled=True,
        competency_constructor_enabled=True,
        is_active=True,
    )
    db.add(admin)
    await db.flush()
    return TokenResponse(
        access_token=create_access_token(admin.id, admin.auth_version),
        user=user_read(admin),
    )
