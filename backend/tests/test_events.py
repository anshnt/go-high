import json
import re
import threading
import time
import uuid
from pathlib import Path

import pytest
from helpers import drain, due_now, wait_for_quiet
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app import events
from app.db import SessionLocal, scoped
from app.events import Event, UnknownEventType, advance, emit, read_batch

APP = Path(__file__).resolve().parents[1] / "app"


def fire(db, workspace_id, n: int = 0) -> Event:
    """An event of a type with a trivial payload, in the caller's transaction."""
    return emit(db, "webhook.test", "webhook_endpoint", uuid.uuid4(),
                {"endpoint_id": str(uuid.uuid4()), "message": f"event {n}"}, workspace_id=workspace_id)


def consume(consumer: str, quiet: bool = True) -> list[int]:
    """What one dispatcher pass does for a consumer: read, process, advance, commit. `quiet=False` where the test
    holds a transaction open on purpose (see helpers.wait_for_quiet)."""
    if quiet:
        wait_for_quiet()
    with SessionLocal() as db:
        batch = read_batch(db, consumer)
        advance(db, consumer, batch)
        db.commit()
        return [e.id for e in batch]


def new_workspace(make_user, email: str = "a@example.com") -> str:
    return make_user(email)[1]["workspace_id"]


@pytest.fixture
def two_workspaces(make_user):
    return new_workspace(make_user), new_workspace(make_user, "b@example.com")


def test_every_registered_type_has_a_valid_schema():
    assert {"workspace.created", "user.signed_up", "webhook_endpoint.created", "webhook.test"} <= set(events.TYPES)
    for name, schema in events.TYPES.items():
        assert re.fullmatch(r"[a-z_]+(\.[a-z_]+)+", name), name
        assert schema["title"] == name and schema["type"] == "object" and schema["additionalProperties"] is False
        assert schema["$schema"].startswith("https://json-schema.org/") and schema["description"]
        assert schema["required"] and set(schema["required"]) <= set(schema["properties"]), name
        assert all("type" in p for p in schema["properties"].values()), name
    files = {p.stem for p in events.SCHEMAS.glob("*.json")}
    assert files == set(events.TYPES)
    for path in events.SCHEMAS.glob("*.json"):
        json.loads(path.read_text())  # also parses on its own


def test_every_type_the_code_emits_is_registered():
    pattern = re.compile(r"emit(?:_many)?\(\s*[\w.]+\s*,\s*\"([\w.]+)\"")
    emitted = {m for path in APP.rglob("*.py") for m in pattern.findall(path.read_text(encoding="utf-8"))}
    assert emitted and emitted <= set(events.TYPES), emitted - set(events.TYPES)
    assert emitted == set(events.TYPES)  # and no schema is left without an emitter


def test_emit_refuses_unknown_types_and_bad_payloads(make_user, db):
    ws = new_workspace(make_user)
    with pytest.raises(UnknownEventType):
        emit(db, "contact.created", "contact", uuid.uuid4(), {}, workspace_id=ws)
    with pytest.raises(ValueError, match="missing"):
        emit(db, "webhook.test", "webhook_endpoint", uuid.uuid4(), {"endpoint_id": str(uuid.uuid4())}, workspace_id=ws)
    with pytest.raises(ValueError, match="unexpected"):
        emit(db, "webhook.test", "webhook_endpoint", uuid.uuid4(),
             {"endpoint_id": str(uuid.uuid4()), "message": "m", "extra": 1}, workspace_id=ws)
    with pytest.raises(ValueError, match="needs a workspace"):
        emit(db, "webhook.test", "webhook_endpoint", uuid.uuid4(), {"endpoint_id": "x", "message": "m"})
    db.rollback()
    assert db.scalar(text("SELECT count(*) FROM events WHERE type = 'webhook.test'")) == 0


def test_an_event_exists_only_if_the_transaction_commits(make_user, db):
    ws = new_workspace(make_user)
    before = db.scalar(text("SELECT count(*) FROM events")), db.scalar(text("SELECT count(*) FROM jobs"))
    fire(db, ws)
    db.rollback()
    assert (db.scalar(text("SELECT count(*) FROM events")), db.scalar(text("SELECT count(*) FROM jobs"))) == before
    event = fire(db, ws)
    db.commit()
    assert db.get(Event, event.id).type == "webhook.test"
    assert event.txid > 0 and event.occurred_at is not None and event.actor_type == "system"


