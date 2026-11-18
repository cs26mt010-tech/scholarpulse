"""Community API routes."""
import html
from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException

from app.api.dependencies import (
    require_authenticated_user,
)
from app.db.session import get_db
from app.schemas.community import CommentCreateRequest, RatingRequest

router = APIRouter()

@router.post('/api/v1/resources/{resource_id}/ratings')
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

@router.get('/api/v1/resources/{resource_id}/comments')
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

@router.post('/api/v1/resources/{resource_id}/comments', status_code=201)
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

@router.delete('/api/v1/comments/{comment_id}')
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
