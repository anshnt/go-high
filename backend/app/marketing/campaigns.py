"""Campaigns API (`/api/v1/email/campaigns`, module 20): drafts with their content, audience, sender and A/B test, the
live audience preview, the pre-send deliverability check, scheduling (in any time zone), pause, resume and cancel,
and the report. Reading is `marketing.read`, editing drafts `marketing.write`, and anything that sends or stops a
send `marketing.send`. A campaign can be edited only while it is a draft; scheduling runs the check and refuses a
campaign with errors. Sending itself is the worker's (sender.py)."""
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints, field_validator
from sqlalchemy import func, select, update

from .. import permissions
from ..api import ApiError, Idem, idempotency, paginate
from ..inbox.models import Channel
from ..permissions import requires
from ..records import store
from ..records.models import Record
from ..records.schema import Catalog
from ..security import Ctx
from . import audience, document, domains, lint, sender, usage
from .models import EmailCampaign, EmailDomain, EmailEvent, EmailLink, EmailSend, EmailTemplate, EmailTopic
from .public import opens_by_link
from .settings import normal_email, settings_of
from .templates import checked

router = APIRouter(prefix="/api/v1/email/campaigns")
read, write, send = requires("marketing.read"), requires("marketing.write"), requires("marketing.send")
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
EDITABLE = ("draft",)
SENT = ("sent", "delivered", "bounced", "complained")  # the provider took it
MAX_SCHEDULE = timedelta(days=365)


class Variant(BaseModel):
    key: Literal["B", "C", "D"]
    subject: Annotated[str, StringConstraints(max_length=500)] | None = None
    preheader: Annotated[str, StringConstraints(max_length=300)] | None = None
    document: dict | None = None


class AB(BaseModel):
    enabled: bool = False
    metric: Literal["opens", "clicks"] = "opens"
    test_percent: Annotated[int, Field(ge=10, le=100)] = 20
    wait_hours: Annotated[int, Field(ge=1, le=72)] = 4
    variants: Annotated[list[Variant], Field(max_length=3)] = []

    @field_validator("variants")
    @classmethod
    def in_order(cls, value: list[Variant]) -> list[Variant]:
        if [v.key for v in value] != ["B", "C", "D"][:len(value)]:
            raise ValueError("variants are B, C and D, in that order")
        return value


class NewCampaign(BaseModel):
    name: Name
    template_id: uuid.UUID | None = None


class PatchCampaign(BaseModel):
    name: Name | None = None
    channel_id: uuid.UUID | None = None
    from_name: Annotated[str, StringConstraints(strip_whitespace=True, max_length=200)] | None = None
    from_email: Annotated[str, StringConstraints(strip_whitespace=True, max_length=320)] | None = None
    reply_to: Annotated[str, StringConstraints(strip_whitespace=True, max_length=320)] | None = None
    topic_id: uuid.UUID | None = None
    template_id: uuid.UUID | None = None  # copies the template's content into the campaign
    subject: Annotated[str, StringConstraints(max_length=500)] | None = None
    preheader: Annotated[str, StringConstraints(max_length=300)] | None = None
    document: dict | None = None
    audience: dict | None = None
    ab: AB | None = None


class Schedule(BaseModel):
    scheduled_at: datetime | None = None  # None: now. Without an offset it is read in `timezone`
    timezone: Annotated[str, StringConstraints(max_length=64)] = "UTC"


def clock() -> datetime:
    return datetime.now(UTC)


# --- reading ----------------------------------------------------------------------------------------------------

def counts_of(c: Ctx, campaign_ids: list[uuid.UUID]) -> dict[uuid.UUID, dict]:
    rows = c.db.execute(select(
        EmailSend.campaign_id, func.count(), func.count().filter(EmailSend.status.in_(SENT)),
        func.count().filter(EmailSend.opened_at.is_not(None)), func.count().filter(EmailSend.clicked_at.is_not(None)))
        .where(EmailSend.campaign_id.in_(campaign_ids)).group_by(EmailSend.campaign_id)).all()
    return {r[0]: {"recipients": r[1], "sent": r[2], "opened": r[3], "clicked": r[4]} for r in rows}


