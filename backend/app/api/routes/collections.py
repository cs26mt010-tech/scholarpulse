
import html
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.dependencies import (
    get_optional_user,
    require_authenticated_user,
)
from app.core.config import settings
from app.db.session import get_db
from app.schemas.collections import (
    CollectionCreateRequest,
    CollectionUpdateRequest,
    CollectionItemAddRequest,
)
from app.services.resource_formatter import format_resource_summary


router = APIRouter(prefix="/api/v1", tags=["Collections"])


@router.get("/collections")
def list_collections(
    request: Request,
    course_code: Optional[str] = Query(None),
    official_only: bool = Query(False),
    mine: bool = Query(
        False,
        description="Only collections owned by the signed-in user (includes private lists).",
    ),
):
    params: List[Any] = []

    if mine:
        me = get_optional_user(request)

        if not me:
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "UNAUTHORIZED",
                    "message": "Authentication required. Please sign in.",
                },
            )

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
            SELECT col.id, col.title, col.description, col.owner_id,
                   u.username AS owner_username, c.course_code,
                   col.is_official, col.is_public, col.created_at,
                   COUNT(ci.id) AS item_count
            FROM collections col
            JOIN users u ON u.id = col.owner_id
            LEFT JOIN categories c ON c.id = col.category_id
            LEFT JOIN collection_items ci ON ci.collection_id = col.id
            WHERE {where_sql}
            GROUP BY col.id, col.title, col.description, col.owner_id,
                     u.username, c.course_code, col.is_official,
                     col.is_public, col.created_at
            ORDER BY col.is_official DESC, item_count DESC, col.id ASC
            """,
            tuple(params),
        )

        for r in rows:
            r["is_official"] = bool(r["is_official"])
            r["is_public"] = bool(r["is_public"])
            r["created_at"] = str(r["created_at"])

        return rows


@router.post("/collections", status_code=201)
def create_collection(
    payload: CollectionCreateRequest,
    user: Dict[str, Any] = Depends(require_authenticated_user),
):
    if payload.is_official and user["role"] not in ("ta", "moderator"):
        raise HTTPException(
            status_code=403,
            detail={
                "error": "TA_ROLE_REQUIRED",
                "message": "Only Teaching Assistants can publish official course reading lists.",
            },
        )

    with get_db() as db:
        cat_id = None

        if payload.course_code:
            cat = db.fetchone(
                "SELECT id FROM categories WHERE course_code = ?",
                (payload.course_code.strip().upper(),),
            )

            if cat:
                cat_id = cat["id"]

        safe_title = html.escape(payload.title.strip())
        safe_desc = (
            html.escape(payload.description.strip())
            if payload.description
            else None
        )

        db.execute(
            """
            INSERT INTO collections (
                title, description, owner_id, category_id,
                is_official, is_public
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                safe_title,
                safe_desc,
                user["id"],
                cat_id,
                1 if payload.is_official else 0,
                1 if payload.is_public else 0,
            ),
        )

        db.commit()

        col = db.fetchone(
            """
            SELECT col.id, col.title, col.description, col.owner_id,
                   u.username AS owner_username, c.course_code,
                   col.is_official, col.is_public, col.created_at
            FROM collections col
            JOIN users u ON u.id = col.owner_id
            LEFT JOIN categories c ON c.id = col.category_id
            WHERE col.owner_id = ?
            ORDER BY col.id DESC
            LIMIT 1
            """,
            (user["id"],),
        )

        col["is_official"] = bool(col["is_official"])
        col["is_public"] = bool(col["is_public"])
        col["item_count"] = 0
        col["created_at"] = str(col["created_at"])

        return col


