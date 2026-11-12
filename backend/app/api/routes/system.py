"""System API routes."""
import html
import json
import math
import os
import time
import uuid
import secrets
import hashlib
import re
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import (
    create_session_cookie_value,
    generate_csrf_token,
    hash_password_argon2id,
    verify_csrf_token,
    verify_password_argon2id,
    verify_session_cookie_value,
)
from app.db.session import get_db
from app.services.rag_service import (
    chunk_text_sliding,
    compute_embedding,
    generate_gemini_general_answer,
    retrieve_chunks_for_scope,
    synthesize_grounded_answer,
)
from app.api.dependencies import (
    _send_verification_email,
    _set_login_session,
    get_optional_user,
    require_authenticated_user,
    require_moderator,
)

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
