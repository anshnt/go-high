import hashlib
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from helpers import PASSWORD
from sqlalchemy import text

from app import config
from app.main import app


def signin(email="a@example.com", password=PASSWORD):
    client = TestClient(app)
    return client, client.post("/api/auth/signin", json={"email": email, "password": password})


def link_token(link: str) -> str:
    return parse_qs(urlparse(link).query)["token"][0]


def test_signup_creates_org_brand_workspace_and_owner(make_user, db):
    client, ids = make_user("a@example.com", "Acme")
    me = client.get("/api/me").json()
    assert me["user"]["email"] == "a@example.com"
    assert [(o["name"], o["role"]) for o in me["orgs"]] == [("Acme", "owner")]
    assert [(w["id"], w["role"]) for w in me["workspaces"]] == [(ids["workspace_id"], "admin")]
    assert db.execute(text("SELECT name FROM brands WHERE id = :id"), {"id": ids["brand_id"]}).scalar() == "Default"


def test_signup_rejects_short_password_duplicate_and_bad_email(make_user):
    client = TestClient(app)
    ok = {"email": "a@example.com", "name": "A", "password": PASSWORD}
    assert client.post("/api/auth/signup", json={**ok, "password": "short"}).status_code == 422
    assert client.post("/api/auth/signup", json={**ok, "email": "nope"}).status_code == 422
    assert client.post("/api/auth/signup", json=ok).status_code == 201
    assert client.post("/api/auth/signup", json={**ok, "email": " A@Example.COM "}).status_code == 409


def test_email_is_case_insensitive_and_password_is_scrypt_hashed(make_user, db):
    make_user("Mixed@Example.com")
    assert signin("mixed@example.COM")[1].status_code == 200
    stored = db.execute(text("SELECT email, password_hash FROM users")).one()
    assert stored.email == "mixed@example.com"
    assert stored.password_hash.startswith("scrypt$") and PASSWORD not in stored.password_hash


def test_signin_wrong_password_and_unknown_email_look_the_same(make_user):
    make_user("a@example.com")
    wrong = signin("a@example.com", "wrong password!")[1]
    unknown = signin("nobody@example.com", PASSWORD)[1]
    assert (wrong.status_code, wrong.json()) == (unknown.status_code, unknown.json()) == (401, wrong.json())
    assert "set-cookie" not in wrong.headers


def test_repeated_failures_are_throttled_even_for_the_right_password(make_user):
    make_user("a@example.com")
    for _ in range(config.LOGIN_MAX_FAILURES):
        assert signin("a@example.com", "wrong password!")[1].status_code == 401
    blocked = signin("a@example.com", PASSWORD)[1]
    assert blocked.status_code == 429 and "retry-after" in blocked.headers
    assert signin("b@example.com", "wrong password!")[1].status_code == 401  # other emails are unaffected


def test_success_resets_the_failure_count(make_user):
    make_user("a@example.com")
    for _ in range(config.LOGIN_MAX_FAILURES - 1):
        signin("a@example.com", "wrong password!")
    assert signin()[1].status_code == 200
    assert signin("a@example.com", "wrong password!")[1].status_code == 401


def test_session_cookie_flags_and_only_its_hash_is_stored(make_user, db, monkeypatch):
    client, _ = make_user("a@example.com")
    r = signin()[1]
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie and "max-age=" in cookie
    assert "secure" not in cookie  # COOKIE_SECURE=0 in tests
    monkeypatch.setattr(config, "COOKIE_SECURE", True)
    secure = signin()[1].headers["set-cookie"].lower()
    assert "secure" in secure

    token = client.cookies["gohigh_session"]
    hashes = db.scalars(text("SELECT token_hash FROM auth_sessions")).all()
    assert hashlib.sha256(token.encode()).hexdigest() in hashes
    assert token not in hashes


def test_signout_revokes_the_session_and_clears_the_cookie(make_user):
    client, _ = make_user("a@example.com")
    r = client.post("/api/auth/signout")
    assert r.status_code == 204 and "max-age=0" in r.headers["set-cookie"].lower()
    assert client.get("/api/me").status_code == 401
    stale = TestClient(app)
    assert stale.post("/api/auth/signout").status_code == 204  # idempotent without a session


