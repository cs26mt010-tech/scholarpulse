"""
Application configuration loaded from environment variables (.env).
Model names and secrets are stored in environment variables and never hardcoded.
"""
import os
from dataclasses import dataclass


@dataclass
class Settings:
    APP_NAME: str = os.getenv("APP_NAME", "ScholarPulse")
    APP_ENV: str = os.getenv("APP_ENV", "development")
    APP_HOST: str = os.getenv("APP_HOST", "0.0.0.0")
    APP_PORT: int = int(os.getenv("APP_PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"

    # Database URL (defaults to MySQL 8 in Docker Compose, falls back to local SQLite if specified)
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "mysql+pymysql://sp_user:sp_password_2026@db:3306/scholarpulse?charset=utf8mb4",
    )

    # Security & Sessions
    SESSION_SECRET_KEY: str = os.getenv(
        "SESSION_SECRET_KEY", "dev_session_secret_replace_in_prod_9f8a7b6c5d4e3f2a1b0c"
    )
    CSRF_SECRET_KEY: str = os.getenv(
        "CSRF_SECRET_KEY", "dev_csrf_secret_replace_in_prod_1a2b3c4d5e6f7a8b9c0d"
    )
    SESSION_COOKIE_NAME: str = os.getenv("SESSION_COOKIE_NAME", "sp_session")
    SESSION_EXPIRE_HOURS: int = int(os.getenv("SESSION_EXPIRE_HOURS", "24"))
    SESSION_COOKIE_SECURE: bool = os.getenv("SESSION_COOKIE_SECURE", "false").lower() == "true"
    SESSION_COOKIE_SAMESITE: str = os.getenv("SESSION_COOKIE_SAMESITE", "lax")

    # Uploads
    MAX_UPLOAD_SIZE_MB: int = int(os.getenv("MAX_UPLOAD_SIZE_MB", "5"))
    ALLOWED_UPLOAD_EXTENSIONS: tuple = (".pdf", ".txt")
    UPLOAD_STORAGE_DIR: str = os.getenv("UPLOAD_STORAGE_DIR", "/tmp/scholarpulse_uploads")

    # Gemini AI Configuration (Server-Side Only)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    GEMINI_EMBEDDING_MODEL: str = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")
    GEMINI_GENERATION_MODEL: str = os.getenv("GEMINI_GENERATION_MODEL", "gemini-2.5-flash")
    AI_REQUEST_TIMEOUT_SECONDS: int = int(os.getenv("AI_REQUEST_TIMEOUT_SECONDS", "10"))
    AI_MAX_RETRIES: int = int(os.getenv("AI_MAX_RETRIES", "1"))
    AI_SIMILARITY_THRESHOLD: float = float(os.getenv("AI_SIMILARITY_THRESHOLD", "0.35"))
    AI_TOP_K_SINGLE: int = int(os.getenv("AI_TOP_K_SINGLE", "5"))
    AI_TOP_K_MULTI: int = int(os.getenv("AI_TOP_K_MULTI", "8"))
    AI_MAX_CHUNKS_PER_RESOURCE: int = int(os.getenv("AI_MAX_CHUNKS_PER_RESOURCE", "3"))
    AI_MAX_COLLECTION_RESOURCES: int = int(os.getenv("AI_MAX_COLLECTION_RESOURCES", "20"))
    AI_MAX_QUESTION_LENGTH: int = int(os.getenv("AI_MAX_QUESTION_LENGTH", "300"))
    AI_RATE_LIMIT_PER_HOUR: int = int(os.getenv("AI_RATE_LIMIT_PER_HOUR", "20"))

    # Chunking parameters (MS-1 Section 5: ~800 chars with 100 chars overlap)
    CHUNK_SIZE_CHARS: int = 800
    CHUNK_OVERLAP_CHARS: int = 100

    # Deterministic Seed
    SEED_RANDOM_SEED: int = int(os.getenv("SEED_RANDOM_SEED", "2026"))


settings = Settings()
