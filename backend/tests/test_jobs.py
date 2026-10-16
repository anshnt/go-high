import threading
from datetime import timedelta

import pytest
from sqlalchemy import func, select, text, update

from app import jobs
from app.db import SessionLocal
from app.jobs import Job, backoff, claim, enqueue, handler, run_one

calls: list[dict] = []


@handler("record")
def record(db, payload):
    calls.append(payload)


@handler("boom")
def boom(db, payload):
    raise RuntimeError("nope")


@pytest.fixture(autouse=True)
def reset_calls():
    calls.clear()


def get(db, job_id) -> Job:
    db.expire_all()
    return db.get(Job, job_id)


def test_due_job_runs_once(db):
    job = enqueue(db, "record", {"n": 1})
    db.commit()
    assert run_one(SessionLocal) is True
    assert run_one(SessionLocal) is False
    assert calls == [{"n": 1}]
    done = get(db, job.id)
    assert (done.status, done.attempts, done.locked_at) == ("done", 1, None)
    assert done.finished_at is not None


def test_scheduled_job_waits_until_run_at(db):
    job = enqueue(db, "noop", run_at=db.scalar(select(func.now())) + timedelta(hours=1))
    db.commit()
    assert run_one(SessionLocal) is False
    db.execute(update(Job).where(Job.id == job.id).values(run_at=func.now() - timedelta(seconds=1)))
    db.commit()
    assert run_one(SessionLocal) is True
    assert get(db, job.id).status == "done"


def test_failure_retries_with_backoff_then_dead(db):
    job = enqueue(db, "boom", max_attempts=2)
    db.commit()
    assert run_one(SessionLocal)
    failed = get(db, job.id)
    assert failed.status == "queued" and failed.attempts == 1 and "nope" in failed.last_error
    assert failed.run_at > db.scalar(select(func.now())) + timedelta(seconds=5)

    db.execute(update(Job).where(Job.id == job.id).values(run_at=func.now()))
    db.commit()
    assert run_one(SessionLocal)
    dead = get(db, job.id)
    assert (dead.status, dead.attempts) == ("dead", 2)
    assert run_one(SessionLocal) is False


def test_handler_side_effects_roll_back_on_failure(db):
    @handler("half")
    def half(session, payload):
        session.execute(text("UPDATE jobs SET payload = '{\"touched\": true}' WHERE kind = 'noop'"))
        raise RuntimeError("after write")

    other = enqueue(db, "noop", run_at=db.scalar(select(func.now())) + timedelta(hours=1))
    enqueue(db, "half", max_attempts=1)
    db.commit()
    run_one(SessionLocal)
    assert get(db, other.id).payload == {}


def test_expired_lease_is_reclaimed(db):
    job = enqueue(db, "record", {"n": 2})
    db.commit()
    assert claim(db).id == job.id  # a worker took it ...
    db.execute(update(Job).where(Job.id == job.id).values(locked_at=func.now() - jobs.LEASE - timedelta(seconds=1)))
    db.commit()  # ... and died
    assert run_one(SessionLocal)
    assert calls == [{"n": 2}]
    assert get(db, job.id).attempts == 2


def test_concurrent_workers_never_share_a_job(db):
    for n in range(40):
        enqueue(db, "record", {"n": n})
    db.commit()
    threads = [threading.Thread(target=lambda: [run_one(SessionLocal) for _ in range(20)]) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(c["n"] for c in calls) == list(range(40))


def test_unknown_kind_is_rejected(db):
    with pytest.raises(ValueError):
        enqueue(db, "missing")


def test_backoff_grows_and_caps():
    assert [backoff(n).total_seconds() for n in (1, 2, 3)] == [10, 20, 40]
    assert backoff(30) == jobs.MAX_BACKOFF


def test_a_kind_can_bring_its_own_backoff(db):
    @handler("slow_retry", backoff=lambda attempts: timedelta(hours=attempts))
    def slow_retry(session, payload):
        raise RuntimeError("down")

    job = enqueue(db, "slow_retry", max_attempts=3)
    db.commit()
    run_one(SessionLocal)
    retry = get(db, job.id)
    assert retry.run_at > db.scalar(select(func.now())) + timedelta(minutes=59)
