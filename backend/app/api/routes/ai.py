import html
import json
import re
import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import require_authenticated_user
from app.core.config import settings
from app.db.session import get_db
from app.schemas.ai import AIAskRequest
from app.services.gemini_service import (
    GeminiUnavailable,
    generate_general_answer,
    generate_grounded_answer,
)
from app.services.rag_service import (
    retrieve_chunks_for_scope,
    strip_prompt_injection_sentences,
    synthesize_grounded_answer,
)

router = APIRouter(prefix="/api/v1/ai", tags=["AI Study Assistant"])


@router.post("/ask")
def ask_study_assistant(
    payload: AIAskRequest,
    user: Dict[str, Any] = Depends(require_authenticated_user),
):
    t0 = time.time()
    question = payload.question.strip()
    scope_type = payload.scope_type
    scope_id = payload.scope_id or "global"

    if len(question) > settings.AI_MAX_QUESTION_LENGTH:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "QUESTION_TOO_LONG",
                "message": (
                    f"Questions are limited to "
                    f"{settings.AI_MAX_QUESTION_LENGTH} characters."
                ),
            },
        )

    if scope_type not in ("resource", "collection", "course", "general"):
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_SCOPE",
                "message": (
                    "scope_type must be resource, collection, course, or general."
                ),
            },
        )

    answer = ""
    not_found = False
    fallback_used = False
    fallback_notice = None
    citations = []
    model_used = settings.GEMINI_GENERATION_MODEL

    with get_db() as db:
        # Rate limit per user
        if db.dialect == "sqlite":
            recent_q = db.fetchone(
                """
                SELECT COUNT(*) AS cnt
                FROM ai_queries
                WHERE user_id = ?
                AND created_at >= datetime('now', '-1 hour')
                """,
                (user["id"],),
            )
        else:
            recent_q = db.fetchone(
                """
                SELECT COUNT(*) AS cnt
                FROM ai_queries
                WHERE user_id = ?
                AND created_at >= NOW() - INTERVAL 1 HOUR
                """,
                (user["id"],),
            )

        if recent_q and recent_q["cnt"] >= settings.AI_RATE_LIMIT_PER_HOUR:
            raise HTTPException(
                status_code=429,
                detail={
                    "error": "RATE_LIMIT_EXCEEDED",
                    "message": (
                        f"Rate limit reached "
                        f"({settings.AI_RATE_LIMIT_PER_HOUR} questions per hour)."
                    ),
                },
            )

        if scope_type == "general":
            try:
                if payload.simulate_failure:
                    raise GeminiUnavailable("Simulated Gemini failure")

                answer = generate_general_answer(question)
                citations = []
                not_found = False

            except GeminiUnavailable:
                answer = (
                    "The AI assistant is temporarily unavailable. "
                    "Please try again later."
                )
                fallback_used = True
                fallback_notice = (
                    "Gemini is unavailable. No general AI answer could be generated."
                )
                model_used = "unavailable-fallback"

        else:
            mode = "keyword" if payload.simulate_failure else "embedding"

            retrieved = retrieve_chunks_for_scope(
                db,
                question,
                scope_type,
                scope_id,
                mode=mode,
            )

            # Keep the existing local synthesizer as a safe fallback
            local_answer, local_not_found, _, _, local_citations = (
                synthesize_grounded_answer(
                    question=question,
                    retrieved_chunks=retrieved,
                    scope_type=scope_type,
                    simulate_failure=False,
                )
            )

            if not retrieved:
                answer = "Not found in this document."
                not_found = True
                citations = []
                model_used = "rag-no-results"

            elif payload.simulate_failure:
                answer, not_found, fallback_used, fallback_notice, citations = (
                    synthesize_grounded_answer(
                        question=question,
                        retrieved_chunks=retrieved,
                        scope_type=scope_type,
                        simulate_failure=True,
                    )
                )
                model_used = "mysql-fulltext-fallback"

            else:
                safe_chunks = [
                    {
                        "chunk_id": chunk["chunk_id"],
                        "resource_title": chunk["resource_title"],
                        "safe_text": strip_prompt_injection_sentences(
                            chunk["chunk_text"]
                        ),
                    }
                    for chunk in retrieved
                ]

                try:
                    gemini_answer = generate_grounded_answer(
                        question=question,
                        chunks=safe_chunks,
                    )

                    if gemini_answer.strip().lower().rstrip(".") == (
                        "not found in this document"
                    ):
                        answer = "Not found in this document."
                        not_found = True
                        citations = []

                    else:
                        # Only accept citations belonging to retrieved chunks
                        retrieved_ids = {
                            int(chunk["chunk_id"]) for chunk in retrieved
                        }
                        cited_ids = [
                            int(value)
                            for value in re.findall(
                                r"\[Chunk\s+(\d+)\]", gemini_answer
                            )
                        ]
                        valid_ids = set(cited_ids) & retrieved_ids

                        if not valid_ids:
                            # Do not return unsupported Gemini claims
                            answer = local_answer
                            citations = local_citations
                            fallback_used = True
                            fallback_notice = (
                                "Gemini returned no valid document citations. "
                                "Showing the local grounded answer instead."
                            )
                            model_used = "local-rag-fallback"
                        else:
                            # Remove citations that do not belong to retrieved chunks
                            def clean_citation(match):
                                chunk_id = int(match.group(1))
                                return (
                                    match.group(0)
                                    if chunk_id in valid_ids
                                    else ""
                                )

                            answer = re.sub(
                                r"\[Chunk\s+(\d+)\]",
                                clean_citation,
                                gemini_answer,
                            ).strip()

                            citations = [
                                citation
                                for citation in local_citations
                                if int(citation["chunk_id"]) in valid_ids
                            ]
                            not_found = False

                except GeminiUnavailable:
                    answer = local_answer
                    not_found = local_not_found
                    citations = local_citations
                    fallback_used = True
                    fallback_notice = (
                        "Gemini is unavailable. Showing the local RAG answer."
                    )
                    model_used = "local-rag-fallback"

        latency_ms = max(1, int((time.time() - t0) * 1000))
        cited_ids = [citation["chunk_id"] for citation in citations]

        db.execute(
            """
            INSERT INTO ai_queries (
                user_id, scope_type, scope_id, question, answer_text,
                cited_chunk_ids_json, not_found, fallback_used,
                model_used, latency_ms
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user["id"],
                scope_type,
                scope_id,
                question,
                html.escape(answer),
                json.dumps(cited_ids),
                1 if not_found else 0,
                1 if fallback_used else 0,
                model_used,
                latency_ms,
            ),
        )

        db.commit()

        q_row = db.fetchone(
            "SELECT id FROM ai_queries WHERE user_id = ? ORDER BY id DESC LIMIT 1",
            (user["id"],),
        )
        qid = q_row["id"] if q_row else 1

    return {
        "query_id": qid,
        "question": question,
        "scope_type": scope_type,
        "scope_id": scope_id,
        "answer": answer,
        "not_found": not_found,
        "fallback_used": fallback_used,
        "fallback_notice": fallback_notice,
        "citations": citations,
        "latency_ms": latency_ms,
    }
