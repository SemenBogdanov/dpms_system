# DPMS — Digital Production Management System

Внутренний инструмент управления производительностью дата-офиса. Нормативная оценка в **Квантах (Q)** вместо экспертной оценки в человеко-часах.

## Стек

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic v2, PostgreSQL
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS

## Быстрый старт (Docker)

```bash
cp .env.example .env
docker-compose up --build
```

- API: http://localhost:8000  
- Документация: http://localhost:8000/docs  
- Frontend: http://localhost:5173  

При первом запуске backend выполняет миграции и seed (тестовые пользователи, каталог, задачи).

## Локальный запуск без Docker

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate   # или .venv\Scripts\activate на Windows
pip install -r requirements.txt
```

Поднять PostgreSQL (например через Docker: `docker run -d -p 5432:5432 -e POSTGRES_DB=dpms -e POSTGRES_USER=dpms_user -e POSTGRES_PASSWORD=dpms_pass postgres:16-alpine`).

```bash
export DATABASE_URL=postgresql+asyncpg://dpms_user:dpms_pass@localhost:5432/dpms
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload --port 8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Укажите `VITE_API_URL=http://localhost:8000` в `.env` если API на другом хосте.

## Структура

- `backend/app/` — FastAPI приложение: модели, схемы, API, сервисы, seed
- `backend/alembic/` — миграции
- `frontend/src/` — React: страницы, компоненты, API-клиент

## MVP (Фаза 1)

- Нет авторизации: в запросах передаётся `user_id` (query/body).
- CRUD пользователей, каталога, задач; калькулятор оценки; очередь (pull/submit/validate); дашборд (Стакан, план/факт).


## Production deploy

Production на VPS разворачивается artifact-based, без `git pull` в `/opt/dpms` и без переноса runtime `.env.prod` в git/release tar. Release создается только из committed git files через `git archive HEAD`; сверху добавляется свежий `frontend/dist`.

Обычный безопасный цикл из проектной сессии:

```bash
scripts/dpms-release.sh
```

Скрипт требует clean working tree, собирает `frontend/dist`, создает release tar без `.env*`, секретных имен, `.git`, `node_modules` и runtime-файлов, загружает его на VPS, запускает stage и preflight. Production deploy по умолчанию не выполняется.

Production deploy запускается только после review preflight:

```bash
scripts/dpms-release.sh --deploy
```

Если preflight показывает новые Alembic migrations, сначала нужен проверенный backup внешней production DB и явное approval. Миграции запускает VPS deploy tool отдельным шагом; backend image не запускает Alembic из container `CMD`.

```bash
scripts/dpms-release.sh --deploy --allow-migrations
```

Rollback на VPS:

```bash
/opt/dpms-tools/dpms-rollback.sh /opt/dpms-backups/<backup-id>
```

Rollback восстанавливает app/frontend/container image state. Для migration releases отдельно оценивай DB rollback или forward-fix, потому что application rollback не откатывает внешнюю production DB автоматически.

Operational safety note: do not run `docker compose config` on production output without redaction; Compose expands `env_file` values into stdout. Use targeted `docker inspect --format ...` queries or sanitized output instead.
