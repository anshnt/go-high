"""Spam protection of the public endpoints: honeypot, minimum fill time, view tokens, rate limit, body size."""
import time
import uuid

import pytest
from forms_helpers import PUBLIC, visitor
from sqlalchemy import text

from app import config
from app.api import seal
from app.forms import spam

ANSWERS = {"first_name": "Ada", "email": "ada@example.com"}


def count(db, table: str) -> int:
    db.expire_all()
    return db.scalar(text(f"SELECT count(*) FROM {table}"))


# --- honeypot ---------------------------------------------------------------------------------------------

def test_a_filled_honeypot_gets_a_success_that_stores_nothing(site, db):
    made = site.live()
    key = made["public_key"]
    r = site.start(key, {"first_name": "Bot"}, hp="http://spam.example")
    assert r.status_code == 201 and uuid.UUID(r.json()["id"]) and r.json()["resume_token"]  # it looks like it worked
    assert count(db, "form_submissions") == 0
    real = site.start(key, {"first_name": "Ada"}).json()
    done = site.finish(key, real, ANSWERS, hp="x")
    assert done.status_code == 200 and done.json()["status"] == "complete"
    assert done.json()["id"] != real["id"]  # not the real response
    assert db.scalar(text("SELECT status FROM form_submissions")) == "partial"
    assert site.records() == [] and db.scalar(text("SELECT count(*) FROM events WHERE type = 'form.submitted'")) == 0
    ok = site.finish(key, real, ANSWERS, hp="")  # an empty honeypot is a person
    assert ok.status_code == 200 and site.records()


# --- minimum fill time ------------------------------------------------------------------------------------

def old_token(form_id: str, seconds: int) -> str:
    return seal([form_id, int(time.time()) - seconds])


def test_a_response_completed_faster_than_a_person_is_refused_and_can_be_sent_again(site, monkeypatch, db):
    monkeypatch.setattr(config, "FORM_MIN_FILL_SECONDS", 3)
    made = site.live()
    key = made["public_key"]
    started = site.start(key, {"first_name": "Ada"})  # saving as you go is never refused for speed
    assert started.status_code == 201
    r = site.finish(key, started.json(), ANSWERS)
    assert r.status_code == 429 and r.json()["error"]["code"] == "too_fast"
    assert 1 <= int(r.headers["retry-after"]) <= 3
    assert db.scalar(text("SELECT status FROM form_submissions")) == "partial" and site.records() == []
    ok = site.finish(key, started.json(), ANSWERS, token=old_token(made["id"], 5))
    assert ok.status_code == 200 and len(site.records()) == 1


def test_the_fill_time_counts_from_when_the_page_was_opened(site, monkeypatch):
    monkeypatch.setattr(config, "FORM_MIN_FILL_SECONDS", 3)
    made = site.live()
    key = made["public_key"]
    token = site.view(key)
    started = site.start(key, {}, token=token).json()
    assert site.finish(key, started, ANSWERS, token=token).status_code == 429
    time.sleep(3.2)  # the person reads and types
    assert site.finish(key, started, ANSWERS, token=token).status_code == 200


# --- view tokens ------------------------------------------------------------------------------------------

def test_a_missing_forged_foreign_or_stale_view_token_is_refused(site):
    made, other = site.live(), site.live(name="Other")
    key = made["public_key"]
    started = site.start(key, {}).json()
    good = site.view(key)
    foreign = site.view(other["public_key"])
    bad = {"missing": None, "garbage": "not a token", "forged": good[:-3] + ("abc" if good[-3:] != "abc" else "xyz"),
           "other form": foreign, "wrong shape": seal(["x"]), "future": old_token(made["id"], -3600),
           "stale": old_token(made["id"], 8 * 86400), "text time": seal([made["id"], "soon"]),
           "bool time": seal([made["id"], True])}
    for name, token in bad.items():
        for call in (lambda t: site.start(key, {}, token=t), lambda t: site.finish(key, started, ANSWERS, token=t)):
            r = call(token)
            assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_view_token", (name, r.text)
    assert site.finish(key, started, ANSWERS, token=good).status_code == 200
    assert site.start(key, {}, token=old_token(made["id"], 6 * 86400)).status_code == 201  # open for days is fine


def test_a_form_without_spam_protection_needs_no_token_and_ignores_the_honeypot(site, monkeypatch):
    monkeypatch.setattr(config, "FORM_MIN_FILL_SECONDS", 3)
    made = site.live(settings={"spam_protection": False})
    key = made["public_key"]
    started = site.start(key, {}, token=None, hp="filled")  # no token, a filled honeypot
    assert started.status_code == 201
    done = site.finish(key, started.json(), ANSWERS, token=None)
    assert done.status_code == 200 and len(site.records()) == 1
    forged = site.start(key, {}, token="garbage")  # a bad token is still refused
    assert forged.status_code == 400


# --- rate limit -------------------------------------------------------------------------------------------

@pytest.fixture
def minute(monkeypatch):
    """A fixed clock for the per-minute counters: `minute.now += 1` moves to the next minute."""
    class Clock:
        now = 29_000_000
    monkeypatch.setattr(spam, "minute", lambda: Clock.now)
    return Clock


