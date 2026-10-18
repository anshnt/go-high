"""Tests run against a real Postgres (the queue and later RLS depend on it). Point
TEST_DATABASE_URL at a server; the test database is created if missing."""
import os
import re

import pytest
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

from app import config, ssrf  # noqa: E402  (must import after DATABASE_URL is set)
from app.db import SessionLocal, engine  # noqa: E402
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
    """Signs up a new user (own org, brand and workspace) and returns (signed-in client, signup response)."""
    def make(email: str, org_name: str | None = None):
        client = TestClient(app)
        r = client.post("/api/auth/signup", json={"email": email, "name": email.split("@")[0], "password": PASSWORD,
                                                  "org_name": org_name or f"Org of {email}"})
        assert r.status_code == 201, r.text
        return client, r.json()
    return make


@pytest.fixture
def crm(make_user):
    """A signed-in admin of a fresh workspace: (client, workspace id, signup ids)."""
    client, ids = make_user("a@example.com")
    return client, ids["workspace_id"], ids
