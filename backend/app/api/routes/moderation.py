"""Moderation API routes."""
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

from app.schemas.moderation import *

router = APIRouter()

@router.post('/api/v1/reports', status_code=201)
def create_report(payload: ReportCreateRequest, user: Dict[str, Any] = Depends(require_authenticated_user)):
    if payload.target_type not in ("resource", "comment"):
        raise HTTPException(status_code=400, detail={"error": "INVALID_TARGET", "message": "target_type must be 'resource' or 'comment'."})
    if payload.reason not in REPORT_REASONS:
        raise HTTPException(status_code=400, detail={"error": "INVALID_REASON", "message": "reason must be one of: " + ", ".join(REPORT_REASONS)})
    safe_details = html.escape(payload.details.strip()) if payload.details else None
    with get_db() as db:
        target_table = "resources" if payload.target_type == "resource" else "comments"
        if not db.fetchone(f"SELECT id FROM {target_table} WHERE id = ?", (payload.target_id,)):
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": f"Reported {payload.target_type} not found."})
        db.execute(
            "INSERT INTO reports (reporter_id, target_type, target_id, reason, details, status) VALUES (?, ?, ?, ?, ?, 'open')",
            (user["id"], payload.target_type, payload.target_id, payload.reason, safe_details),
        )
        db.commit()
        rep = db.fetchone("SELECT * FROM reports WHERE reporter_id = ? ORDER BY id DESC LIMIT 1", (user["id"],))
        rep["reporter_username"] = user["username"]
        rep["created_at"] = str(rep["created_at"])
        return rep

@router.get('/api/v1/moderation/reports')
def list_moderation_reports(status: Optional[str] = Query(None), mod: Dict[str, Any] = Depends(require_moderator)):
    with get_db() as db:
        if status:
            rows = db.fetchall(
                """
                SELECT rp.*, u.username AS reporter_username
                FROM reports rp
                JOIN users u ON u.id = rp.reporter_id
                WHERE rp.status = ?
                ORDER BY rp.created_at DESC
                """,
                (status,),
            )
        else:
            rows = db.fetchall(
                """
                SELECT rp.*, u.username AS reporter_username
                FROM reports rp
                JOIN users u ON u.id = rp.reporter_id
                ORDER BY CASE rp.status WHEN 'open' THEN 1 WHEN 'reviewing' THEN 2 ELSE 3 END, rp.id DESC
                """
            )
        for r in rows:
            if r["target_type"] == "resource":
                t = db.fetchone("SELECT title FROM resources WHERE id = ?", (r["target_id"],))
                r["target_title_or_preview"] = t["title"] if t else f"Resource #{r['target_id']}"
            else:
                t = db.fetchone("SELECT body FROM comments WHERE id = ?", (r["target_id"],))
                r["target_title_or_preview"] = (t["body"][:80] if t else f"Comment #{r['target_id']}")
            r["created_at"] = str(r["created_at"])
            r["resolved_at"] = str(r["resolved_at"]) if r.get("resolved_at") else None
        return rows

@router.patch('/api/v1/moderation/reports/{report_id}')
def resolve_moderation_report(
    report_id: int,
    payload: ModerationActionRequest,
    mod: Dict[str, Any] = Depends(require_moderator),
):
    if payload.action not in ("hide", "restore", "remove", "dismiss"):
        raise HTTPException(status_code=400, detail={"error": "INVALID_ACTION", "message": "action must be hide, restore, remove, or dismiss."})

    with get_db() as db:
        rep = db.fetchone("SELECT * FROM reports WHERE id = ?", (report_id,))
        if not rep:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Report not found."})

        target_table = "resources" if rep["target_type"] == "resource" else "comments"
        if payload.action == "hide":
            db.execute(f"UPDATE {target_table} SET status = 'hidden' WHERE id = ?", (rep["target_id"],))
            new_rep_status = "resolved"
        elif payload.action == "restore":
            db.execute(f"UPDATE {target_table} SET status = 'active' WHERE id = ?", (rep["target_id"],))
            new_rep_status = "resolved"
        elif payload.action == "remove":
            db.execute(f"UPDATE {target_table} SET status = 'removed' WHERE id = ?", (rep["target_id"],))
            new_rep_status = "resolved"
        else:
            new_rep_status = "dismissed"

        now_fn = "CURRENT_TIMESTAMP"
        db.execute(
            f"""
            UPDATE reports
            SET status = ?, moderator_id = ?, moderation_action = ?, moderation_note = ?, resolved_at = {now_fn}
            WHERE id = ?
            """,
            (new_rep_status, mod["id"], payload.action, payload.note, report_id),
        )
        db.commit()
        updated = db.fetchone(
            """
            SELECT rp.*, u.username AS reporter_username
            FROM reports rp JOIN users u ON u.id = rp.reporter_id
            WHERE rp.id = ?
            """,
            (report_id,),
        )
        updated["created_at"] = str(updated["created_at"])
        updated["resolved_at"] = str(updated["resolved_at"]) if updated.get("resolved_at") else None
        return updated
