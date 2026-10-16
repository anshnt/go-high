"""/api/auth/* (sign up, sign in, magic links, sessions) and /api/me."""
import logging
import secrets
import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import config, events, security
from .db import scoped
from .models import AuthSession, Brand, MagicLink, Organization, OrgMember, User, Workspace
from .security import COOKIE, Ctx, system_db, token_hash, user
from .tenancy import my_orgs, my_workspaces, workspace_data

log = logging.getLogger("auth")
router = APIRouter(prefix="/api")

Email = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=254,
                                         pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
# Shorter passwords are rejected at sign up only; sign in must answer a wrong one with 401, not 422.
NewPassword = Annotated[str, StringConstraints(min_length=10, max_length=256)]
# ponytail: at most this many live links per user, so the endpoint cannot be used to flood an inbox.
MAGIC_LINKS_PER_WINDOW = 5


class SignUp(BaseModel):
    email: Email
    name: Name
    password: NewPassword | None = None  # none: the user signs in with magic links only
    org_name: Name | None = None


class SignIn(BaseModel):
    email: Email
    password: Annotated[str, StringConstraints(max_length=256)]


class MagicRequest(BaseModel):
    email: Email


class MagicConsume(BaseModel):
    token: Annotated[str, StringConstraints(max_length=200)]


def user_json(u: User) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "email_verified": u.email_verified_at is not None,
            "has_password": u.password_hash is not None}


@router.post("/auth/signup", status_code=201)
def signup(body: SignUp, request: Request, response: Response, db: Session = Depends(system_db)):
    account = User(email=body.email, name=body.name, password_hash=security.hash_password(body.password)
                   if body.password else None)
    org = Organization(name=body.org_name or f"{body.name}'s organization")
    db.add_all([account, org])
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists") from None
    brand = Brand(org_id=org.id, name="Default")
    db.add_all([brand, OrgMember(user_id=account.id, org_id=org.id, role="owner")])
    db.flush()
    workspace = Workspace(org_id=org.id, brand_id=brand.id, name="Main")
    db.add(workspace)
    db.flush()
    actor = ("user", account.id)
    events.emit(db, "workspace.created", "workspace", workspace.id, workspace_data(workspace), actor=actor,
                workspace_id=workspace.id)
    events.emit(db, "user.signed_up", "user", account.id,
                {"id": account.id, "email": account.email, "name": account.name, "org_id": org.id,
                 "workspace_id": workspace.id}, actor=actor, workspace_id=workspace.id)
    security.start_session(db, response, request, account.id)
    db.commit()
    return {"user": user_json(account), "org_id": org.id, "brand_id": brand.id, "workspace_id": workspace.id}


@router.post("/auth/signin")
def signin(body: SignIn, request: Request, response: Response, db: Session = Depends(system_db)):
    ip = security.client_ip(request)
    if wait := security.retry_after(db, body.email, ip):
        raise HTTPException(429, "Too many failed attempts, try again later", headers={"Retry-After": str(wait)})
    account = db.scalar(select(User).where(User.email == body.email))
    stored = account.password_hash if account and account.password_hash else security.DUMMY_HASH
    if not security.verify_password(body.password, stored) or not account or not account.password_hash:
        security.record_failure(db, body.email, ip)
        raise HTTPException(401, "Wrong email or password")
    security.clear_failures(db, body.email, ip)
    security.start_session(db, response, request, account.id)
    db.commit()
    return {"user": user_json(account)}


@router.post("/auth/signout", status_code=204)
def signout(request: Request, response: Response, db: Session = Depends(system_db)):
    if token := request.cookies.get(COOKIE):
        db.execute(update(AuthSession).where(AuthSession.token_hash == token_hash(token),
                                             AuthSession.revoked_at.is_(None)).values(revoked_at=func.now()))
        db.commit()
    response.delete_cookie(COOKIE, path="/")


@router.post("/auth/magic-link", status_code=202)
def request_magic_link(body: MagicRequest, db: Session = Depends(system_db)):
    """Always answers the same way, so it cannot be used to find out which emails have accounts."""
    out = {"status": "sent"}
    account = db.scalar(select(User).where(User.email == body.email))
    window = func.now() - timedelta(minutes=config.MAGIC_LINK_MINUTES)
    recent = db.scalar(select(func.count()).where(MagicLink.email == body.email, MagicLink.created_at > window))
    if account and recent < MAGIC_LINKS_PER_WINDOW:
        token = secrets.token_urlsafe(32)
        db.add(MagicLink(token_hash=token_hash(token), email=account.email, user_id=account.id,
                         expires_at=func.now() + timedelta(minutes=config.MAGIC_LINK_MINUTES)))
        db.commit()
        link = f"{config.ALLOWED_ORIGINS[0]}/auth/magic?token={token}"
        # ponytail: delivery is a log line until the email module exists (swap this call for a send).
        log.info("magic link for %s: %s", account.email, link)
        if config.DEV_EXPOSE_MAGIC_LINKS:
            out["link"] = link
    return out


