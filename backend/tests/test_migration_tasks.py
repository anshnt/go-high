"""Migration 0009 on a database that has an event log and organizations already: notifications start from the end of
the log, the system roles get the tasks capabilities, the tables match the models, and it goes both ways."""
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app import config

URL = make_url(config.DATABASE_URL)  # conftest pointed DATABASE_URL at the test database

BACKEND = Path(__file__).resolve().parents[1]
NAME = f"{URL.database}_migrate_tasks"  # a database of its own: the test database stays at head
TABLES = ("tasks", "notifications", "notification_prefs")


def alembic(url: str, *args: str) -> None:
    done = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, text=True, capture_output=True,
                          env={**os.environ, "DATABASE_URL": url})
    assert done.returncode == 0, done.stdout + done.stderr


def test_old_events_never_become_notifications_and_the_migration_reverses():
    admin = create_engine(URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    url = URL.set(database=NAME).render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{NAME}"'))
    try:
        alembic(url, "upgrade", "0004")
        engine = create_engine(url)
        with engine.begin() as conn:  # a workspace with some history, from before tasks existed
            org = conn.scalar(text("INSERT INTO organizations (name) VALUES ('Old') RETURNING id"))
            brand = conn.scalar(text("INSERT INTO brands (org_id, name) VALUES (:o, 'B') RETURNING id"), {"o": org})
            workspace = conn.scalar(text("INSERT INTO workspaces (org_id, brand_id, name) VALUES (:o, :b, 'W') "
                                         "RETURNING id"), {"o": org, "b": brand})
            for _ in range(3):
                last = conn.scalar(text(
                    "INSERT INTO events (workspace_id, type, subject_type, subject_id, actor_type, data) "
                    "VALUES (:w, 'record.updated', 'record', gen_random_uuid(), 'system', '{}') RETURNING id"),
                    {"w": workspace})
        alembic(url, "upgrade", "head")
        alembic(url, "check")  # the models and the migration say the same thing
        cursor = text("SELECT last_id FROM event_cursors WHERE consumer = 'notifications'")
        with engine.begin() as conn:
            assert conn.scalar(cursor) == last  # nothing before this point is replayed
            flags = conn.execute(text("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                                      "WHERE relname = ANY(:t)"), {"t": list(TABLES)}).all()
            assert len(flags) == 3 and all(f[1] and f[2] for f in flags)
            roles = dict(conn.execute(text("SELECT key, capabilities FROM roles WHERE org_id = :o"), {"o": org}).all())
            tasks = {key: sorted(c for c in caps if c.startswith("tasks.")) for key, caps in roles.items()}
            everything = ["tasks.delete", "tasks.read", "tasks.write"]
            assert tasks == {"owner": everything, "admin": everything, "manager": everything, "member": everything,
                             "viewer": ["tasks.read"], "automation": ["tasks.read", "tasks.write"]}
        alembic(url, "downgrade", "0005")
        with engine.begin() as conn:
            assert conn.scalar(text("SELECT count(*) FROM pg_tables WHERE tablename = ANY(:t)"),
                               {"t": list(TABLES)}) == 0
            left = text("SELECT count(*) FROM roles WHERE array_to_string(capabilities, ',') LIKE '%tasks.%'")
            assert conn.scalar(left) == 0  # taken away again
            assert conn.scalar(cursor) is None
            assert conn.scalar(text("SELECT count(*) FROM events")) == 3  # the rest is untouched
        alembic(url, "upgrade", "head")
        with engine.begin() as conn:
            assert conn.scalar(cursor) == last
        engine.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))
        admin.dispose()
