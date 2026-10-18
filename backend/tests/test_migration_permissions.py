"""Migration 0005 on a database that already has people: every organization gets the system roles, the fixed role
strings become role ids, the policies that read them keep working, and it goes both ways."""
import os
import subprocess
import sys
from pathlib import Path

import pytest
from helpers import context
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from app import config, roles_seed

URL = make_url(config.DATABASE_URL)  # conftest pointed DATABASE_URL at the test database

BACKEND = Path(__file__).resolve().parents[1]
NAME = f"{URL.database}_perms_migrate"  # a database of its own: the test database stays at head


def alembic(url: str, *args: str) -> None:
    done = subprocess.run([sys.executable, "-m", "alembic", *args], cwd=BACKEND, text=True, capture_output=True,
                          env={**os.environ, "DATABASE_URL": url})
    assert done.returncode == 0, done.stdout + done.stderr


def visible_workspaces(engine, user_id) -> list[str]:
    with engine.connect() as conn, conn.begin():
        context(conn, user_id=user_id)  # what the API sees of a user before a workspace is chosen
        return conn.execute(text("SELECT name FROM workspaces ORDER BY name")).scalars().all()


def test_existing_people_get_the_system_roles_and_the_migration_reverses():
    admin = create_engine(URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    url = URL.set(database=NAME).render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{NAME}"'))
    try:
        alembic(url, "upgrade", "0004")
        engine = create_engine(url)
        who: dict[str, str] = {}
        hashes = {"owner": "scrypt$16384$aa$bb", "member": "scrypt$16384$cc$dd"}  # the others sign in by link only
        with engine.begin() as conn:  # an organization with an owner, an admin and two members, as 0002 stored them
            org = conn.scalar(text("INSERT INTO organizations (name) VALUES ('Old') RETURNING id"))
            other = conn.scalar(text("INSERT INTO organizations (name) VALUES ('Other') RETURNING id"))
            brand = conn.scalar(text("INSERT INTO brands (org_id, name) VALUES (:o, 'B') RETURNING id"), {"o": org})
            workspaces = {n: conn.scalar(text("INSERT INTO workspaces (org_id, brand_id, name) VALUES (:o, :b, :n) "
                                              "RETURNING id"), {"o": org, "b": brand, "n": n}) for n in ("One", "Two")}
            for name, org_id, role in (("owner", org, "owner"), ("admin", org, "admin"), ("member", org, "member"),
                                       ("wsadmin", org, "member"), ("stranger", other, "owner")):
                who[name] = conn.scalar(text("INSERT INTO users (email, name) VALUES (:e, :n) RETURNING id"),
                                        {"e": f"{name}@example.com", "n": name})
                conn.execute(text("INSERT INTO org_members (user_id, org_id, role) VALUES (:u, :o, :r)"),
                             {"u": who[name], "o": org_id, "r": role})
                if name in hashes:
                    conn.execute(text("UPDATE users SET password_hash = :h WHERE id = :u"),
                                 {"h": hashes[name], "u": who[name]})
            for name, workspace, role in (("member", "One", "member"), ("wsadmin", "Two", "admin")):
                conn.execute(text("INSERT INTO workspace_members (user_id, workspace_id, role) VALUES (:u, :w, :r)"),
                             {"u": who[name], "w": workspaces[workspace], "r": role})
        assert visible_workspaces(engine, who["admin"]) == ["One", "Two"]
        alembic(url, "upgrade", "head")

        with engine.begin() as conn:
            roles = conn.execute(text("SELECT org_id, key, is_system, capabilities, name FROM roles")).all()
            assert len(roles) == 12 and {r.key for r in roles} == set(roles_seed.SYSTEM_ROLES)
            assert all(r.is_system for r in roles) and {r.org_id for r in roles} == {org, other}
            owner_role = next(r for r in roles if r.key == "owner" and r.org_id == org)
            assert set(owner_role.capabilities) == roles_seed.SYSTEM_ROLES["owner"][2]
            assert conn.scalar(text("SELECT count(*) FROM role_object_rules "
                                    "WHERE object_key = '*' AND scope = 'all'")) == 12
            mapped = conn.execute(text("SELECT u.name, r.key FROM org_members m JOIN users u ON u.id = m.user_id "
                                       "JOIN roles r ON r.id = m.role_id AND r.org_id = m.org_id "
                                       "ORDER BY u.name")).all()
            assert [tuple(m) for m in mapped] == [("admin", "admin"), ("member", "member"), ("owner", "owner"),
                                                  ("stranger", "owner"), ("wsadmin", "member")]
            mapped = conn.execute(text("SELECT u.name, r.key FROM workspace_members m JOIN users u ON u.id = m.user_id "
                                       "JOIN roles r ON r.id = m.role_id ORDER BY u.name")).all()
            assert [tuple(m) for m in mapped] == [("member", "member"), ("wsadmin", "admin")]
            assert conn.scalar(text("SELECT count(*) FROM information_schema.columns WHERE column_name = 'role' "
                                    "AND table_name IN ('org_members', 'workspace_members')")) == 0
            # password hashes moved out of users: one row for each user who had one, and no column left behind
            kept = conn.execute(text("SELECT u.name, c.password_hash FROM user_credentials c "
                                     "JOIN users u ON u.id = c.user_id ORDER BY u.name")).all()
            assert [tuple(k) for k in kept] == [("member", hashes["member"]), ("owner", hashes["owner"])]
            assert conn.scalar(text("SELECT count(*) FROM information_schema.columns "
                                    "WHERE table_name = 'users' AND column_name = 'password_hash'")) == 0
            flags = conn.execute(text("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname "
                                      "IN ('roles', 'role_object_rules', 'teams', 'team_members')")).all()
            assert len(flags) == 4 and all(f[1] and f[2] for f in flags)
            assert not conn.scalar(text("SELECT has_table_privilege('gohigh_app', 'events', 'UPDATE')"))
            assert not conn.scalar(text("SELECT has_table_privilege('gohigh_app', 'events', 'DELETE')"))
        # the two workspace policies that read a member's role were rewritten, and still say the same
        assert visible_workspaces(engine, who["admin"]) == ["One", "Two"]  # an org admin sees every workspace
        assert visible_workspaces(engine, who["owner"]) == ["One", "Two"]
        assert visible_workspaces(engine, who["member"]) == ["One"]
        assert visible_workspaces(engine, who["wsadmin"]) == ["Two"]
        assert visible_workspaces(engine, who["stranger"]) == []
        with engine.begin() as conn:
            brand = conn.scalar(text("SELECT id FROM brands"))
        create = text("INSERT INTO workspaces (org_id, brand_id, name) VALUES (:o, :b, 'Three')")
        with engine.connect() as conn, conn.begin():  # an org admin may create a workspace
            context(conn, user_id=who["admin"])
            conn.execute(create, {"o": org, "b": brand})
            conn.rollback()
        with pytest.raises(DBAPIError, match="row-level security"), engine.connect() as conn, conn.begin():
            context(conn, user_id=who["member"])  # a member may not
            conn.execute(create, {"o": org, "b": brand})
        # a custom role, held in a workspace, goes back to `member` when the strings come back
        with engine.begin() as conn:
            custom = conn.scalar(text("INSERT INTO roles (org_id, key, name, capabilities) VALUES (:o, 'custom', 'C', "
                                      "'{contacts.read}') RETURNING id"), {"o": org})
            conn.execute(text("UPDATE workspace_members SET role_id = :r WHERE user_id = :u"),
                         {"r": custom, "u": who["wsadmin"]})
        alembic(url, "downgrade", "0004")
        with engine.begin() as conn:
            assert conn.scalar(text("SELECT count(*) FROM pg_tables WHERE tablename IN ('roles', 'teams')")) == 0
            org_roles = conn.execute(text("SELECT u.name, m.role FROM org_members m JOIN users u ON u.id = m.user_id "
                                          "ORDER BY u.name")).all()
            assert [tuple(r) for r in org_roles] == [("admin", "admin"), ("member", "member"), ("owner", "owner"),
                                                     ("stranger", "owner"), ("wsadmin", "member")]
            ws_roles = conn.execute(text("SELECT u.name, m.role FROM workspace_members m "
                                         "JOIN users u ON u.id = m.user_id ORDER BY u.name")).all()
            assert [tuple(r) for r in ws_roles] == [("member", "member"), ("wsadmin", "member")]
            assert conn.scalar(text("SELECT count(*) FROM workspaces")) == 2  # the rest is untouched
            back = conn.execute(text("SELECT name, password_hash FROM users WHERE password_hash IS NOT NULL "
                                     "ORDER BY name")).all()
            assert [tuple(b) for b in back] == [("member", hashes["member"]), ("owner", hashes["owner"])]
            assert conn.scalar(text("SELECT count(*) FROM pg_tables WHERE tablename = 'user_credentials'")) == 0
        assert visible_workspaces(engine, who["admin"]) == ["One", "Two"]  # the old policies are back
        assert visible_workspaces(engine, who["member"]) == ["One"]
        assert visible_workspaces(engine, who["stranger"]) == []
        alembic(url, "upgrade", "head")  # and forward again, seeding once more
        with engine.begin() as conn:
            assert conn.scalar(text("SELECT count(*) FROM roles")) == 12
            assert conn.scalar(text("SELECT count(*) FROM user_credentials")) == 2
            assert conn.scalar(text("SELECT count(*) FROM workspace_members m JOIN roles r ON r.id = m.role_id "
                                    "WHERE r.key = 'member'")) == 2
        assert visible_workspaces(engine, who["admin"]) == ["One", "Two"]
        engine.dispose()
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))
        admin.dispose()