def test_me_requires_a_session():
    assert TestClient(app).get("/api/me").status_code == 401


def test_revoking_a_session_takes_effect_immediately(make_user):
    first, _ = make_user("a@example.com")
    second, _ = signin()
    sessions = first.get("/api/auth/sessions").json()
    assert len(sessions) == 2 and [s["current"] for s in sessions].count(True) == 1
    other = next(s for s in sessions if not s["current"])
    assert second.get("/api/me").status_code == 200
    assert first.delete(f"/api/auth/sessions/{other['id']}").status_code == 204
    assert second.get("/api/me").status_code == 401
    assert first.get("/api/me").status_code == 200
    assert first.delete(f"/api/auth/sessions/{other['id']}").status_code == 404  # already revoked
    assert len(first.get("/api/auth/sessions").json()) == 1


def test_users_cannot_see_or_revoke_each_others_sessions(make_user):
    a, _ = make_user("a@example.com")
    b, _ = make_user("b@example.com")
    b_session = b.get("/api/auth/sessions").json()[0]["id"]
    assert a.delete(f"/api/auth/sessions/{b_session}").status_code == 404
    assert b.get("/api/me").status_code == 200
    assert b_session not in [s["id"] for s in a.get("/api/auth/sessions").json()]


def test_idle_and_absolute_timeouts(make_user, db):
    client, _ = make_user("a@example.com")
    db.execute(text("UPDATE auth_sessions SET last_seen_at = now() - interval '2 days'"))
    db.commit()
    assert client.get("/api/me").status_code == 401  # idle too long

    client, _ = signin()
    db.execute(text("UPDATE auth_sessions SET expires_at = now() - interval '1 second'"))
    db.commit()
    assert client.get("/api/me").status_code == 401  # past its absolute expiry


def test_activity_keeps_a_session_alive(make_user, db):
    client, _ = make_user("a@example.com")
    db.execute(text("UPDATE auth_sessions SET last_seen_at = now() - make_interval(mins => :m)"),
               {"m": config.SESSION_IDLE_MINUTES - 5})
    db.commit()
    assert client.get("/api/me").status_code == 200
    assert db.execute(text("SELECT now() - last_seen_at < interval '1 minute' FROM auth_sessions")).scalar()


def test_magic_link_signs_in_once(make_user):
    make_user("a@example.com")
    r = TestClient(app).post("/api/auth/magic-link", json={"email": "A@example.com"})
    assert r.status_code == 202
    token = link_token(r.json()["link"])
    client = TestClient(app)
    ok = client.post("/api/auth/magic-link/consume", json={"token": token})
    assert ok.status_code == 200 and ok.json()["user"]["email"] == "a@example.com"
    assert client.get("/api/me").status_code == 200
    again = TestClient(app).post("/api/auth/magic-link/consume", json={"token": token})
    assert again.status_code == 401


def test_magic_link_expires(make_user, db):
    make_user("a@example.com")
    link = TestClient(app).post("/api/auth/magic-link", json={"email": "a@example.com"}).json()["link"]
    db.execute(text("UPDATE magic_links SET expires_at = now() - interval '1 second'"))
    db.commit()
    assert TestClient(app).post("/api/auth/magic-link/consume", json={"token": link_token(link)}).status_code == 401
    assert TestClient(app).post("/api/auth/magic-link/consume", json={"token": "garbage"}).status_code == 401


def test_magic_link_lives_fifteen_minutes_and_only_its_hash_is_stored(make_user, db):
    make_user("a@example.com")
    link = TestClient(app).post("/api/auth/magic-link", json={"email": "a@example.com"}).json()["link"]
    row = db.execute(text("SELECT token_hash, extract(epoch FROM expires_at - created_at) ttl FROM magic_links")).one()
    assert round(row.ttl) == 15 * 60 and row.token_hash == hashlib.sha256(link_token(link).encode()).hexdigest()


