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
