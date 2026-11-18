"""Auth API routes."""
import hashlib
import html
import re
import secrets
import uuid
import urllib.parse
import httpx
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict

from fastapi import APIRouter, Depends, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from app.api.dependencies import (
    _send_verification_email,
    _send_security_email,
    _set_login_session,
    get_optional_user,
    require_authenticated_user,
)
from app.core.config import settings
from app.core.security import (
    generate_csrf_token,
    hash_password_argon2id,
    verify_password_argon2id,
)
from app.db.session import get_db
from app.schemas.auth import (
    EmailOnlyRequest,
    EmailVerificationRequest,
    PasswordResetRequest,
    PasswordResetConfirmRequest,
    GoogleOAuthStartRequest,
    PasswordChangeRequest,
    UserLoginRequest,
    UserRegisterRequest,
    UserUpdateRequest,
)
from app.services.resource_formatter import format_resource_summary

router = APIRouter()

@router.post('/api/v1/auth/register', status_code=201)
def register_user(payload: UserRegisterRequest):
    if not payload.consent_accepted:
        raise HTTPException(status_code=400, detail={"error": "CONSENT_REQUIRED", "message": "You must accept the DPDP Act 2023 data collection consent notice to create an account."})
    uname = html.escape(payload.username.strip())
    email = payload.email.strip().lower()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._%+-]*@gmail\.com", email) or ".." in email.split("@", 1)[0] or email.split("@", 1)[0].endswith("."):
        raise HTTPException(status_code=400, detail={"error": "GMAIL_REQUIRED", "message": "Enter a valid @gmail.com email address."})
    bio = html.escape(payload.bio.strip()) if payload.bio else None
    code = f"{secrets.randbelow(1000000):06d}"
    code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
    expires = datetime.utcnow() + timedelta(minutes=settings.EMAIL_VERIFICATION_TTL_MINUTES)

    with get_db() as db:
        dup = db.fetchone("SELECT id FROM users WHERE username = ? OR email = ?", (uname, email))
        if dup:
            raise HTTPException(status_code=400, detail={"error": "DUPLICATE_USER", "message": "Username or Gmail address is already registered."})
        pw_hash = hash_password_argon2id(payload.password)
        db.execute(
            "INSERT INTO users (username, email, password_hash, bio, role, consent_accepted, email_verified, verification_code_hash, verification_expires_at, verification_attempts) VALUES (?, ?, ?, ?, 'student', 1, 0, ?, ?, 0)",
            (uname, email, pw_hash, bio, code_hash, expires),
        )
        db.commit()

    try:
        _send_verification_email(email, code)
    except HTTPException:
        with get_db() as db:
            db.execute("DELETE FROM users WHERE email = ? AND email_verified = 0", (email,))
            db.commit()
        raise
    return {"message": "Verification code sent. Check your Gmail inbox.", "email": email, "expires_in_minutes": settings.EMAIL_VERIFICATION_TTL_MINUTES}

@router.post('/api/v1/auth/resend-verification')
def resend_verification(payload: EmailOnlyRequest):
    email = payload.email.strip().lower()
    if not email.endswith("@gmail.com"):
        raise HTTPException(status_code=400, detail={"error": "GMAIL_REQUIRED", "message": "Only @gmail.com addresses are allowed."})
    with get_db() as db:
        user = db.fetchone("SELECT id, email_verified FROM users WHERE LOWER(email) = ?", (email,))
        if not user or user.get("email_verified"):
            return {"message": "If the account needs verification, a new code has been sent."}
        code = f"{secrets.randbelow(1000000):06d}"
        code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
        expires = datetime.utcnow() + timedelta(minutes=settings.EMAIL_VERIFICATION_TTL_MINUTES)
        db.execute("UPDATE users SET verification_code_hash = ?, verification_expires_at = ?, verification_attempts = 0 WHERE id = ?", (code_hash, expires, user["id"]))
        db.commit()
    _send_verification_email(email, code)
    return {"message": "If the account needs verification, a new code has been sent."}

