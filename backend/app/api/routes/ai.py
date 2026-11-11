"""Ai API routes."""
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

from app.schemas.ai import *

from app.services.resource_formatter import format_resource_summary

from app.api.routes.collections import get_collection_detail

router = APIRouter()

@router.post('/api/v1/ai/ask')
def ask_study_assistant(payload: AIAskRequest, user: Dict[str, Any] = Depends(require_authenticated_user)):
    t0 = time.time()
    question = payload.question.strip()
        # Block AI questions containing "gayathri"
    if "gayathri" in question.casefold():
        raise HTTPException(
            status_code=403,
            detail="This question is blocked."
        )

    # Guardrail 1: Question length <= 300 characters
    if len(question) > settings.AI_MAX_QUESTION_LENGTH:
        raise HTTPException(
            status_code=400,
            detail={"error": "QUESTION_TOO_LONG", "message": f"Questions are limited to {settings.AI_MAX_QUESTION_LENGTH} characters."},
        )

    if payload.scope_type not in ("resource", "collection", "course"):
        raise HTTPException(status_code=400, detail={"error": "INVALID_SCOPE", "message": "scope_type must be 'resource', 'collection', or 'course'."})

    with get_db() as db:
        # Guardrail 2: Rate limit 20 questions per hour per user
        if db.dialect == "sqlite":
            recent_q = db.fetchone(
                "SELECT COUNT(*) AS cnt FROM ai_queries WHERE user_id = ? AND created_at >= datetime('now', '-1 hour')",
                (user["id"],),
            )
        else:
            recent_q = db.fetchone(
                "SELECT COUNT(*) AS cnt FROM ai_queries WHERE user_id = ? AND created_at >= NOW() - INTERVAL 1 HOUR",
                (user["id"],),
            )
        if recent_q and recent_q["cnt"] >= settings.AI_RATE_LIMIT_PER_HOUR:
            raise HTTPException(
                status_code=429,
                detail={"error": "RATE_LIMIT_EXCEEDED", "message": f"Rate limit reached ({settings.AI_RATE_LIMIT_PER_HOUR} questions per hour). Please use keyword search or try again later."},
            )

        mode = "keyword" if payload.simulate_failure else "embedding"
        retrieved = retrieve_chunks_for_scope(db, question, payload.scope_type, payload.scope_id, mode=mode)
        answer, not_found, fallback_used, fallback_notice, citations = synthesize_grounded_answer(
            question=question,
            retrieved_chunks=retrieved,
            scope_type=payload.scope_type,
            simulate_failure=payload.simulate_failure,
        )

        # Fallback: nothing relevant in the stored data -> ask Google Gemini (general knowledge).
        # Skipped when the user chose "keyword search only". If no key is configured or the call
        # fails, the normal "Not found" refusal is returned unchanged.
        general_ai_used = False
        general_ai_error = None
        doc_miss = not_found
        if not_found and not payload.simulate_failure:
            general_answer, general_ai_error = generate_gemini_general_answer(question)
            if general_answer:
                answer, not_found, general_ai_used = general_answer, False, True
                citations = []

        latency_ms = max(1, int((time.time() - t0) * 1000))
        cited_ids = [c["chunk_id"] for c in citations]

        db.execute(
            """
            INSERT INTO ai_queries (
                user_id, scope_type, scope_id, question, answer_text,
                cited_chunk_ids_json, not_found, fallback_used, model_used, latency_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                payload.scope_type,
                payload.scope_id,
                question,
                html.escape(answer),
                json.dumps(cited_ids),
                1 if (not_found or doc_miss) else 0,  # log the data miss even when Gemini answered
                1 if fallback_used else 0,
                "mysql-fulltext-fallback" if fallback_used else settings.GEMINI_GENERATION_MODEL,
                latency_ms,
            ),
        )
        db.commit()
        q_row = db.fetchone("SELECT id FROM ai_queries WHERE user_id = ? ORDER BY id DESC LIMIT 1", (user["id"],))
        qid = q_row["id"] if q_row else 1

    return {
        "query_id": qid,
        "question": question,
        "scope_type": payload.scope_type,
        "scope_id": payload.scope_id,
        "answer": answer,
        "not_found": not_found,
        "fallback_used": fallback_used,
        "fallback_notice": fallback_notice,
        "general_ai_used": general_ai_used,
        "general_ai_error": general_ai_error,
        "general_ai_notice": (
            "Not found in ScholarPulse documents. This answer comes from Google Gemini's general "
            "knowledge, has no citations, and may be inaccurate - verify it against your course material."
            if general_ai_used else None
        ),
        "citations": citations,
        "latency_ms": latency_ms,
    }
