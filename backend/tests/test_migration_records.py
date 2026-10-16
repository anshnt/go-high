"""Migration 0004 on a database that already has workspaces: each gets the system objects, and it goes both ways."""
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app import config
from app.records import seed

URL = make_url(config.DATABASE_URL)  # conftest pointed DATABASE_URL at the test database

BACKEND = Path(__file__).resolve().parents[1]
NAME = f"{URL.database}_migrate"  # a database of its own: the test database stays at head


def alembic(url: str, *args: str) -> None:
    done = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, text=True, capture_output=True,
                          env={**os.environ, "DATABASE_URL": url})
    assert done.returncode == 0, done.stdout + done.stderr


def test_existing_workspaces_get_the_system_objects_and_the_migration_reverses():
    admin = create_engine(URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    url = URL.set(database=NAME).render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{NAME}"'))
    try:
        alembic(url, "upgrade", "0003")
        engine = create_engine(url)
        with engine.begin() as conn:  # two workspaces that exist before the record engine does
            org = conn.scalar(text("INSERT INTO organizations (name) VALUES ('Old') RETURNING id"))
            brand = conn.scalar(text("INSERT INTO brands (org_id, name) VALUES (:o, 'B') RETURNING id"), {"o": org})
            for name in ("One", "Two"):
                conn.execute(text("INSERT INTO workspaces (org_id, brand_id, name) VALUES (:o, :b, :n)"),
                             {"o": org, "b": brand, "n": name})
        alembic(url, "upgrade", "head")
        expected = {key: [f[0] for f in spec[4]] for key, spec in seed.SYSTEM_OBJECTS.items()}
        with engine.begin() as conn:
            for (workspace,) in conn.execute(text("SELECT id FROM workspaces")).all():
                objects = conn.execute(text("SELECT key, id, is_system, primary_fields FROM objects "
                                            "WHERE workspace_id = :w ORDER BY key"), {"w": workspace}).all()
                assert [o.key for o in objects] == ["company", "contact", "deal"] and all(o.is_system for o in objects)
                for o in objects:
                    keys = conn.execute(text("SELECT key FROM fields WHERE object_id = :o ORDER BY position"),
                                        {"o": o.id}).scalars().all()
                    assert keys == expected[o.key] and set(o.primary_fields) <= set(keys)
                labels = conn.execute(text("SELECT label, inverse_label FROM association_types WHERE workspace_id = :w "
                                           "ORDER BY label"), {"w": workspace}).all()
                assert [tuple(r) for r in labels] == [("company", "deal"), ("contact", "deal"), ("works at", "employs")]
            assert conn.scalar(text("SELECT count(DISTINCT id) FROM objects")) == 6  # not shared between workspaces
            flags = conn.execute(text("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname "
                                      "IN ('objects', 'fields', 'records', 'tags', 'record_tags', 'association_types', "
                                      "'associations', 'saved_views', 'event_records')")).all()
            assert len(flags) == 9 and all(f[1] and f[2] for f in flags)
        alembic(url, "downgrade", "0003")
        with engine.begin() as conn:
            assert conn.scalar(text("SELECT count(*) FROM pg_tables WHERE tablename IN ('objects', 'records')")) == 0
            assert conn.scalar(text("SELECT count(*) FROM workspaces")) == 2  # the rest is untouched
        alembic(url, "upgrade", "head")  # and forward again, seeding once more
        with engine.begin() as conn:
            assert conn.scalar(text("SELECT count(*) FROM objects")) == 6
        engine.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))
        admin.dispose()
