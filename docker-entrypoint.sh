#!/bin/sh
# Container entrypoint for Bagel.
set -eu
mkdir -p /app/data

DB_URL="${DATABASE_URL:-}"
case "$DB_URL" in
  postgresql*|postgres*)
    echo "Running alembic upgrade (Postgres)…"
    if ! uv run alembic upgrade head; then
      echo "WARN: alembic upgrade failed; applying create_all safety net for missing tables…"
      uv run python -c "from bagel.storage.database import ensure_schema; ensure_schema()"
      echo "Retrying alembic upgrade…"
      uv run alembic upgrade head
    fi
    # Idempotent: fill any ORM tables still missing after migrations.
    uv run python -c "from bagel.storage.database import ensure_schema; ensure_schema()"
    ;;
  *)
    # SQLite / empty: Alembic 0001 uses JSONB — rely on app lifespan create_all.
    echo "Skipping alembic (non-Postgres URL); schema via init_db on startup."
    ;;
esac

exec uv run uvicorn bagel.main:app --host 0.0.0.0 --port 8000
