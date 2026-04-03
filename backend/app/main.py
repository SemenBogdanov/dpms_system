"""FastAPI приложение DPMS: CORS, lifespan, роуты, rate limiting."""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from app.config import settings
from app.api.routes import users, catalog, calculator, tasks, queue, dashboard, shop, admin, auth, notifications, reports


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Жизненный цикл приложения (при необходимости — инициализация)."""
    yield
    # shutdown при необходимости


limiter = Limiter(key_func=get_remote_address)

app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": "Слишком много попыток. Подождите минуту."},
    )


import os
_cors_origins = os.getenv("CORS_ORIGINS", "*").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Роуты
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(notifications.router, prefix="/api/notifications", tags=["notifications"])
app.include_router(users.router, prefix="/api/users", tags=["users"])
app.include_router(catalog.router, prefix="/api/catalog", tags=["catalog"])
app.include_router(calculator.router, prefix="/api/calculator", tags=["calculator"])
app.include_router(tasks.router, prefix="/api/tasks", tags=["tasks"])
app.include_router(queue.router, prefix="/api/queue", tags=["queue"])
app.include_router(dashboard.router, prefix="/api/dashboard", tags=["dashboard"])
app.include_router(shop.router, prefix="/api/shop", tags=["shop"])
app.include_router(admin.router, prefix="/api/admin", tags=["admin"])
app.include_router(reports.router, prefix="/api/reports", tags=["reports"])


@app.get("/health")
async def health():
    """Проверка доступности API."""
    return {"status": "ok"}
