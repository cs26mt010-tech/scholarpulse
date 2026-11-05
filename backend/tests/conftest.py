"""Self-contained local test database setup.

CI may set DATABASE_URL to its MySQL service. Otherwise pytest uses an isolated
SQLite file, applies the committed Alembic migration, and loads deterministic seed data.
"""
import os
from pathlib import Path

os.environ.setdefault("DATABASE_URL", "sqlite:////tmp/scholarpulse_pytest.db")
# Start every run from a clean SQLite file so rate-limit counters etc. never leak between runs.
if os.environ["DATABASE_URL"].startswith("sqlite:///"):
    Path(os.environ["DATABASE_URL"].replace("sqlite:///", "", 1)).unlink(missing_ok=True)
os.environ.setdefault("UPLOAD_STORAGE_DIR", "/tmp/scholarpulse_pytest_uploads")

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"

# Import after setting DATABASE_URL because app settings are loaded at import time.
import sys

sys.path.insert(0, str(BACKEND))

from alembic import command  # noqa: E402
from alembic.config import Config  # noqa: E402

from scripts.seed_db import run_seed  # noqa: E402

alembic_cfg = Config(str(BACKEND / "alembic.ini"))
alembic_cfg.set_main_option("script_location", str(BACKEND / "alembic"))
command.upgrade(alembic_cfg, "head")
run_seed()
