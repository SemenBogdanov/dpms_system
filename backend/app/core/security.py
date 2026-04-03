"""
JWT-утилиты и хеширование паролей.

SECRET_KEY из DPMS_SECRET_KEY, ALGORITHM HS256, ACCESS_TOKEN_EXPIRE_MINUTES 480.
"""
import re
from datetime import datetime, timedelta, timezone

from jose import jwt, JWTError
from passlib.context import CryptContext

from app.config import settings

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM = "HS256"


def verify_password(plain: str, hashed: str) -> bool:
    """Проверить пароль против хеша."""
    return pwd_context.verify(plain, hashed)


def get_password_hash(password: str) -> str:
    """Получить bcrypt-хеш пароля."""
    return pwd_context.hash(password)


def validate_password_strength(password: str) -> list[str]:
    """Проверить надежность пароля. Возвращает список ошибок (пусто если валиден)."""
    errors = []
    
    if len(password) < 8:
        errors.append("Пароль должен содержать минимум 8 символов")
    
    if not re.search(r"[A-Z]", password):
        errors.append("Пароль должен содержать хотя бы одну заглавную букву (A-Z)")
    
    if not re.search(r"[a-z]", password):
        errors.append("Пароль должен содержать хотя бы одну строчную букву (a-z)")
    
    if not re.search(r"[0-9]", password):
        errors.append("Пароль должен содержать хотя бы одну цифру (0-9)")
    
    return errors


def create_access_token(data: dict, expires_delta: timedelta | None = None) -> str:
    """Создать JWT. data должен содержать sub (user_id)."""
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode["exp"] = expire
    return jwt.encode(to_encode, settings.DPMS_SECRET_KEY, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict | None:
    """Декодировать JWT. Возвращает payload или None при ошибке."""
    try:
        return jwt.decode(
            token,
            settings.DPMS_SECRET_KEY,
            algorithms=[ALGORITHM],
        )
    except JWTError:
        return None
