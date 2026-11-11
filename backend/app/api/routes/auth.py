
import html
import uuid
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse

from app.api.dependencies import (
    get_optional_user,
    require_authenticated_user,
)
from app.core.config import settings
from app.core.security import (
    create_session_cookie_value,
    generate_csrf_token,
    hash_password_argon2id,
    verify_password_argon2id,
)
from app.db.session import get_db
from app.schemas.auth import (
    PasswordChangeRequest,
    UserLoginRequest,
    UserRegisterRequest,
    UserUpdateRequest,
)
from app.services.resource_formatter import format_resource_summary


router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/register", status_code=201)
def register_user(payload: UserRegisterRequest, response: Response):
    if not payload.consent_accepted:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "CONSENT_REQUIRED",
                "message": "You must accept the DPDP Act 2023 data collection consent notice to create an account.",
            },
        )

    uname = html.escape(payload.username.strip())
    email = payload.email.strip().lower()
    bio = html.escape(payload.bio.strip()) if payload.bio else None

    with get_db() as db:
        dup = db.fetchone(
            "SELECT id FROM users WHERE username = ? OR email = ?",
            (uname, email),
        )
        if dup:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "DUPLICATE_USER",
                    "message": "Username or university email is already registered.",
                },
            )

        pw_hash = hash_password_argon2id(payload.password)
        db.execute(
            "INSERT INTO users (username, email, password_hash, bio, role, consent_accepted) "
            "VALUES (?, ?, ?, ?, 'student', 1)",
            (uname, email, pw_hash, bio),
        )
        db.commit()

        user = db.fetchone(
            "SELECT id, username, email, bio, programme, profile_photo_path, "
            "email_notifications, public_profile, role, consent_accepted, created_at "
            "FROM users WHERE email = ?",
            (email,),
        )

    cookie_val = create_session_cookie_value(
        user["id"], user["role"], user["username"]
    )
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
    user["email_notifications"] = bool(user.get("email_notifications", 1))
    user["public_profile"] = bool(user.get("public_profile", 1))
    user["profile_photo_url"] = (
        "/api/v1/auth/me/photo"
        if user.get("profile_photo_path")
        else None
    )
    user.pop("profile_photo_path", None)
    user["csrf_token"] = csrf_token

    return user


@router.post("/login")
def login_user(payload: UserLoginRequest, response: Response):
    email = payload.email.strip().lower()

    with get_db() as db:
        user = db.fetchone(
            "SELECT * FROM users WHERE LOWER(email) = ? OR username = ?",
            (email, payload.email.strip()),
        )
        if not user or not verify_password_argon2id(
            payload.password, user["password_hash"]
        ):
            raise HTTPException(
                status_code=401,
                detail={
                    "error": "INVALID_CREDENTIALS",
                    "message": "We couldn't sign you in with that email and password. Try again.",
                },
            )

    cookie_val = create_session_cookie_value(
        user["id"], user["role"], user["username"]
    )
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
        "programme": user.get("programme"),
        "profile_photo_url": (
            "/api/v1/auth/me/photo"
            if user.get("profile_photo_path")
            else None
        ),
        "email_notifications": bool(user.get("email_notifications", 1)),
        "public_profile": bool(user.get("public_profile", 1)),
        "role": user["role"],
        "consent_accepted": bool(user["consent_accepted"]),
        "created_at": str(user["created_at"]),
    }

    return {"user": public_user, "csrf_token": csrf_token}


@router.post("/logout")
def logout_user(
    response: Response,
    user: Dict[str, Any] = Depends(require_authenticated_user),
):
    response.delete_cookie(key=settings.SESSION_COOKIE_NAME)
    return {"status": "logged_out"}


@router.get("/me")
def get_me(request: Request):
    user = get_optional_user(request)

    if not user:
        raise HTTPException(
            status_code=401,
            detail={"error": "UNAUTHORIZED", "message": "Not authenticated"},
        )

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

        formatted_uploads = [
            format_resource_summary(db, r) for r in uploads
        ]

    user["consent_accepted"] = bool(user["consent_accepted"])
    user["email_notifications"] = bool(user.get("email_notifications", 1))
    user["public_profile"] = bool(user.get("public_profile", 1))
    user["profile_photo_url"] = (
        "/api/v1/auth/me/photo"
        if user.get("profile_photo_path")
        else None
    )
    user.pop("profile_photo_path", None)
    user["csrf_token"] = generate_csrf_token(cookie_val)
    user["uploads"] = formatted_uploads
    user["collections_count"] = len(colls)

    return user


