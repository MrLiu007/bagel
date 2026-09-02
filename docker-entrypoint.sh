#!/bin/sh
# Container entrypoint for Bagel.
set -eu
mkdir -p /app/data

DB_URL="${DATABASE_URL:-}"
case "$DB_URL" in
  postgresql*|postgres*)
    echo "Running alembic upgrade (Postgres)…"
    uv run alembic upgrade head
    ;;
  *)
    # SQLite / empty: Alembic 0001 uses JSONB — rely on app lifespan create_all.
    echo "Skipping alembic (non-Postgres URL); schema via init_db on startup."
    ;;
esac

exec uv run uvicorn bagel.main:app --host 0.0.0.0 --port 8000
