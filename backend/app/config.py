"""Runtime settings, read once from the environment."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql+psycopg://gohigh:gohigh@127.0.0.1:5432/gohigh")
FRONTEND_DIST = Path(os.getenv("FRONTEND_DIST", str(ROOT / "frontend" / "dist")))
WORKER_POLL_SECONDS = float(os.getenv("WORKER_POLL_SECONDS", "1"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
VERSION = os.getenv("APP_VERSION", "0.0.0-dev")  # baked into release images

# Comma separated browser origins allowed to send cookie-authenticated writes; the first one builds magic links.
PUBLIC_URL = os.getenv(
    "PUBLIC_URL", "http://127.0.0.1:8000,http://localhost:8000,http://127.0.0.1:5173,http://localhost:5173")
ALLOWED_ORIGINS = [o.strip().rstrip("/") for o in PUBLIC_URL.split(",") if o.strip()]
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "1") == "1"
SESSION_IDLE_MINUTES = int(os.getenv("SESSION_IDLE_MINUTES", "720"))
SESSION_ABSOLUTE_HOURS = int(os.getenv("SESSION_ABSOLUTE_HOURS", str(24 * 30)))
MAGIC_LINK_MINUTES = int(os.getenv("MAGIC_LINK_MINUTES", "15"))
LOGIN_MAX_FAILURES = int(os.getenv("LOGIN_MAX_FAILURES", "5"))  # per email and IP
LOGIN_MAX_FAILURES_PER_EMAIL = int(os.getenv("LOGIN_MAX_FAILURES_PER_EMAIL", "20"))  # across all IPs
LOGIN_WINDOW_MINUTES = int(os.getenv("LOGIN_WINDOW_MINUTES", "15"))
RECENT_AUTH_MINUTES = int(os.getenv("RECENT_AUTH_MINUTES", "15"))  # setting a first password needs a fresh session
DEV_EXPOSE_MAGIC_LINKS = os.getenv("DEV_EXPOSE_MAGIC_LINKS", "0") == "1"  # tests and local dev only

DEV_SECRET_KEY = "dev-only-secret-key-change-me"
SECRET_KEY = os.getenv("SECRET_KEY") or DEV_SECRET_KEY  # signs pagination cursors; set the same value on every replica

# Webhook targets must be https and resolve to a public address. The two switches below are for tests and local
# development: plain http, and exact addresses (a local receiver on 127.0.0.1) that pass the address check.
# The addresses only count while ALLOW_HTTP_WEBHOOKS is on. Never set either on a reachable server.
ALLOW_HTTP_WEBHOOKS = os.getenv("ALLOW_HTTP_WEBHOOKS", "0") == "1"
WEBHOOK_ALLOW_IPS = {a.strip() for a in os.getenv("WEBHOOK_ALLOW_IPS", "").split(",") if a.strip()}

# ponytail: there is no workspace settings table yet, so a phone field's own `options.region` wins and this is the
# fallback (ISO 3166 alpha-2). Move it to a workspace setting when that exists.
DEFAULT_PHONE_REGION = os.getenv("DEFAULT_PHONE_REGION", "US")

# Requests per minute to the public webchat endpoints, per visitor IP and per widget key: sending (a session or a
# message) and polling for replies.
CHAT_SEND_PER_IP = int(os.getenv("CHAT_SEND_PER_IP", "10"))
CHAT_SEND_PER_KEY = int(os.getenv("CHAT_SEND_PER_KEY", "300"))
CHAT_POLL_PER_IP = int(os.getenv("CHAT_POLL_PER_IP", "120"))
CHAT_POLL_PER_KEY = int(os.getenv("CHAT_POLL_PER_KEY", "6000"))

# Public forms: a form completed sooner than this after its page was opened came from a script, not a person.
# 0 switches the check off (tests).
FORM_MIN_FILL_SECONDS = int(os.getenv("FORM_MIN_FILL_SECONDS", "3"))

# Public booking requests (module 16) one visitor (a hash of their IP) and one calendar may make within the window, and
# all visitors together for one calendar.
BOOKING_MAX_PER_IP = int(os.getenv("BOOKING_MAX_PER_IP", "8"))
BOOKING_MAX_PER_CALENDAR = int(os.getenv("BOOKING_MAX_PER_CALENDAR", "120"))
BOOKING_WINDOW_MINUTES = int(os.getenv("BOOKING_WINDOW_MINUTES", "10"))

# Workflows (module 18): how many steps of one workspace's runs may execute at the same moment, so a workspace that
# enrolls thousands of records at once cannot take every worker.
WORKFLOW_CONCURRENCY = int(os.getenv("WORKFLOW_CONCURRENCY", "8"))

# Payments (module 21). The platform's Stripe keys: the secret key, and the signing secrets of the Connect webhook
# endpoint (comma separated while one is rotated). Workspaces connect their own Stripe accounts through Connect; only
# Stripe's ids are stored. STRIPE_API_BASE is for tests (a local server). The test provider takes "payments" without
# money, for development and tests only: never switch it on where real customers pay.
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRETS = [s.strip() for s in os.getenv("STRIPE_WEBHOOK_SECRETS", "").split(",") if s.strip()]
STRIPE_CONNECT_TYPE = os.getenv("STRIPE_CONNECT_TYPE", "standard")
STRIPE_API_BASE = os.getenv("STRIPE_API_BASE", "https://api.stripe.com")
PAYMENTS_FAKE_PROVIDER = os.getenv("PAYMENTS_FAKE_PROVIDER", "0") == "1"
# Public checkout attempts (payment links and invoice pages) one visitor may start per window, and all visitors of one
# link or invoice together.
CHECKOUT_MAX_PER_IP = int(os.getenv("CHECKOUT_MAX_PER_IP", "10"))
CHECKOUT_MAX_PER_TARGET = int(os.getenv("CHECKOUT_MAX_PER_TARGET", "200"))
CHECKOUT_WINDOW_MINUTES = int(os.getenv("CHECKOUT_WINDOW_MINUTES", "10"))
