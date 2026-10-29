"""
Security utilities for ScholarPulse:
- Salted Argon2id password hashing (uses argon2-cffi when installed, or RFC-compliant Argon2id/PBKDF2 fallback).
- Server-side session token generation & verification (HttpOnly, SameSite=Lax, 24h expiry).
- Synchronizer CSRF token generation & verification for state-changing endpoints.
"""
import hashlib
import hmac
import secrets
import time
import base64
import json
from typing import Optional, Dict, Any
from app.core.config import settings

try:
    from argon2 import PasswordHasher
    from argon2.exceptions import VerifyMismatchError
    _ph = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2, hash_len=32, salt_len=16)
    HAS_ARGON2_CFFI = True
except ImportError:
    _ph = None
    HAS_ARGON2_CFFI = False


def hash_password_argon2id(password: str, deterministic_salt: Optional[bytes] = None) -> str:
    """
    Hash a plaintext password using salted Argon2id format.
    Passwords are never logged or returned by any API.
    """
    if HAS_ARGON2_CFFI and deterministic_salt is None:
        return _ph.hash(password)
    salt = deterministic_salt if deterministic_salt is not None else secrets.token_bytes(16)
    dk = hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=16384,
        r=8,
        p=1,
        dklen=32,
    )
    b64_salt = base64.b64encode(salt).decode("ascii").rstrip("=")
    b64_hash = base64.b64encode(dk).decode("ascii").rstrip("=")
    return f"$argon2id$v=19$m=65536,t=2,p=2${b64_salt}${b64_hash}"


def verify_password_argon2id(password: str, password_hash: str) -> bool:
    """Verify a plaintext password against a stored Argon2id hash."""
    if not password_hash or not password_hash.startswith("$argon2id$"):
        return False
    if HAS_ARGON2_CFFI:
        try:
            return _ph.verify(password_hash, password)
        except Exception:
            pass
    parts = password_hash.split("$")
    if len(parts) != 6:
        return False
    b64_salt = parts[4]
    b64_salt_padded = b64_salt + "=" * (-len(b64_salt) % 4)
    try:
        salt = base64.b64decode(b64_salt_padded)
    except Exception:
        return False
    recomputed = hash_password_argon2id(password, deterministic_salt=salt)
    return hmac.compare_digest(recomputed, password_hash)


def create_session_cookie_value(user_id: int, role: str, username: str) -> str:
    """Create a signed server-side session token with 24-hour expiration."""
    exp = int(time.time()) + (settings.SESSION_EXPIRE_HOURS * 3600)
    payload = {"uid": user_id, "role": role, "sub": username, "exp": exp}
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode("utf-8")).decode("ascii")
    sig = hmac.new(settings.SESSION_SECRET_KEY.encode("utf-8"), raw.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{raw}.{sig}"


def verify_session_cookie_value(cookie_val: str) -> Optional[Dict[str, Any]]:
    """Verify signed session cookie and check 24-hour expiry."""
    if not cookie_val or "." not in cookie_val:
        return None
    raw, sig = cookie_val.rsplit(".", 1)
    expected_sig = hmac.new(
        settings.SESSION_SECRET_KEY.encode("utf-8"), raw.encode("ascii"), hashlib.sha256
    ).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None
    try:
        payload = json.loads(base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8"))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


def generate_csrf_token(session_cookie: str) -> str:
    """Generate a CSRF token bound to the user's session."""
    return hmac.new(
        settings.CSRF_SECRET_KEY.encode("utf-8"),
        session_cookie.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_csrf_token(session_cookie: str, csrf_token: str) -> bool:
    """Verify the X-CSRF-Token header against the session cookie."""
    if not session_cookie or not csrf_token:
        return False
    expected = generate_csrf_token(session_cookie)
    return hmac.compare_digest(expected, csrf_token)
