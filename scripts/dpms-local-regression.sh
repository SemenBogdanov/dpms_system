#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="${1:-full}"
PROJECT_NAME="${COMPOSE_PROJECT_NAME:-dpms-local}"

if [[ "$PROJECT_NAME" != "dpms-local" ]]; then
  echo "Regression refuses Compose project '$PROJECT_NAME'; use dpms-local." >&2
  exit 2
fi

if [[ "$PROFILE" != "quick" && "$PROFILE" != "full" ]]; then
  echo "Usage: $0 [quick|full]" >&2
  exit 2
fi

export COMPOSE_PROJECT_NAME="$PROJECT_NAME"
export DPMS_FRONTEND_PORT="${DPMS_FRONTEND_PORT:-5177}"
export DPMS_BACKEND_PORT="${DPMS_BACKEND_PORT:-8004}"
export DPMS_DB_PORT="${DPMS_DB_PORT:-5436}"

compose=(docker compose -p "$PROJECT_NAME")

step() {
  printf '\n==> %s\n' "$1"
}

run_backend_smoke() {
  local script="$1"
  shift
  step "backend/$script"
  "${compose[@]}" exec -T backend python "scripts/$script" "$@"
}

cd "$ROOT_DIR"

step "Build and start canonical local stack"
"${compose[@]}" up -d --build

step "Container health and migration head"
health_url="http://127.0.0.1:${DPMS_BACKEND_PORT}/health"
backend_ready=0
for attempt in $(seq 1 60); do
  if curl --fail --silent --show-error "$health_url" >/dev/null 2>&1; then
    backend_ready=1
    break
  fi
  sleep 1
done
if [[ "$backend_ready" != "1" ]]; then
  "${compose[@]}" ps >&2
  "${compose[@]}" logs --tail=120 backend >&2
  echo "Backend did not become healthy within 60 seconds." >&2
  exit 1
fi
"${compose[@]}" ps
curl --fail --silent --show-error "$health_url"
"${compose[@]}" exec -T backend alembic current
"${compose[@]}" exec -T backend alembic heads

step "Python syntax"
"${compose[@]}" exec -T backend python -m compileall -q app alembic scripts

step "Backend unit tests"
"${compose[@]}" exec -T backend python -m unittest discover -s tests -p 'test_*.py'

run_backend_smoke smoke_messages.py --allow-compose-db
run_backend_smoke smoke_email_outbox.py
run_backend_smoke smoke_auth_session.py
run_backend_smoke smoke_admin_user_audit.py
run_backend_smoke smoke_personal_task_execution_guard.py
run_backend_smoke smoke_personal_task_artifacts.py
run_backend_smoke smoke_storage_quota.py
run_backend_smoke smoke_task_acceptance.py
run_backend_smoke smoke_execution_contracts.py
run_backend_smoke smoke_work_entities.py
run_backend_smoke smoke_work_entity_workspace.py
run_backend_smoke smoke_project_cockpit.py
run_backend_smoke smoke_quick_note_collaboration.py

if [[ "$PROFILE" == "full" ]]; then
  step "Migration upgrade/downgrade contract"
  "${compose[@]}" exec -T \
    -e DPMS_MIGRATION_SMOKE_ALLOW_CREATE_DATABASE=1 \
    backend python scripts/smoke_work_entity_migrations.py
fi

step "Frontend dependencies"
if [[ ! -d frontend/node_modules ]]; then
  npm --prefix frontend ci
fi

step "Frontend lint, navigation inventory, mobile readiness, and build"
npm --prefix frontend run lint
npm --prefix frontend run build

if [[ "$PROFILE" == "full" ]]; then
  step "Messages browser matrix"
  npm --prefix frontend run test:messages

  step "Realtime notes browser matrix"
  npm --prefix frontend run test:realtime-notes

  step "Mobile WebKit and Chromium matrix"
  npm --prefix frontend run test:mobile

  step "Execution and draft-safety browser matrix"
  npm --prefix frontend run test:ux-safety
fi

step "Working tree whitespace check"
git diff --check

printf '\nDPMS local regression (%s) OK on frontend %s, backend %s, database %s.\n' \
  "$PROFILE" "$DPMS_FRONTEND_PORT" "$DPMS_BACKEND_PORT" "$DPMS_DB_PORT"
