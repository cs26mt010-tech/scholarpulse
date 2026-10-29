"""
ScholarPulse FastAPI Backend Application (backend/app/main.py)
--------------------------------------------------------------
Implements all 21 paths and 30 schemas defined in `docs/openapi.yaml` (MS-3):
- Health & Database Readiness (`/api/v1/health`, `/api/v1/openapi.yaml`)
- Auth & DPDP Act 2023 Compliance (`/api/v1/auth/register`, `/api/v1/auth/login`, `/api/v1/auth/logout`, `/api/v1/auth/me`, `/api/v1/auth/password`)
- Categories & Tags (`/api/v1/categories`, `/api/v1/tags`)
- Resources Catalogue, Upload (.pdf/.txt <= 5MB with text extraction & chunking), Detail, Update, Delete (`/api/v1/resources`, `/api/v1/resources/{resource_id}`)
- Community Ratings & Comments (`/api/v1/resources/{resource_id}/ratings`, `/api/v1/resources/{resource_id}/comments`, `/api/v1/comments/{comment_id}`)
- Curated & Official TA Reading Lists (`/api/v1/collections`, `/api/v1/collections/{collection_id}`, `/api/v1/collections/{collection_id}/items`)
- Grounded AI Study Assistant (`/api/v1/ai/ask`) supporting single resource, collection (<=20 resources), and course scopes, citation validation, refusal, rate limiting (20/hr, <=300 chars), and keyword fallback
- Content Reporting & Moderator Queue (`/api/v1/reports`, `/api/v1/moderation/reports`, `/api/v1/moderation/reports/{report_id}`)
"""
import os
import html
import json
import math
import time
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Request, Response, HTTPException, UploadFile, File, Form, Query, Depends
from fastapi.responses import JSONResponse, FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.security import (
    hash_password_argon2id,
    verify_password_argon2id,
    create_session_cookie_value,
    verify_session_cookie_value,
    generate_csrf_token,
    verify_csrf_token,
)
from app.db.session import get_db, init_schema_ddl
from app.services.rag_service import (
    chunk_text_sliding,
    compute_embedding,
    retrieve_chunks_for_scope,
    synthesize_grounded_answer,
    gemini_enabled,
)

app = FastAPI(
    title="ScholarPulse: AI-Enabled Academic Knowledge Hub API",
    version="1.0.0-ms3",
    description="Course Project 2026 | Theme 4: Knowledge Hub | Milestone 3 Backend & Database Stack",
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


# ---------------------------------------------------------------------------
# Pydantic Request Schemas
# ---------------------------------------------------------------------------
class UserRegisterRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: str = Field(..., min_length=5, max_length=120)
    password: str = Field(..., min_length=8, max_length=128)
    bio: Optional[str] = Field(None, max_length=500)
    consent_accepted: bool = Field(...)


class UserLoginRequest(BaseModel):
    email: str
    password: str
    remember_me: bool = False


class UserUpdateRequest(BaseModel):
    username: Optional[str] = Field(None, min_length=3, max_length=50)
    bio: Optional[str] = Field(None, max_length=500)


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str = Field(..., min_length=8, max_length=128)


class ResourceUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=200)
    course_code: Optional[str] = None
    tags: Optional[List[str]] = None


class RatingRequest(BaseModel):
    score: int = Field(..., ge=1, le=5)


class CommentCreateRequest(BaseModel):
    body: str = Field(..., min_length=2, max_length=2000)


class CollectionCreateRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=150)
    description: Optional[str] = Field(None, max_length=1000)
    course_code: Optional[str] = None
    is_public: bool = True
    is_official: bool = False


class CollectionUpdateRequest(BaseModel):
    title: Optional[str] = Field(None, min_length=3, max_length=150)
    description: Optional[str] = Field(None, max_length=1000)
    ordered_resource_ids: Optional[List[int]] = None


class CollectionItemAddRequest(BaseModel):
    resource_id: int
    position: Optional[int] = None
    notes: Optional[str] = Field(None, max_length=300)


class AIAskRequest(BaseModel):
    question: str = Field(..., min_length=1, max_length=500)
    scope_type: str = Field(..., description="resource | collection | course")
    scope_id: str = Field(...)
    simulate_failure: bool = False


class ReportCreateRequest(BaseModel):
    target_type: str = Field(..., description="resource | comment")
    target_id: int
    reason: str
    details: Optional[str] = Field(None, max_length=1000)


REPORT_REASONS = ("copyright_concern", "incorrect_or_misleading", "low_quality_or_spam", "inappropriate_content")


class ModerationActionRequest(BaseModel):
    action: str = Field(..., description="hide | restore | remove | dismiss")
    note: Optional[str] = Field(None, max_length=500)