def get_collection_detail(collection_id: int):
    with get_db() as db:
        col = db.fetchone(
            """
            SELECT col.id, col.title, col.description, col.owner_id,
                   u.username AS owner_username, c.course_code,
                   col.is_official, col.is_public, col.created_at
            FROM collections col
            JOIN users u ON u.id = col.owner_id
            LEFT JOIN categories c ON c.id = col.category_id
            WHERE col.id = ?
            """,
            (collection_id,),
        )

        if not col:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "NOT_FOUND",
                    "message": "Collection not found.",
                },
            )

        item_rows = db.fetchall(
            """
            SELECT ci.position, ci.notes, r.*, c.course_code,
                   u.username AS uploader_username
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


@router.get("/collections/{collection_id}")
def get_collection_detail_route(
    collection_id: int,
    request: Request,
):
    detail = get_collection_detail(collection_id)

    if not detail["is_public"]:
        viewer = get_optional_user(request)

        if (
            not viewer
            or (
                viewer["id"] != detail["owner_id"]
                and viewer["role"] != "moderator"
            )
        ):
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "NOT_FOUND",
                    "message": "Collection not found.",
                },
            )

    return detail


@router.patch("/collections/{collection_id}")
def update_collection(
    collection_id: int,
    payload: CollectionUpdateRequest,
    user: Dict[str, Any] = Depends(require_authenticated_user),
):
    with get_db() as db:
        col = db.fetchone(
            "SELECT * FROM collections WHERE id = ?",
            (collection_id,),
        )

        if not col:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "NOT_FOUND",
                    "message": "Collection not found.",
                },
            )

        if col["owner_id"] != user["id"] and user["role"] != "moderator":
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "FORBIDDEN",
                    "message": "Only the collection owner can edit or reorder this list.",
                },
            )

        if payload.title:
            db.execute(
                "UPDATE collections SET title = ? WHERE id = ?",
                (html.escape(payload.title.strip()), collection_id),
            )

        if payload.description is not None:
            db.execute(
                "UPDATE collections SET description = ? WHERE id = ?",
                (
                    html.escape(payload.description.strip()),
                    collection_id,
                ),
            )

        if payload.ordered_resource_ids is not None:
            for pos, rid in enumerate(
                payload.ordered_resource_ids,
                start=1,
            ):
                db.execute(
                    """
                    UPDATE collection_items
                    SET position = ?
                    WHERE collection_id = ? AND resource_id = ?
                    """,
                    (pos, collection_id, rid),
                )

        db.commit()

    return get_collection_detail(collection_id)


@router.delete("/collections/{collection_id}")
def delete_collection(
    collection_id: int,
    user: Dict[str, Any] = Depends(require_authenticated_user),
):
    with get_db() as db:
        col = db.fetchone(
            "SELECT * FROM collections WHERE id = ?",
            (collection_id,),
        )

        if not col:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "NOT_FOUND",
                    "message": "Collection not found.",
                },
            )

        if col["owner_id"] != user["id"] and user["role"] != "moderator":
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "FORBIDDEN",
                    "message": "Only the owner can delete this collection.",
                },
            )

        db.execute(
            "DELETE FROM collections WHERE id = ?",
            (collection_id,),
        )
        db.commit()

    return {"status": "deleted", "collection_id": collection_id}


@router.post("/collections/{collection_id}/items", status_code=201)
def add_collection_item(
    collection_id: int,
    payload: CollectionItemAddRequest,
    user: Dict[str, Any] = Depends(require_authenticated_user),
):
    with get_db() as db:
        col = db.fetchone(
            "SELECT * FROM collections WHERE id = ?",
            (collection_id,),
        )

        if not col:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "NOT_FOUND",
                    "message": "Collection not found.",
                },
            )

        if col["owner_id"] != user["id"] and user["role"] != "moderator":
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "FORBIDDEN",
                    "message": "Only the collection owner can add items.",
                },
            )

        res = db.fetchone(
            "SELECT id FROM resources WHERE id = ? AND status = 'active'",
            (payload.resource_id,),
        )

        if not res:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "NOT_FOUND",
                    "message": "Resource not found.",
                },
            )

        dup = db.fetchone(
            """
            SELECT id FROM collection_items
            WHERE collection_id = ? AND resource_id = ?
            """,
            (collection_id, payload.resource_id),
        )

        if dup:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": "DUPLICATE_ITEM",
                    "message": "This resource is already in the collection.",
                },
            )

        cnt = db.fetchone(
            "SELECT COUNT(*) AS cnt FROM collection_items WHERE collection_id = ?",
            (collection_id,),
        )

        if cnt and cnt["cnt"] >= settings.AI_MAX_COLLECTION_RESOURCES:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "COLLECTION_FULL",
                    "message": (
                        f"Collections are capped at "
                        f"{settings.AI_MAX_COLLECTION_RESOURCES} resources "
                        "for multi-document AI scope."
                    ),
                },
            )

        pos = payload.position or ((cnt["cnt"] if cnt else 0) + 1)

        db.execute(
            """
            INSERT INTO collection_items (
                collection_id, resource_id, position, notes
            ) VALUES (?, ?, ?, ?)
            """,
            (
                collection_id,
                payload.resource_id,
                pos,
                payload.notes,
            ),
        )

        db.commit()

    return get_collection_detail(collection_id)


@router.delete("/collections/{collection_id}/items/{resource_id}")
def remove_collection_item(
    collection_id: int,
    resource_id: int,
    user: Dict[str, Any] = Depends(require_authenticated_user),
):
    with get_db() as db:
        col = db.fetchone(
            "SELECT * FROM collections WHERE id = ?",
            (collection_id,),
        )

        if not col:
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "NOT_FOUND",
                    "message": "Collection not found.",
                },
            )

        if col["owner_id"] != user["id"] and user["role"] != "moderator":
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "FORBIDDEN",
                    "message": "Only the collection owner can remove items.",
                },
            )

        db.execute(
            """
            DELETE FROM collection_items
            WHERE collection_id = ? AND resource_id = ?
            """,
            (collection_id, resource_id),
        )
        db.commit()

    return {
        "status": "removed",
        "collection_id": collection_id,
        "resource_id": resource_id,
    }
