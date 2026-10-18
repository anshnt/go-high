"""Password hashes live in `user_credentials`, which only their own user (and the pre-auth flows) can reach, so listing
the people of a workspace never exposes them."""
import pytest
from helpers import H, add_member, context, role_id, user_id_of
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.db import engine


def test_the_users_table_has_no_password_hash_column(db):
    columns = set(db.scalars(text("SELECT column_name FROM information_schema.columns WHERE table_name = 'users'")))
    assert "password_hash" not in columns and {"id", "email", "name", "email_verified_at"} <= columns
    assert set(db.scalars(text("SELECT column_name FROM information_schema.columns "
                               "WHERE table_name = 'user_credentials'"))) == {"user_id", "password_hash", "updated_at"}


def test_a_session_cannot_read_or_change_another_users_credentials_even_as_a_peer(make_user, db):
    alice, a_ids = make_user("alice@example.com")
    bob, b_ids = make_user("bob@example.com")
    carol = add_member(db, a_ids["org_id"], "carol@example.com", workspace_id=a_ids["workspace_id"])  # no password
    a_org, a_ws = a_ids["org_id"], a_ids["workspace_id"]
    me, bob_id, carol_id = user_id_of(alice), user_id_of(bob), user_id_of(carol)
    # Bob is also a person of Alice's workspace, so Alice's session can list him
    member = role_id(db, a_org, "member")
    db.execute(text("INSERT INTO org_members (user_id, org_id, role_id) VALUES (:u, :o, :r)"),
               {"u": bob_id, "o": a_org, "r": member})
    db.execute(text("INSERT INTO workspace_members (user_id, workspace_id, role_id) VALUES (:u, :w, :r)"),
               {"u": bob_id, "w": a_ws, "r": member})
    db.commit()
    ctx = {"user_id": me, "org_id": a_org, "workspace_id": a_ws}
    with engine.connect() as conn:
        with conn.begin():
            context(conn, **ctx)
            peers = conn.execute(text("SELECT email FROM users ORDER BY email")).scalars().all()
            assert peers == ["alice@example.com", "bob@example.com", "carol@example.com"]  # peers are visible
            assert "scrypt" not in " ".join(conn.execute(text("SELECT to_jsonb(u)::text FROM users u")).scalars())
            mine = conn.execute(text("SELECT user_id::text FROM user_credentials")).scalars().all()
            assert mine == [me]  # hers only
            assert conn.execute(text("SELECT password_hash FROM user_credentials WHERE user_id = :b"),
                                {"b": bob_id}).all() == []
            assert conn.execute(text("UPDATE user_credentials SET password_hash = 'x' WHERE user_id = :b"),
                                {"b": bob_id}).rowcount == 0
            assert conn.execute(text("DELETE FROM user_credentials WHERE user_id = :b"), {"b": bob_id}).rowcount == 0
            assert conn.execute(text("DELETE FROM user_credentials")).rowcount == 0  # nobody deletes one, hers included
            own = conn.execute(text("UPDATE user_credentials SET password_hash = password_hash"))
            assert own.rowcount == 1  # she may change her own
            conn.rollback()
        insert = "INSERT INTO user_credentials (user_id, password_hash) VALUES (:{}, 'x')"
        for statement in (insert.format("c"), insert.format("me")):  # a peer who has no password, and herself again
            with pytest.raises(DBAPIError, match="row-level security|duplicate key"), conn.begin():
                context(conn, **ctx)
                conn.execute(text(statement), {"c": carol_id, "me": me})
        for scope in ({"workspace_id": a_ws, "org_id": a_org}, {}):  # no user: no credentials at all
            with conn.begin():
                context(conn, **scope)
                assert conn.execute(text("SELECT count(*) FROM user_credentials")).scalar() == 0
        with conn.begin():  # the pre-auth scope (sign in, sign up) is the one that sees them all
            context(conn, system="on")
            assert conn.execute(text("SELECT count(*) FROM user_credentials")).scalar() == 2
    # and nothing the API lists carries a hash
    for path in ("/api/v1/members", "/api/v1/permissions/explain", "/api/me", "/api/v1/teams"):
        r = alice.get(path, headers={H: a_ws})
        assert r.status_code == 200 and "scrypt" not in r.text and "password_hash" not in r.text, path
    assert db.scalar(text("SELECT count(*) FROM user_credentials WHERE password_hash LIKE 'scrypt$%'")) == 2


def test_a_password_can_be_set_changed_and_cleared_through_the_credentials_table(make_user, db):
    from fastapi.testclient import TestClient
    from helpers import PASSWORD

    from app.main import app
    client, ids = make_user("a@example.com")
    assert client.get("/api/me").json()["user"]["has_password"] is True
    old = db.scalar(text("SELECT password_hash FROM user_credentials"))
    r = client.post("/api/auth/password", json={"current_password": PASSWORD, "password": "a different horse battery"})
    assert r.status_code == 204
    db.expire_all()
    assert db.scalar(text("SELECT password_hash FROM user_credentials")) != old
    assert db.scalar(text("SELECT count(*) FROM user_credentials")) == 1  # changed in place
    other = TestClient(app)
    assert other.post("/api/auth/signin", json={"email": "a@example.com", "password": "a different horse battery"}
                      ).status_code == 200
    # the first emailed link clears a password (it may belong to someone who only registered the address), and
    # setting one afterwards creates the row again
    magic, _ = make_user("m@example.com", verified=False)
    link = magic.post("/api/auth/magic-link", json={"email": "m@example.com"}).json()["link"]
    fresh = TestClient(app)
    assert fresh.post("/api/auth/magic-link/consume", json={"token": link.split("token=")[1]}).status_code == 200
    assert fresh.get("/api/me").json()["user"]["has_password"] is False  # the first link clears the password
    assert db.scalar(text("SELECT count(*) FROM user_credentials c JOIN users u ON u.id = c.user_id "
                          "WHERE u.email = 'm@example.com'")) == 0
    assert fresh.post("/api/auth/password", json={"password": "my first long password"}).status_code == 204
    assert fresh.get("/api/me").json()["user"]["has_password"] is True
    assert db.scalar(text("SELECT count(*) FROM user_credentials")) == 2