# ---------------------------------------------------------------------------
# Auth & CSRF Dependencies
# ---------------------------------------------------------------------------
def get_optional_user(request: Request) -> Optional[Dict[str, Any]]:
    cookie_val = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not cookie_val:
        return None
    payload = verify_session_cookie_value(cookie_val)
    if not payload:
        return None
    with get_db() as db:
        user = db.fetchone(
            "SELECT id, username, email, bio, role, consent_accepted, created_at FROM users WHERE id = ?",
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


def format_resource_summary(db, row: Dict[str, Any]) -> Dict[str, Any]:
    tag_rows = db.fetchall(
        """
        SELECT t.name FROM tags t
        JOIN resource_tags rt ON rt.tag_id = t.id
        WHERE rt.resource_id = ?
        ORDER BY t.name ASC
        """,
        (row["id"],),
    )
    return {
        "id": row["id"],
        "title": row["title"],
        "resource_type": row["resource_type"],
        "course_code": row.get("course_code", "CS301"),
        "source_authors": row.get("source_authors"),
        "source_ref": row.get("source_ref"),
        "published_on": str(row["published_on"]) if row.get("published_on") else None,
        "tldr_summary": row.get("tldr_summary"),
        "is_official": bool(row.get("is_official")),
        "status": row.get("status", "active"),
        "embedding_status": row.get("embedding_status", "completed"),
        "avg_rating": round(float(row.get("avg_rating", 0.0)), 2),
        "rating_count": int(row.get("rating_count", 0)),
        "comment_count": int(row.get("comment_count", 0)),
        "tags": [t["name"] for t in tag_rows],
        "uploader_username": row.get("uploader_username"),
        "created_at": str(row.get("created_at", "")),
    }


# ---------------------------------------------------------------------------
# 1. System & Health Endpoints
# ---------------------------------------------------------------------------
@app.get("/api/v1/health")
def health_check():
    with get_db() as db:
        init_schema_ddl(db)
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


@app.get("/api/v1/openapi.yaml")
def get_openapi_yaml():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    yaml_path = os.path.join(base_dir, "docs", "openapi.yaml")
    if os.path.exists(yaml_path):
        return FileResponse(yaml_path, media_type="application/yaml")
    raise HTTPException(status_code=404, detail="openapi.yaml not found")


# ---------------------------------------------------------------------------
# 2. Authentication & Profile Endpoints (Argon2id + Session Cookie + CSRF + DPDP)
# ---------------------------------------------------------------------------
@app.post("/api/v1/auth/register", status_code=201)
def register_user(payload: UserRegisterRequest, response: Response):
    if not payload.consent_accepted:
        raise HTTPException(
            status_code=400,
            detail={"error": "CONSENT_REQUIRED", "message": "You must accept the DPDP Act 2023 data collection consent notice to create an account."},
        )
    uname = html.escape(payload.username.strip())
    email = payload.email.strip().lower()
    bio = html.escape(payload.bio.strip()) if payload.bio else None

    with get_db() as db:
        dup = db.fetchone("SELECT id FROM users WHERE username = ? OR email = ?", (uname, email))
        if dup:
            raise HTTPException(status_code=400, detail={"error": "DUPLICATE_USER", "message": "Username or university email is already registered."})

        pw_hash = hash_password_argon2id(payload.password)
        db.execute(
            "INSERT INTO users (username, email, password_hash, bio, role, consent_accepted) VALUES (?, ?, ?, ?, 'student', 1)",
            (uname, email, pw_hash, bio),
        )
        db.commit()
        user = db.fetchone("SELECT id, username, email, bio, role, consent_accepted, created_at FROM users WHERE email = ?", (email,))

    cookie_val = create_session_cookie_value(user["id"], user["role"], user["username"])
    csrf_token = generate_csrf_token(cookie_val)
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=cookie_val,
        httponly=True,
        samesite=settings.SESSION_COOKIE_SAMESITE,
        secure=settings.SESSION_COOKIE_SECURE,
        max_age=settings.SESSION_EXPIRE_HOURS * 3600,
    )
    user["consent_accepted"] = bool(user["consent_accepted"])
    user["csrf_token"] = csrf_token
    return user


@app.post("/api/v1/auth/login")
def login_user(payload: UserLoginRequest, response: Response):
    email = payload.email.strip().lower()
    with get_db() as db:
        user = db.fetchone("SELECT * FROM users WHERE LOWER(email) = ? OR username = ?", (email, payload.email.strip()))
        if not user or not verify_password_argon2id(payload.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail={"error": "INVALID_CREDENTIALS", "message": "We couldn't sign you in with that email and password. Try again."})

    cookie_val = create_session_cookie_value(user["id"], user["role"], user["username"])
    csrf_token = generate_csrf_token(cookie_val)
    response.set_cookie(
        key=settings.SESSION_COOKIE_NAME,
        value=cookie_val,
        httponly=True,
        samesite=settings.SESSION_COOKIE_SAMESITE,
        secure=settings.SESSION_COOKIE_SECURE,
        max_age=settings.SESSION_EXPIRE_HOURS * 3600,
    )
    public_user = {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "bio": user["bio"],
        "role": user["role"],
        "consent_accepted": bool(user["consent_accepted"]),
        "created_at": str(user["created_at"]),
    }
    return {"user": public_user, "csrf_token": csrf_token}


@app.post("/api/v1/auth/logout")
def logout_user(response: Response, user: Dict[str, Any] = Depends(require_authenticated_user)):
    response.delete_cookie(key=settings.SESSION_COOKIE_NAME)
    return {"status": "logged_out"}


