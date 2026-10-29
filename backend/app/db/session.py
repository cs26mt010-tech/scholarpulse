"""
Database connection and schema initialization manager for ScholarPulse (MS-3).
Supports MySQL 8.0 (`mysql+pymysql://...`) in Docker Compose and SQLite3 (`sqlite:///...`)
for local/CI self-contained testing.
"""
import os
import sqlite3
from contextlib import contextmanager
from urllib.parse import urlparse
from app.core.config import settings

try:
    import pymysql
    HAS_PYMYSQL = True
except ImportError:
    HAS_PYMYSQL = False


def get_sqlite_path() -> str:
    url = settings.DATABASE_URL
    if url.startswith("sqlite:///"):
        return url.replace("sqlite:///", "", 1)
    # Default local SQLite fallback path when running outside Docker MySQL
    base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
    return "/tmp/scholarpulse.db"


def is_mysql_configured() -> bool:
    return settings.DATABASE_URL.startswith("mysql") and HAS_PYMYSQL


class DBConnectionWrapper:
    """
    Uniform parameterized DB-API 2.0 wrapper supporting both MySQL 8 (PyMySQL)
    and SQLite3 with dictionary row results. All queries use parameterized placeholders.
    """
    def __init__(self, raw_conn, dialect: str):
        self.raw_conn = raw_conn
        self.dialect = dialect

    def execute(self, sql: str, params: tuple = ()):
        if self.dialect == "mysql":
            sql_adapted = sql.replace("?", "%s")
            cur = self.raw_conn.cursor(pymysql.cursors.DictCursor)
            cur.execute(sql_adapted, params)
            return cur
        else:
            cur = self.raw_conn.cursor()
            cur.execute(sql, params)
            return cur

    def executemany(self, sql: str, seq_of_params):
        if self.dialect == "mysql":
            sql_adapted = sql.replace("?", "%s")
            cur = self.raw_conn.cursor(pymysql.cursors.DictCursor)
            cur.executemany(sql_adapted, seq_of_params)
            return cur
        else:
            cur = self.raw_conn.cursor()
            cur.executemany(sql, seq_of_params)
            return cur

    def fetchall(self, sql: str, params: tuple = ()):
        cur = self.execute(sql, params)
        rows = cur.fetchall()
        if self.dialect == "sqlite":
            return [dict(r) for r in rows]
        return list(rows)

    def fetchone(self, sql: str, params: tuple = ()):
        cur = self.execute(sql, params)
        row = cur.fetchone()
        if row is None:
            return None
        if self.dialect == "sqlite":
            return dict(row)
        return dict(row)

    def commit(self):
        self.raw_conn.commit()

    def close(self):
        self.raw_conn.close()


@contextmanager
def get_db():
    if is_mysql_configured():
        try:
            parsed = urlparse(settings.DATABASE_URL.replace("mysql+pymysql://", "mysql://"))
            conn = pymysql.connect(
                host=parsed.hostname or "db",
                port=parsed.port or 3306,
                user=parsed.username or "sp_user",
                password=parsed.password or "sp_password_2026",
                database=(parsed.path or "/scholarpulse").lstrip("/"),
                charset="utf8mb4",
                autocommit=False,
            )
            wrapper = DBConnectionWrapper(conn, "mysql")
            try:
                yield wrapper
            finally:
                wrapper.close()
            return
        except Exception:
            pass

    # SQLite3 connection
    db_path = get_sqlite_path()
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = MEMORY;"); conn.execute("PRAGMA synchronous = OFF;"); conn.execute("PRAGMA foreign_keys = ON;")
    wrapper = DBConnectionWrapper(conn, "sqlite")
    try:
        yield wrapper
    finally:
        wrapper.close()