def campaign_json(cm: EmailCampaign, stats: dict | None = None, full: bool = True) -> dict:
    out = {"id": cm.id, "name": cm.name, "status": cm.status, "paused_from": cm.paused_from,
           "channel_id": cm.channel_id, "domain_id": cm.domain_id, "topic_id": cm.topic_id,
           "template_id": cm.template_id, "from_name": cm.from_name, "from_email": cm.from_email,
           "reply_to": cm.reply_to, "subject": cm.subject, "preheader": cm.preheader, "audience": cm.audience,
           "ab": cm.ab or AB().model_dump(), "winner": cm.winner, "scheduled_at": cm.scheduled_at,
           "timezone": cm.timezone, "started_at": cm.started_at, "test_ends_at": cm.test_ends_at,
           "finished_at": cm.finished_at, "audience_count": cm.audience_count, "error": cm.error,
           "created_by": cm.created_by, "scheduled_by": cm.scheduled_by, "created_at": cm.created_at,
           "updated_at": cm.updated_at,
           "stats": stats or {"recipients": 0, "sent": 0, "opened": 0, "clicked": 0}}
    if full:
        out["document"] = cm.document
    return out


def campaign_or_404(c: Ctx, campaign_id: uuid.UUID, lock: bool = False) -> EmailCampaign:
    cm = c.db.get(EmailCampaign, campaign_id, with_for_update=lock)
    if cm is None:
        raise HTTPException(404, "Campaign not found")
    return cm


def editable(cm: EmailCampaign) -> EmailCampaign:
    if cm.status not in EDITABLE:
        raise ApiError(409, "not_editable", "Only a draft can be changed: unschedule it first" if cm.status ==
                       "scheduled" else f"The campaign is {cm.status}: duplicate it to send it again")
    return cm


@router.get("")
def list_campaigns(status: Literal["draft", "scheduled", "sending", "testing", "paused", "sent", "cancelled",
                                   "failed"] | None = None,
                   q: Annotated[str, StringConstraints(max_length=200)] | None = None,
                   limit: int = Query(50, ge=1, le=200), cursor: str | None = None, c: Ctx = Depends(read)):
    stmt = select(EmailCampaign)
    if status:
        stmt = stmt.where(EmailCampaign.status == status)
    if q:
        stmt = stmt.where(EmailCampaign.name.icontains(q.strip(), autoescape=True))
    rows, next_cursor = paginate(c.db, stmt, EmailCampaign, limit, cursor, by="updated_at")
    stats = counts_of(c, [cm.id for (cm,) in rows])
    return {"data": [campaign_json(cm, stats.get(cm.id), full=False) for (cm,) in rows], "next_cursor": next_cursor}


@router.post("", status_code=201)
def create_campaign(body: NewCampaign, c: Ctx = Depends(write), idem: Idem = Depends(idempotency)):
    """A draft, with the content of `template_id` when given, and the workspace's first email channel and verified
    sending domain filled in."""
    cm = EmailCampaign(workspace_id=c.workspace.id, name=body.name, created_by=c.user_id, ab=AB().model_dump(),
                       document={"version": 1, "blocks": []})
    if body.template_id:
        apply_template(c, cm, body.template_id)
    channel = c.db.scalar(select(Channel).where(Channel.kind == "email", Channel.status != "disabled")
                          .order_by(Channel.created_at).limit(1))
    if channel:
        cm.channel_id = channel.id
    domain = c.db.scalar(select(EmailDomain).order_by((EmailDomain.status == "verified").desc(),
                                                       EmailDomain.created_at).limit(1))
    if domain:
        cm.domain_id, cm.from_email = domain.id, f"hello@{domain.domain}"
        cm.from_name = settings_of(c.db, c.workspace.id).company_name or c.workspace.name
    c.db.add(cm)
    c.db.flush()
    c.db.refresh(cm, ["created_at", "updated_at"])
    sender.emit(c.db, "email_campaign.created", cm, actor=("user", c.user_id))
    return idem.commit(201, campaign_json(cm))


@router.get("/{campaign_id}")
def get_campaign(campaign_id: uuid.UUID, c: Ctx = Depends(read)):
    cm = campaign_or_404(c, campaign_id)
    return campaign_json(cm, counts_of(c, [cm.id]).get(cm.id))


def apply_template(c: Ctx, cm: EmailCampaign, template_id: uuid.UUID) -> None:
    t = c.db.get(EmailTemplate, template_id)
    if t is None:
        raise ApiError(422, "validation_failed", "The template is not valid", {"template_id": "is not a template"})
    cm.template_id, cm.subject, cm.preheader, cm.document = t.id, t.subject, t.preheader, t.document