@app.get("/api/v1/auth/me")
def get_me(request: Request):
    user = get_optional_user(request)
    if not user:
        raise HTTPException(status_code=401, detail={"error": "UNAUTHORIZED", "message": "Not authenticated"})
    cookie_val = request.cookies.get(settings.SESSION_COOKIE_NAME, "")
    with get_db() as db:
        uploads = db.fetchall(
            """
            SELECT r.*, c.course_code, u.username AS uploader_username
            FROM resources r
            JOIN categories c ON c.id = r.category_id
            LEFT JOIN users u ON u.id = r.uploader_id
            WHERE r.uploader_id = ? AND r.status != 'removed'
            ORDER BY r.created_at DESC
            """,
            (user["id"],),
        )
        colls = db.fetchall(
            "SELECT * FROM collections WHERE owner_id = ? ORDER BY created_at DESC",
            (user["id"],),
        )
        formatted_uploads = [format_resource_summary(db, r) for r in uploads]
    user["consent_accepted"] = bool(user["consent_accepted"])
    user["csrf_token"] = generate_csrf_token(cookie_val)
    user["uploads"] = formatted_uploads
    user["collections_count"] = len(colls)
    return user


@app.patch("/api/v1/auth/me")
def update_me(payload: UserUpdateRequest, user: Dict[str, Any] = Depends(require_authenticated_user)):
    with get_db() as db:
        if payload.username is not None:
            uname = html.escape(payload.username.strip())
            dup = db.fetchone("SELECT id FROM users WHERE username = ? AND id != ?", (uname, user["id"]))
            if dup:
                raise HTTPException(status_code=400, detail={"error": "DUPLICATE_USER", "message": "That username is already taken."})
            db.execute("UPDATE users SET username = ? WHERE id = ?", (uname, user["id"]))
        if payload.bio is not None:
            bio = html.escape(payload.bio.strip())
            db.execute("UPDATE users SET bio = ? WHERE id = ?", (bio, user["id"]))
        db.commit()
        updated = db.fetchone("SELECT id, username, email, bio, role, consent_accepted, created_at FROM users WHERE id = ?", (user["id"],))
        updated["consent_accepted"] = bool(updated["consent_accepted"])
        return updated


@app.put("/api/v1/auth/password")
def change_password(payload: PasswordChangeRequest, user: Dict[str, Any] = Depends(require_authenticated_user)):
    with get_db() as db:
        row = db.fetchone("SELECT password_hash FROM users WHERE id = ?", (user["id"],))
        if not row or not verify_password_argon2id(payload.current_password, row["password_hash"]):
            raise HTTPException(status_code=400, detail={"error": "INVALID_PASSWORD", "message": "Current password is incorrect."})
        new_hash = hash_password_argon2id(payload.new_password)
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user["id"]))
        db.commit()
    return {"status": "password_updated"}


@app.delete("/api/v1/auth/me")
def delete_own_account(response: Response, user: Dict[str, Any] = Depends(require_authenticated_user)):
    """DPDP Act 2023 compliance: delete account and all associated user data."""
    with get_db() as db:
        db.execute("DELETE FROM ratings WHERE user_id = ?", (user["id"],))
        db.execute("DELETE FROM comments WHERE user_id = ?", (user["id"],))
        db.execute("DELETE FROM collections WHERE owner_id = ?", (user["id"],))
        db.execute("DELETE FROM resources WHERE uploader_id = ?", (user["id"],))
        db.execute("DELETE FROM ai_queries WHERE user_id = ?", (user["id"],))
        db.execute("DELETE FROM users WHERE id = ?", (user["id"],))
        db.commit()
    response.delete_cookie(key=settings.SESSION_COOKIE_NAME)
    return {"status": "account_deleted", "deleted_user_id": user["id"]}


# ---------------------------------------------------------------------------
# 3. Categories & Tags Endpoints
# ---------------------------------------------------------------------------
@app.get("/api/v1/categories")
def list_categories():
    with get_db() as db:
        rows = db.fetchall(
            """
            SELECT c.id, c.course_code, c.course_name, c.department, c.description,
                   COUNT(r.id) AS resource_count
            FROM categories c
            LEFT JOIN resources r ON r.category_id = c.id AND r.status = 'active'
            GROUP BY c.id, c.course_code, c.course_name, c.department, c.description
            ORDER BY c.course_code ASC
            """
        )
        return rows


@app.get("/api/v1/tags")
def list_tags():
    with get_db() as db:
        rows = db.fetchall(
            """
            SELECT t.id, t.name, t.slug, COUNT(rt.resource_id) AS usage_count
            FROM tags t
            LEFT JOIN resource_tags rt ON rt.tag_id = t.id
            GROUP BY t.id, t.name, t.slug
            ORDER BY usage_count DESC, t.name ASC
            LIMIT 40
            """
        )
        return rows


