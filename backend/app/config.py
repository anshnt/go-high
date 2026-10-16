"""Runtime settings, read once from the environment."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://gohigh:gohigh@127.0.0.1:5432/gohigh")
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", str(ROOT / "frontend" / "dist")))
WORKER_POLL_SECONDS = float(os.getenv("WORKER_POLL_SECONDS", "1"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Comma separated browser origins allowed to send cookie-authenticated writes; the first one builds magic links.
PUBLIC_URL = os.getenv(
    "PUBLIC_URL", "http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5173,http://localhost:5173")
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in PUBLIC_URL.split(",") if o.strip()]
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "1") == "1"
SESSION_IDLE_MINUTES = int(os.getenv("SESSION_IDLE_MINUTES", "720"))
SESSION_ABSOLUTE_HOURS = int(os.getenv("SESSION_ABSOLUTE_HOURS", str(24 * 30)))
MAGIC_LINK_MINUTES = int(os.getenv("MAGIC_LINK_MINUTES", "15"))
LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "5"))
LOGIN_WINDOW_MINUTES = int(os.getenv("LOGIN_WINDOW_MINUTES", "15"))
DEV_EXPOSE_MAGIC_LINKS = os.getenv("DEV_EXPOSE_MAGIC_LINKS", "0") == "1"  # tests and local dev only
