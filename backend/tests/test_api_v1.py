import threading
import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from helpers import PASSWORD, H, add_member
from sqlalchemy import text

from app import api, config
from app.api import ApiError, decode_cursor, encode_cursor
from app.main import app

ROOT = "/api/v1/webhooks"
URL = "https://hooks.example.com/in"


def count(db, table="webhook_endpoints") -> int:
    db.expire_all()
    return db.scalar(text(f"SELECT count(*) FROM {table}"))


def test_v1_errors_share_one_envelope_with_the_trace_id(make_user, db):
    client, ids = make_user("a@example.com")
    ws = ids["workspace_id"]
    anonymous = TestClient(app)
    r = anonymous.get(ROOT, headers={"x-request-id": "trace-1"})
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "unauthenticated", "message": "Sign in required", "trace_id": "trace-1"}}

    for response, status, code in [
        (client.get(f"{ROOT}/{uuid.uuid4()}", headers={H: ws}), 404, "not_found"),
        (client.get(ROOT), 400, "bad_request"),
        (client.get(ROOT, headers={H: str(uuid.uuid4())}), 404, "not_found"),
        (client.get("/api/v1/nothing-here", headers={H: ws}), 404, "not_found"),
        (client.put(ROOT, headers={H: ws}), 405, "method_not_allowed"),
        (add_member(db, ids["org_id"], "m@example.com", workspace_id=ws).get(ROOT, headers={H: ws}), 403, "forbidden"),
    ]:
        error = response.json()["error"]
        assert response.status_code == status and error["code"] == code, response.text
        assert error["message"] and "fields" not in error
        assert error["trace_id"] == response.headers["x-request-id"] and len(error["trace_id"]) == 32


def test_validation_errors_name_the_fields(make_user):
    client, ids = make_user("a@example.com")
    ws = ids["workspace_id"]
    r = client.post(ROOT, json={"url": 5, "event_types": ["nope.nope", "webhook.test"], "filter": []}, headers={H: ws})
    error = r.json()["error"]
    assert r.status_code == 422 and error["code"] == "validation_failed"
    assert set(error["fields"]) == {"url", "event_types.0", "filter"}
    assert error["fields"]["event_types.0"] == "unknown event type 'nope.nope'"
    assert client.get(ROOT, params={"limit": 0}, headers={H: ws}).json()["error"]["fields"] == {
        "limit": "Input should be greater than or equal to 1"}
    assert "limit" in client.get(ROOT, params={"limit": 201}, headers={H: ws}).json()["error"]["fields"]
    assert client.get(f"{ROOT}/not-a-uuid", headers={H: ws}).json()["error"]["fields"].keys() == {"endpoint_id"}
    r = client.post(ROOT, content=b"{not json", headers={H: ws, "content-type": "application/json"})
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed"


