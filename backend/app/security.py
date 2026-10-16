"""Passwords, session cookies, sign-in throttling and the per-request database scope (stdlib only)."""
import hashlib
import hmac
import os
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta

from fastapi import Depends, Header, HTTPException, Request, Response
from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from . import config
from .db import rescope, scoped
from .models import AuthSession, LoginAttempt, Workspace
from .tenancy import workspace_role

COOKIE = "gohigh_session"
UNSAFE = {"POST", "PUT", "PATCH", "DELETE"}
SCRYPT_N = 2**14


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=8, p=1)
    return f"scrypt${SCRYPT_N}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, n, salt, digest = stored.split("$")
        candidate = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt), n=int(n), r=8, p=1)
    except ValueError:
        return False
    return hmac.compare_digest(candidate.hex(), digest)


DUMMY_HASH = hash_password("not-a-real-password")  # burned on unknown emails so timing does not reveal them


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def start_session(db: Session, response: Response, request: Request, user_id: uuid.UUID) -> None:
    """Adds a session row (caller commits) and sets the cookie. Only the SHA-256 of the token is stored."""
    token = secrets.token_urlsafe(32)
    old = func.now() - timedelta(days=1)
    db.execute(delete(AuthSession).where(or_(AuthSession.expires_at < old, AuthSession.revoked_at < old)))
    db.add(AuthSession(token_hash=token_hash(token), user_id=user_id, ip=client_ip(request),
                       user_agent=request.headers.get("user-agent", "")[:300] or None,
                       expires_at=func.now() + timedelta(hours=config.SESSION_ABSOLUTE_HOURS)))
    response.set_cookie(COOKIE, token, max_age=config.SESSION_ABSOLUTE_HOURS * 3600, httponly=True, samesite="lax",
                        secure=config.COOKIE_SECURE, path="/")


# ponytail: failures counted in a table. Per email+IP stops one guesser fast; the per-email ceiling stops
# IP rotation, at the cost that a flood of failures locks the real user out for the window. Add a CAPTCHA
# step instead of the hard ceiling when that becomes a nuisance.
def retry_after(db: Session, email: str, ip: str) -> int:
    """Seconds until this email may try again from this IP; 0 when it may try now. Blocked while the
    limit-th most recent failure is still inside the window, so the wait is until that one ages out."""
    window = timedelta(minutes=config.LOGIN_WINDOW_MINUTES)
    left = func.ceil(func.extract("epoch", LoginAttempt.created_at + window - func.now()))
    recent = (select(left).where(LoginAttempt.email == email, LoginAttempt.created_at > func.now() - window)
              .order_by(LoginAttempt.created_at.desc()))
    limits = ((recent.where(LoginAttempt.ip == ip), config.LOGIN_MAX_FAILURES),
              (recent, config.LOGIN_MAX_FAILURES_PER_EMAIL))
    waits = [db.scalar(q.offset(n - 1).limit(1)) for q, n in limits]
    return max([int(w) for w in waits if w is not None] + [0])


def record_failure(db: Session, email: str, ip: str) -> None:
    db.execute(delete(LoginAttempt).where(
        LoginAttempt.created_at < func.now() - timedelta(minutes=config.LOGIN_WINDOW_MINUTES)))
    db.add(LoginAttempt(email=email, ip=ip))
    db.commit()


def clear_failures(db: Session, email: str, ip: str) -> None:
    db.execute(delete(LoginAttempt).where(LoginAttempt.email == email, LoginAttempt.ip == ip))


def system_db():
    """Session for pre-auth flows (sign up, sign in, magic links): sees every row of the auth tables."""
    with scoped(system="on") as db:
        yield db


@dataclass
class Ctx:
    db: Session
    user_id: uuid.UUID
    session_id: uuid.UUID
    token_hash: str
    workspace: Workspace | None = None
    workspace_role: str | None = None


def user(request: Request):
    """Resolves the session cookie, then hands out a session scoped to that user: row level security
    shows it only that user's rows. Idle timeout, absolute expiry and revocation are checked in SQL."""
    token = request.cookies.get(COOKIE)
    with scoped(system="on") as db:
        row = db.execute(
            # ponytail: one UPDATE per request; write last_seen at most once a minute if it shows in profiles.
            update(AuthSession)
            .where(AuthSession.token_hash == token_hash(token or ""), AuthSession.revoked_at.is_(None),
                   AuthSession.expires_at > func.now(),
                   AuthSession.last_seen_at > func.now() - timedelta(minutes=config.SESSION_IDLE_MINUTES))
            .values(last_seen_at=func.now())
            .returning(AuthSession.id, AuthSession.user_id)
        ).first() if token else None
        db.commit()
        if row is None:
            raise HTTPException(401, "Sign in required")
        rescope(db, user_id=row.user_id)
        yield Ctx(db, row.user_id, row.id, token_hash(token))


def in_workspace(c: Ctx = Depends(user), x_workspace_id: str | None = Header(default=None)) -> Ctx:
    """The workspace convention: send `X-Workspace-Id`. Anything the user cannot access is a 404 and the
    request then runs with app.workspace_id and app.org_id set, so row level security confines it to that workspace."""
    try:
        wid = uuid.UUID(x_workspace_id or "")
    except ValueError:
        raise HTTPException(400, "X-Workspace-Id header required") from None
    ws = c.db.get(Workspace, wid)  # row level security: only workspaces this user can access are visible
    if ws is None:
        raise HTTPException(404, "Workspace not found")
    c.workspace, c.workspace_role = ws, workspace_role(c.db, c.user_id, ws)
    rescope(c.db, user_id=c.user_id, org_id=ws.org_id, workspace_id=ws.id)
    return c
