"""Frontend API routes."""
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

@router.get('/', response_class=HTMLResponse)
def serve_frontend():
    base_dir = str(Path(__file__).resolve().parents[4])
    idx_path = os.path.join(base_dir, "frontend", "index.html")
    if os.path.exists(idx_path):
        with open(idx_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>ScholarPulse MS-3 API Server Running</h1><p>Visit <a href='/docs'>/docs</a> for OpenAPI UI.</p>")
