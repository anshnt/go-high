"""Migration 0011 on a database that already has workspaces and roles: every workspace gets a public handle, the system
roles gain the calendar capabilities (custom roles are left alone), and it goes both ways."""
import re

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from test_migration_records import alembic

from app import config, roles_seed

URL = make_url(config.DATABASE_URL)  # conftest pointed DATABASE_URL at the test database
NAME = f"{URL.database}_calendars_migrate"  # a database of its own: the test database stays at head
CAPS = {"owner": {"calendars.read", "calendars.write", "calendars.manage"},
        "admin": {"calendars.read", "calendars.write", "calendars.manage"},
        "manager": {"calendars.read", "calendars.write", "calendars.manage"},
        "member": {"calendars.read", "calendars.write"}, "viewer": {"calendars.read"},
        "automation": {"calendars.read", "calendars.write"}}


@pytest.fixture
def old_database():
    admin = create_engine(URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    url = URL.set(database=NAME).render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{NAME}"'))
    engine = None
    try:
        alembic(url, "upgrade", "0005")
        engine = create_engine(url)
        with engine.begin() as conn:
            org = conn.scalar(text("INSERT INTO organizations (name) VALUES ('Old') RETURNING id"))
            brand = conn.scalar(text("INSERT INTO brands (org_id, name) VALUES (:o, 'B') RETURNING id"), {"o": org})
            for name in ("Acme Plumbing", "Acme Plumbing", "!!!", "Ünïcode Café"):
                conn.execute(text("INSERT INTO workspaces (org_id, brand_id, name) VALUES (:o, :b, :n)"),
                             {"o": org, "b": brand, "n": name})
            roles_seed.add(conn, org)
            conn.execute(text("UPDATE roles SET capabilities = ARRAY(SELECT c FROM unnest(capabilities) c "
                              "WHERE c NOT LIKE 'calendars.%')"))  # roles as they were before the module
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
    return {key: {c for c in caps if c.startswith("calendars.")}
            for key, caps in conn.execute(text("SELECT key, capabilities FROM roles"))}


def test_workspaces_get_handles_roles_get_capabilities_and_it_reverses(old_database):
    url, engine = old_database
    alembic(url, "upgrade", "head")
    with engine.begin() as conn:
        slugs = conn.execute(text("SELECT name, slug FROM workspaces ORDER BY slug")).all()
        assert len({s for _, s in slugs}) == 4  # two of one name still differ
        by = {n: [s for name, s in slugs if name == n] for n in {n for n, _ in slugs}}
        assert all(s.startswith("acme-plumbing-") for s in by["Acme Plumbing"]) and len(by["Acme Plumbing"]) == 2
        assert by["!!!"][0].startswith("workspace-")  # nothing left of the name: a plain word
        assert all(re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", s) for _, s in slugs)  # letters, digits and single hyphens
        assert all(len(s) <= 60 and s == s.lower() for _, s in slugs)
        held = capabilities(conn)
        assert {k: v for k, v in held.items() if k != "custom"} == CAPS and held["custom"] == set()
        assert conn.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_name IN "
                                "('calendars', 'bookings', 'availability', 'feed_tokens')")) == 4
    alembic(url, "upgrade", "head")  # nothing to do, and nothing doubled
    with engine.begin() as conn:
        assert conn.scalar(text("SELECT max(cardinality(capabilities)) FROM roles WHERE key = 'owner'")) == len(
            set(roles_seed.SYSTEM_ROLES["owner"][2]))
    alembic(url, "downgrade", "0005")
    with engine.begin() as conn:
        assert all(not v for v in capabilities(conn).values())
        assert conn.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_name IN "
                                "('calendars', 'bookings', 'availability', 'feed_tokens')")) == 0
        assert conn.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_name = 'workspaces' "
                                "AND column_name = 'slug'")) == 0
        assert conn.scalar(text("SELECT capabilities FROM roles WHERE key = 'custom'")) == ["contacts.read"]
    alembic(url, "upgrade", "head")  # and forward again
    with engine.begin() as conn:
        assert capabilities(conn)["viewer"] == {"calendars.read"}
        assert conn.scalar(text("SELECT count(DISTINCT slug) FROM workspaces")) == 4
