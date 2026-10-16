"""Tests run against a real Postgres (the queue and later RLS depend on it). Point
TEST_DATABASE_URL at a server; the test database is created if missing."""
import os

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

URL = make_url(os.getenv("TEST_DATABASE_URL", "postgresql+psycopg://gohigh:gohigh@127.0.0.1:5432/gohigh_test"))
os.environ["DATABASE_URL"] = URL.render_as_string(hide_password=False)

with create_engine(URL.set(database="postgres"), isolation_level="AUTOCOMMIT").connect() as conn:
    if not conn.scalar(text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": URL.database}):
        conn.execute(text(f'CREATE DATABASE "{URL.database}"'))

from app.db import SessionLocal, engine  # noqa: E402  (must import after DATABASE_URL is set)
from app.main import migrate  # noqa: E402

migrate()


@pytest.fixture(autouse=True)
def clean():
    yield
    with engine.begin() as conn:
        conn.execute(text("TRUNCATE jobs RESTART IDENTITY"))


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session
