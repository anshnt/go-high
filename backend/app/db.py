from contextlib import contextmanager

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from . import config

engine = create_engine(config.DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)  # owner role: migrations, worker, health
AppSession = sessionmaker(engine, expire_on_commit=False)  # request handling: gohigh_app, row level security applies
SCOPE_KEYS = ("system", "user_id", "org_id", "workspace_id")


class Base(DeclarativeBase):
    pass


def get_db():
    with SessionLocal() as db:
        yield db


def _apply(connection, scope: dict) -> None:
    """SET LOCAL role and context for the current transaction; they vanish at commit or rollback."""
    connection.execute(text("SET LOCAL ROLE gohigh_app"))
    connection.execute(
        text("SELECT " + ", ".join(f"set_config('app.{k}', :{k}, true)" for k in SCOPE_KEYS)),
        {k: str(scope.get(k, "")) for k in SCOPE_KEYS},
    )


@event.listens_for(AppSession, "after_begin")
def _scope_every_transaction(session, transaction, connection):
    _apply(connection, session.info.get("scope", {}))


def scoped(**scope) -> Session:
    """A session whose every transaction runs as gohigh_app with the given app.* context.
    No scope sees nothing; `system="on"` is for pre-auth flows (sign in, sign up)."""
    return AppSession(info={"scope": scope})


def rescope(db: Session, **scope) -> None:
    db.info["scope"] = scope
    if db.in_transaction():
        _apply(db.connection(), scope)


@contextmanager
def acting(db: Session, **scope):
    """Runs a block of an owner role session (the worker's) the way a request runs: as gohigh_app with `scope`
    (workspace_id, org_id), so row level security confines every query in it. Code written for requests (the record
    engine, the filter compiler) looks objects up by key and relies on that. Nothing is committed here: the block is
    part of the caller's transaction, which the owner role gets back when it ends (see `elevated` for one statement)."""
    db.info["scope"] = scope
    _apply(db.connection(), scope)
    try:
        yield
    except BaseException:
        db.info.pop("scope", None)  # the transaction is going to roll back, which also ends the role
        raise
    db.execute(text("RESET ROLE"))
    db.info.pop("scope", None)


@contextmanager
def elevated(db: Session):
    """The owner role again, inside `acting`, for the few writes the app role has no grant for (a notification)."""
    scope = db.info["scope"]
    db.execute(text("RESET ROLE"))
    yield  # an error leaves the transaction to roll back; there is no role to put back then
    _apply(db.connection(), scope)
