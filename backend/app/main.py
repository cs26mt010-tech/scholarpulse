
"""
ScholarPulse FastAPI application entry point.
"""

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.db.session import get_db

from app.api.routes.auth import router as auth_router
from app.api.routes.resources import router as resources_router
from app.api.routes.community import router as community_router
from app.api.routes.collections import router as collections_router
from app.api.routes.ai import router as ai_router
from app.api.routes.moderation import router as moderation_router
from app.api.routes.frontend import router as frontend_router


app = FastAPI(
    title="ScholarPulse: AI-Enabled Academic Knowledge Hub API",
    version="1.0.0-ms3",
    description=(
        "Course Project 2026 | Theme 4: Knowledge Hub | "
        "Milestone 3 Backend & Database Stack"
    ),
    docs_url="/docs",
    redoc_url="/redoc",
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Register application routers
app.include_router(auth_router)
app.include_router(resources_router)
app.include_router(community_router)
app.include_router(collections_router)
app.include_router(ai_router)
app.include_router(moderation_router)
app.include_router(frontend_router)


@app.get("/api/v1/health")
def health_check():
    with get_db() as db:
        counts = {}

        for table in [
            "users",
            "categories",
            "resources",
            "resource_chunks",
            "tags",
            "resource_tags",
            "ratings",
            "comments",
            "collections",
            "collection_items",
            "reports",
            "ai_queries",
        ]:
            result = db.fetchone(
                f"SELECT COUNT(*) AS cnt FROM {table}"
            )
            counts[table] = result["cnt"] if result else 0

        version = db.fetchone(
            "SELECT version_num FROM alembic_version LIMIT 1"
        )

    return {
        "status": "ok",
        "service": "ScholarPulse Backend",
        "milestone": "MS-3",
        "database": "connected",
        "alembic_revision": (
            version["version_num"]
            if version
            else "0001_initial_schema"
        ),
        "counts": counts,
    }


@app.get("/api/v1/openapi.yaml")
def get_openapi_yaml():
    base_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )

    yaml_path = os.path.join(
        base_dir, "docs", "openapi.yaml"
    )

    if os.path.exists(yaml_path):
        return FileResponse(
            yaml_path,
            media_type="application/yaml",
        )

    raise HTTPException(
        status_code=404,
        detail="openapi.yaml not found",
    )
