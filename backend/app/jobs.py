"""Postgres-backed job queue (ADR 0001). A job is a row; workers claim due rows with
FOR UPDATE SKIP LOCKED, so any number of workers can run without a broker."""
import logging
import traceback
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import BigInteger, DateTime, Index, Integer, String, Text, and_, func, or_, select, text, update
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column, sessionmaker

from .db import Base

log = logging.getLogger("jobs")

# ponytail: fixed lease; a job running longer than this is assumed dead and re-run. Add heartbeats
# when a handler legitimately needs more than a few minutes.
LEASE = timedelta(minutes=15)
MAX_BACKOFF = timedelta(hours=1)

HANDLERS: dict[str, Callable[[Session, dict], None]] = {}


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (Index("ix_jobs_due", "run_at", postgresql_where=text("status = 'queued'")),)
    # Request handlers (gohigh_app) may INSERT jobs and read back only the id. Fetching run_at and created_at after
    # the insert would need SELECT on the whole queue, whose rows are not tenant scoped.
    __mapper_args__ = {"eager_defaults": False}

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(100))
    payload: Mapped[dict] = mapped_column(JSONB, default=dict)
    # queued, running, done, dead
    status: Mapped[str] = mapped_column(String(10), default="queued", server_default="queued")
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, default=5, server_default="5")
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def handler(kind: str):
    def register(fn):
        HANDLERS[kind] = fn
        return fn
    return register


def enqueue(db: Session, kind: str, payload: dict | None = None, *, run_at: datetime | None = None,
            max_attempts: int = 5) -> Job:
    """Adds a job in the caller's transaction, so it only exists if the caller commits."""
    if kind not in HANDLERS:
        raise ValueError(f"no handler for job kind {kind!r}")
    job = Job(kind=kind, payload=payload or {}, max_attempts=max_attempts)
    if run_at is not None:
        job.run_at = run_at
    db.add(job)
    db.flush()
    return job


def claim(db: Session) -> Job | None:
    """Locks the next due job (or one whose lease expired) and marks it running."""
    due = (
        select(Job.id)
        .where(or_(and_(Job.status == "queued", Job.run_at <= func.now()),
                   and_(Job.status == "running", Job.locked_at < func.now() - LEASE)))
        .order_by(Job.run_at)
        .limit(1)
        .with_for_update(skip_locked=True)
        .scalar_subquery()
    )
    return db.scalars(
        update(Job).where(Job.id == due)
        .values(status="running", locked_at=func.now(), attempts=Job.attempts + 1)
        .returning(Job),
        execution_options={"populate_existing": True},
    ).first()


def backoff(attempts: int) -> timedelta:
    return min(timedelta(seconds=10 * 2 ** (attempts - 1)), MAX_BACKOFF)


def run_one(sessions: sessionmaker) -> bool:
    """Runs one due job. Returns False when nothing was due."""
    with sessions() as db:
        job = claim(db)
        db.commit()
    if job is None:
        return False
    with sessions() as db:
        try:
            HANDLERS[job.kind](db, job.payload)
            db.commit()
            outcome = dict(status="done", finished_at=func.now(), last_error=None)
        except Exception:
            db.rollback()
            error = traceback.format_exc(limit=5)
            log.warning("job %s (%s) failed on attempt %s", job.id, job.kind, job.attempts)
            if job.attempts >= job.max_attempts:
                outcome = dict(status="dead", finished_at=func.now(), last_error=error)
            else:
                outcome = dict(status="queued", run_at=func.now() + backoff(job.attempts), last_error=error)
        db.execute(update(Job).where(Job.id == job.id).values(**outcome, locked_at=None))
        db.commit()
    return True


@handler("noop")
def noop(db: Session, payload: dict) -> None:
    """Does nothing; proves the queue end to end (tests, deploy smoke checks)."""
    log.info("noop job ran %s", payload)
