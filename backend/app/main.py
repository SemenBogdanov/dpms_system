"""FastAPI приложение DPMS: CORS, lifespan, роуты."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.api.routes import users, catalog, calculator, tasks, queue, dashboard, shop, admin, auth, notifications, reports


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Жизненный цикл приложения (при необходимости — инициализация)."""
    yield
    # shutdown при необходимости


app = FastAPI(
    title=settings.APP_TITLE,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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