@router.post('/api/v1/auth/verify-email')
def verify_email(payload: EmailVerificationRequest, response: Response):
    email = payload.email.strip().lower()
    if not email.endswith("@gmail.com"):
        raise HTTPException(status_code=400, detail={"error": "GMAIL_REQUIRED", "message": "Only @gmail.com addresses are allowed."})
    supplied_hash = hashlib.sha256(payload.code.encode("utf-8")).hexdigest()
    with get_db() as db:
        user = db.fetchone("SELECT * FROM users WHERE LOWER(email) = ?", (email,))
        if not user:
            raise HTTPException(status_code=400, detail={"error": "INVALID_VERIFICATION", "message": "Invalid email or verification code."})
        if user.get("email_verified"):
            raise HTTPException(status_code=400, detail={"error": "ALREADY_VERIFIED", "message": "This email is already verified. Please sign in."})
        expires = user.get("verification_expires_at")
        if isinstance(expires, str):
            expires = datetime.fromisoformat(expires)
        if int(user.get("verification_attempts") or 0) >= 5:
            raise HTTPException(status_code=429, detail={"error": "TOO_MANY_ATTEMPTS", "message": "Too many incorrect codes. Request a new verification code."})
        if not user.get("verification_code_hash") or not secrets.compare_digest(user["verification_code_hash"], supplied_hash) or not expires or expires < datetime.utcnow():
            db.execute("UPDATE users SET verification_attempts = verification_attempts + 1 WHERE id = ?", (user["id"],))
            db.commit()
            raise HTTPException(status_code=400, detail={"error": "INVALID_OR_EXPIRED_CODE", "message": "The verification code is invalid or expired. Request a new code."})
        db.execute("UPDATE users SET email_verified = 1, verification_code_hash = NULL, verification_expires_at = NULL, verification_attempts = 0 WHERE id = ?", (user["id"],))
        db.commit()
        verified_user = db.fetchone("SELECT id, username, email, bio, programme, profile_photo_path, email_notifications, public_profile, role, consent_accepted, created_at FROM users WHERE id = ?", (user["id"],))
    csrf_token = _set_login_session(response, verified_user)
    verified_user["consent_accepted"] = bool(verified_user["consent_accepted"])
    verified_user["email_notifications"] = bool(verified_user.get("email_notifications", 1))
    verified_user["public_profile"] = bool(verified_user.get("public_profile", 1))
    verified_user["profile_photo_url"] = "/api/v1/auth/me/photo" if verified_user.get("profile_photo_path") else None
    verified_user.pop("profile_photo_path", None)
    return {"user": verified_user, "csrf_token": csrf_token, "message": "Email verified successfully."}

@router.post('/api/v1/auth/login')
def login_user(payload: UserLoginRequest, response: Response):
    email = payload.email.strip().lower()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._%+-]*@gmail\.com", email) or ".." in email.split("@", 1)[0] or email.split("@", 1)[0].endswith("."):
        raise HTTPException(status_code=400, detail={"error": "GMAIL_REQUIRED", "message": "Enter a valid @gmail.com email address."})
    with get_db() as db:
        user = db.fetchone("SELECT * FROM users WHERE LOWER(email) = ?", (email,))
        if not user or not verify_password_argon2id(payload.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail={"error": "INVALID_CREDENTIALS", "message": "We couldn't sign you in with that email and password. Try again."})
        if not user.get("email_verified"):
            raise HTTPException(status_code=403, detail={"error": "EMAIL_NOT_VERIFIED", "message": "Verify your Gmail address before signing in."})

    csrf_token = _set_login_session(response, user)
    public_user = {
        "id": user["id"],
        "username": user["username"],
        "email": user["email"],
        "bio": user["bio"],
        "programme": user.get("programme"),
        "profile_photo_url": "/api/v1/auth/me/photo" if user.get("profile_photo_path") else None,
        "email_notifications": bool(user.get("email_notifications", 1)),
        "public_profile": bool(user.get("public_profile", 1)),
        "role": user["role"],
        "consent_accepted": bool(user["consent_accepted"]),
        "created_at": str(user["created_at"]),
    }
    return {"user": public_user, "csrf_token": csrf_token}

