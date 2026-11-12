#!/usr/bin/env bash
set -e

echo "============================================================"
echo "ScholarPulse MS-3 Container Entrypoint"
echo "============================================================"

cd /app/backend

echo "[0/3] Checking alembic_version table for duplicate rows (self-heal)..."
python3 - <<'PY'
import os
from sqlalchemy import create_engine, text
try:
    eng = create_engine(os.environ["DATABASE_URL"])
    with eng.begin() as c:
        rows = [r[0] for r in c.execute(text("SELECT version_num FROM alembic_version"))]
        if len(rows) > 1:
            keep = "0002_profile_settings" if "0002_profile_settings" in rows else sorted(rows)[-1]
            c.execute(text("DELETE FROM alembic_version WHERE version_num <> :k"), {"k": keep})
            print("Fixed duplicate alembic_version rows:", rows, "->", keep)
        else:
            print("alembic_version OK:", rows)
except Exception as ex:
    print("alembic_version check skipped:", ex)
PY

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
