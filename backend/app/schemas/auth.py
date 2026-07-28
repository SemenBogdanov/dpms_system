"""Схемы аутентификации."""
from pydantic import BaseModel, EmailStr, Field

from app.schemas.user import AuthenticatedUserRead


class LoginRequest(BaseModel):
    """Запрос на вход."""
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    """Ответ с токеном и пользователем."""
    access_token: str
    token_type: str = "bearer"
    user: AuthenticatedUserRead


class SetPasswordRequest(BaseModel):
    """Замена выданного администратором временного пароля."""
    new_password: str = Field(..., min_length=8, max_length=128)


class ChangePasswordRequest(BaseModel):
    """Смена пароля (для пользователей с установленным паролем)."""
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)
