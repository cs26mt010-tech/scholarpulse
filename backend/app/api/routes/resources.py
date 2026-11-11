
import html
import io
import json
import math
import os
import time

from typing import Any, Dict, List, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)

from app.core.config import settings
from app.db.session import get_db

from app.api.dependencies import require_authenticated_user

from app.schemas.resources import ResourceUpdateRequest

from app.services.rag_service import (
    chunk_text_sliding,
    compute_embedding,
)

from app.services.resource_formatter import format_resource_summary


router = APIRouter(prefix="/api/v1", tags=["Resources"])


@router.get("/categories")
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


@router.get("/tags")
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


@router.get("/resources")
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
            "EXISTS (SELECT 1 FROM resource_tags rt "
            "JOIN tags t ON t.id = rt.tag_id "
            "WHERE rt.resource_id = r.id "
            "AND (t.name = ? OR t.slug = ?))"
        )
        params.extend([tag.strip(), tag.strip().lower()])

    if q and q.strip():
        kw = f"%{q.strip()}%"
        where_clauses.append(
            "(r.title LIKE ? OR r.content_text LIKE ? OR r.source_authors LIKE ?)"
        )
        params.extend([kw, kw, kw])

    where_sql = " AND ".join(where_clauses)

    if sort_by == "newest":
        order_sql = "r.is_official DESC, r.published_on DESC, r.id DESC"
    elif sort_by == "comments":
        order_sql = "r.comment_count DESC, r.avg_rating DESC, r.id ASC"
    else:
        order_sql = (
            "r.is_official DESC, r.avg_rating DESC, "
            "r.rating_count DESC, r.id ASC"
        )

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


@router.post("/resources", status_code=201)
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
        raise HTTPException(
            status_code=400,
            detail={
                "error": "RIGHTS_NOT_CONFIRMED",
                "message": "You must confirm that you have the right to share this material.",
            },
        )

    if is_official and user["role"] not in ("ta", "moderator"):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "TA_ROLE_REQUIRED",
                "message": "Only Teaching Assistants and Moderators can mark resources as official.",
            },
        )

    fname = file.filename or "upload.txt"
    ext = os.path.splitext(fname)[1].lower()

    if ext not in settings.ALLOWED_UPLOAD_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_FILE_TYPE",
                "message": "Only .pdf and .txt files are allowed.",
            },
        )

    raw_bytes = await file.read()
    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024

    if len(raw_bytes) > max_bytes:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "FILE_TOO_LARGE",
                "message": f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit.",
            },
        )

    extracted_text = ""

    if ext == ".txt":
        extracted_text = raw_bytes.decode("utf-8", errors="replace").strip()

    elif ext == ".pdf":
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(raw_bytes))
            pages_txt = [p.extract_text() or "" for p in reader.pages]
            extracted_text = "\n".join(pages_txt).strip()
        except Exception:
            extracted_text = ""

    if len(extracted_text) < 20:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "EMPTY_OR_SCANNED_FILE",
                "message": "Rejected: File contains no extractable text (scanned or empty PDFs cannot be indexed).",
            },
        )

    safe_title = html.escape(title.strip()[:200])
    safe_content = html.escape(extracted_text)

    tldr = (
        safe_content[:220].rsplit(" ", 1)[0] + "..."
        if len(safe_content) > 220
        else safe_content
    )

    with get_db() as db:
        cat = db.fetchone(
            "SELECT id, course_code FROM categories WHERE course_code = ?",
            (course_code.strip().upper(),),
        )

        if not cat:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "INVALID_COURSE",
                    "message": f"Unknown course code: {course_code}",
                },
            )

        source_ref = f"upload-{int(time.time() * 1000)}-{user['id']}"

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

        res_row = db.fetchone(
            "SELECT * FROM resources WHERE source_ref = ?",
            (source_ref,),
        )
        rid = res_row["id"]

        chunks = chunk_text_sliding(
            safe_content,
            chunk_size=800,
            overlap=100,
        )

        for idx, c_txt in enumerate(chunks):
            vec = compute_embedding(c_txt)

            db.execute(
                """
                INSERT INTO resource_chunks (
                    resource_id, chunk_index, chunk_text, char_length,
                    embedding_json, embedding_model
                ) VALUES (?, ?, ?, ?, ?, 'gemini-embedding-001')
                """,
                (rid, idx, c_txt, len(c_txt), json.dumps(vec)),
            )

        tag_list = [t.strip() for t in tags.split(",") if t.strip()]

        for t_name in tag_list:
            slug = t_name.lower().replace(".", "-").replace(" ", "-")

            t_row = db.fetchone(
                "SELECT id FROM tags WHERE slug = ?",
                (slug,),
            )

            if not t_row:
                db.execute(
                    "INSERT INTO tags (name, slug) VALUES (?, ?)",
                    (t_name, slug),
                )
                t_row = db.fetchone(
                    "SELECT id FROM tags WHERE slug = ?",
                    (slug,),
                )

            db.execute(
                "INSERT INTO resource_tags (resource_id, tag_id) VALUES (?, ?)",
                (rid, t_row["id"]),
            )

        db.commit()

        res_row["course_code"] = cat["course_code"]
        res_row["uploader_username"] = user["username"]

        detail = format_resource_summary(db, res_row)
        detail["content_text"] = safe_content
        detail["chunk_count"] = len(chunks)
        detail["file_name"] = fname
        detail["file_size_bytes"] = len(raw_bytes)

        return detail