@router.post('/api/v1/auth/password/forgot')
def forgot_password(payload: PasswordResetRequest):
    """Send a short-lived reset code; response does not reveal whether an account exists."""
    email = payload.email.strip().lower()
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._%+-]*@gmail\.com", email) or ".." in email.split("@", 1)[0]:
        raise HTTPException(status_code=400, detail={"error": "GMAIL_REQUIRED", "message": "Enter a valid Gmail address."})
    with get_db() as db:
        user = db.fetchone("SELECT id, email_verified FROM users WHERE LOWER(email) = ?", (email,))
        if not user or not user.get("email_verified"):
            return {"message": "If a verified account exists for that Gmail address, a reset code has been sent."}
        code = f"{secrets.randbelow(1000000):06d}"
        code_hash = hashlib.sha256(code.encode()).hexdigest()
        expires = datetime.utcnow() + timedelta(minutes=settings.PASSWORD_RESET_TTL_MINUTES)
        db.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user["id"],))
        db.execute("INSERT INTO password_reset_tokens (user_id, code_hash, expires_at, attempts) VALUES (?, ?, ?, 0)", (user["id"], code_hash, expires))
        db.commit()
    try:
        _send_security_email(email, "Reset your ScholarPulse password", f"Your password reset code is {code}.\n\nIt expires in {settings.PASSWORD_RESET_TTL_MINUTES} minutes. If you did not request this, ignore this email.")
    except HTTPException:
        with get_db() as db:
            db.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user["id"],))
            db.commit()
        raise
    return {"message": "If a verified account exists for that Gmail address, a reset code has been sent."}


@router.post('/api/v1/auth/password/reset')
def reset_password(payload: PasswordResetConfirmRequest):
    email = payload.email.strip().lower()
    supplied_hash = hashlib.sha256(payload.code.encode()).hexdigest()
    with get_db() as db:
        user = db.fetchone("SELECT id FROM users WHERE LOWER(email) = ? AND email_verified = 1", (email,))
        if not user:
            raise HTTPException(status_code=400, detail={"error": "INVALID_RESET_CODE", "message": "Invalid or expired reset code."})
        token = db.fetchone("SELECT * FROM password_reset_tokens WHERE user_id = ? ORDER BY created_at DESC LIMIT 1", (user["id"],))
        expires = token.get("expires_at") if token else None
        if isinstance(expires, str):
            expires = datetime.fromisoformat(expires)
        if not token or int(token.get("attempts") or 0) >= 5 or not secrets.compare_digest(token["code_hash"], supplied_hash) or not expires or expires < datetime.utcnow():
            if token and int(token.get("attempts") or 0) < 5:
                db.execute("UPDATE password_reset_tokens SET attempts = attempts + 1 WHERE id = ?", (token["id"],))
                db.commit()
            raise HTTPException(status_code=400, detail={"error": "INVALID_RESET_CODE", "message": "Invalid or expired reset code. Request a new one if needed."})
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (hash_password_argon2id(payload.new_password), user["id"]))
        db.execute("DELETE FROM password_reset_tokens WHERE user_id = ?", (user["id"],))
        db.commit()
    return {"status": "password_reset", "message": "Password updated. You can now sign in."}


