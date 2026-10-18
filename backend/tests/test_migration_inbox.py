"""Migration 0006 on a database that has workspaces from before the inbox: their contact objects get a source and a time
zone field after the fields they have, a field of the same key that a workspace made itself is left alone, and it goes
both ways."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from test_migration_records import alembic

from app import config
from app.records import seed

URL = make_url(config.DATABASE_URL)  # conftest pointed DATABASE_URL at the test database
NAME = f"{URL.database}_inbox_migrate"  # a database of its own: the test database stays at head
INBOX = ["conversations.read", "conversations.write", "consents.manage", "channels.manage"]


@pytest.fixture
def old_database():
    admin = create_engine(URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    url = URL.set(database=NAME).render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{NAME}"'))
    engine = None
    try:
        alembic(url, "upgrade", "0003")
        engine = create_engine(url)
        with engine.begin() as conn:
            org = conn.scalar(text("INSERT INTO organizations (name) VALUES ('Old') RETURNING id"))
            brand = conn.scalar(text("INSERT INTO brands (org_id, name) VALUES (:o, 'B') RETURNING id"), {"o": org})
            for name in ("One", "Two"):
                conn.execute(text("INSERT INTO workspaces (org_id, brand_id, name) VALUES (:o, :b, :n)"),
                             {"o": org, "b": brand, "n": name})
        alembic(url, "upgrade", "0005")
        with engine.begin() as conn:  # make the contacts look like those before the inbox: six fields
            conn.execute(text("DELETE FROM fields WHERE key IN ('source', 'timezone')"))
            conn.execute(text("UPDATE roles SET capabilities = ARRAY(SELECT c FROM unnest(capabilities) c "
                              "WHERE c <> ALL(CAST(:caps AS text[])))"), {"caps": INBOX})  # roles of the old days
            conn.execute(text("INSERT INTO roles (org_id, key, name, capabilities) SELECT id, 'custom', 'Custom', "
                              "ARRAY['contacts.read'] FROM organizations"))
            one = conn.scalar(text("SELECT o.id FROM objects o JOIN workspaces w ON w.id = o.workspace_id "
                                   "WHERE w.name = 'One' AND o.key = 'contact'"))
            conn.execute(text("INSERT INTO fields (workspace_id, object_id, key, label, type, position) "
                              "SELECT workspace_id, id, 'source', 'Where from', 'text', 6 FROM objects WHERE id = :o"),
                         {"o": one})  # a workspace that made a "source" field of its own
        yield url, engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))
        admin.dispose()


def role_capabilities(conn) -> dict[str, set[str]]:
    return {key: set(caps) & set(INBOX) for key, caps in conn.execute(text("SELECT key, capabilities FROM roles"))}


def contact_fields(conn, workspace: str) -> list[tuple]:
    return [tuple(r) for r in conn.execute(text(
        "SELECT f.key, f.type, f.position, f.is_system FROM fields f JOIN objects o ON o.id = f.object_id "
        "JOIN workspaces w ON w.id = o.workspace_id WHERE w.name = :w AND o.key = 'contact' ORDER BY f.position"),
        {"w": workspace}).all()]


def test_contacts_get_a_source_and_a_time_zone_and_a_field_of_the_same_key_is_kept(old_database):
    url, engine = old_database
    alembic(url, "upgrade", "head")
    with engine.begin() as conn:
        assert contact_fields(conn, "Two") == [
            ("first_name", "text", 0, True), ("last_name", "text", 1, True), ("email", "email", 2, True),
            ("phone", "phone", 3, True), ("lifecycle", "select", 4, True), ("company", "record", 5, True),
            ("source", "select", 6, True), ("timezone", "text", 7, True)]
        assert contact_fields(conn, "One")[6:] == [("source", "text", 6, False), ("timezone", "text", 7, True)]
        choices = conn.scalar(text(
            "SELECT f.options FROM fields f JOIN objects o ON o.id = f.object_id JOIN workspaces w ON w.id = "
            "o.workspace_id WHERE w.name = 'Two' AND o.key = 'contact' AND f.key = 'source'"))
        assert [c["id"] for c in choices["choices"]] == [i for i, _ in seed.SOURCES]
        rules = conn.scalar(text("SELECT rules FROM fields WHERE key = 'timezone' LIMIT 1"))
        assert rules == {"timezone": True}
        assert conn.scalar(text("SELECT count(*) FROM fields WHERE key IN ('source', 'timezone') AND object_id IN "
                                "(SELECT id FROM objects WHERE key <> 'contact')")) == 0  # only contacts


def test_the_system_roles_gain_the_inbox_capabilities_and_a_custom_role_is_left_alone(old_database):
    url, engine = old_database
    alembic(url, "upgrade", "head")
    agent = {"conversations.read", "conversations.write", "consents.manage"}
    with engine.begin() as conn:
        assert role_capabilities(conn) == {
            "owner": set(INBOX), "admin": set(INBOX), "manager": agent, "member": agent,
            "viewer": {"conversations.read"}, "automation": {"conversations.read", "conversations.write"},
            "custom": set()}
        assert conn.scalar(text("SELECT capabilities FROM roles WHERE key = 'custom'")) == ["contacts.read"]
    alembic(url, "downgrade", "0005")
    with engine.begin() as conn:
        assert set().union(*role_capabilities(conn).values()) == set()
        assert conn.scalar(text("SELECT capabilities FROM roles WHERE key = 'custom'")) == ["contacts.read"]
    alembic(url, "upgrade", "head")
    with engine.begin() as conn:
        assert role_capabilities(conn)["manager"] == agent
        owner = conn.scalar(text("SELECT capabilities FROM roles WHERE key = 'owner'"))
        assert len(owner) == len(set(owner))  # nothing is granted twice


def test_the_migration_reverses_and_runs_again(old_database):
    url, engine = old_database
    alembic(url, "upgrade", "head")
    alembic(url, "downgrade", "0005")
    with engine.begin() as conn:
        assert conn.scalar(text("SELECT count(*) FROM pg_tables WHERE tablename IN ('channels', 'secrets', "
                                "'conversations', 'messages', 'consents', 'chat_limits', 'conversation_reads')")) == 0
        assert [f[0] for f in contact_fields(conn, "Two")] == [
            "first_name", "last_name", "email", "phone", "lifecycle", "company"]
        assert contact_fields(conn, "One")[6:] == [("source", "text", 6, False)]  # theirs stays
    alembic(url, "upgrade", "head")
    with engine.begin() as conn:
        assert [f[0] for f in contact_fields(conn, "Two")][6:] == ["source", "timezone"]
        assert conn.scalar(text("SELECT count(*) FROM workspaces")) == 2