@router.get("/resources/{resource_id}")
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
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "NOT_FOUND",
                    "message": "Resource not found or unavailable.",
                },
            )

        c_cnt = db.fetchone(
            "SELECT COUNT(*) AS cnt FROM resource_chunks WHERE resource_id = ?",
            (resource_id,),
        )

        detail = format_resource_summary(db, row)
        detail["content_text"] = row["content_text"]
        detail["chunk_count"] = c_cnt["cnt"] if c_cnt else 0
        detail["file_name"] = row.get("file_name")
        detail["file_size_bytes"] = row.get("file_size_bytes")

        return detail


@router.patch("/resources/{resource_id}")
def update_resource(
    resource_id: int,
    payload: ResourceUpdateRequest,
    user: Dict[str, Any] = Depends(require_authenticated_user),
):
    with get_db() as db:
        row = db.fetchone(
            "SELECT * FROM resources WHERE id = ?",
            (resource_id,),
        )

        if not row:
            raise HTTPException(
                status_code=404,
                detail={"error": "NOT_FOUND", "message": "Resource not found."},
            )

        if row["uploader_id"] != user["id"] and user["role"] != "moderator":
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "FORBIDDEN",
                    "message": "You can only edit your own uploaded resources.",
                },
            )

        if payload.title:
            db.execute(
                "UPDATE resources SET title = ? WHERE id = ?",
                (html.escape(payload.title.strip()[:200]), resource_id),
            )

        db.commit()

    return get_resource_detail(resource_id)


@router.delete("/resources/{resource_id}")
def delete_resource(
    resource_id: int,
    user: Dict[str, Any] = Depends(require_authenticated_user),
):
    with get_db() as db:
        row = db.fetchone(
            "SELECT * FROM resources WHERE id = ?",
            (resource_id,),
        )

        if not row:
            raise HTTPException(
                status_code=404,
                detail={"error": "NOT_FOUND", "message": "Resource not found."},
            )

        if row["uploader_id"] != user["id"] and user["role"] != "moderator":
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "FORBIDDEN",
                    "message": "You can only delete your own resources.",
                },
            )

        db.execute("DELETE FROM resources WHERE id = ?", (resource_id,))
        db.commit()

    return {"status": "deleted", "resource_id": resource_id}