def check_variants(c: Ctx, cm: EmailCampaign, ab: AB) -> dict:
    out = ab.model_dump(exclude_none=True)
    for i, v in enumerate(ab.variants):
        if v.subject is None and v.preheader is None and v.document is None:
            raise ApiError(422, "validation_failed", "The A/B test is not valid",
                           {f"ab.variants.{i}": "must change the subject, preheader or content"})
        if v.document is not None or v.subject is not None or v.preheader is not None:
            try:
                doc = checked(c, v.document if v.document is not None else cm.document, v.subject or cm.subject,
                              v.preheader if v.preheader is not None else cm.preheader)
            except ApiError as e:
                raise ApiError(422, "validation_failed", "The A/B test is not valid",
                               {f"ab.variants.{i}.{k}": m for k, m in (e.fields or {}).items()}) from None
            if v.document is not None:
                out["variants"][i]["document"] = doc
    return out


@router.patch("/{campaign_id}")
def update_campaign(campaign_id: uuid.UUID, body: PatchCampaign, c: Ctx = Depends(write)):
    cm = editable(campaign_or_404(c, campaign_id, lock=True))
    sent = body.model_fields_set
    before = campaign_json(cm)
    if body.template_id is not None:
        apply_template(c, cm, body.template_id)
    for key in ("name", "from_name"):
        if key in sent and getattr(body, key) is not None:
            setattr(cm, key, getattr(body, key))
    if "reply_to" in sent:
        if body.reply_to and not normal_email(body.reply_to):
            raise ApiError(422, "validation_failed", "The campaign is not valid", {"reply_to": "must be an address"})
        cm.reply_to = normal_email(body.reply_to) if body.reply_to else None
    if "channel_id" in sent:
        channel = c.db.get(Channel, body.channel_id) if body.channel_id else None
        if body.channel_id and (channel is None or channel.kind != "email"):
            raise ApiError(422, "validation_failed", "The campaign is not valid",
                           {"channel_id": "is not an email channel"})
        cm.channel_id = body.channel_id
    if "from_email" in sent:
        address = normal_email(body.from_email or "")
        if body.from_email and not address:
            raise ApiError(422, "validation_failed", "The campaign is not valid", {"from_email": "must be an address"})
        domain = domains.for_address(c.db, address) if address else None
        if address and domain is None:
            raise ApiError(422, "validation_failed", "The campaign is not valid",
                           {"from_email": f"{address.rpartition('@')[2]} is not one of your sending domains: add it "
                                          "under Domains"})
        cm.from_email, cm.domain_id = address or "", domain.id if domain else None
    if "topic_id" in sent:
        if body.topic_id and c.db.get(EmailTopic, body.topic_id) is None:
            raise ApiError(422, "validation_failed", "The campaign is not valid", {"topic_id": "is not a topic"})
        cm.topic_id = body.topic_id
    if "audience" in sent:
        spec = audience.spec_of(body.audience or {})
        if audience.chosen(spec):
            audience.conditions(Catalog(c), spec)  # a view that is not there or a filter that does not compile: 4xx
        cm.audience = spec
    for key in ("subject", "preheader"):
        if key in sent and getattr(body, key) is not None:
            setattr(cm, key, getattr(body, key))
    if {"document", "subject", "preheader", "template_id"} & sent:
        cm.document = checked(c, body.document if body.document is not None else cm.document, cm.subject,
                              cm.preheader)
    if "ab" in sent and body.ab is not None:
        cm.ab = check_variants(c, cm, body.ab)
    after = campaign_json(cm)
    changed = sorted(k for k in after if after[k] != before[k] and k not in ("updated_at", "stats"))
    if changed:
        cm.updated_at = func.now()
        c.db.flush()
        c.db.refresh(cm, ["updated_at"])
        sender.emit(c.db, "email_campaign.updated", cm, actor=("user", c.user_id), changed=changed)
    c.db.commit()
    return campaign_json(cm, counts_of(c, [cm.id]).get(cm.id))


@router.delete("/{campaign_id}", status_code=204)
def delete_campaign(campaign_id: uuid.UUID, c: Ctx = Depends(write)):
    cm = campaign_or_404(c, campaign_id, lock=True)
    if cm.status != "draft":
        raise ApiError(409, "not_deletable", "Only a draft can be deleted; a sent campaign keeps its report")
    sender.emit(c.db, "email_campaign.deleted", cm, actor=("user", c.user_id))
    c.db.delete(cm)
    c.db.commit()


