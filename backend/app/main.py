"""ScholarPulse FastAPI application entry point."""

import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.api.routes.ai import router as ai_router
from app.api.routes.auth import router as auth_router
from app.api.routes.collections import router as collections_router
from app.api.routes.community import router as community_router
from app.api.routes.frontend import router as frontend_router
from app.api.routes.moderation import router as moderation_router
from app.api.routes.resources import router as resources_router
from app.api.routes.system import router as system_router

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
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

for route_router in (
    system_router,
    auth_router,
    resources_router,
    community_router,
    collections_router,
    ai_router,
    moderation_router,
    frontend_router,
):
    app.include_router(route_router)