def test_a_visitor_is_limited_per_form_and_minute(site, minute, db):
    made = site.live(settings={"rate_limit_per_minute": 3})
    other = site.live(name="Other", settings={"rate_limit_per_minute": 3})
    key = made["public_key"]
    token = site.view(key)
    for _ in range(3):
        assert site.start(key, {}, token=token).status_code == 201
    r = site.start(key, {}, token=token)
    assert r.status_code == 429 and r.json()["error"]["code"] == "rate_limited"
    assert 1 <= int(r.headers["retry-after"]) <= 60
    assert site.anonymous.post(f"{PUBLIC}/{key}/resume", json={"resume_token": "x"}).status_code == 429
    assert db.scalar(text("SELECT max(count) FROM form_rate")) >= 4  # refused requests count too
    assert site.start(other["public_key"], {}).status_code == 201  # another form, same visitor
    site.anonymous = visitor("198.51.100.7")  # another visitor
    assert site.start(key, {}, token=site.view(key)).status_code == 201
    site.anonymous = visitor()
    minute.now += 1  # the next minute
    assert site.start(key, {}, token=token).status_code == 201


def test_completing_counts_against_the_limit_and_old_minutes_are_removed(site, minute, db):
    made = site.live(settings={"rate_limit_per_minute": 2})
    key = made["public_key"]
    token = site.view(key)
    started = site.start(key, {}, token=token).json()
    assert site.finish(key, started, ANSWERS, token=token).status_code == 200
    assert site.finish(key, started, ANSWERS, token=token).status_code == 429
    assert count(db, "form_rate") == 2  # one counter for views and one for writes
    minute.now += 90  # an hour and a half later
    site.start(key, {}, token=token)
    rows = db.execute(text("SELECT bucket FROM form_rate")).scalars().all()
    assert rows == [minute.now]  # the old minute is gone


def test_views_beyond_the_limit_get_a_token_but_are_not_counted(site, minute, monkeypatch, db):
    monkeypatch.setattr(spam, "VIEW_LIMIT", 2)
    made = site.live()
    for _ in range(4):
        assert site.view(made["public_key"])
    assert db.scalar(text("SELECT count FROM form_views")) == 2


def test_a_form_without_spam_protection_is_still_rate_limited(site, minute):
    made = site.live(settings={"spam_protection": False, "rate_limit_per_minute": 2})
    key = made["public_key"]
    assert [site.start(key, {}, token=None).status_code for _ in range(3)] == [201, 201, 429]


# --- body size ------------------------------------------------------------------------------------------------

def test_a_body_over_the_forms_limit_is_refused_before_it_is_read(site, db):
    made = site.live()
    key = made["public_key"]
    token = site.view(key)
    big = {"answers": {"first_name": "x" * 70_000}, "view_token": token}
    r = site.anonymous.post(f"{PUBLIC}/{key}/submissions", json=big)
    assert r.status_code == 413 and r.json()["error"]["code"] == "payload_too_large"
    assert count(db, "form_submissions") == 0
    small = site.anonymous.post(f"{PUBLIC}/{key}/submissions", json={"answers": {"first_name": "x" * 900},
                                                                      "view_token": token})
    assert small.status_code == 201


def test_the_limit_is_per_form_and_holds_without_a_content_length(site):
    tight = site.live(settings={"max_body_kb": 4})
    roomy = site.live(name="Roomy", settings={"max_body_kb": 200})
    payload = {"answers": {"first_name": "x" * 5000}}
    assert site.anonymous.post(f"{PUBLIC}/{tight['public_key']}/submissions", json=payload).status_code == 413
    r = site.anonymous.post(f"{PUBLIC}/{roomy['public_key']}/submissions", json=payload)
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_view_token"  # it fits; no view token

    def chunks():  # no Content-Length: the body is counted as it arrives
        yield b'{"answers": {"first_name": "'
        for _ in range(10):
            yield b"y" * 1000
        yield b'"}}'
    r = site.anonymous.post(f"{PUBLIC}/{tight['public_key']}/submissions", content=chunks(),
                            headers={"Content-Type": "application/json"})
    assert r.status_code == 413


def test_bad_bodies_are_400_or_422_never_500(site):
    made = site.live()
    path = f"{PUBLIC}/{made['public_key']}/submissions"
    token = site.view(made["public_key"]).encode()
    for content, status in [(b"", 400), (b"[]", 400), (b"null", 400), (b"{", 400), (b'"text"', 400),
                            (b'{"view_token": "' + token + b'"}', 201),
                            (b'{"answers": "x", "view_token": "' + token + b'"}', 422),
                            (b'{"step": 5, "view_token": "' + token + b'"}', 422),
                            (b'{"utm": {"utm_source": 5}, "view_token": "' + token + b'"}', 422)]:
        r = site.anonymous.post(path, content=content, headers={"Content-Type": "application/json"})
        assert r.status_code == status, (content, r.status_code, r.text)
