#!/usr/bin/env bash
set -e

echo "============================================================"
echo "ScholarPulse MS-3 Container Entrypoint"
echo "============================================================"

cd /app/backend

echo "[1/3] Running Alembic database migrations (alembic upgrade head)..."
alembic upgrade head

if [ "${AUTO_SEED_ON_STARTUP:-true}" = "true" ]; then
    echo "[2/3] Running idempotent database seed script (scripts/seed_db.py)..."
    python3 /app/scripts/seed_db.py
else
    echo "[2/3] Skipping auto-seed (AUTO_SEED_ON_STARTUP=${AUTO_SEED_ON_STARTUP})."
fi

echo "[3/3] Starting FastAPI server on 0.0.0.0:8000..."
exec uvicorn app.main:app --host 0.0.0.0 --port 8000
