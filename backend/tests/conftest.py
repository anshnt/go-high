"""Tests run against a real Postgres (the queue and later RLS depend on it). Point
TEST_DATABASE_URL at a server; the test database is created if missing."""
import os
import re
import ssl
import threading
import time
from datetime import UTC, datetime

import pytest
import uvicorn
from fakes import FakeSMTP, Files, make_cert
from fastapi.testclient import TestClient
from helpers import PASSWORD, Receiver
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

URL = make_url(os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://gohigh:gohigh@127.0.0.1:5432/gohigh_test"))
os.environ["DATABASE_URL"] = URL.render_as_string(hide_password=False)
os.environ["COOKIE_SECURE"] = "0"  # the test client talks plain http
os.environ["DEV_EXPOSE_MAGIC_LINKS"] = "1"

with create_engine(URL.set(database="postgres"), isolation_level="AUTOCOMMIT").connect() as conn:
    if not conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": URL.database}):
        conn.execute(text(f'CREATE DATABASE "{URL.database}"'))

from email_helpers import email_fixture, fake_dns  # noqa: E402, F401  (the email marketing fixtures)

from app import config, ssrf  # noqa: E402  (must import after DATABASE_URL is set)
from app.db import SessionLocal, engine  # noqa: E402
from app.inbox import consent, stream  # noqa: E402
from app.main import app, migrate  # noqa: E402

migrate()


@pytest.fixture(autouse=True)
def clean():
    yield
    with engine.begin() as conn:  # owner role: TRUNCATE is not subject to row level security
        conn.execute(text("TRUNCATE jobs RESTART IDENTITY"))
        conn.execute(text("TRUNCATE event_cursors, login_attempts, magic_links, auth_sessions, workspace_members, "
                          "org_members, workspaces, brands, organizations, users CASCADE"))  # events etc. follow by FK


@pytest.fixture(autouse=True)
def dns(monkeypatch):
    """No test touches real DNS: names resolve from the returned dict (tests edit it), numeric hosts and localhost
    go through the system resolver, anything else does not resolve."""
    real = ssrf.resolve
    hosts = {"hooks.example.com": ["93.184.216.34"], "hooks.test": ["127.0.0.1"]}

    def fake(host, port):
        if host in hosts:
            return hosts[host]
        if host == "localhost" or re.fullmatch(r"[0-9a-fA-Fx:.%]+", host):
            return real(host, port)
        raise ssrf.Blocked(f"{host} does not resolve")

    monkeypatch.setattr(ssrf, "resolve", fake)
    return hosts


@pytest.fixture(autouse=True)
def afternoon(monkeypatch):
    """Consent rules look at the time of day (quiet hours): by default it is 19:00 UTC, afternoon in every US zone."""
    at = datetime.now(UTC).replace(hour=19, minute=0, second=0, microsecond=0)
    monkeypatch.setattr(consent, "clock", lambda: at)


@pytest.fixture
def receiver(monkeypatch):
    """A local HTTP server standing in for a customer's webhook endpoint, allowed past the SSRF guard."""
    monkeypatch.setattr(config, "ALLOW_HTTP_WEBHOOKS", True)
    monkeypatch.setattr(config, "WEBHOOK_ALLOW_IPS", {"127.0.0.1"})
    server = Receiver()
    yield server
    server.close()


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


@pytest.fixture
def make_user():
    """Signs up a new user (own org, brand and workspace) and returns (signed-in client, signup response). The address
    counts as proved, as if an email link had been used, unless `verified=False` (what sign up alone leaves)."""
    def make(email: str, org_name: str | None = None, verified: bool = True):
        client = TestClient(app)
        r = client.post("/api/auth/signup", json={"email": email, "name": email.split("@")[0], "password": PASSWORD,
                                                  "org_name": org_name or f"Org of {email}"})
        assert r.status_code == 201, r.text
        if verified:
            with engine.begin() as conn:
                conn.execute(text("UPDATE users SET email_verified_at = now() WHERE email = :e"), {"e": email})
        return client, r.json()
    return make


@pytest.fixture
def crm(make_user):
    """A signed-in admin of a fresh workspace: (client, workspace id, signup ids)."""
    client, ids = make_user("a@example.com")
    return client, ids["workspace_id"], ids


@pytest.fixture
def files():
    """A local server for attachment URLs (use with `receiver`, which allows 127.0.0.1 past the SSRF guard)."""
    server = Files()
    yield server
    server.close()


@pytest.fixture
def smtp_server():
    """Starts a FakeSMTP: smtp_server(context=None, implicit=False, login=("user", "secret"))."""
    servers = []

    def start(**kwargs):
        servers.append(FakeSMTP(**kwargs))
        return servers[-1]

    yield start
    for server in servers:
        server.close()


@pytest.fixture
def tls(monkeypatch, tmp_path):
    """tls("smtp.test") makes a certificate for that name, makes the client trust it, returns the server context."""
    real = ssl.create_default_context
    trusted = []
    monkeypatch.setattr(ssl, "create_default_context", lambda *a, **k: _trusting(real(*a, **k), trusted))

    def make(name="smtp.test", trust=True):
        context, pem = make_cert(tmp_path, name)
        if trust:
            trusted.append(pem)
        return context

    return make


def _trusting(context, trusted):
    for pem in trusted:
        context.load_verify_locations(cadata=pem)
    return context


@pytest.fixture(scope="module")
def live():
    """The app under uvicorn on a free port, with its lifespan (and so its LISTEN connection), for what a test client
    cannot do: read a stream that never ends, run a script that makes its own HTTP calls. Yields the port."""
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 30
    while not server.started:
        assert time.monotonic() < deadline and thread.is_alive(), "the server did not start"
        time.sleep(0.05)
    deadline = time.monotonic() + 10
    while not stream.hub.seen_connection:  # the LISTEN connection is up
        assert time.monotonic() < deadline, "the listener did not connect"
        time.sleep(0.05)
    yield server.servers[0].sockets[0].getsockname()[1]
    server.should_exit = True
    thread.join(15)


@pytest.fixture
def site(crm, monkeypatch):
    """The forms of a fresh workspace (see forms_helpers.Site). A form can be completed at once, without the minimum
    fill time that spam protection asks of a person."""
    from forms_helpers import Site
    monkeypatch.setattr(config, "FORM_MIN_FILL_SECONDS", 0)
    client, ws, _ = crm
    return Site(client, ws)