def test_magic_link_request_does_not_reveal_whether_the_account_exists(make_user, monkeypatch):
    make_user("a@example.com")
    monkeypatch.setattr(config, "DEV_EXPOSE_MAGIC_LINKS", False)
    known = TestClient(app).post("/api/auth/magic-link", json={"email": "a@example.com"})
    unknown = TestClient(app).post("/api/auth/magic-link", json={"email": "nobody@example.com"})
    assert (known.status_code, known.json()) == (unknown.status_code, unknown.json()) == (202, {"status": "sent"})


def test_magic_link_is_logged_and_works_for_a_passwordless_user(db, caplog):
    client = TestClient(app)
    assert client.post("/api/auth/signup", json={"email": "m@example.com", "name": "M"}).status_code == 201
    assert signin("m@example.com", "anything at all")[1].status_code == 401  # no password to guess
    with caplog.at_level("INFO", logger="auth"):
        link = TestClient(app).post("/api/auth/magic-link", json={"email": "m@example.com"}).json()["link"]
    assert link in caplog.text
    assert TestClient(app).post("/api/auth/magic-link/consume", json={"token": link_token(link)}).status_code == 200


def test_magic_link_requests_are_capped(make_user, db):
    make_user("a@example.com")
    for _ in range(8):
        assert TestClient(app).post("/api/auth/magic-link", json={"email": "a@example.com"}).status_code == 202
    assert db.execute(text("SELECT count(*) FROM magic_links")).scalar() == 5


def test_cross_origin_writes_with_a_session_cookie_are_refused(make_user):
    client, _ = make_user("a@example.com")
    evil = {"Origin": "https://evil.example"}
    assert client.post("/api/auth/signout", headers=evil).status_code == 403
    assert client.get("/api/me", headers=evil).status_code == 200  # safe methods are not state changing
    assert client.get("/api/me").status_code == 200  # the refused signout did nothing
    assert client.post("/api/auth/signout", headers={"Origin": config.ALLOWED_ORIGINS[0] + "/"}).status_code == 204


def test_writes_without_an_origin_header_or_without_a_cookie_are_not_blocked():
    anonymous = TestClient(app)
    r = anonymous.post("/api/auth/signup", json={"email": "a@example.com", "name": "A", "password": PASSWORD},
                       headers={"Origin": "https://partner.example"})
    assert r.status_code == 201  # no cookie yet; third-party pages may post to public endpoints


def test_first_magic_link_evicts_whoever_registered_the_address_before_it_was_verified(make_user):
    squatter, _ = make_user("victim@example.com")  # signed up with someone else's address and a password
    assert squatter.get("/api/me").json()["user"]["email_verified"] is False
    link = TestClient(app).post("/api/auth/magic-link", json={"email": "victim@example.com"}).json()["link"]
    owner = TestClient(app)
    r = owner.post("/api/auth/magic-link/consume", json={"token": link_token(link)})
    assert r.status_code == 200 and r.json()["user"]["email_verified"] is True
    assert squatter.get("/api/me").status_code == 401  # pre-verification session revoked
    assert signin("victim@example.com", PASSWORD)[1].status_code == 401  # pre-verification password cleared
    # Later links only sign in: the verified owner's session survives.
    link = TestClient(app).post("/api/auth/magic-link", json={"email": "victim@example.com"}).json()["link"]
    assert TestClient(app).post("/api/auth/magic-link/consume", json={"token": link_token(link)}).status_code == 200
    assert owner.get("/api/me").status_code == 200


def test_failures_from_many_addresses_hit_the_per_email_ceiling(make_user, monkeypatch):
    make_user("a@example.com")
    monkeypatch.setattr(config, "LOGIN_MAX_FAILURES", 100)  # as if every guess came from a new IP
    monkeypatch.setattr(config, "LOGIN_MAX_FAILURES_PER_EMAIL", 3)
    for _ in range(3):
        assert signin("a@example.com", "wrong password!")[1].status_code == 401
    assert signin("a@example.com", PASSWORD)[1].status_code == 429
