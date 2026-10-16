"""Runtime settings, read once from the environment."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://gohigh:gohigh@127.0.0.1:5432/gohigh")
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", str(ROOT / "frontend" / "dist")))
WORKER_POLL_SECONDS = float(os.getenv("WORKER_POLL_SECONDS", "1"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