def test_a_workspace_session_emits_into_its_own_workspace_only(two_workspaces):
    a, b = two_workspaces
    with scoped(workspace_id=a) as db:
        event = emit(db, "webhook.test", "webhook_endpoint", uuid.uuid4(),
                     {"endpoint_id": str(uuid.uuid4()), "message": "m"}, actor=("user", uuid.uuid4()))
        db.commit()
        assert str(event.workspace_id) == a and event.actor_type == "user"
        with pytest.raises(DBAPIError, match="row-level security"):
            fire(db, b)
        db.rollback()
        assert event.id in db.scalars(select(Event.id)).all()
        assert set(db.scalars(select(Event.workspace_id))) == {uuid.UUID(a)}  # and it reads only its own workspace


def test_signup_and_workspace_creation_emit_events(make_user, db):
    client, ids = make_user("a@example.com", "Acme")
    signup = db.execute(text("SELECT type, subject_type, subject_id, actor_type, actor_id, workspace_id, data "
                             "FROM events ORDER BY id")).mappings().all()
    user_id = client.get("/api/me").json()["user"]["id"]
    assert [e["type"] for e in signup] == ["workspace.created", "user.signed_up"]
    assert {str(e["workspace_id"]) for e in signup} == {ids["workspace_id"]}
    assert [(e["subject_type"], str(e["subject_id"])) for e in signup] == [
        ("workspace", ids["workspace_id"]), ("user", user_id)]
    assert {(e["actor_type"], str(e["actor_id"])) for e in signup} == {("user", user_id)}
    assert signup[0]["data"] == {"id": ids["workspace_id"], "name": "Main", "org_id": ids["org_id"],
                                 "brand_id": ids["brand_id"]}
    assert signup[1]["data"] == {"id": user_id, "email": "a@example.com", "name": "a", "org_id": ids["org_id"],
                                 "workspace_id": ids["workspace_id"]}

    new = client.post("/api/workspaces", json={"name": "Client", "brand_id": ids["brand_id"]}).json()
    created = db.execute(text("SELECT subject_id, actor_id, workspace_id, data FROM events "
                              "WHERE type = 'workspace.created' ORDER BY id DESC LIMIT 1")).one()
    assert str(created.subject_id) == str(created.workspace_id) == new["id"] and str(created.actor_id) == user_id
    assert created.data == {"id": new["id"], "name": "Client", "org_id": ids["org_id"], "brand_id": ids["brand_id"]}
    assert db.scalar(text("SELECT count(*) FROM events")) == 3


def test_a_failed_signup_or_workspace_request_leaves_no_event(make_user, db):
    client, ids = make_user("a@example.com")
    count = db.scalar(text("SELECT count(*) FROM events"))
    other, other_ids = make_user("b@example.com")
    assert db.scalar(text("SELECT count(*) FROM events")) == count + 2
    assert client.post("/api/workspaces", json={"name": "x", "brand_id": other_ids["brand_id"]}).status_code == 404
    assert client.post("/api/auth/signup", json={"email": "a@example.com", "name": "A", "password": "x" * 12}
                       ).status_code == 409
    assert db.scalar(text("SELECT count(*) FROM events")) == count + 2


def test_a_late_committing_transaction_is_never_skipped(make_user):
    ws = new_workspace(make_user)
    consume("late")  # start after the sign up events
    t1, t2 = SessionLocal(), SessionLocal()
    try:
        e1 = fire(t1, ws, 1)  # T1 takes the lower id and stays open
        e2 = fire(t2, ws, 2)
        t2.commit()  # T2 takes the higher id and commits first
        assert e1.id < e2.id and e1.txid < e2.txid

        with SessionLocal() as reader:
            # A plain `id > last_id` cursor reads e2 now, moves past e1 and never sees it.
            assert reader.scalars(select(Event.id).where(Event.id >= e1.id)).all() == [e2.id]
            assert read_batch(reader, "late") == []  # here e2 waits for the older, still open transaction
        t1.commit()
        assert consume("late") == [e1.id, e2.id]  # nothing skipped, in commit-safe order
        assert consume("late") == []
    finally:
        t1.close()
        t2.close()


