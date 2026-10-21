"""Sending domains (module 20): the domains a workspace sends campaigns from, the DNS records to publish, the live
SPF, DKIM and DMARC check, and the warm-up schedule that limits how fast a new domain sends. A managed domain gets its
own DKIM key (the private half is a vault secret, like a channel's API key); a provider-managed one names the selector
its provider signs with. Reading is `marketing.read`, changing is `marketing.manage`."""
import math
import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session

from .. import config, events
from ..api import ApiError, Idem, idempotency, paginate
from ..channels import dkim
from ..inbox import vault
from ..permissions import requires
from ..security import Ctx
from . import dnscheck
from .models import EmailCampaign, EmailDomain, EmailSend

router = APIRouter(prefix="/api/v1/email/domains")
read, manage = requires("marketing.read"), requires("marketing.manage")
DOMAIN = re.compile(r"^(?=.{4,253}$)([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
Selector = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")]
Include = Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=253)]
# (first day, emails a day): a new domain sends little and earns reputation, then more; after the last stage the
# workspace's own ceiling applies. A day's mail is spread over at least ten hours.
WARMUP = ((1, 200), (2, 500), (3, 1000), (4, 2000), (5, 4000), (6, 7000), (7, 10000), (9, 20000), (11, 35000),
          (14, 50000), (21, 100000))
WARM_AFTER_DAYS = 28


class NewDomain(BaseModel):
    domain: Annotated[str, StringConstraints(strip_whitespace=True, to_lower=True, max_length=253)]
    dkim_mode: Literal["managed", "provider"] = "managed"
    dkim_selector: Selector | None = None
    spf_include: Include | None = None


class PatchDomain(BaseModel):
    dkim_selector: Selector | None = None
    spf_include: Include | None = None
    hourly_limit: Annotated[int, Field(ge=1, le=1_000_000)] | None = None  # null: back to the warm-up schedule


def clock() -> datetime:
    return datetime.now(UTC)


def normal(domain: str) -> str:
    try:
        domain = domain.strip().rstrip(".").encode("idna").decode("ascii").lower()
    except UnicodeError:
        domain = ""
    if not DOMAIN.fullmatch(domain):
        raise ApiError(422, "validation_failed", "The domain is not valid", {"domain": "must be a domain like "
                                                                             "mail.example.com"})
    return domain


def limits(d: EmailDomain, now: datetime | None = None) -> dict:
    """How much the domain may send now: `hourly` and `daily` (None: no limit but the workspace ceiling), the warm-up
    `day` (None before it starts or once it is over) and the schedule, for the screen."""
    now = now or clock()
    schedule = [{"day": day, "daily": daily} for day, daily in WARMUP]
    ceiling = config.EMAIL_MAX_PER_HOUR
    if d.hourly_limit:
        return {"hourly": d.hourly_limit, "daily": None, "day": None, "stage": "custom", "schedule": schedule}
    if d.warmup_started_at is None:
        return {"hourly": 0, "daily": 0, "day": None, "stage": "not_verified", "schedule": schedule}
    day = (now - d.warmup_started_at).days + 1
    if day >= WARM_AFTER_DAYS:
        return {"hourly": ceiling, "daily": None, "day": None, "stage": "warm", "schedule": schedule}
    daily = next(n for first, n in reversed(WARMUP) if day >= first)
    return {"hourly": min(ceiling, math.ceil(daily / 10)), "daily": daily, "day": day, "stage": "warming",
            "schedule": schedule}


def sent_since(db: Session, domain_id: uuid.UUID, since: datetime) -> int:
    """Sends the domain has handed out (claimed by a batch) since `since`: what the throttle counts."""
    return db.scalar(select(func.count()).select_from(EmailSend).where(
        EmailSend.domain_id == domain_id, EmailSend.claimed_at >= since)) or 0


def domain_json(db: Session, d: EmailDomain) -> dict:
    now = clock()
    return {"id": d.id, "domain": d.domain, "dkim_mode": d.dkim_mode, "dkim_selector": d.dkim_selector,
            "spf_include": d.spf_include, "status": d.status, "checks": d.checks, "checked_at": d.checked_at,
            "verified_at": d.verified_at, "warmup_started_at": d.warmup_started_at, "hourly_limit": d.hourly_limit,
            "records": dnscheck.records(d.domain, d.dkim_selector, d.dkim_public_key, d.spf_include),
            "limits": limits(d, now),
            "sent": {"last_hour": sent_since(db, d.id, now - timedelta(hours=1)),
                     "last_day": sent_since(db, d.id, now - timedelta(days=1))},
            "created_at": d.created_at, "updated_at": d.updated_at}


def event_data(d: EmailDomain, **more) -> dict:
    return {"id": d.id, "domain": d.domain, "status": d.status, "dkim_mode": d.dkim_mode, **more}


def domain_or_404(c: Ctx, domain_id: uuid.UUID) -> EmailDomain:
    d = c.db.get(EmailDomain, domain_id)
    if d is None:
        raise HTTPException(404, "Domain not found")
    return d


def for_address(db: Session, address: str) -> EmailDomain | None:
    """The workspace's sending domain of a From address (the request's or the worker's scope)."""
    domain = address.rpartition("@")[2].strip().lower()
    return db.scalar(select(EmailDomain).where(EmailDomain.domain == domain)) if domain else None


