"""/api/auth/* (sign up, sign in, magic links, sessions) and /api/me."""
import logging
import secrets
import uuid
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, StringConstraints
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import config, events, roles_seed, security
from .db import rescope, scoped
from .events import Event
from .models import (
    AuthSession,
    Brand,
    MagicLink,
    Organization,
    OrgMember,
    User,
    UserCredential,
    Workspace,
    new_slug,
)
from .records.seed import seed_workspace
from .security import COOKIE, Ctx, system_db, token_hash, user
from .tenancy import my_orgs, my_workspaces, workspace_data, workspace_ids
from .webhooks import WebhookEndpoint

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


def user_json(u: User, has_password: bool) -> dict:
    return {"id": u.id, "email": u.email, "name": u.name, "email_verified": u.email_verified_at is not None,
            "has_password": has_password}


def password_of(db: Session, user_id: uuid.UUID) -> str | None:
    """The user's password hash, if they have a password. Row level security: only their own, or the pre-auth scope."""
    return db.scalar(select(UserCredential.password_hash).where(UserCredential.user_id == user_id))


def sessions_revoked(db: Session, user_id: uuid.UUID, count: int, reason: str) -> None:
    """The audit log of every workspace the user can act in learns that their sessions were ended. The events go in
    the caller's transaction, one workspace at a time (the events policy checks the workspace of each row).
    ponytail: one event per workspace; an agency admin with hundreds of workspaces wants an org level stream."""
    if count:
        scope = dict(db.info.get("scope", {}))
        for workspace_id in workspace_ids(db, user_id):
            rescope(db, **{**scope, "workspace_id": workspace_id})
            events.emit(db, "auth.sessions_revoked", "user", user_id,
                        {"user_id": user_id, "count": count, "reason": reason}, actor=("user", user_id),
                        workspace_id=workspace_id)
        rescope(db, **scope)


def disable_squatter_webhooks(db: Session, user_id: uuid.UUID) -> None:
    """Turns off the webhooks of the organizations this account created at sign up, before the address was proved:
    whoever registered it may have pointed them at themselves. The owner can check the URL and turn them back on.
    One workspace at a time, as the webhook policy checks the workspace of each row."""
    orgs = [uuid.UUID(o) for o in db.scalars(select(Event.data["org_id"].astext).where(
        Event.type == "user.signed_up", Event.subject_id == user_id))]
    scope = dict(db.info.get("scope", {}))
    for workspace_id in db.scalars(select(Workspace.id).where(Workspace.org_id.in_(orgs))).all():
        rescope(db, **{**scope, "workspace_id": workspace_id})
        db.execute(update(WebhookEndpoint).where(WebhookEndpoint.workspace_id == workspace_id, WebhookEndpoint.active)
                   .values(active=False, disabled_reason="Disabled when the email address was verified: check the "
                                                         "URL before turning it back on"))
    rescope(db, **scope)


@router.post("/auth/signup", status_code=201)
def signup(body: SignUp, request: Request, response: Response, db: Session = Depends(system_db)):
    account = User(email=body.email, name=body.name)
    org = Organization(name=body.org_name or f"{body.name}'s organization")
    db.add_all([account, org])
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An account with this email already exists") from None
    if body.password:
        db.add(UserCredential(user_id=account.id, password_hash=security.hash_password(body.password)))
    brand = Brand(org_id=org.id, name="Default")
    roles = roles_seed.add(db, org.id)
    db.add_all([brand, OrgMember(user_id=account.id, org_id=org.id, role_id=roles["owner"])])
    db.flush()
    workspace = Workspace(org_id=org.id, brand_id=brand.id, name="Main", slug=new_slug(org.name))
    db.add(workspace)
    db.flush()
    seed_workspace(db, workspace.id)
    actor = ("user", account.id)
    events.emit(db, "workspace.created", "workspace", workspace.id, workspace_data(workspace), actor=actor,
                workspace_id=workspace.id)
    events.emit(db, "user.signed_up", "user", account.id,
                {"id": account.id, "email": account.email, "name": account.name, "org_id": org.id,
                 "workspace_id": workspace.id}, actor=actor, workspace_id=workspace.id)
    security.start_session(db, response, request, account.id)
    db.commit()
    return {"user": user_json(account, bool(body.password)), "org_id": org.id, "brand_id": brand.id,
            "workspace_id": workspace.id}