def test_order_follows_the_transaction_not_the_id(make_user):
    ws = new_workspace(make_user)
    consume("order")
    t1, t2 = SessionLocal(), SessionLocal()
    try:
        t1.execute(text("SELECT pg_current_xact_id()"))  # T1 gets its transaction id first ...
        e_a = fire(t2, ws, 1)
        t2.commit()  # ... T2 takes id a and commits ...
        e_b = fire(t1, ws, 2)  # ... and T1 then takes the higher id b.
        assert e_a.id < e_b.id and e_b.txid < e_a.txid
        assert consume("order", quiet=False) == []
        t1.commit()
        assert consume("order") == [e_b.id, e_a.id]
        assert consume("order") == []
    finally:
        t1.close()
        t2.close()


def test_batches_resume_at_the_cursor_and_advance_belongs_to_the_transaction(make_user):
    ws = new_workspace(make_user)
    consume("batches")
    with SessionLocal() as db:
        ids = [fire(db, ws, n).id for n in range(5)]
        db.commit()
    wait_for_quiet()
    with SessionLocal() as db:
        first = read_batch(db, "batches", limit=2)
        advance(db, "batches", first)
        assert [e.id for e in first] == ids[:2]
        db.rollback()  # the consumer crashed before committing: nothing moved
    got = []
    for _ in range(4):
        with SessionLocal() as db:
            batch = read_batch(db, "batches", limit=2)
            advance(db, "batches", batch)
            db.commit()
            got.append([e.id for e in batch])
    assert got == [ids[:2], ids[2:4], ids[4:], []]


def test_consumers_keep_independent_cursors(make_user):
    ws = new_workspace(make_user)
    with SessionLocal() as db:
        fire(db, ws)
        db.commit()
    first = consume("one")
    assert consume("one") == [] and consume("two") == first and len(first) == 3


def test_two_runs_of_one_consumer_take_turns(make_user):
    ws = new_workspace(make_user)
    consume("turns")
    with SessionLocal() as db:
        fire(db, ws)
        db.commit()
    wait_for_quiet()
    a = SessionLocal()
    seen = {}
    try:
        batch_a = read_batch(a, "turns")  # holds the cursor
        thread = threading.Thread(target=lambda: seen.update(second=consume("turns", quiet=False)))
        thread.start()
        time.sleep(0.5)
        assert thread.is_alive()  # the second run waits instead of reading the same events
        advance(a, "turns", batch_a)
        a.commit()
        thread.join(10)
    finally:
        a.close()
    assert len(batch_a) == 1 and seen["second"] == []


def test_the_dispatcher_collapses_a_burst_and_waits_out_an_open_transaction(make_user, monkeypatch):
    ws = new_workspace(make_user)
    seen: list[int] = []
    monkeypatch.setitem(events.CONSUMERS, "probe", lambda db, batch: seen.extend(e.id for e in batch))
    assert drain() == 1  # sign up queued two dispatch jobs; the first run marks the other done
    baseline = list(seen)

    t1 = SessionLocal()
    try:
        e1 = fire(t1, ws, 1)  # an old transaction stays open ...
        with SessionLocal() as t2:
            e2 = fire(t2, ws, 2)
            t2.commit()
        assert drain(quiet=False) == 1 and seen == baseline  # ... so e2 is not handed out, and the run asks again
        with SessionLocal() as db:
            assert db.scalar(text("SELECT count(*) FROM jobs WHERE status = 'queued'")) == 1
        t1.commit()
        with SessionLocal() as db:
            due_now(db)
        drain()  # T1's own wake-up job and the repeat
        assert seen[-2:] == [e1.id, e2.id] and e1.id not in baseline
        with SessionLocal() as db:
            assert db.scalar(text("SELECT count(*) FROM jobs WHERE status = 'queued'")) == 0  # and it stopped asking
    finally:
        t1.close()


def test_the_log_is_not_readable_across_workspaces(make_user, db):
    ws_a = new_workspace(make_user)
    ws_b = new_workspace(make_user, "b@example.com")
    fire(db, ws_a)
    db.commit()
    with scoped(workspace_id=ws_b) as other:
        assert other.scalars(select(Event.workspace_id)).all() == [uuid.UUID(ws_b)] * 2  # B's two sign up events