@router.post("/{campaign_id}/duplicate", status_code=201)
def duplicate_campaign(campaign_id: uuid.UUID, c: Ctx = Depends(write), idem: Idem = Depends(idempotency)):
    src = campaign_or_404(c, campaign_id)
    cm = EmailCampaign(workspace_id=c.workspace.id, name=f"{src.name} (copy)"[:200], created_by=c.user_id,
                       **{k: getattr(src, k) for k in ("channel_id", "domain_id", "topic_id", "template_id",
                                                        "from_name", "from_email", "reply_to", "subject", "preheader",
                                                        "document", "audience", "ab", "timezone")})
    c.db.add(cm)
    c.db.flush()
    c.db.refresh(cm, ["created_at", "updated_at"])
    sender.emit(c.db, "email_campaign.created", cm, actor=("user", c.user_id))
    return idem.commit(201, campaign_json(cm))


@router.get("/{campaign_id}/audience")
def audience_preview(campaign_id: uuid.UUID, c: Ctx = Depends(read)):
    """Exactly who would receive the campaign if it went now (count, who is ruled out and why, a sample)."""
    cm = campaign_or_404(c, campaign_id)
    return audience.preview(Catalog(c), cm.audience or {}, cm.topic_id)


# --- the check --------------------------------------------------------------------------------------------------

def issue(level: str, code: str, message: str) -> dict:
    return {"level": level, "code": code, "message": message}


def deliverability(c: Ctx, cm: EmailCampaign) -> dict:
    """Everything that stands between this campaign and the inbox, as errors (which stop a send) and warnings."""
    found: list[dict] = []
    channel = c.db.get(Channel, cm.channel_id) if cm.channel_id else None
    if channel is None:
        found.append(issue("error", "no_channel", "Choose the email channel to send through"))
    elif channel.status == "disabled":
        found.append(issue("error", "channel_disabled", f"The channel {channel.name} is disabled"))
    elif channel.status == "failing":
        found.append(issue("warning", "channel_failing", f"The channel {channel.name} failed its last test: "
                                                         f"{channel.status_detail or 'test it again'}"))
    domain = c.db.get(EmailDomain, cm.domain_id) if cm.domain_id else None
    if not cm.from_email or domain is None:
        found.append(issue("error", "no_sender", "Choose a From address on one of your sending domains"))
    else:
        for key, name in (("spf", "SPF"), ("dkim", "DKIM"), ("dmarc", "DMARC")):
            result = (domain.checks or {}).get(key)
            if result is None:
                found.append(issue("error", f"{key}_unchecked", f"{domain.domain}: {name} has not been checked yet"))
            elif result["status"] in ("fail", "error"):
                found.append(issue("error", f"{key}_failing", f"{domain.domain}: {result['message']}"))
            elif result["status"] == "warn":
                found.append(issue("warning", f"{key}_warning", f"{domain.domain}: {result['message']}"))
        lim = domains.limits(domain)
        if lim["stage"] == "warming":
            found.append(issue("info", "warming", f"{domain.domain} is on day {lim['day']} of its warm-up: it sends "
                                                  f"at most {lim['daily']:,} a day, so a large audience takes longer"))
        if channel is not None and channel.provider == "mailgun":
            mg = (channel.config.get("domain") or "").lower()
            if mg and mg != domain.domain and not domain.domain.endswith("." + mg) and not mg.endswith(
                    "." + domain.domain):
                found.append(issue("warning", "provider_domain", f"The channel sends through Mailgun's {mg}, not "
                                                                 f"{domain.domain}: SPF and DKIM will not align"))
    st = settings_of(c.db, c.workspace.id)
    if not st.postal_address.strip():
        found.append(issue("warning", "no_address", "Add your postal address under Email settings: the law in most "
                                                    "places asks every marketing email to show it"))
    keys = sender.variant_keys(cm)
    for key in keys:
        subject, preheader, doc = sender.content(cm, key)
        out = document.render(doc, subject, preheader, document.Recipient(company=st.company_name,
                                                                         address=st.postal_address))
        prefix = f"Variant {key}: " if len(keys) > 1 else ""
        found += [issue(i.level, i.code, prefix + i.message) for i in lint.content(doc, subject, out)]
    preview = audience.preview(Catalog(c), cm.audience or {}, cm.topic_id)
    if not audience.chosen(cm.audience or {}):
        found.append(issue("error", "no_audience", "Choose who receives the campaign"))
    elif preview["recipients"] == 0:
        found.append(issue("error", "empty_audience", "Nobody in this audience can receive the campaign"))
    if (cm.ab or {}).get("enabled"):
        need = sender.MIN_PER_VARIANT * len(keys)
        size = preview["recipients"] * int(cm.ab.get("test_percent", 20)) // 100
        if len(keys) < 2:
            found.append(issue("error", "ab_variants", "An A/B test needs a variant B"))
        elif size < need:
            found.append(issue("warning", "ab_small", f"The test group would be {size} people, fewer than {need}: "
                                                      "the test will not run and everyone gets variant A"))
    errors = [f for f in found if f["level"] == "error"]
    return {"ok": not errors, "issues": found, "audience": preview, "estimate": usage.estimate(preview["recipients"])}


