"""Migration 0012 on a database that already has workspaces and roles: the system roles gain the workflow capabilities
(custom roles are left alone), messages gain their idempotency key, and it goes both ways."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from test_migration_records import alembic

from app import config, roles_seed

URL = make_url(config.DATABASE_URL)  # conftest pointed DATABASE_URL at the test database
NAME = f"{URL.database}_workflows_migrate"  # a database of its own: the test database stays at head
TABLES = ("workflows", "workflow_versions", "workflow_runs", "workflow_steps", "workflow_trigger_checks",
          "workflow_waiters", "workflow_refs", "workflow_deliveries")
# `workflows.publish` was in the catalog before this module: Manager and the locked roles already held it
CAPS = {"owner": {"workflows.read", "workflows.write", "workflows.publish"},
        "admin": {"workflows.read", "workflows.write", "workflows.publish"},
        "manager": {"workflows.read", "workflows.write", "workflows.publish"},
        "member": {"workflows.read", "workflows.write"}, "viewer": {"workflows.read"}, "automation": set()}


@pytest.fixture
def old_database():
    admin = create_engine(URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    url = URL.set(database=NAME).render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{NAME}"'))
    engine = None
    try:
        alembic(url, "upgrade", "0011")
        engine = create_engine(url)
        with engine.begin() as conn:
            org = conn.scalar(text("INSERT INTO organizations (name) VALUES ('Old') RETURNING id"))
            roles_seed.add(conn, org)
            conn.execute(text("UPDATE roles SET capabilities = ARRAY(SELECT c FROM unnest(capabilities) c "
                              "WHERE c NOT IN ('workflows.read', 'workflows.write'))"))  # roles as they were before
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
    return {key: {c for c in caps if c.startswith("workflows.")}
            for key, caps in conn.execute(text("SELECT key, capabilities FROM roles"))}


def tables(conn) -> int:
    return conn.scalar(text("SELECT count(*) FROM information_schema.tables WHERE table_name = ANY(:t)"),
                       {"t": list(TABLES)})


def key_column(conn) -> int:
    return conn.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_name = 'messages' "
                            "AND column_name = 'idempotency_key'"))


def test_roles_get_capabilities_the_tables_and_the_key_appear_and_it_reverses(old_database):
    url, engine = old_database
    with engine.begin() as conn:
        assert tables(conn) == 0 and key_column(conn) == 0
        assert capabilities(conn)["viewer"] == set() and capabilities(conn)["owner"] == {"workflows.publish"}
    alembic(url, "upgrade", "head")
    with engine.begin() as conn:
        held = capabilities(conn)
        assert {k: v for k, v in held.items() if k != "custom"} == CAPS and held["custom"] == set()
        assert tables(conn) == len(TABLES) and key_column(conn) == 1
        assert conn.scalar(text("SELECT capabilities FROM roles WHERE key = 'custom'")) == ["contacts.read"]
    alembic(url, "upgrade", "head")  # nothing to do, and nothing doubled
    with engine.begin() as conn:
        assert conn.scalar(text("SELECT max(cardinality(capabilities)) FROM roles WHERE key = 'owner'")) == len(
            set(roles_seed.SYSTEM_ROLES["owner"][2]))
    alembic(url, "downgrade", "0011")
    with engine.begin() as conn:
        assert tables(conn) == 0 and key_column(conn) == 0
        held = capabilities(conn)
        assert held["viewer"] == held["member"] == held["automation"] == set()
        assert held["owner"] == held["admin"] == held["manager"] == {"workflows.publish"}  # which it had before
        assert conn.scalar(text("SELECT capabilities FROM roles WHERE key = 'custom'")) == ["contacts.read"]
    alembic(url, "upgrade", "head")  # and forward again
    with engine.begin() as conn:
        assert capabilities(conn)["member"] == {"workflows.read", "workflows.write"} and tables(conn) == len(TABLES)


def test_the_message_key_is_unique_per_workspace_and_a_workspace_may_repeat_a_missing_one(old_database):
    url, engine = old_database
    alembic(url, "upgrade", "head")
    with engine.begin() as conn:
        org = conn.scalar(text("SELECT id FROM organizations"))
        brand = conn.scalar(text("INSERT INTO brands (org_id, name) VALUES (:o, 'B') RETURNING id"), {"o": org})
        ws = [conn.scalar(text("INSERT INTO workspaces (org_id, brand_id, name) VALUES (:o, :b, 'W') RETURNING id"),
                          {"o": org, "b": brand}) for _ in range(2)]
        conn.execute(text("INSERT INTO objects (workspace_id, key, singular, plural, primary_fields) "
                          "VALUES (:w, 'contact', 'C', 'Cs', '{}')"), {"w": ws[0]})
        contact = conn.scalar(text("INSERT INTO records (workspace_id, object_id) SELECT workspace_id, id FROM objects "
                                   "RETURNING id"))
        conv = conn.scalar(text("INSERT INTO conversations (workspace_id, contact_id) VALUES (:w, :c) RETURNING id"),
                           {"w": ws[0], "c": contact})
    insert = text("INSERT INTO messages (workspace_id, conversation_id, seq, direction, status, idempotency_key) "
                  "VALUES (:w, :c, :s, 'out', 'queued', :k)")
    with engine.begin() as conn:
        conn.execute(insert, {"w": ws[0], "c": conv, "s": 1, "k": None})
        conn.execute(insert, {"w": ws[0], "c": conv, "s": 2, "k": None})  # no key: any number of them
        conn.execute(insert, {"w": ws[0], "c": conv, "s": 3, "k": "run:node"})
    from sqlalchemy.exc import IntegrityError
    with pytest.raises(IntegrityError), engine.begin() as conn:
        conn.execute(insert, {"w": ws[0], "c": conv, "s": 4, "k": "run:node"})
