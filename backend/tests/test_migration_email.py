"""Migration 0015 on a database that already has organizations and roles: the email marketing tables appear with row
level security, the system roles gain the marketing capabilities (custom roles are left alone), a send is unique per
campaign and recipient in the schema itself, and it goes both ways."""
import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from test_migration_records import alembic

from app import config, roles_seed

URL = make_url(config.DATABASE_URL)
NAME = f"{URL.database}_email_migrate"
TABLES = ("email_settings", "email_domains", "email_templates", "email_topics", "email_preferences",
          "email_campaigns", "email_links", "email_sends", "email_events", "email_suppressions")
CAPS = {"owner": {"marketing.read", "marketing.write", "marketing.send", "marketing.manage"},
        "admin": {"marketing.read", "marketing.write", "marketing.send", "marketing.manage"},
        "manager": {"marketing.read", "marketing.write", "marketing.send", "marketing.manage"},
        "member": {"marketing.read", "marketing.write"}, "viewer": {"marketing.read"}, "automation": set()}


def previous() -> str:
    """The revision 0015 follows (read from the file, so a rebase onto a newer head keeps this test right)."""
    path = Path(__file__).parents[1] / "alembic" / "versions" / "0015_email_marketing.py"
    spec = importlib.util.spec_from_file_location("m0015", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.down_revision


@pytest.fixture
def old_database():
    admin = create_engine(URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    url = URL.set(database=NAME).render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{NAME}"'))
    engine = None
    try:
        alembic(url, "upgrade", previous())
        engine = create_engine(url)
        with engine.begin() as conn:
            org = conn.scalar(text("INSERT INTO organizations (name) VALUES ('Old') RETURNING id"))
            roles_seed.add(conn, org)
            conn.execute(text("UPDATE roles SET capabilities = ARRAY(SELECT c FROM unnest(capabilities) c "
                              "WHERE c NOT LIKE 'marketing.%')"))  # roles as they were before
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
    return {key: {c for c in caps if c.startswith("marketing.")}
            for key, caps in conn.execute(text("SELECT key, capabilities FROM roles"))}


def tables(conn) -> list[str]:
    return sorted(conn.scalars(text("SELECT relname FROM pg_class WHERE relname = ANY(:t) AND relkind = 'r' "
                                    "AND relrowsecurity AND relforcerowsecurity"), {"t": list(TABLES)}))


def test_tables_with_row_level_security_and_capabilities_appear_and_it_reverses(old_database):
    url, engine = old_database
    with engine.begin() as conn:
        assert tables(conn) == [] and capabilities(conn)["owner"] == set()
    alembic(url, "upgrade", "head")
    with engine.begin() as conn:
        assert tables(conn) == sorted(TABLES)
        held = capabilities(conn)
        assert {k: v for k, v in held.items() if k != "custom"} == CAPS and held["custom"] == set()
    alembic(url, "upgrade", "head")
    with engine.begin() as conn:  # nothing doubled
        assert conn.scalar(text("SELECT max(cardinality(capabilities)) FROM roles WHERE key = 'owner'")) == len(
            set(roles_seed.SYSTEM_ROLES["owner"][2]))
    alembic(url, "downgrade", previous())
    with engine.begin() as conn:
        assert tables(conn) == [] and set().union(*capabilities(conn).values()) == set()
        assert conn.scalar(text("SELECT capabilities FROM roles WHERE key = 'custom'")) == ["contacts.read"]
    alembic(url, "upgrade", "head")
    with engine.begin() as conn:
        assert capabilities(conn)["member"] == {"marketing.read", "marketing.write"}


def test_a_send_is_unique_per_campaign_by_contact_and_by_address_in_the_schema(old_database):
    url, engine = old_database
    alembic(url, "upgrade", "head")
    with engine.begin() as conn:
        org = conn.scalar(text("SELECT id FROM organizations"))
        brand = conn.scalar(text("INSERT INTO brands (org_id, name) VALUES (:o, 'B') RETURNING id"), {"o": org})
        ws = conn.scalar(text("INSERT INTO workspaces (org_id, brand_id, name) VALUES (:o, :b, 'W') RETURNING id"),
                         {"o": org, "b": brand})
        obj = conn.scalar(text("INSERT INTO objects (workspace_id, key, singular, plural, primary_fields) "
                               "VALUES (:w, 'contact', 'C', 'Cs', '{}') RETURNING id"), {"w": ws})
        a, b = (conn.scalar(text("INSERT INTO records (workspace_id, object_id) VALUES (:w, :o) RETURNING id"),
                            {"w": ws, "o": obj}) for _ in range(2))
        campaign = conn.scalar(text("INSERT INTO email_campaigns (workspace_id, name) VALUES (:w, 'C') RETURNING id"),
                               {"w": ws})
    insert = text("INSERT INTO email_sends (workspace_id, campaign_id, contact_id, email) VALUES (:w, :c, :r, :e)")
    with engine.begin() as conn:
        conn.execute(insert, {"w": ws, "c": campaign, "r": a, "e": "a@example.net"})
    for contact, address in ((a, "other@example.net"), (b, "a@example.net")):
        with pytest.raises(IntegrityError), engine.begin() as conn:
            conn.execute(insert, {"w": ws, "c": campaign, "r": contact, "e": address})