@router.post("/auth/signin")
def signin(body: SignIn, request: Request, response: Response, db: Session = Depends(system_db)):
    ip = security.client_ip(request)
    if wait := security.retry_after(db, body.email, ip):
        raise HTTPException(429, "Too many failed attempts, try again later", headers={"Retry-After": str(wait)})
    account = db.scalar(select(User).where(User.email == body.email))
    stored = password_of(db, account.id) if account else None
    if not security.verify_password(body.password, stored or security.DUMMY_HASH) or not stored:
        security.record_failure(db, body.email, ip)
        raise HTTPException(401, "Wrong email or password")
    security.clear_failures(db, body.email, ip)
    security.start_session(db, response, request, account.id)
    db.commit()
    return {"user": user_json(account, True)}


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
        db.execute(delete(UserCredential).where(UserCredential.user_id == user_id))
        ended = db.execute(update(AuthSession).where(AuthSession.user_id == user_id, AuthSession.revoked_at.is_(None))
                           .values(revoked_at=func.now())).rowcount
        sessions_revoked(db, user_id, ended, "email_verified")
        disable_squatter_webhooks(db, user_id)
    security.start_session(db, response, request, user_id)
    db.commit()
    db.refresh(account)
    return {"user": user_json(account, password_of(db, user_id) is not None)}


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
    if revoked is None:
        raise HTTPException(404, "Session not found")
    sessions_revoked(c.db, c.user_id, 1, "revoked")
    c.db.commit()
    if revoked == c.session_id:
        response.delete_cookie(COOKIE, path="/")


@router.post("/auth/sessions/revoke-others")
def revoke_other_sessions(c: Ctx = Depends(user)):
    revoked = c.db.execute(update(AuthSession).where(
        AuthSession.user_id == c.user_id, AuthSession.id != c.session_id, AuthSession.revoked_at.is_(None))
        .values(revoked_at=func.now())).rowcount
    sessions_revoked(c.db, c.user_id, revoked, "others_revoked")
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
    current = password_of(c.db, c.user_id)
    if current:
        with scoped(system="on") as sdb:  # login_attempts is read in the pre-auth scope only
            wait = security.retry_after(sdb, account.email, ip)
        if wait:
            raise HTTPException(429, "Too many failed attempts, try again later", headers={"Retry-After": str(wait)})
        if not security.verify_password(body.current_password or "", current):
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
    with scoped(system="on") as sdb:  # the pre-auth scope may write credentials
        new_hash = security.hash_password(body.password)
        sdb.execute(pg_insert(UserCredential).values(user_id=c.user_id, password_hash=new_hash).on_conflict_do_update(
            index_elements=[UserCredential.user_id], set_={"password_hash": new_hash, "updated_at": func.now()}))
        ended = sdb.execute(update(AuthSession).where(
            AuthSession.user_id == c.user_id, AuthSession.id != c.session_id, AuthSession.revoked_at.is_(None))
            .values(revoked_at=func.now())).rowcount
        for workspace_id in workspace_ids(sdb, c.user_id):
            events.emit(sdb, "user.password_changed", "user", c.user_id, {"id": c.user_id}, actor=("user", c.user_id),
                        workspace_id=workspace_id)
        sessions_revoked(sdb, c.user_id, ended, "password_changed")
        sdb.commit()


@router.get("/me")
def me(c: Ctx = Depends(user)):
    person = user_json(c.db.get(User, c.user_id), password_of(c.db, c.user_id) is not None)
    return {"user": person, "orgs": my_orgs(c.db, c.user_id),
            "workspaces": my_workspaces(c.db, c.user_id)}
