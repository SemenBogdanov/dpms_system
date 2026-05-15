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

Production управляется VPS-first release manager: source of truth — GitHub, а VPS сам
fetch/checkout/build/preflight делает на своей стороне. Локальная машина не собирает и не
копирует production-релиз.

Новый VPS bootstrap:

```bash
sudo bash deploy/dpms-node.sh bootstrap main
```

Bootstrap ставит host-зависимости, клонирует GitHub repo, готовит release и печатает
approval sheet. Runtime env остается вне git и должен существовать на VPS как
`/opt/dpms/deploy/.env.prod` или путь из `DPMS_ENV_FILE`. Скрипт не создает secret-файлы
из example и не печатает значения env.

Обычный update существующего VPS:

```bash
scripts/dpms-release.sh prepare main
```

Команда запускает `/opt/dpms-tools/dpms-node.sh prepare main` на VPS. VPS делает
`git fetch`, resolve exact commit SHA, build frontend/backend, DB connectivity check,
staging container check, migration delta и approval sheet. Production при этом не
переключается.

Production promote запускается отдельной командой из approval sheet:

```bash
scripts/dpms-release.sh promote <release-id> --approval <approval-phrase>
```

Если есть новые Alembic migrations, promote блокируется без внешнего DB backup id:

```bash
scripts/dpms-release.sh promote <release-id> --approval <approval-phrase> \
  --allow-migrations --backup-id <external-db-backup-id>
```

Rollback app/frontend/container state:

```bash
scripts/dpms-release.sh rollback /opt/dpms-backups/<backup-id>
```

Rollback не откатывает внешнюю production DB. Для migration releases отдельно нужен DB
rollback или forward-fix plan.

Operational safety note: do not run `docker compose config` on production output without
redaction; Compose expands `env_file` values into stdout. Use targeted
`docker inspect --format ...` queries or sanitized output instead.