@router.patch("/me")
def update_me(
    payload: UserUpdateRequest,
    user: Dict[str, Any] = Depends(require_authenticated_user),
):
    with get_db() as db:
        if payload.username is not None:
            uname = html.escape(payload.username.strip())
            dup = db.fetchone(
                "SELECT id FROM users WHERE username = ? AND id != ?",
                (uname, user["id"]),
            )
            if dup:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "error": "DUPLICATE_USER",
                        "message": "That username is already taken.",
                    },
                )
            db.execute(
                "UPDATE users SET username = ? WHERE id = ?",
                (uname, user["id"]),
            )

        if payload.bio is not None:
            db.execute(
                "UPDATE users SET bio = ? WHERE id = ?",
                (html.escape(payload.bio.strip()), user["id"]),
            )

        if payload.programme is not None:
            db.execute(
                "UPDATE users SET programme = ? WHERE id = ?",
                (html.escape(payload.programme.strip()), user["id"]),
            )

        if payload.email_notifications is not None:
            db.execute(
                "UPDATE users SET email_notifications = ? WHERE id = ?",
                (int(payload.email_notifications), user["id"]),
            )

        if payload.public_profile is not None:
            db.execute(
                "UPDATE users SET public_profile = ? WHERE id = ?",
                (int(payload.public_profile), user["id"]),
            )

        db.commit()

        updated = db.fetchone(
            "SELECT id, username, email, bio, programme, profile_photo_path, "
            "email_notifications, public_profile, role, consent_accepted, created_at "
            "FROM users WHERE id = ?",
            (user["id"],),
        )

        updated["consent_accepted"] = bool(updated["consent_accepted"])
        updated["email_notifications"] = bool(updated["email_notifications"])
        updated["public_profile"] = bool(updated["public_profile"])
        updated["profile_photo_url"] = (
            "/api/v1/auth/me/photo"
            if updated.get("profile_photo_path")
            else None
        )
        updated.pop("profile_photo_path", None)

        return updated


@router.post("/me/photo", status_code=200)
async def upload_profile_photo(
    file: UploadFile = File(...),
    user: Dict[str, Any] = Depends(require_authenticated_user),
):
    """Upload a profile image (JPEG/PNG/WebP, maximum 2 MB)."""
    allowed = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
    }

    if file.content_type not in allowed:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_PHOTO_TYPE",
                "message": "Use a JPEG, PNG or WebP image.",
            },
        )

    content = await file.read(2 * 1024 * 1024 + 1)

    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "PHOTO_TOO_LARGE",
                "message": "Profile photos must be 2 MB or smaller.",
            },
        )

    if not content:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "EMPTY_PHOTO",
                "message": "The selected image is empty.",
            },
        )

    valid = (
        file.content_type == "image/jpeg"
        and content.startswith(b"\xff\xd8\xff")
    ) or (
        file.content_type == "image/png"
        and content.startswith(b"\x89PNG\r\n\x1a\n")
    ) or (
        file.content_type == "image/webp"
        and content[:4] == b"RIFF"
        and content[8:12] == b"WEBP"
    )

    if not valid:
        raise HTTPException(
            status_code=400,
            detail={
                "error": "INVALID_PHOTO",
                "message": "The uploaded file does not match its image type.",
            },
        )

    photo_dir = Path(settings.UPLOAD_STORAGE_DIR) / "profile_photos"
    photo_dir.mkdir(parents=True, exist_ok=True)

    filename = f"user-{user['id']}-{uuid.uuid4().hex}{allowed[file.content_type]}"
    target = photo_dir / filename
    target.write_bytes(content)

    with get_db() as db:
        old = db.fetchone(
            "SELECT profile_photo_path FROM users WHERE id = ?",
            (user["id"],),
        )
        db.execute(
            "UPDATE users SET profile_photo_path = ? WHERE id = ?",
            (str(target), user["id"]),
        )
        db.commit()

    if old and old.get("profile_photo_path"):
        try:
            Path(old["profile_photo_path"]).unlink(missing_ok=True)
        except OSError:
            pass

    return {"profile_photo_url": "/api/v1/auth/me/photo"}


@router.get("/me/photo")
def get_profile_photo(
    user: Dict[str, Any] = Depends(require_authenticated_user),
):
    path = user.get("profile_photo_path")

    if not path or not Path(path).is_file():
        raise HTTPException(
            status_code=404,
            detail={
                "error": "PHOTO_NOT_FOUND",
                "message": "No profile photo has been uploaded.",
            },
        )

    return FileResponse(path)


@router.put("/password")
def change_password(
    payload: PasswordChangeRequest,
    user: Dict[str, Any] = Depends(require_authenticated_user),
):
    with get_db() as db:
        row = db.fetchone(
            "SELECT password_hash FROM users WHERE id = ?",
            (user["id"],),
        )

        if not row or not verify_password_argon2id(
            payload.current_password, row["password_hash"]
        ):
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "INVALID_PASSWORD",
                    "message": "Current password is incorrect.",
                },
            )

        new_hash = hash_password_argon2id(payload.new_password)
        db.execute(
            "UPDATE users SET password_hash = ? WHERE id = ?",
            (new_hash, user["id"]),
        )
        db.commit()

    return {"status": "password_updated"}


@router.delete("/me")
def delete_own_account(
    response: Response,
    user: Dict[str, Any] = Depends(require_authenticated_user),
):
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

    return {
        "status": "account_deleted",
        "deleted_user_id": user["id"],
    }