@router.post('/api/v1/auth/google/start')
def google_oauth_start(payload: GoogleOAuthStartRequest, response: Response):
    if not payload.consent_accepted:
        raise HTTPException(status_code=400, detail={"error": "CONSENT_REQUIRED", "message": "Accept the ScholarPulse data notice before continuing with Google."})
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise HTTPException(status_code=503, detail={"error": "GOOGLE_OAUTH_NOT_CONFIGURED", "message": "Google sign-in is not configured yet. Add Google OAuth credentials to .env."})
    state = secrets.token_urlsafe(32)
    response.set_cookie("sp_google_oauth_state", state, httponly=True, secure=settings.SESSION_COOKIE_SECURE, samesite="lax", max_age=600)
    params = {
        "client_id": settings.GOOGLE_CLIENT_ID,
        "redirect_uri": settings.GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    return {"authorization_url": "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(params)}


@router.get('/api/v1/auth/google/callback')
def google_oauth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    expected_state = request.cookies.get("sp_google_oauth_state", "")
    if error or not code or not expected_state or not secrets.compare_digest(state, expected_state):
        result = RedirectResponse(url="/?auth_error=google_signin_failed", status_code=303)
        result.delete_cookie("sp_google_oauth_state")
        return result
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        result = RedirectResponse(url="/?auth_error=google_not_configured", status_code=303)
        result.delete_cookie("sp_google_oauth_state")
        return result
    try:
        token_response = httpx.post("https://oauth2.googleapis.com/token", data={
            "code": code, "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": settings.GOOGLE_REDIRECT_URI, "grant_type": "authorization_code",
        }, timeout=15)
        token_response.raise_for_status()
        access_token = token_response.json().get("access_token")
        profile_response = httpx.get("https://openidconnect.googleapis.com/v1/userinfo", headers={"Authorization": f"Bearer {access_token}"}, timeout=15)
        profile_response.raise_for_status()
        profile = profile_response.json()
    except Exception:
        result = RedirectResponse(url="/?auth_error=google_exchange_failed", status_code=303)
        result.delete_cookie("sp_google_oauth_state")
        return result
    email = str(profile.get("email", "")).strip().lower()
    if not profile.get("email_verified") or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._%+-]*@gmail\.com", email):
        result = RedirectResponse(url="/?auth_error=google_email_unverified", status_code=303)
        result.delete_cookie("sp_google_oauth_state")
        return result
    with get_db() as db:
        user = db.fetchone("SELECT * FROM users WHERE LOWER(email) = ?", (email,))
        if user:
            if not user.get("email_verified"):
                db.execute("UPDATE users SET email_verified = 1, verification_code_hash = NULL, verification_expires_at = NULL, verification_attempts = 0 WHERE id = ?", (user["id"],))
                db.commit()
                user = db.fetchone("SELECT * FROM users WHERE id = ?", (user["id"],))
        else:
            base_name = re.sub(r"[^A-Za-z0-9_]", "_", email.split("@", 1)[0])[:40].strip("_") or "google_user"
            username = base_name
            suffix = 1
            while db.fetchone("SELECT id FROM users WHERE username = ?", (username,)):
                suffix += 1
                username = f"{base_name[:44]}_{suffix}"
            random_password = secrets.token_urlsafe(48)
            db.execute("INSERT INTO users (username, email, password_hash, role, consent_accepted, email_verified) VALUES (?, ?, ?, 'student', 1, 1)", (username, email, hash_password_argon2id(random_password)))
            db.commit()
            user = db.fetchone("SELECT * FROM users WHERE LOWER(email) = ?", (email,))
    result = RedirectResponse(url="/", status_code=303, headers={"Cache-Control": "no-store"})
    result.delete_cookie("sp_google_oauth_state")
    _set_login_session(result, user)
    return result


@router.post('/api/v1/auth/logout')
def logout_user(response: Response, user: Dict[str, Any] = Depends(require_authenticated_user)):
    response.delete_cookie(key=settings.SESSION_COOKIE_NAME)
    return {"status": "logged_out"}

@router.get('/api/v1/auth/me')
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
    user["email_notifications"] = bool(user.get("email_notifications", 1))
    user["public_profile"] = bool(user.get("public_profile", 1))
    user["profile_photo_url"] = "/api/v1/auth/me/photo" if user.get("profile_photo_path") else None
    user.pop("profile_photo_path", None)
    user["csrf_token"] = generate_csrf_token(cookie_val)
    user["uploads"] = formatted_uploads
    user["collections_count"] = len(colls)
    return user

@router.patch('/api/v1/auth/me')
def update_me(payload: UserUpdateRequest, user: Dict[str, Any] = Depends(require_authenticated_user)):
    with get_db() as db:
        if payload.username is not None:
            uname = html.escape(payload.username.strip())
            dup = db.fetchone("SELECT id FROM users WHERE username = ? AND id != ?", (uname, user["id"]))
            if dup:
                raise HTTPException(status_code=400, detail={"error": "DUPLICATE_USER", "message": "That username is already taken."})
            db.execute("UPDATE users SET username = ? WHERE id = ?", (uname, user["id"]))
        if payload.bio is not None:
            db.execute("UPDATE users SET bio = ? WHERE id = ?", (html.escape(payload.bio.strip()), user["id"]))
        if payload.programme is not None:
            db.execute("UPDATE users SET programme = ? WHERE id = ?", (html.escape(payload.programme.strip()), user["id"]))
        if payload.email_notifications is not None:
            db.execute("UPDATE users SET email_notifications = ? WHERE id = ?", (int(payload.email_notifications), user["id"]))
        if payload.public_profile is not None:
            db.execute("UPDATE users SET public_profile = ? WHERE id = ?", (int(payload.public_profile), user["id"]))
        db.commit()
        updated = db.fetchone("SELECT id, username, email, bio, programme, profile_photo_path, email_notifications, public_profile, role, consent_accepted, created_at FROM users WHERE id = ?", (user["id"],))
        updated["consent_accepted"] = bool(updated["consent_accepted"])
        updated["email_notifications"] = bool(updated["email_notifications"])
        updated["public_profile"] = bool(updated["public_profile"])
        updated["profile_photo_url"] = "/api/v1/auth/me/photo" if updated.get("profile_photo_path") else None
        updated.pop("profile_photo_path", None)
        return updated

@router.post('/api/v1/auth/me/photo', status_code=200)
async def upload_profile_photo(file: UploadFile = File(...), user: Dict[str, Any] = Depends(require_authenticated_user)):
    """Upload a profile image (JPEG/PNG/WebP, maximum 2 MB) for the signed-in user."""
    allowed = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
    if file.content_type not in allowed:
        raise HTTPException(status_code=400, detail={"error": "INVALID_PHOTO_TYPE", "message": "Use a JPEG, PNG or WebP image."})
    content = await file.read(2 * 1024 * 1024 + 1)
    if len(content) > 2 * 1024 * 1024:
        raise HTTPException(status_code=400, detail={"error": "PHOTO_TOO_LARGE", "message": "Profile photos must be 2 MB or smaller."})
    if not content:
        raise HTTPException(status_code=400, detail={"error": "EMPTY_PHOTO", "message": "The selected image is empty."})
    # Verify file signatures rather than trusting the client-supplied MIME type.
    valid = (file.content_type == "image/jpeg" and content.startswith(b"\xff\xd8\xff")) or (file.content_type == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n")) or (file.content_type == "image/webp" and content[:4] == b"RIFF" and content[8:12] == b"WEBP")
    if not valid:
        raise HTTPException(status_code=400, detail={"error": "INVALID_PHOTO", "message": "The uploaded file does not match its image type."})
    photo_dir = Path(settings.UPLOAD_STORAGE_DIR) / "profile_photos"
    photo_dir.mkdir(parents=True, exist_ok=True)
    filename = f"user-{user['id']}-{uuid.uuid4().hex}{allowed[file.content_type]}"
    target = photo_dir / filename
    target.write_bytes(content)
    with get_db() as db:
        old = db.fetchone("SELECT profile_photo_path FROM users WHERE id = ?", (user["id"],))
        db.execute("UPDATE users SET profile_photo_path = ? WHERE id = ?", (str(target), user["id"]))
        db.commit()
    if old and old.get("profile_photo_path"):
        try:
            Path(old["profile_photo_path"]).unlink(missing_ok=True)
        except OSError:
            pass
    return {"profile_photo_url": "/api/v1/auth/me/photo"}

@router.get('/api/v1/auth/me/photo')
def get_profile_photo(user: Dict[str, Any] = Depends(require_authenticated_user)):
    path = user.get("profile_photo_path")
    if not path or not Path(path).is_file():
        raise HTTPException(status_code=404, detail={"error": "PHOTO_NOT_FOUND", "message": "No profile photo has been uploaded."})
    return FileResponse(path)

@router.put('/api/v1/auth/password')
def change_password(payload: PasswordChangeRequest, user: Dict[str, Any] = Depends(require_authenticated_user)):
    with get_db() as db:
        row = db.fetchone("SELECT password_hash FROM users WHERE id = ?", (user["id"],))
        if not row or not verify_password_argon2id(payload.current_password, row["password_hash"]):
            raise HTTPException(status_code=400, detail={"error": "INVALID_PASSWORD", "message": "Current password is incorrect."})
        new_hash = hash_password_argon2id(payload.new_password)
        db.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user["id"]))
        db.commit()
    return {"status": "password_updated"}

@router.delete('/api/v1/auth/me')
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
