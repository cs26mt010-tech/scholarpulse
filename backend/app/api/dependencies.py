
from typing import Any, Dict, Optional

from fastapi import Depends, HTTPException, Request

from app.core.config import settings
from app.core.security import (
    verify_csrf_token,
    verify_session_cookie_value,
)
from app.db.session import get_db


def get_optional_user(request: Request) -> Optional[Dict[str, Any]]:
    cookie_val = request.cookies.get(settings.SESSION_COOKIE_NAME)
    if not cookie_val:
        return None

    payload = verify_session_cookie_value(cookie_val)
    if not payload:
        return None

    with get_db() as db:
        user = db.fetchone(
            "SELECT id, username, email, bio, programme, profile_photo_path, "
            "email_notifications, public_profile, role, consent_accepted, "
            "created_at FROM users WHERE id = ?",
            (payload["uid"],),
        )
        return user


def require_authenticated_user(request: Request) -> Dict[str, Any]:
    user = get_optional_user(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail={
                "error": "UNAUTHORIZED",
                "message": "Authentication required. Please sign in.",
            },
        )

    # Verify CSRF token on state-changing HTTP methods.
    if request.method in ("POST", "PUT", "PATCH", "DELETE"):
        cookie_val = request.cookies.get(settings.SESSION_COOKIE_NAME, "")
        csrf_hdr = request.headers.get("X-CSRF-Token", "")

        if not verify_csrf_token(cookie_val, csrf_hdr):
            raise HTTPException(
                status_code=403,
                detail={
                    "error": "CSRF_INVALID",
                    "message": "Missing or invalid X-CSRF-Token header.",
                },
            )

    return user


def require_moderator(
    user: Dict[str, Any] = Depends(require_authenticated_user),
) -> Dict[str, Any]:
    if user["role"] != "moderator":
        raise HTTPException(
            status_code=403,
            detail={
                "error": "FORBIDDEN",
                "message": "Moderator role required for this action.",
            },
        )

    return user
