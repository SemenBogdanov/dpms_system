FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
ENV PYTHONPATH=/app

# Не запускаем приложение поверх схемы, которую не удалось обновить.
CMD ["sh", "-c", "set -e; alembic upgrade head; python -m app.seed || true; exec uvicorn app.main:app --host 0.0.0.0 --port 8000"]