@router.post("/auth/magic-link/consume")
def consume_magic_link(body: MagicConsume, request: Request, response: Response, db: Session = Depends(system_db)):
    """Single use: the UPDATE only matches an unused, unexpired link, so two racing requests cannot both win."""
    user_id = db.scalar(update(MagicLink).where(
        MagicLink.token_hash == token_hash(body.token), MagicLink.used_at.is_(None),
        MagicLink.expires_at > func.now()).values(used_at=func.now()).returning(MagicLink.user_id))
    if user_id is None:
        db.commit()
        raise HTTPException(401, "This link is invalid, expired or already used")
    account = db.get(User, user_id)
    if account.email_verified_at is None:
        # The first link proves the address. Sign up does not, so a password or session created before
        # this point may belong to someone who registered the address without owning it: both go.
        account.email_verified_at = func.now()
        account.password_hash = None
        db.execute(update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
                   .values(revoked_at=func.now()))
    security.start_session(db, response, request, user_id)
    db.commit()
    db.refresh(account)
    return {"user": user_json(account)}


@router.get("/auth/sessions")
def list_sessions(c: Ctx = Depends(user)):
    rows = c.db.scalars(select(AuthSession).where(
        AuthSession.user_id == c.user_id, AuthSession.revoked_at.is_(None), AuthSession.expires_at > func.now(),
        AuthSession.last_seen_at > func.now() - timedelta(minutes=config.SESSION_IDLE_MINUTES))
        .order_by(AuthSession.created_at.desc()))
    return [{"id": s.id, "created_at": s.created_at, "last_seen_at": s.last_seen_at, "expires_at": s.expires_at,
             "ip": s.ip, "user_agent": s.user_agent, "current": s.id == c.session_id} for s in rows]


@router.delete("/auth/sessions/{session_id}", status_code=204)
def revoke_session(session_id: uuid.UUID, response: Response, c: Ctx = Depends(user)):
    revoked = c.db.scalar(update(AuthSession).where(
        AuthSession.id == session_id, AuthSession.user_id == c.user_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=func.now()).returning(AuthSession.id))
    c.db.commit()
    if revoked is None:
        raise HTTPException(404, "Session not found")
    if revoked == c.session_id:
        response.delete_cookie(COOKIE, path="/")


@router.post("/auth/sessions/revoke-others")
def revoke_other_sessions(c: Ctx = Depends(user)):
    revoked = c.db.execute(update(AuthSession).where(
        AuthSession.user_id == c.user_id, AuthSession.id != c.session_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=func.now())).rowcount
    c.db.commit()
    return {"revoked": revoked}


class PasswordChange(BaseModel):
    password: NewPassword
    current_password: Annotated[str, StringConstraints(max_length=256)] | None = None


@router.post("/auth/password", status_code=204)
def set_password(body: PasswordChange, request: Request, c: Ctx = Depends(user)):
    """Changing a password needs the current one. Setting a first one (magic-link users, or after the first
    link cleared a pre-verification password) needs a session started in the last few minutes instead, so a
    stolen old session cannot lock the owner out. Other sessions are signed out either way."""
    account = c.db.get(User, c.user_id)
    ip = security.client_ip(request)
    if account.password_hash:
        if wait := security.retry_after(c.db, account.email, ip):
            raise HTTPException(429, "Too many failed attempts, try again later", headers={"Retry-After": str(wait)})
        if not security.verify_password(body.current_password or "", account.password_hash):
            with scoped(system="on") as sdb:
                security.record_failure(sdb, account.email, ip)
            raise HTTPException(403, "Current password is wrong")
    else:
        fresh = c.db.scalar(select(AuthSession.id).where(
            AuthSession.id == c.session_id,
            AuthSession.created_at > func.now() - timedelta(minutes=config.RECENT_AUTH_MINUTES)))
        if fresh is None:
            raise HTTPException(403, "Sign in again with an email link to set a password")
    c.db.commit()
    with scoped(system="on") as sdb:  # users rows are writable only in the system scope
        new_hash = security.hash_password(body.password)
        sdb.execute(update(User).where(User.id == c.user_id).values(password_hash=new_hash))
        sdb.execute(update(AuthSession).where(AuthSession.user_id == c.user_id, AuthSession.id != c.session_id,
                                              AuthSession.revoked_at.is_(None)).values(revoked_at=func.now()))
        sdb.commit()


@router.get("/me")
def me(c: Ctx = Depends(user)):
    return {"user": user_json(c.db.get(User, c.user_id)), "orgs": my_orgs(c.db, c.user_id),
            "workspaces": my_workspaces(c.db, c.user_id)}
