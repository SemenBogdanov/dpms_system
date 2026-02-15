"""Схемы аутентификации."""
from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import UserRead


class LoginRequest(BaseModel):
    """Запрос на вход."""
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    """Ответ с токеном и пользователем."""
    access_token: str
    token_type: str = "bearer"
    user: UserRead


class SetPasswordRequest(BaseModel):
    """Установка пароля (для пользователей с password_hash=NULL)."""
    new_password: str = Field(..., min_length=6)
