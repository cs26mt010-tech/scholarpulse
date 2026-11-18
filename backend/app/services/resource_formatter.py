"""Shared resource serialization helpers."""
from typing import Any, Dict


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
