"""Self-contained local test database setup.

CI may set DATABASE_URL to its MySQL service. Otherwise pytest uses an
isolated SQLite file, applies the committed Alembic migration, and loads
deterministic seed data.
"""

import os
import sys
import tempfile
from pathlib import Path

# Use the system temporary directory (Windows or Linux).
TEMP_DIR = Path(tempfile.gettempdir())
TEST_DB = TEMP_DIR / "scholarpulse_pytest.db"
TEST_UPLOADS = TEMP_DIR / "scholarpulse_pytest_uploads"

# Preserve DATABASE_URL if CI has already configured MySQL.
os.environ.setdefault(
    "DATABASE_URL",
    f"sqlite:///{TEST_DB.as_posix()}",
)
os.environ.setdefault("UPLOAD_STORAGE_DIR", str(TEST_UPLOADS))

# Tests must be hermetic: never call the real Gemini API, even if a key is set in .env or the
# shell. With no key, unanswerable questions return the "Not found" refusal the tests expect.
os.environ["GEMINI_API_KEY"] = ""

# Start each SQLite test run with a clean database.
if os.environ["DATABASE_URL"].startswith("sqlite:///"):
    db_path = os.environ["DATABASE_URL"].replace("sqlite:///", "", 1)
    Path(db_path).unlink(missing_ok=True)

TEST_UPLOADS.mkdir(parents=True, exist_ok=True)

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

# Import after setting DATABASE_URL because app settings are loaded at import time.
sys.path.insert(0, str(BACKEND))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from scripts.seed_db import run_seed  # noqa: E402

alembic_cfg = Config(str(BACKEND / "alembic.ini"))
alembic_cfg.set_main_option("script_location", str(BACKEND / "alembic"))

command.upgrade(alembic_cfg, "head")
run_seed()