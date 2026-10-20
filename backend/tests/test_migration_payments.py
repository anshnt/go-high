"""Migration 0016 on a database that already has organizations: the system roles gain the payments capabilities (custom
roles are left alone), the tables arrive with row level security forced, and it goes both ways."""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from test_migration_records import alembic

from app import config, roles_seed

URL = make_url(config.DATABASE_URL)
NAME = f"{URL.database}_payments_migrate"
FILE = Path(__file__).resolve().parents[1] / "alembic" / "versions" / "0016_payments.py"
spec = importlib.util.spec_from_file_location("payments_migration", FILE)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)
CAPS = {"owner": {"payments.read", "payments.write", "payments.refund", "payments.manage"},
        "admin": {"payments.read", "payments.write", "payments.refund", "payments.manage"},
        "manager": {"payments.read", "payments.write", "payments.refund"}, "member": {"payments.read", "payments.write"},
        "viewer": {"payments.read"}, "automation": {"payments.read", "payments.write"}, "custom": set()}


@pytest.fixture
def old_database():
    admin = create_engine(URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    url = URL.set(database=NAME).render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{NAME}"'))
    engine = None
    try:
        alembic(url, "upgrade", migration.down_revision)
        engine = create_engine(url)
        with engine.begin() as conn:
            conn.execute(text("SELECT set_config('app.system', 'on', true)"))
            org = conn.scalar(text("INSERT INTO organizations (name) VALUES ('Old') RETURNING id"))
            roles_seed.add(conn, org)
            conn.execute(text("UPDATE roles SET capabilities = ARRAY(SELECT c FROM unnest(capabilities) c "
                              "WHERE c NOT LIKE 'payments.%')"))  # roles as they were before
            conn.execute(text("INSERT INTO roles (org_id, key, name, capabilities) VALUES (:o, 'custom', 'C', "
                              "'{contacts.read}')"), {"o": org})
        yield url, engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))
        admin.dispose()


def capabilities(conn) -> dict[str, set[str]]:
    conn.execute(text("SELECT set_config('app.system', 'on', false)"))
    return {key: {c for c in caps if c.startswith("payments.")}
            for key, caps in conn.execute(text("SELECT key, capabilities FROM roles"))}


def test_the_migration_grants_the_system_roles_and_forces_row_level_security_both_ways(old_database):
    url, engine = old_database
    alembic(url, "upgrade", "0016")
    with engine.connect() as conn:
        assert capabilities(conn) == CAPS
        flags = conn.execute(text("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                                  "WHERE relname = ANY(:t)"), {"t": list(migration.RLS)}).all()
        assert len(flags) == len(migration.RLS) == 16 and all(f[1] and f[2] for f in flags)
    alembic(url, "downgrade", migration.down_revision)
    with engine.connect() as conn:
        assert capabilities(conn) == {k: set() for k in CAPS}
        assert conn.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_name = ANY(:t)"),
                           {"t": list(migration.RLS)}) == 0
