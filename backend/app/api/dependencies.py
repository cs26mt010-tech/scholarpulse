"""Shared authentication, session, and authorization dependencies."""
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


def _send_verification_email(recipient: str, code: str) -> None:
    if not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        raise HTTPException(status_code=503, detail={"error": "EMAIL_NOT_CONFIGURED", "message": "Email verification is not configured. Ask the administrator to configure Gmail SMTP."})
    msg = EmailMessage()
    msg["Subject"] = "Your ScholarPulse verification code"
    msg["From"] = settings.SMTP_FROM_EMAIL or settings.SMTP_USER
    msg["To"] = recipient
    msg.set_content(
        f"Your ScholarPulse verification code is {code}.\n\n"
        f"It expires in {settings.EMAIL_VERIFICATION_TTL_MINUTES} minutes. "
        "If you did not create this account, you can ignore this email."
    )
    try:
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15) as server:
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)
    except Exception as exc:
        raise HTTPException(status_code=502, detail={"error": "EMAIL_SEND_FAILED", "message": "Could not send the verification email. Check the Gmail SMTP settings and try again."}) from exc

def _set_login_session(response: Response, user: Dict[str, Any]) -> str:
    cookie_val = create_session_cookie_value(user["id"], user["role"], user["username"])
    csrf_token = generate_csrf_token(cookie_val)
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME, value=cookie_val, httponly=True,
        samesite=settings.SESSION_COOKIE_SAMESITE, secure=settings.SESSION_COOKIE_SECURE,
        max_age=settings.SESSION_EXPIRE_HOURS * 3600,
    )
    return csrf_token

def get_optional_user(request: Request) -> Optional[Dict[str, Any]]:
    cookie_val = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not cookie_val:
        return None
    payload = verify_session_cookie_value(cookie_val)
    if not payload:
        return None
    with get_db() as db:
        user = db.fetchone(
            "SELECT id, username, email, bio, programme, profile_photo_path, email_notifications, public_profile, role, consent_accepted, created_at, email_verified FROM users WHERE id = ? AND email_verified = 1",
            (payload["uid"],),
        )
        return user

def require_authenticated_user(request: Request) -> Dict[str, Any]:
    user = get_optional_user(request)
    if not user:
        raise HTTPException(status_code=401, detail={"error": "UNAUTHORIZED", "message": "Authentication required. Please sign in."})
    # Verify CSRF token on state-changing HTTP methods
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        cookie_val = request.cookies.get(settings.SESSION_COOKIE_NAME, "")
        csrf_hdr = request.headers.get("X-CSRF-Token", "")
        if not verify_csrf_token(cookie_val, csrf_hdr):
            raise HTTPException(status_code=403, detail={"error": "CSRF_INVALID", "message": "Missing or invalid X-CSRF-Token header."})
    return user

def require_moderator(user: Dict[str, Any] = Depends(require_authenticated_user)) -> Dict[str, Any]:
    if user["role"] != "moderator":
        raise HTTPException(status_code=403, detail={"error": "FORBIDDEN", "message": "Moderator role required for this action."})
    return user