# ---------------------------------------------------------------------------
# 4. Resources Endpoints (Browse, Search, Filter, Upload, View, Edit, Delete)
# ---------------------------------------------------------------------------
@app.get("/api/v1/resources")
def list_resources(
    q: Optional[str] = Query(None),
    course_code: Optional[str] = Query(None),
    tag: Optional[str] = Query(None),
    resource_type: Optional[str] = Query(None),
    official_only: bool = Query(False),
    sort_by: str = Query("rating"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=50),
):
    where_clauses = ["r.status = 'active'"]
    params: List[Any] = []

    if course_code:
        where_clauses.append("c.course_code = ?")
        params.append(course_code.strip().upper())

    if resource_type:
        where_clauses.append("r.resource_type = ?")
        params.append(resource_type.strip())

    if official_only:
        where_clauses.append("r.is_official = 1")

    if tag:
        where_clauses.append(
            "EXISTS (SELECT 1 FROM resource_tags rt JOIN tags t ON t.id = rt.tag_id WHERE rt.resource_id = r.id AND (t.name = ? OR t.slug = ?))"
        )
        params.extend([tag.strip(), tag.strip().lower()])

    if q and q.strip():
        kw = f"%{q.strip()}%"
        where_clauses.append("(r.title LIKE ? OR r.content_text LIKE ? OR r.source_authors LIKE ?)")
        params.extend([kw, kw, kw])

    where_sql = " AND ".join(where_clauses)

    if sort_by == "newest":
        order_sql = "r.is_official DESC, r.published_on DESC, r.id DESC"
    elif sort_by == "comments":
        order_sql = "r.comment_count DESC, r.avg_rating DESC, r.id ASC"
    else:
        order_sql = "r.is_official DESC, r.avg_rating DESC, r.rating_count DESC, r.id ASC"

    offset = (page - 1) * page_size

    with get_db() as db:
        count_row = db.fetchone(
            f"""
            SELECT COUNT(*) AS total
            FROM resources r
            JOIN categories c ON c.id = r.category_id
            WHERE {where_sql}
            """,
            tuple(params),
        )
        total = count_row["total"] if count_row else 0
        total_pages = max(1, math.ceil(total / page_size))

        rows = db.fetchall(
            f"""
            SELECT r.*, c.course_code, u.username AS uploader_username
            FROM resources r
            JOIN categories c ON c.id = r.category_id
            LEFT JOIN users u ON u.id = r.uploader_id
            WHERE {where_sql}
            ORDER BY {order_sql}
            LIMIT ? OFFSET ?
            """,
            tuple(params + [page_size, offset]),
        )
        items = [format_resource_summary(db, r) for r in rows]

    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