@router.post("/{campaign_id}/check")
def check_campaign(campaign_id: uuid.UUID, c: Ctx = Depends(read)):
    """The pre-send check: the sending domain's DNS, the channel, the content lint for every variant, the audience
    and the A/B test. `ok` is false while any issue is an `error`."""
    return deliverability(c, campaign_or_404(c, campaign_id))


# --- sending ----------------------------------------------------------------------------------------------------

def when(body: Schedule) -> datetime:
    try:
        zone = ZoneInfo(body.timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ApiError(422, "validation_failed", "The schedule is not valid", {"timezone": "is not a time zone"}) \
            from None
    if body.scheduled_at is None:
        return clock()
    at = body.scheduled_at
    if at.tzinfo is None:
        local = at.replace(tzinfo=zone)
        if local.astimezone(UTC).astimezone(zone).replace(tzinfo=None) != at:
            raise ApiError(422, "validation_failed", "The schedule is not valid",
                           {"scheduled_at": f"{at:%Y-%m-%d %H:%M} does not exist in {body.timezone} (the clocks "
                                            "change then)"})
        at = local
    at = at.astimezone(UTC)
    if at < clock() - timedelta(minutes=1):
        raise ApiError(422, "validation_failed", "The schedule is not valid", {"scheduled_at": "is in the past"})
    if at > clock() + MAX_SCHEDULE:
        raise ApiError(422, "validation_failed", "The schedule is not valid",
                       {"scheduled_at": "is more than a year away"})
    return at


@router.post("/{campaign_id}/schedule")
def schedule_campaign(campaign_id: uuid.UUID, body: Schedule, c: Ctx = Depends(send)):
    """Sends now (no `scheduled_at`) or at a time, after the check: a campaign with errors is refused (422,
    `fields.issues`). The audience is read when the send starts, with the scheduler's permissions."""
    cm = editable(campaign_or_404(c, campaign_id, lock=True))
    at = when(body)
    result = deliverability(c, cm)
    if not result["ok"]:
        errors = [i["message"] for i in result["issues"] if i["level"] == "error"]
        raise ApiError(422, "check_failed", f"Fix these first: {'; '.join(errors)}",
                       {f"issues.{i}": m for i, m in enumerate(errors)})
    cm.status, cm.scheduled_at, cm.timezone, cm.scheduled_by = "scheduled", at, body.timezone, c.user_id
    cm.error, cm.updated_at = None, func.now()
    sender.enqueue(c.db, "email.campaign.start", cm.id, run_at=at, request=True)
    sender.emit(c.db, "email_campaign.scheduled", cm, actor=("user", c.user_id), scheduled_at=at,
                recipients=result["audience"]["recipients"])
    c.db.commit()
    return campaign_json(cm)


@router.post("/{campaign_id}/unschedule")
def unschedule_campaign(campaign_id: uuid.UUID, c: Ctx = Depends(send)):
    cm = campaign_or_404(c, campaign_id, lock=True)
    if cm.status != "scheduled" and not (cm.status == "paused" and cm.paused_from == "scheduled"):
        raise ApiError(409, "not_scheduled", "Only a campaign that has not started can go back to a draft")
    cm.status, cm.paused_from, cm.scheduled_at, cm.updated_at = "draft", None, None, func.now()
    sender.emit(c.db, "email_campaign.updated", cm, actor=("user", c.user_id), changed=["status"])
    c.db.commit()
    return campaign_json(cm)


@router.post("/{campaign_id}/pause")
def pause_campaign(campaign_id: uuid.UUID, c: Ctx = Depends(send)):
    cm = campaign_or_404(c, campaign_id)
    if cm.status not in ("scheduled", "sending", "testing"):
        raise ApiError(409, "not_running", f"A {cm.status} campaign cannot be paused")
    sender.pause(c.db, cm, actor=("user", c.user_id))
    c.db.refresh(cm)
    return campaign_json(cm, counts_of(c, [cm.id]).get(cm.id))


@router.post("/{campaign_id}/resume")
def resume_campaign(campaign_id: uuid.UUID, c: Ctx = Depends(send)):
    cm = campaign_or_404(c, campaign_id, lock=True)
    if cm.status != "paused":
        raise ApiError(409, "not_paused", "Only a paused campaign can be resumed")
    sender.resume(c.db, cm, actor=("user", c.user_id))
    cm.updated_at = func.now()
    c.db.commit()
    return campaign_json(cm, counts_of(c, [cm.id]).get(cm.id))


@router.post("/{campaign_id}/cancel")
def cancel_campaign(campaign_id: uuid.UUID, c: Ctx = Depends(send)):
    """Stops for good: what has not gone yet never goes. What went stays in the report."""
    cm = campaign_or_404(c, campaign_id, lock=True)
    if cm.status not in ("scheduled", "sending", "testing", "paused"):
        raise ApiError(409, "not_running", f"A {cm.status} campaign cannot be cancelled")
    left = c.db.execute(update(EmailSend).where(EmailSend.campaign_id == cm.id,
                                                EmailSend.status.in_(("queued", "held")))
                        .values(status="cancelled", reason="The campaign was cancelled")).rowcount
    cm.status, cm.paused_from, cm.finished_at, cm.updated_at = "cancelled", None, clock(), func.now()
    sender.emit(c.db, "email_campaign.cancelled", cm, actor=("user", c.user_id), not_sent=left)
    c.db.commit()
    return campaign_json(cm, counts_of(c, [cm.id]).get(cm.id))


# --- the report -------------------------------------------------------------------------------------------------

def rate(n: int, base: int) -> float | None:
    return round(n / base, 4) if base else None


@router.get("/{campaign_id}/report")
def report(campaign_id: uuid.UUID, c: Ctx = Depends(read)):
    """Totals, rates (opens and clicks by people only: privacy proxy opens and scanner clicks are counted apart),
    each variant, each link and why sends were skipped."""
    cm = campaign_or_404(c, campaign_id)
    db = c.db
    status = dict(db.execute(select(EmailSend.status, func.count()).where(EmailSend.campaign_id == cm.id)
                             .group_by(EmailSend.status)).all())
    one = db.execute(select(
        func.count(), func.count().filter(EmailSend.opened_at.is_not(None)),
        func.count().filter(EmailSend.clicked_at.is_not(None)),
        func.count().filter(EmailSend.unsubscribed_at.is_not(None)),
        func.count().filter(EmailSend.delivered_at.is_not(None))).where(EmailSend.campaign_id == cm.id)).one()
    machine = dict(db.execute(select(EmailEvent.type, func.count()).where(
        EmailEvent.campaign_id == cm.id, EmailEvent.machine.is_(True)).group_by(EmailEvent.type)).all())
    proxy_only = db.scalar(select(func.count(func.distinct(EmailEvent.send_id))).where(
        EmailEvent.campaign_id == cm.id, EmailEvent.type == "open", EmailEvent.detail == "privacy_proxy")
        .where(~EmailEvent.send_id.in_(select(EmailSend.id).where(EmailSend.campaign_id == cm.id,
                                                                  EmailSend.opened_at.is_not(None)))))
    sent = sum(status.get(s, 0) for s in SENT)
    base = one[4] if one[4] else sent  # with delivery reports, rates are of what arrived; without, of what went
    totals = {"recipients": one[0], "sent": sent, "delivered": one[4], "opened": one[1], "clicked": one[2],
              "unsubscribed": one[3], "bounced": status.get("bounced", 0), "complained": status.get("complained", 0),
              "failed": status.get("failed", 0), "skipped": status.get("skipped", 0),
              "cancelled": status.get("cancelled", 0), "uncertain": status.get("uncertain", 0),
              "waiting": status.get("queued", 0) + status.get("held", 0) + status.get("sending", 0),
              "machine_opens": machine.get("open", 0), "machine_clicks": machine.get("click", 0),
              "privacy_proxy_only": proxy_only}
    rates = {"base": "delivered" if one[4] else "sent", "open": rate(one[1], base), "click": rate(one[2], base),
             "click_to_open": rate(one[2], one[1]), "bounce": rate(totals["bounced"], sent),
             "complaint": rate(totals["complained"], sent), "unsubscribe": rate(one[3], base)}
    per_variant = db.execute(select(
        EmailSend.variant, func.count().filter(EmailSend.status.in_(SENT)),
        func.count().filter(EmailSend.opened_at.is_not(None)), func.count().filter(EmailSend.clicked_at.is_not(None)))
        .where(EmailSend.campaign_id == cm.id).group_by(EmailSend.variant)).all()
    variants = []
    for key in sender.variant_keys(cm):
        row = next((r for r in per_variant if r[0] == key), (key, 0, 0, 0))
        variants.append({"variant": key, "subject": sender.content(cm, key)[0], "sent": row[1], "opened": row[2],
                         "clicked": row[3], "open_rate": rate(row[2], row[1]), "click_rate": rate(row[3], row[1]),
                         "winner": cm.winner == key})
    clicks = opens_by_link(db, cm.id)
    links = [{"idx": idx, "url": url, "clicks": clicks.get(idx, (0, 0, 0))[0], "people": clicks.get(idx, (0, 0, 0))[1],
              "machine_clicks": clicks.get(idx, (0, 0, 0))[2]}
             for idx, url in db.execute(select(EmailLink.idx, EmailLink.url).where(EmailLink.campaign_id == cm.id)
                                        .order_by(EmailLink.idx)).all()]
    skipped = dict(db.execute(select(func.coalesce(EmailSend.reason, "Other"), func.count()).where(
        EmailSend.campaign_id == cm.id, EmailSend.status.in_(("skipped", "failed", "bounced", "uncertain")))
        .group_by(EmailSend.reason)).all())
    hourly = db.execute(select(
        func.date_trunc("hour", EmailEvent.occurred_at).label("hour"),
        func.count().filter(EmailEvent.type == "open"), func.count().filter(EmailEvent.type == "click"))
        .where(EmailEvent.campaign_id == cm.id, EmailEvent.machine.is_(False),
               EmailEvent.type.in_(("open", "click"))).group_by("hour").order_by("hour").limit(168)).all()
    return {"campaign": campaign_json(cm, full=False), "totals": totals, "rates": rates, "variants": variants,
            "links": links, "reasons": skipped,
            "timeline": [{"hour": h, "opens": o, "clicks": k} for h, o, k in hourly]}


@router.get("/{campaign_id}/recipients")
def recipients(campaign_id: uuid.UUID,
               status: Literal["queued", "held", "sending", "sent", "delivered", "bounced", "complained", "failed",
                               "skipped", "cancelled", "uncertain"] | None = None,
               limit: int = Query(50, ge=1, le=200), cursor: str | None = None, c: Ctx = Depends(read)):
    """The sends, one per recipient, of contacts the caller may see (others are left out, as everywhere)."""
    cm = campaign_or_404(c, campaign_id)
    cat = Catalog(c)
    obj = cat.need("contact")
    stmt = (select(EmailSend, Record.display_name).join(Record, Record.id == EmailSend.contact_id)
            .where(EmailSend.campaign_id == cm.id, store.scope(cat, obj)))
    if status:
        stmt = stmt.where(EmailSend.status == status)
    rows, next_cursor = paginate(c.db, stmt, EmailSend, limit, cursor)
    hidden = permissions.hidden(c, obj)  # a role that hides contacts' addresses or names sees neither here
    return {"data": [{"id": s.id, "contact_id": s.contact_id,
                      "display_name": "(hidden)" if "display_name" in hidden else name,
                      "email": None if "email" in hidden else s.email,
                      "variant": s.variant, "status": s.status, "reason": s.reason, "sent_at": s.sent_at,
                      "delivered_at": s.delivered_at, "opened_at": s.opened_at, "clicked_at": s.clicked_at,
                      "opens": s.opens, "clicks": s.clicks, "unsubscribed_at": s.unsubscribed_at}
                     for s, name in rows], "next_cursor": next_cursor}