def init_schema_ddl(db: DBConnectionWrapper) -> None:
    """
    Ensure all 12 tables and indexes from Migration 0001_initial_schema exist.
    Also records the Alembic version (`0001_initial_schema`) in `alembic_version`.
    """
    auto_inc = "INT AUTO_INCREMENT PRIMARY KEY" if db.dialect == "mysql" else "INTEGER PRIMARY KEY AUTOINCREMENT"

    ddl_statements = [
        f"""
        CREATE TABLE IF NOT EXISTS alembic_version (
            version_num VARCHAR(32) NOT NULL PRIMARY KEY
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS users (
            id {auto_inc},
            username VARCHAR(50) NOT NULL UNIQUE,
            email VARCHAR(120) NOT NULL UNIQUE,
            password_hash VARCHAR(255) NOT NULL,
            bio VARCHAR(500),
            role VARCHAR(20) NOT NULL DEFAULT 'student',
            consent_accepted BOOLEAN NOT NULL DEFAULT 1,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS categories (
            id {auto_inc},
            course_code VARCHAR(20) NOT NULL UNIQUE,
            course_name VARCHAR(150) NOT NULL,
            department VARCHAR(100) NOT NULL DEFAULT 'Computer Science & Engineering',
            description VARCHAR(500),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS resources (
            id {auto_inc},
            title VARCHAR(200) NOT NULL,
            content_text TEXT NOT NULL,
            tldr_summary VARCHAR(1000),
            resource_type VARCHAR(30) NOT NULL DEFAULT 'paper_summary',
            category_id INTEGER NOT NULL,
            uploader_id INTEGER,
            source_authors VARCHAR(500),
            source_ref VARCHAR(100) UNIQUE,
            published_on DATE,
            file_name VARCHAR(255),
            file_size_bytes INTEGER,
            is_official BOOLEAN NOT NULL DEFAULT 0,
            rights_confirmed BOOLEAN NOT NULL DEFAULT 1,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            embedding_status VARCHAR(20) NOT NULL DEFAULT 'completed',
            avg_rating REAL NOT NULL DEFAULT 0.0,
            rating_count INTEGER NOT NULL DEFAULT 0,
            comment_count INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE RESTRICT,
            FOREIGN KEY (uploader_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS resource_chunks (
            id {auto_inc},
            resource_id INTEGER NOT NULL,
            chunk_index INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            char_length INTEGER NOT NULL,
            embedding_json TEXT,
            embedding_model VARCHAR(60) NOT NULL DEFAULT 'gemini-embedding-001',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (resource_id, chunk_index),
            FOREIGN KEY (resource_id) REFERENCES resources(id) ON DELETE CASCADE
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS tags (
            id {auto_inc},
            name VARCHAR(60) NOT NULL UNIQUE,
            slug VARCHAR(60) NOT NULL UNIQUE,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS resource_tags (
            resource_id INTEGER NOT NULL,
            tag_id INTEGER NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (resource_id, tag_id),
            FOREIGN KEY (resource_id) REFERENCES resources(id) ON DELETE CASCADE,
            FOREIGN KEY (tag_id) REFERENCES tags(id) ON DELETE CASCADE
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS ratings (
            id {auto_inc},
            resource_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            score INTEGER NOT NULL CHECK (score >= 1 AND score <= 5),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (resource_id, user_id),
            FOREIGN KEY (resource_id) REFERENCES resources(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS comments (
            id {auto_inc},
            resource_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            body TEXT NOT NULL,
            status VARCHAR(20) NOT NULL DEFAULT 'active',
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (resource_id) REFERENCES resources(id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS collections (
            id {auto_inc},
            title VARCHAR(150) NOT NULL,
            description VARCHAR(1000),
            owner_id INTEGER NOT NULL,
            category_id INTEGER,
            is_official BOOLEAN NOT NULL DEFAULT 0,
            is_public BOOLEAN NOT NULL DEFAULT 1,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (owner_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS collection_items (
            id {auto_inc},
            collection_id INTEGER NOT NULL,
            resource_id INTEGER NOT NULL,
            position INTEGER NOT NULL DEFAULT 1,
            notes VARCHAR(300),
            added_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (collection_id, resource_id),
            FOREIGN KEY (collection_id) REFERENCES collections(id) ON DELETE CASCADE,
            FOREIGN KEY (resource_id) REFERENCES resources(id) ON DELETE CASCADE
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS reports (
            id {auto_inc},
            reporter_id INTEGER NOT NULL,
            target_type VARCHAR(20) NOT NULL,
            target_id INTEGER NOT NULL,
            reason VARCHAR(50) NOT NULL,
            details VARCHAR(1000),
            status VARCHAR(20) NOT NULL DEFAULT 'open',
            moderator_id INTEGER,
            moderation_action VARCHAR(30),
            moderation_note VARCHAR(500),
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            resolved_at TIMESTAMP,
            FOREIGN KEY (reporter_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY (moderator_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
        f"""
        CREATE TABLE IF NOT EXISTS ai_queries (
            id {auto_inc},
            user_id INTEGER,
            scope_type VARCHAR(20) NOT NULL,
            scope_id VARCHAR(50) NOT NULL,
            question VARCHAR(300) NOT NULL,
            answer_text TEXT NOT NULL,
            cited_chunk_ids_json VARCHAR(500) NOT NULL DEFAULT '[]',
            not_found BOOLEAN NOT NULL DEFAULT 0,
            fallback_used BOOLEAN NOT NULL DEFAULT 0,
            model_used VARCHAR(60) NOT NULL DEFAULT 'gemini-2.5-flash',
            latency_ms INTEGER NOT NULL DEFAULT 0,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
        """,
    ]

    index_statements = [
        "CREATE INDEX IF NOT EXISTS ix_users_role ON users(role)",
        "CREATE INDEX IF NOT EXISTS ix_resources_title ON resources(title)",
        "CREATE INDEX IF NOT EXISTS ix_resources_cat_status_rating ON resources(category_id, status, avg_rating)",
        "CREATE INDEX IF NOT EXISTS ix_resources_type_status_created ON resources(resource_type, status, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_chunks_resource_idx ON resource_chunks(resource_id, chunk_index)",
        "CREATE INDEX IF NOT EXISTS ix_resource_tags_tag_id ON resource_tags(tag_id)",
        "CREATE INDEX IF NOT EXISTS ix_comments_resource_status ON comments(resource_id, status, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_collections_official_public ON collections(is_official, is_public, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_collection_items_order ON collection_items(collection_id, position)",
        "CREATE INDEX IF NOT EXISTS ix_reports_status_created ON reports(status, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_reports_target ON reports(target_type, target_id)",
        "CREATE INDEX IF NOT EXISTS ix_ai_queries_user_created ON ai_queries(user_id, created_at)",
        "CREATE INDEX IF NOT EXISTS ix_ai_queries_scope ON ai_queries(scope_type, scope_id)",
    ]

    for stmt in ddl_statements:
        db.execute(stmt)

    for idx_stmt in index_statements:
        try:
            if db.dialect == "mysql":
                idx_stmt_mysql = idx_stmt.replace("CREATE INDEX IF NOT EXISTS ", "CREATE INDEX ")
                db.execute(idx_stmt_mysql)
            else:
                db.execute(idx_stmt)
        except Exception:
            pass

    existing_ver = db.fetchone("SELECT version_num FROM alembic_version WHERE version_num = ?", ("0001_initial_schema",))
    if not existing_ver:
        db.execute("INSERT INTO alembic_version (version_num) VALUES (?)", ("0001_initial_schema",))
    db.commit()