def test_cross_site_writes_get_the_envelope_too(make_user):
    client, ids = make_user("a@example.com")
    r = client.post(ROOT, json={"url": URL}, headers={H: ids["workspace_id"], "Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "forbidden"
    old = client.post("/api/workspaces", json={}, headers={"Origin": "https://evil.example"})
    assert old.status_code == 403 and old.json() == {"detail": "Origin not allowed"}


def test_the_older_api_keeps_its_detail_errors(make_user):
    client, ids = make_user("a@example.com")
    assert client.get("/api/nope").json() == {"detail": "Not Found"}
    assert TestClient(app).get("/api/me").json() == {"detail": "Sign in required"}
    wrong = TestClient(app).post("/api/auth/signin", json={"email": "a@example.com", "password": "wrong password"})
    assert wrong.status_code == 401 and wrong.json() == {"detail": "Wrong email or password"}
    invalid = client.post("/api/auth/signin", json={"email": "nope"})
    assert invalid.status_code == 422 and isinstance(invalid.json()["detail"], list)
    assert client.get("/api/workspaces/current").json() == {"detail": "X-Workspace-Id header required"}


def test_cursors_round_trip_and_cannot_be_forged(monkeypatch):
    at, id_ = datetime(2026, 10, 16, 12, 30, tzinfo=UTC), uuid.uuid4()
    cursor = encode_cursor(at, id_)
    assert decode_cursor(cursor) == (at, id_) and "=" not in cursor and cursor.count(".") == 1
    payload, signature = cursor.split(".")
    for forged in (cursor + "0", payload, f"{payload}.", f".{signature}", f"{payload}x.{signature}", "", "junk",
                   f"{payload}.{'0' * 32}", encode_cursor(at, id_).replace(".", ":")):
        with pytest.raises(ApiError) as caught:
            decode_cursor(forged)
        assert caught.value.status_code == 400 and caught.value.code == "invalid_cursor"
    monkeypatch.setattr(config, "SECRET_KEY", "another key")  # a different key cannot read it, nor sign for the old one
    with pytest.raises(ApiError):
        decode_cursor(cursor)
    assert decode_cursor(encode_cursor(at, id_)) == (at, id_)


def test_pages_cover_every_row_once_and_the_last_page_has_no_cursor(make_user):
    client, ids = make_user("a@example.com")
    ws = ids["workspace_id"]
    made = [client.post(ROOT, json={"url": f"{URL}/{n}"}, headers={H: ws}).json()["id"] for n in range(5)]
    for limit, pages in [(2, 3), (5, 1), (4, 2), (1, 5), (200, 1)]:
        seen, cursor, taken = [], None, 0
        while True:
            r = client.get(ROOT, params={"limit": limit, **({"cursor": cursor} if cursor else {})}, headers={H: ws})
            body = r.json()
            assert set(body) == {"data", "next_cursor"}
            seen += [e["id"] for e in body["data"]]
            taken += 1
            if not (cursor := body["next_cursor"]):
                break
        assert seen == made[::-1] and taken == pages, (limit, seen)  # newest first
    assert client.get(ROOT, params={"cursor": "x.y"}, headers={H: ws}).json()["error"]["code"] == "invalid_cursor"


def test_the_same_key_and_request_return_the_stored_response(make_user, db):
    client, ids = make_user("a@example.com")
    ws = ids["workspace_id"]
    key = {H: ws, "Idempotency-Key": "create-1"}
    first = client.post(ROOT, json={"url": URL}, headers=key)
    again = client.post(ROOT, json={"url": URL}, headers=key)
    assert first.status_code == again.status_code == 201
    assert again.json() == first.json() and "secret" in again.json()  # the retry gets the lost response back
    assert "idempotent-replayed" not in first.headers and again.headers["idempotent-replayed"] == "true"
    assert count(db) == 1 and count(db, "idempotency_keys") == 1
    assert db.scalar(text("SELECT count(*) FROM events WHERE type = 'webhook_endpoint.created'")) == 1

    assert client.post(ROOT, json={"url": URL}, headers={H: ws}).status_code == 201  # no key: no replay
    assert client.post(ROOT, json={"url": URL}, headers={H: ws}).status_code == 201
    assert count(db) == 3


def test_the_same_key_with_another_request_is_a_conflict(make_user, db):
    client, ids = make_user("a@example.com")
    ws = ids["workspace_id"]
    key = {H: ws, "Idempotency-Key": "k"}
    made = client.post(ROOT, json={"url": URL}, headers=key).json()
    for r in (client.post(ROOT, json={"url": URL + "2"}, headers=key),  # another body
              client.post(f"{ROOT}/{made['id']}/test", headers=key),  # another route
              client.post(ROOT + "?x=1", json={"url": URL}, headers=key)):  # another query
        assert r.status_code == 409 and r.json()["error"]["code"] == "idempotency_key_reused", r.text
    assert count(db) == 1
    assert client.post(ROOT, json={"url": URL}, headers=key).status_code == 201  # the original still replays


def test_keys_are_per_workspace_and_only_for_posts(make_user, db):
    client, ids = make_user("a@example.com")
    second = client.post("/api/workspaces", json={"name": "Two", "brand_id": ids["brand_id"]}).json()["id"]
    key = "shared-key"
    one = client.post(ROOT, json={"url": URL}, headers={H: ids["workspace_id"], "Idempotency-Key": key}).json()
    two = client.post(ROOT, json={"url": URL}, headers={H: second, "Idempotency-Key": key})
    assert two.status_code == 201 and two.json()["id"] != one["id"] and "idempotent-replayed" not in two.headers
    r = client.get(ROOT, headers={H: second, "Idempotency-Key": key})
    assert r.status_code == 200 and "idempotent-replayed" not in r.headers
    for bad in ("", "k" * 256):
        r = client.post(ROOT, json={"url": URL}, headers={H: second, "Idempotency-Key": bad})
        assert r.status_code == 422 and "idempotency-key" in r.json()["error"]["fields"], bad


def test_failed_requests_store_nothing_so_the_retry_can_succeed(make_user, db):
    client, ids = make_user("a@example.com")
    key = {H: ids["workspace_id"], "Idempotency-Key": "retry-me"}
    assert client.post(ROOT, json={"url": "https://10.0.0.1/x"}, headers=key).status_code == 422
    assert client.post(ROOT, json={}, headers=key).status_code == 422
    assert count(db, "idempotency_keys") == 0
    assert client.post(ROOT, json={"url": URL}, headers=key).status_code == 201


def test_keys_expire_after_24_hours(make_user, db):
    client, ids = make_user("a@example.com")
    key = {H: ids["workspace_id"], "Idempotency-Key": "old"}
    first = client.post(ROOT, json={"url": URL}, headers=key).json()
    db.execute(text("UPDATE idempotency_keys SET created_at = now() - interval '23 hours'"))
    db.commit()
    assert client.post(ROOT, json={"url": URL}, headers=key).json() == first
    db.execute(text("UPDATE idempotency_keys SET created_at = now() - interval '25 hours'"))
    db.commit()
    again = client.post(ROOT, json={"url": URL}, headers=key)
    assert again.status_code == 201 and again.json()["id"] != first["id"]  # a new request, the old row is replaced
    assert count(db) == 2 and count(db, "idempotency_keys") == 1


def test_a_request_that_loses_the_race_for_a_key_replays_the_winner(make_user, db, monkeypatch):
    """Both requests pass the lookup before either stores; the second commit fails on the key, rolling its work back."""
    client, ids = make_user("a@example.com")
    key = {H: ids["workspace_id"], "Idempotency-Key": "race"}
    first = client.post(ROOT, json={"url": URL}, headers=key)
    real, calls = api.stored_for, []

    def blind_once(db, workspace_id, key):  # the lookup in the dependency finds nothing, as if it ran too early
        calls.append(key)
        return None if len(calls) == 1 else real(db, workspace_id, key)

    monkeypatch.setattr(api, "stored_for", blind_once)
    loser = client.post(ROOT, json={"url": URL}, headers=key)
    assert loser.status_code == 201 and loser.json() == first.json() and loser.headers["idempotent-replayed"] == "true"
    assert len(calls) == 2 and count(db) == 1  # its endpoint, event and job were rolled back
    assert db.scalar(text("SELECT count(*) FROM events WHERE type = 'webhook_endpoint.created'")) == 1

    calls.clear()
    other_body = client.post(ROOT, json={"url": URL + "x"}, headers=key)  # same race, but a different request
    assert other_body.status_code == 409 and count(db) == 1


def test_concurrent_requests_with_one_key_create_one_resource(make_user, db):
    client, ids = make_user("a@example.com")
    second = TestClient(app)
    assert second.post("/api/auth/signin", json={"email": "a@example.com", "password": PASSWORD}).status_code == 200
    key = {H: ids["workspace_id"], "Idempotency-Key": "parallel"}
    start, results = threading.Barrier(2), []

    def post(c):
        start.wait()
        results.append(c.post(ROOT, json={"url": URL}, headers=key))

    threads = [threading.Thread(target=post, args=(c,)) for c in (client, second)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert [r.status_code for r in results] == [201, 201]
    assert results[0].json() == results[1].json() and count(db) == 1