@router.get("")
def list_domains(limit: int = Query(50, ge=1, le=200), cursor: str | None = None, c: Ctx = Depends(read)):
    rows, next_cursor = paginate(c.db, select(EmailDomain), EmailDomain, limit, cursor)
    return {"data": [domain_json(c.db, d) for (d,) in rows], "next_cursor": next_cursor}


@router.post("", status_code=201)
def create_domain(body: NewDomain, c: Ctx = Depends(manage), idem: Idem = Depends(idempotency)):
    """Adds a domain. A managed one gets a new DKIM key (selector `gh1` unless given); a provider one needs the
    selector its provider signs with."""
    name = normal(body.domain)
    if c.db.scalar(select(exists().where(EmailDomain.domain == name))):
        raise ApiError(409, "conflict", f"{name} is already a sending domain here", {"domain": "is already added"})
    if body.dkim_mode == "provider" and not body.dkim_selector:
        raise ApiError(422, "validation_failed", "Name the DKIM selector your provider uses",
                       {"dkim_selector": "is required for a provider-managed key"})
    d = EmailDomain(workspace_id=c.workspace.id, domain=name, dkim_mode=body.dkim_mode,
                    dkim_selector=body.dkim_selector or "gh1", spf_include=body.spf_include or None,
                    created_by=c.user_id)
    if body.dkim_mode == "managed":
        private, d.dkim_public_key = dkim.generate()
        d.dkim_secret_ref = vault.put(c.db, c.workspace.id, {"dkim_private_key": private})
    c.db.add(d)
    c.db.flush()
    c.db.refresh(d, ["created_at", "updated_at"])
    events.emit(c.db, "email_domain.created", "email_domain", d.id, event_data(d), actor=("user", c.user_id))
    return idem.commit(201, domain_json(c.db, d))


@router.get("/{domain_id}")
def get_domain(domain_id: uuid.UUID, c: Ctx = Depends(read)):
    return domain_json(c.db, domain_or_404(c, domain_id))


@router.patch("/{domain_id}")
def update_domain(domain_id: uuid.UUID, body: PatchDomain, c: Ctx = Depends(manage)):
    d = domain_or_404(c, domain_id)
    sent = body.model_fields_set
    changed = []
    if "dkim_selector" in sent and body.dkim_selector and body.dkim_selector != d.dkim_selector:
        if d.dkim_mode == "managed":
            raise ApiError(422, "validation_failed", "A managed key keeps its selector",
                           {"dkim_selector": "cannot change for a managed key"})
        d.dkim_selector = body.dkim_selector
        changed.append("dkim_selector")
    if "spf_include" in sent and (body.spf_include or None) != d.spf_include:
        d.spf_include = body.spf_include or None
        changed.append("spf_include")
    if "hourly_limit" in sent and body.hourly_limit != d.hourly_limit:
        d.hourly_limit = body.hourly_limit
        changed.append("hourly_limit")
    if changed:
        if {"dkim_selector", "spf_include"} & set(changed):  # what was verified no longer is until checked again
            d.status = "pending"
        d.updated_at = func.now()
        c.db.flush()
        c.db.refresh(d, ["updated_at"])
        events.emit(c.db, "email_domain.updated", "email_domain", d.id, event_data(d, changed=changed),
                    actor=("user", c.user_id))
    c.db.commit()
    return domain_json(c.db, d)


@router.delete("/{domain_id}", status_code=204)
def delete_domain(domain_id: uuid.UUID, c: Ctx = Depends(manage)):
    d = domain_or_404(c, domain_id)
    used = c.db.scalar(select(exists().where(EmailCampaign.domain_id == d.id))) or c.db.scalar(
        select(exists().where(EmailSend.domain_id == d.id)))
    if used:
        raise ApiError(409, "domain_in_use", "Campaigns use this domain: it stays for their reports")
    events.emit(c.db, "email_domain.deleted", "email_domain", d.id, event_data(d), actor=("user", c.user_id))
    c.db.delete(d)
    c.db.commit()


def run_check(db: Session, d: EmailDomain, actor: tuple[str, uuid.UUID] | None = None) -> dict:
    """Asks DNS now and records the answer; the first verification starts the warm-up. The caller commits."""
    found = dnscheck.check(d.domain, d.dkim_selector, d.dkim_public_key if d.dkim_mode == "managed" else None,
                           d.spf_include)
    now = clock()
    before = d.status
    d.checks, d.checked_at = found, now
    d.status = "verified" if found["verified"] else "failing"
    if found["verified"]:
        d.verified_at = d.verified_at or now
        d.warmup_started_at = d.warmup_started_at or now
    if d.status != before:
        events.emit(db, "email_domain.updated", "email_domain", d.id, event_data(d, changed=["status"]), actor=actor,
                    workspace_id=d.workspace_id)
    db.flush()
    return found


@router.post("/{domain_id}/check")
def check_domain(domain_id: uuid.UUID, c: Ctx = Depends(manage)):
    """Looks the records up in DNS now and answers the domain with each check's result and sentence."""
    d = domain_or_404(c, domain_id)
    c.db.commit()  # DNS can take seconds: no transaction stays open meanwhile
    run_check(c.db, d, ("user", c.user_id))
    c.db.commit()
    return domain_json(c.db, d)