@app.post("/api/v1/resources", status_code=201)
async def upload_resource(
    title: str = Form(...),
    resource_type: str = Form("lecture_notes"),
    course_code: str = Form(...),
    tags: str = Form(""),
    is_official: bool = Form(False),
    rights_confirmed: bool = Form(...),
    file: UploadFile = File(...),
    user: Dict[str, Any] = Depends(require_authenticated_user),
):
    if not rights_confirmed:
        raise HTTPException(status_code=400, detail={"error": "RIGHTS_NOT_CONFIRMED", "message": "You must confirm that you have the right to share this material."})

    if is_official and user["role"] not in ("ta", "moderator"):
        raise HTTPException(status_code=403, detail={"error": "TA_ROLE_REQUIRED", "message": "Only Teaching Assistants and Moderators can mark resources as official."})

    fname = file.filename or "upload.txt"
    ext = os.path.splitext(fname)[1].lower()
    if ext not in settings.ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(status_code=400, detail={"error": "INVALID_FILE_TYPE", "message": "Only .pdf and .txt files are allowed."})

    raw_bytes = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    if len(raw_bytes) > max_bytes:
        raise HTTPException(status_code=400, detail={"error": "FILE_TOO_LARGE", "message": f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit."})

    extracted_text = ""
    if ext == ".txt":
        extracted_text = raw_bytes.decode("utf-8", errors="replace").strip()
    elif ext == ".pdf":
        try:
            import io
            from pypdf import PdfReader
            reader = PdfReader(io.BytesIO(raw_bytes))
            pages_txt = [p.extract_text() or "" for p in reader.pages]
            extracted_text = "\n".join(pages_txt).strip()
        except Exception:
            extracted_text = ""

    if len(extracted_text) < 20:
        raise HTTPException(
            status_code=400,
            detail={"error": "EMPTY_OR_SCANNED_FILE", "message": "Rejected: File contains no extractable text (scanned or empty PDFs cannot be indexed)."},
        )

    safe_title = html.escape(title.strip()[:200])
    safe_content = html.escape(extracted_text)
    tldr = safe_content[:220].rsplit(" ", 1)[0] + "..." if len(safe_content) > 220 else safe_content

    with get_db() as db:
        cat = db.fetchone("SELECT id, course_code FROM categories WHERE course_code = ?", (course_code.strip().upper(),))
        if not cat:
            raise HTTPException(status_code=400, detail={"error": "INVALID_COURSE", "message": f"Unknown course code: {course_code}"})

        source_ref = f"upload-{int(time.time()*1000)}-{user['id']}"
        db.execute(
            """
            INSERT INTO resources (
                title, content_text, tldr_summary, resource_type, category_id,
                uploader_id, source_authors, source_ref, published_on,
                file_name, file_size_bytes, is_official, rights_confirmed,
                status, embedding_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, DATE('now'), ?, ?, ?, 1, 'active', 'completed')
            """ if db.dialect == "sqlite" else """
            INSERT INTO resources (
                title, content_text, tldr_summary, resource_type, category_id,
                uploader_id, source_authors, source_ref, published_on,
                file_name, file_size_bytes, is_official, rights_confirmed,
                status, embedding_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, CURDATE(), ?, ?, ?, 1, 'active', 'completed')
            """,
            (
                safe_title,
                safe_content,
                tldr,
                resource_type,
                cat["id"],
                user["id"],
                user["username"],
                source_ref,
                fname,
                len(raw_bytes),
                1 if is_official else 0,
            ),
        )
        res_row = db.fetchone("SELECT * FROM resources WHERE source_ref = ?", (source_ref,))
        rid = res_row["id"]

        # Chunk (~800 chars, 100 overlap) and embed
        chunks = chunk_text_sliding(safe_content, chunk_size=800, overlap=100)
        for idx, c_txt in enumerate(chunks):
            vec = compute_embedding(c_txt)
            db.execute(
                "INSERT INTO resource_chunks (resource_id, chunk_index, chunk_text, char_length, embedding_json, embedding_model) VALUES (?, ?, ?, ?, ?, 'gemini-embedding-001')",
                (rid, idx, c_txt, len(c_txt), json.dumps(vec)),
            )

        # Tags
        tag_list = [t.strip() for t in tags.split(",") if t.strip()]
        for t_name in tag_list:
            slug = t_name.lower().replace(".", "-").replace(" ", "-")
            t_row = db.fetchone("SELECT id FROM tags WHERE slug = ?", (slug,))
            if not t_row:
                db.execute("INSERT INTO tags (name, slug) VALUES (?, ?)", (t_name, slug))
                t_row = db.fetchone("SELECT id FROM tags WHERE slug = ?", (slug,))
            db.execute("INSERT INTO resource_tags (resource_id, tag_id) VALUES (?, ?)", (rid, t_row["id"]))

        db.commit()
        res_row["course_code"] = cat["course_code"]
        res_row["uploader_username"] = user["username"]
        detail = format_resource_summary(db, res_row)
        detail["content_text"] = safe_content
        detail["chunk_count"] = len(chunks)
        detail["file_name"] = fname
        detail["file_size_bytes"] = len(raw_bytes)
        return detail


@app.get("/api/v1/resources/{resource_id}")
def get_resource_detail(resource_id: int):
    with get_db() as db:
        row = db.fetchone(
            """
            SELECT r.*, c.course_code, u.username AS uploader_username
            FROM resources r
            JOIN categories c ON c.id = r.category_id
            LEFT JOIN users u ON u.id = r.uploader_id
            WHERE r.id = ? AND r.status = 'active'
            """,
            (resource_id,),
        )
        if not row:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Resource not found or unavailable."})
        c_cnt = db.fetchone("SELECT COUNT(*) AS cnt FROM resource_chunks WHERE resource_id = ?", (resource_id,))
        detail = format_resource_summary(db, row)
        detail["content_text"] = row["content_text"]
        detail["chunk_count"] = c_cnt["cnt"] if c_cnt else 0
        detail["file_name"] = row.get("file_name")
        detail["file_size_bytes"] = row.get("file_size_bytes")
        return detail


@app.patch("/api/v1/resources/{resource_id}")
def update_resource(resource_id: int, payload: ResourceUpdateRequest, user: Dict[str, Any] = Depends(require_authenticated_user)):
    with get_db() as db:
        row = db.fetchone("SELECT * FROM resources WHERE id = ?", (resource_id,))
        if not row:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Resource not found."})
        if row["uploader_id"] != user["id"] and user["role"] != "moderator":
            raise HTTPException(status_code=403, detail={"error": "FORBIDDEN", "message": "You can only edit your own uploaded resources."})
        if payload.title:
            db.execute("UPDATE resources SET title = ? WHERE id = ?", (html.escape(payload.title.strip()[:200]), resource_id))
        db.commit()
    return get_resource_detail(resource_id)


@app.delete("/api/v1/resources/{resource_id}")
def delete_resource(resource_id: int, user: Dict[str, Any] = Depends(require_authenticated_user)):
    with get_db() as db:
        row = db.fetchone("SELECT * FROM resources WHERE id = ?", (resource_id,))
        if not row:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Resource not found."})
        if row["uploader_id"] != user["id"] and user["role"] != "moderator":
            raise HTTPException(status_code=403, detail={"error": "FORBIDDEN", "message": "You can only delete your own resources."})
        db.execute("DELETE FROM resources WHERE id = ?", (resource_id,))
        db.commit()
    return {"status": "deleted", "resource_id": resource_id}


# ---------------------------------------------------------------------------
# 5. Ratings & Comments Endpoints
# ---------------------------------------------------------------------------
@app.post("/api/v1/resources/{resource_id}/ratings")
def rate_resource(resource_id: int, payload: RatingRequest, user: Dict[str, Any] = Depends(require_authenticated_user)):
    with get_db() as db:
        res = db.fetchone("SELECT id FROM resources WHERE id = ? AND status = 'active'", (resource_id,))
        if not res:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Resource not found."})
        existing = db.fetchone("SELECT id FROM ratings WHERE resource_id = ? AND user_id = ?", (resource_id, user["id"]))
        if existing:
            db.execute("UPDATE ratings SET score = ? WHERE id = ?", (payload.score, existing["id"]))
        else:
            db.execute("INSERT INTO ratings (resource_id, user_id, score) VALUES (?, ?, ?)", (resource_id, user["id"], payload.score))

        stats = db.fetchone("SELECT AVG(score) AS avg_s, COUNT(*) AS cnt FROM ratings WHERE resource_id = ?", (resource_id,))
        avg_s = round(float(stats["avg_s"] or 0.0), 2)
        cnt = int(stats["cnt"] or 0)
        db.execute("UPDATE resources SET avg_rating = ?, rating_count = ? WHERE id = ?", (avg_s, cnt, resource_id))
        db.commit()

    return {
        "resource_id": resource_id,
        "user_id": user["id"],
        "score": payload.score,
        "avg_rating": avg_s,
        "rating_count": cnt,
    }


@app.get("/api/v1/resources/{resource_id}/comments")
def list_comments(resource_id: int):
    with get_db() as db:
        rows = db.fetchall(
            """
            SELECT cm.id, cm.resource_id, cm.user_id, u.username, cm.body, cm.status, cm.created_at
            FROM comments cm
            JOIN users u ON u.id = cm.user_id
            WHERE cm.resource_id = ? AND cm.status = 'active'
            ORDER BY cm.created_at DESC, cm.id DESC
            """,
            (resource_id,),
        )
        for r in rows:
            r["created_at"] = str(r["created_at"])
        return rows


@app.post("/api/v1/resources/{resource_id}/comments", status_code=201)
def create_comment(resource_id: int, payload: CommentCreateRequest, user: Dict[str, Any] = Depends(require_authenticated_user)):
    safe_body = html.escape(payload.body.strip())
    with get_db() as db:
        res = db.fetchone("SELECT id FROM resources WHERE id = ? AND status = 'active'", (resource_id,))
        if not res:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Resource not found."})
        db.execute(
            "INSERT INTO comments (resource_id, user_id, body, status) VALUES (?, ?, ?, 'active')",
            (resource_id, user["id"], safe_body),
        )
        cnt_row = db.fetchone("SELECT COUNT(*) AS cnt FROM comments WHERE resource_id = ? AND status = 'active'", (resource_id,))
        db.execute("UPDATE resources SET comment_count = ? WHERE id = ?", (cnt_row["cnt"], resource_id))
        db.commit()
        new_cm = db.fetchone(
            """
            SELECT cm.id, cm.resource_id, cm.user_id, u.username, cm.body, cm.status, cm.created_at
            FROM comments cm JOIN users u ON u.id = cm.user_id
            WHERE cm.resource_id = ? AND cm.user_id = ?
            ORDER BY cm.id DESC LIMIT 1
            """,
            (resource_id, user["id"]),
        )
        new_cm["created_at"] = str(new_cm["created_at"])
        return new_cm


@app.delete("/api/v1/comments/{comment_id}")
def delete_comment(comment_id: int, user: Dict[str, Any] = Depends(require_authenticated_user)):
    with get_db() as db:
        cm = db.fetchone("SELECT * FROM comments WHERE id = ?", (comment_id,))
        if not cm:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Comment not found."})
        if cm["user_id"] != user["id"] and user["role"] != "moderator":
            raise HTTPException(status_code=403, detail={"error": "FORBIDDEN", "message": "You can only delete your own comments."})
        rid = cm["resource_id"]
        db.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
        cnt_row = db.fetchone("SELECT COUNT(*) AS cnt FROM comments WHERE resource_id = ? AND status = 'active'", (rid,))
        db.execute("UPDATE resources SET comment_count = ? WHERE id = ?", (cnt_row["cnt"], rid))
        db.commit()
    return {"status": "deleted", "comment_id": comment_id}


# ---------------------------------------------------------------------------
# 6. Collections (Reading Lists) Endpoints
# ---------------------------------------------------------------------------
@app.get("/api/v1/collections")
def list_collections(
    request: Request,
    course_code: Optional[str] = Query(None),
    official_only: bool = Query(False),
    mine: bool = Query(False, description="Only collections owned by the signed-in user (includes private lists)."),
):
    params: List[Any] = []
    if mine:
        me = get_optional_user(request)
        if not me:
            raise HTTPException(status_code=401, detail={"error": "UNAUTHORIZED", "message": "Authentication required. Please sign in."})
        where_clauses = ["col.owner_id = ?"]
        params.append(me["id"])
    else:
        where_clauses = ["col.is_public = 1"]
    if course_code:
        where_clauses.append("c.course_code = ?")
        params.append(course_code.strip().upper())
    if official_only:
        where_clauses.append("col.is_official = 1")
    where_sql = " AND ".join(where_clauses)

    with get_db() as db:
        rows = db.fetchall(
            f"""
            SELECT col.id, col.title, col.description, col.owner_id, u.username AS owner_username,
                   c.course_code, col.is_official, col.is_public, col.created_at,
                   COUNT(ci.id) AS item_count
            FROM collections col
            JOIN users u ON u.id = col.owner_id
            LEFT JOIN categories c ON c.id = col.category_id
            LEFT JOIN collection_items ci ON ci.collection_id = col.id
            WHERE {where_sql}
            GROUP BY col.id, col.title, col.description, col.owner_id, u.username, c.course_code, col.is_official, col.is_public, col.created_at
            ORDER BY col.is_official DESC, item_count DESC, col.id ASC
            """,
            tuple(params),
        )
        for r in rows:
            r["is_official"] = bool(r["is_official"])
            r["is_public"] = bool(r["is_public"])
            r["created_at"] = str(r["created_at"])
        return rows


@app.post("/api/v1/collections", status_code=201)
def create_collection(payload: CollectionCreateRequest, user: Dict[str, Any] = Depends(require_authenticated_user)):
    if payload.is_official and user["role"] not in ("ta", "moderator"):
        raise HTTPException(status_code=403, detail={"error": "TA_ROLE_REQUIRED", "message": "Only Teaching Assistants can publish official course reading lists."})

    with get_db() as db:
        cat_id = None
        if payload.course_code:
            cat = db.fetchone("SELECT id FROM categories WHERE course_code = ?", (payload.course_code.strip().upper(),))
            if cat:
                cat_id = cat["id"]
        safe_title = html.escape(payload.title.strip())
        safe_desc = html.escape(payload.description.strip()) if payload.description else None
        db.execute(
            "INSERT INTO collections (title, description, owner_id, category_id, is_official, is_public) VALUES (?, ?, ?, ?, ?, ?)",
            (safe_title, safe_desc, user["id"], cat_id, 1 if payload.is_official else 0, 1 if payload.is_public else 0),
        )
        db.commit()
        col = db.fetchone(
            """
            SELECT col.id, col.title, col.description, col.owner_id, u.username AS owner_username,
                   c.course_code, col.is_official, col.is_public, col.created_at
            FROM collections col
            JOIN users u ON u.id = col.owner_id
            LEFT JOIN categories c ON c.id = col.category_id
            WHERE col.owner_id = ? ORDER BY col.id DESC LIMIT 1
            """,
            (user["id"],),
        )
        col["is_official"] = bool(col["is_official"])
        col["is_public"] = bool(col["is_public"])
        col["item_count"] = 0
        col["created_at"] = str(col["created_at"])
        return col


@app.get("/api/v1/collections/{collection_id}")
def get_collection_detail_route(collection_id: int, request: Request):
    detail = get_collection_detail(collection_id)
    if not detail["is_public"]:
        viewer = get_optional_user(request)
        if not viewer or (viewer["id"] != detail["owner_id"] and viewer["role"] != "moderator"):
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Collection not found."})
    return detail


def get_collection_detail(collection_id: int):
    with get_db() as db:
        col = db.fetchone(
            """
            SELECT col.id, col.title, col.description, col.owner_id, u.username AS owner_username,
                   c.course_code, col.is_official, col.is_public, col.created_at
            FROM collections col
            JOIN users u ON u.id = col.owner_id
            LEFT JOIN categories c ON c.id = col.category_id
            WHERE col.id = ?
            """,
            (collection_id,),
        )
        if not col:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Collection not found."})

        item_rows = db.fetchall(
            """
            SELECT ci.position, ci.notes, r.*, c.course_code, u.username AS uploader_username
            FROM collection_items ci
            JOIN resources r ON r.id = ci.resource_id
            JOIN categories c ON c.id = r.category_id
            LEFT JOIN users u ON u.id = r.uploader_id
            WHERE ci.collection_id = ? AND r.status = 'active'
            ORDER BY ci.position ASC
            """,
            (collection_id,),
        )
        items = [
            {
                "position": ir["position"],
                "notes": ir["notes"],
                "resource": format_resource_summary(db, ir),
            }
            for ir in item_rows
        ]
        col["is_official"] = bool(col["is_official"])
        col["is_public"] = bool(col["is_public"])
        col["item_count"] = len(items)
        col["created_at"] = str(col["created_at"])
        col["items"] = items
        return col


@app.patch("/api/v1/collections/{collection_id}")
def update_collection(collection_id: int, payload: CollectionUpdateRequest, user: Dict[str, Any] = Depends(require_authenticated_user)):
    with get_db() as db:
        col = db.fetchone("SELECT * FROM collections WHERE id = ?", (collection_id,))
        if not col:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Collection not found."})
        if col["owner_id"] != user["id"] and user["role"] != "moderator":
            raise HTTPException(status_code=403, detail={"error": "FORBIDDEN", "message": "Only the collection owner can edit or reorder this list."})
        if payload.title:
            db.execute("UPDATE collections SET title = ? WHERE id = ?", (html.escape(payload.title.strip()), collection_id))
        if payload.description is not None:
            db.execute("UPDATE collections SET description = ? WHERE id = ?", (html.escape(payload.description.strip()), collection_id))
        if payload.ordered_resource_ids is not None:
            for pos, rid in enumerate(payload.ordered_resource_ids, start=1):
                db.execute(
                    "UPDATE collection_items SET position = ? WHERE collection_id = ? AND resource_id = ?",
                    (pos, collection_id, rid),
                )
        db.commit()
    return get_collection_detail(collection_id)


@app.delete("/api/v1/collections/{collection_id}")
def delete_collection(collection_id: int, user: Dict[str, Any] = Depends(require_authenticated_user)):
    with get_db() as db:
        col = db.fetchone("SELECT * FROM collections WHERE id = ?", (collection_id,))
        if not col:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Collection not found."})
        if col["owner_id"] != user["id"] and user["role"] != "moderator":
            raise HTTPException(status_code=403, detail={"error": "FORBIDDEN", "message": "Only the owner can delete this collection."})
        db.execute("DELETE FROM collections WHERE id = ?", (collection_id,))
        db.commit()
    return {"status": "deleted", "collection_id": collection_id}


@app.post("/api/v1/collections/{collection_id}/items", status_code=201)
def add_collection_item(collection_id: int, payload: CollectionItemAddRequest, user: Dict[str, Any] = Depends(require_authenticated_user)):
    with get_db() as db:
        col = db.fetchone("SELECT * FROM collections WHERE id = ?", (collection_id,))
        if not col:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Collection not found."})
        if col["owner_id"] != user["id"] and user["role"] != "moderator":
            raise HTTPException(status_code=403, detail={"error": "FORBIDDEN", "message": "Only the collection owner can add items."})
        res = db.fetchone("SELECT id FROM resources WHERE id = ? AND status = 'active'", (payload.resource_id,))
        if not res:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Resource not found."})
        dup = db.fetchone("SELECT id FROM collection_items WHERE collection_id = ? AND resource_id = ?", (collection_id, payload.resource_id))
        if dup:
            raise HTTPException(status_code=409, detail={"error": "DUPLICATE_ITEM", "message": "This resource is already in the collection."})
        cnt = db.fetchone("SELECT COUNT(*) AS cnt FROM collection_items WHERE collection_id = ?", (collection_id,))
        if cnt and cnt["cnt"] >= settings.AI_MAX_COLLECTION_RESOURCES:
            raise HTTPException(status_code=400, detail={"error": "COLLECTION_FULL", "message": f"Collections are capped at {settings.AI_MAX_COLLECTION_RESOURCES} resources for multi-document AI scope."})
        pos = payload.position or ((cnt["cnt"] if cnt else 0) + 1)
        db.execute(
            "INSERT INTO collection_items (collection_id, resource_id, position, notes) VALUES (?, ?, ?, ?)",
            (collection_id, payload.resource_id, pos, payload.notes),
        )
        db.commit()
    return get_collection_detail(collection_id)


@app.delete("/api/v1/collections/{collection_id}/items/{resource_id}")
def remove_collection_item(collection_id: int, resource_id: int, user: Dict[str, Any] = Depends(require_authenticated_user)):
    with get_db() as db:
        col = db.fetchone("SELECT * FROM collections WHERE id = ?", (collection_id,))
        if not col:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Collection not found."})
        if col["owner_id"] != user["id"] and user["role"] != "moderator":
            raise HTTPException(status_code=403, detail={"error": "FORBIDDEN", "message": "Only the collection owner can remove items."})
        db.execute("DELETE FROM collection_items WHERE collection_id = ? AND resource_id = ?", (collection_id, resource_id))
        db.commit()
    return {"status": "removed", "collection_id": collection_id, "resource_id": resource_id}


# ---------------------------------------------------------------------------
# 7. Grounded AI Study Assistant Endpoint (`/api/v1/ai/ask`)
# ---------------------------------------------------------------------------
@app.post("/api/v1/ai/ask")
def ask_study_assistant(payload: AIAskRequest, user: Dict[str, Any] = Depends(require_authenticated_user)):
    t0 = time.time()
    question = payload.question.strip()

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

        latency_ms = max(1, int((time.time() - t0) * 1000))
        if fallback_used:
            model_used = "mysql-fulltext-fallback"
        elif gemini_enabled() and not not_found:
            model_used = settings.GEMINI_GENERATION_MODEL
        else:
            model_used = "local-extractive"
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
                1 if not_found else 0,
                1 if fallback_used else 0,
                model_used,
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
        "citations": citations,
        "model_used": model_used,
        "latency_ms": latency_ms,
    }


# ---------------------------------------------------------------------------
# 8. Content Reporting & Moderation Queue Endpoints
# ---------------------------------------------------------------------------
@app.post("/api/v1/reports", status_code=201)
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


@app.get("/api/v1/moderation/reports")
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


@app.patch("/api/v1/moderation/reports/{report_id}")
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


# ---------------------------------------------------------------------------
# 9. Frontend Static Serving (`/`)
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def serve_frontend():
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    idx_path = os.path.join(base_dir, "frontend", "index.html")
    if os.path.exists(idx_path):
        with open(idx_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    return HTMLResponse(content="<h1>ScholarPulse MS-3 API Server Running</h1><p>Visit <a href='/docs'>/docs</a> for OpenAPI UI.</p>")
