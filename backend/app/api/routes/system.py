"""System API routes."""
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from app.db.session import get_db

router = APIRouter()

@router.get('/api/v1/health')
def health_check():
    with get_db() as db:
        # Schema lifecycle belongs to Alembic migrations, never to a request handler.
        counts = {}
        for tbl in ["users", "categories", "resources", "resource_chunks", "tags", "resource_tags", "ratings", "comments", "collections", "collection_items", "reports", "ai_queries"]:
            r = db.fetchone(f"SELECT COUNT(*) AS cnt FROM {tbl}")
            counts[tbl] = r["cnt"] if r else 0
        ver = db.fetchone("SELECT version_num FROM alembic_version LIMIT 1")
    return {
        "status": "ok",
        "service": "ScholarPulse Backend",
        "milestone": "MS-3",
        "database": "connected",
        "alembic_revision": ver["version_num"] if ver else "0001_initial_schema",
        "counts": counts,
    }

@router.get('/api/v1/openapi.yaml')
def get_openapi_yaml():
    base_dir = str(Path(__file__).resolve().parents[4])
    yaml_path = os.path.join(base_dir, "docs", "openapi.yaml")
    if os.path.exists(yaml_path):
        return FileResponse(yaml_path, media_type="application/yaml")
    raise HTTPException(status_code=404, detail="openapi.yaml not found")
