"""Migration 0010 on a database that already has people: the system roles of an existing organization get the
capabilities of forms (Manager publishes, Member only drafts, Viewer reads), custom roles get none, and it reverses."""
import os
import subprocess
import sys
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app import config, roles_seed

URL = make_url(config.DATABASE_URL)  # conftest pointed DATABASE_URL at the test database
BACKEND = Path(__file__).resolve().parents[1]
NAME = f"{URL.database}_forms_migrate"  # a database of its own: the test database stays at head
FORMS = ("forms.read", "forms.write", "forms.publish", "forms.delete", "responses.read", "responses.export")


def alembic(url: str, *args: str) -> None:
    done = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, text=True, capture_output=True,
                          env={**os.environ, "DATABASE_URL": url})
    assert done.returncode == 0, done.stdout + done.stderr


def capabilities(engine) -> dict[str, set[str]]:
    with engine.connect() as conn:
        return {key: set(caps) for key, caps in conn.execute(text("SELECT key, capabilities FROM roles"))}


def test_existing_roles_get_the_form_capabilities_and_the_migration_reverses():
    admin = create_engine(URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    url = URL.set(database=NAME).render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{NAME}"'))
    try:
        alembic(url, "upgrade", "0006")
        engine = create_engine(url)
        with engine.begin() as conn:  # an organization seeded by a release that knew nothing of forms
            org = conn.scalar(text("INSERT INTO organizations (name) VALUES ('Old') RETURNING id"))
            roles_seed.add(conn, org)
            conn.execute(text("UPDATE roles SET capabilities = array(SELECT c FROM unnest(capabilities) c "
                              "WHERE c <> ALL(CAST(:forms AS text[])))"), {"forms": list(FORMS)})
            conn.execute(text("INSERT INTO roles (org_id, key, name, description, is_system, capabilities) "
                              "VALUES (:o, 'custom', 'Custom', '', false, '{contacts.read}')"), {"o": org})
        assert not any(set(FORMS) & caps for caps in capabilities(engine).values())

        alembic(url, "upgrade", "head")
        caps = capabilities(engine)
        for key in ("owner", "admin", "manager"):
            assert set(FORMS) <= caps[key], key
        assert caps["member"] & set(FORMS) == {"forms.read", "forms.write", "responses.read"}
        assert caps["viewer"] & set(FORMS) == {"forms.read", "responses.read"}
        assert not caps["automation"] & set(FORMS) and not caps["custom"] & set(FORMS)
        assert "contacts.read" in caps["custom"] and "contacts.read" in caps["member"]  # nothing else was touched
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT count(*) FROM roles WHERE cardinality(capabilities) <> "
                                    "(SELECT count(DISTINCT c) FROM unnest(capabilities) c)")) == 0  # no duplicates

        alembic(url, "downgrade", "0006")
        assert not any(set(FORMS) & caps for caps in capabilities(engine).values())
        with engine.connect() as conn:
            assert conn.scalar(text("SELECT to_regclass('form_submissions')")) is None
        alembic(url, "upgrade", "head")
        assert set(FORMS) <= capabilities(engine)["owner"]
        engine.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))
