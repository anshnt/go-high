"""Sending a campaign (module 20), all of it through the job queue:

`email.campaign.start` runs at the scheduled time. It checks the sending domain's DNS again, evaluates the audience
now, as the person who scheduled it (the segment is read at send time), writes one send per address, marks what
consent and the suppression list rule out, splits an A/B test, numbers the links and starts the batches.

`email.campaign.batch` hands out sends at the pace the sending domain allows (its warm-up stage or its own hourly
limit, counted across every campaign of the domain under the domain's row lock), at most EMAIL_BATCH_SIZE at a time,
then sends each through the campaign's channel and queues itself again. A send is claimed (`sending`) and committed
before the provider is called, and its outcome is committed right after, so:

- a send is handed to the provider at most once: two batches cannot claim the same row (SKIP LOCKED and a status
  change), and a row still `sending` after the lease (a worker died between the provider and the commit) becomes
  `uncertain` and is never sent again. So does a send whose provider call failed after the request went out (a lost
  answer), because the provider may have taken it. A refusal the provider gave (429, 5xx, an SMTP 4xx) is retried
  with backoff; a permanent one fails, and a refused address is a hard bounce that goes on the suppression list.
- consent, the suppression list, the topic and the contact are checked again right before each send, so someone who
  unsubscribes or bounces mid-campaign is skipped.

`email.campaign.decide` ends an A/B test: the variant with the best rate of human opens (or clicks) wins, ties go to
the first variant, and the held part of the audience is queued with it."""
import logging
import uuid
from datetime import UTC, datetime, timedelta
from email.utils import formataddr

from sqlalchemy import exists, func, select, text, update
from sqlalchemy.orm import Session

from .. import config, events, jobs
from ..channels.base import ChannelError, Outbound
from ..db import acting
from ..inbox import gateway, vault
from ..inbox.models import Channel, Consent
from ..jobs import Job
from ..models import Workspace
from ..records.models import FieldDef, Record
from ..records.schema import Catalog
from ..security import Ctx
from ..tenancy import effective_role
from . import audience, document, domains, tokens, usage
from .models import EmailCampaign, EmailDomain, EmailEvent, EmailLink, EmailPreference, EmailSend
from .settings import settings_of, suppress, suppressed
from .templates import values_of

log = logging.getLogger("marketing")
LEASE = timedelta(minutes=15)  # a send still `sending` after this was lost with its worker: it becomes uncertain
MAX_ATTEMPTS = 5  # provider refusals worth retrying, per send
MIN_PER_VARIANT = 10  # an A/B test needs at least this many recipients per variant, else everyone gets variant A
BOUNCE_CODES = ("550", "551", "553", "554")  # SMTP: the address does not exist or the server refuses it for good


def clock() -> datetime:
    return datetime.now(UTC)


# --- content ----------------------------------------------------------------------------------------------------

def variant_keys(c: EmailCampaign) -> list[str]:
    ab = c.ab or {}
    return ["A", *[v["key"] for v in ab.get("variants", [])]] if ab.get("enabled") else ["A"]


def content(c: EmailCampaign, variant: str | None) -> tuple[str, str, document.Document]:
    """(subject, preheader, document) of a variant: A is the campaign's own content, B and on override parts of it."""
    subject, preheader, raw = c.subject, c.preheader, c.document
    if variant and variant != "A":
        v = next((v for v in (c.ab or {}).get("variants", []) if v["key"] == variant), {})
        subject = v.get("subject") or subject
        preheader = v.get("preheader") if v.get("preheader") is not None else preheader
        raw = v.get("document") or raw
    return subject, preheader, document.parse(raw)


def campaign_links(c: EmailCampaign) -> list[str]:
    found: list[str] = []
    for key in variant_keys(c):
        for url in document.links(content(c, key)[2]):
            if url not in found:
                found.append(url)
    return found


# --- scheduling helpers -----------------------------------------------------------------------------------------

def queued_job(db: Session, kind: str, campaign_id: uuid.UUID) -> bool:
    return bool(db.scalar(select(exists().where(Job.kind == kind, Job.status == "queued",
                                                Job.payload["campaign_id"].astext == str(campaign_id)))))


def enqueue(db: Session, kind: str, campaign_id: uuid.UUID, run_at: datetime | None = None,
            request: bool = False) -> None:
    """Queues the campaign's next job of this kind unless one is already waiting (keeps one chain per campaign). A
    request cannot read the queue (`request=True`): it always adds one, and every job checks the campaign's state
    first, so a spare job does nothing."""
    if request or not queued_job(db, kind, campaign_id):
        jobs.enqueue(db, kind, {"campaign_id": str(campaign_id)}, run_at=run_at, max_attempts=10)


def campaign_data(c: EmailCampaign, **more) -> dict:
    return {"id": c.id, "name": c.name, "status": c.status, **more}


def emit(db: Session, type_: str, c: EmailCampaign, actor=None, **more) -> None:
    events.emit(db, type_, "email_campaign", c.id, campaign_data(c, **more), actor=actor, workspace_id=c.workspace_id)


def fail(db: Session, c: EmailCampaign, reason: str) -> None:
    c.status, c.error, c.finished_at = "failed", reason[:500], clock()
    db.execute(update(EmailSend).where(EmailSend.campaign_id == c.id, EmailSend.status.in_(("queued", "held")))
               .values(status="cancelled", reason="The campaign failed"))
    emit(db, "email_campaign.failed", c, error=c.error)
    db.commit()


def scheduler(db: Session, c: EmailCampaign, ws: Workspace) -> Ctx | None:
    """The person who scheduled the send, with the role they hold now: the audience is what they may see."""
    found = effective_role(db, c.scheduled_by, ws) if c.scheduled_by else None
    if found is None:
        return None
    role, org_admin = found
    return Ctx(db, c.scheduled_by, None, "", ws, workspace_role="admin" if org_admin else role.key, role=role,
               org_admin=org_admin)


# --- start ------------------------------------------------------------------------------------------------------

@jobs.handler("email.campaign.start")
def start(db: Session, payload: dict) -> None:
    c = db.get(EmailCampaign, uuid.UUID(payload["campaign_id"]))
    if c is None or c.status != "scheduled" or (c.scheduled_at and c.scheduled_at > clock() + timedelta(seconds=5)):
        return  # unscheduled, paused, cancelled or moved to a later time (that time has its own job)
    domain = db.get(EmailDomain, c.domain_id) if c.domain_id else None
    if domain is None:
        return fail(db, c, "The campaign has no sending domain")
    db.commit()
    try:
        domains.run_check(db, domain)  # the DNS may have changed since the check before scheduling
    except Exception:  # noqa: BLE001  (DNS libraries raise many things; a broken resolver must not hold the send)
        log.exception("DNS check of %s failed before campaign %s", domain.domain, c.id)
    db.commit()
    c = db.get(EmailCampaign, c.id, with_for_update=True, populate_existing=True)
    if c.status != "scheduled":
        return db.commit()
    if domain.status != "verified":
        return fail(db, c, f"{domain.domain} no longer passes SPF, DKIM and DMARC: fix the DNS records and send "
                           "again")
    ws = db.get(Workspace, c.workspace_id)
    ctx = scheduler(db, c, ws)
    if ctx is None:
        return fail(db, c, "The person who scheduled the campaign can no longer act in this workspace")
    try:
        with acting(db, workspace_id=ws.id, org_id=ws.org_id, user_id=c.scheduled_by):
            ready = audience.snapshot(Catalog(ctx), c)
    except Exception as e:  # noqa: BLE001  (a view that is gone, a filter that no longer compiles)
        db.rollback()
        c = db.get(EmailCampaign, c.id, with_for_update=True, populate_existing=True)
        return fail(db, c, f"The audience could not be read: {getattr(e, 'detail', None) or e}")
    note = split(db, c, ready)
    for i, url in enumerate(campaign_links(c)):
        db.add(EmailLink(campaign_id=c.id, idx=i, workspace_id=c.workspace_id, url=url))
    c.audience_count = db.scalar(select(func.count()).select_from(EmailSend).where(EmailSend.campaign_id == c.id))
    c.status, c.started_at, c.error = "sending", clock(), None
    if note:
        c.error = note
    emit(db, "email_campaign.started", c, recipients=ready)
    if (c.ab or {}).get("enabled") and not c.winner:
        c.test_ends_at = c.started_at + timedelta(hours=int(c.ab.get("wait_hours", 4)))
    enqueue(db, "email.campaign.batch", c.id)
    db.commit()


def split(db: Session, c: EmailCampaign, ready: int) -> str | None:
    """Splits an A/B test: `test_percent` of the deliverable audience, in a random order fixed by the send ids, is
    shared out between the variants and the rest is held for the winner. Returns a note when the test cannot run."""
    ab = c.ab or {}
    if not ab.get("enabled"):
        db.execute(update(EmailSend).where(EmailSend.campaign_id == c.id).values(variant="A"))
        return None
    keys = variant_keys(c)
    test_size = ready * int(ab.get("test_percent", 20)) // 100
    if test_size < MIN_PER_VARIANT * len(keys):
        db.execute(update(EmailSend).where(EmailSend.campaign_id == c.id).values(variant="A"))
        c.winner = "A"
        return (f"The A/B test did not run: {ready} recipients give fewer than {MIN_PER_VARIANT} per variant, so "
                "everyone got variant A")
    db.execute(text(
        "WITH ranked AS (SELECT id, row_number() OVER (ORDER BY md5(id::text)) - 1 AS n FROM email_sends "
        "WHERE campaign_id = :c AND status = 'queued') "
        "UPDATE email_sends s SET phase = CASE WHEN r.n < :size THEN 'test' ELSE 'main' END, "
        "variant = CASE WHEN r.n < :size THEN (CAST(:keys AS text[]))[(r.n % :k) + 1] END, "
        "status = CASE WHEN r.n < :size THEN 'queued' ELSE 'held' END FROM ranked r WHERE s.id = r.id"),
        {"c": c.id, "size": test_size, "keys": keys, "k": len(keys)})
    if test_size >= ready:  # everyone is in the test (100 %): nothing to hold, the winner is for the report
        return None
    return None


# --- batches ----------------------------------------------------------------------------------------------------

def room(db: Session, d: EmailDomain, now: datetime) -> tuple[int, datetime | None]:
    """How many sends the domain may hand out now, and, when none, the moment that changes."""
    lim = domains.limits(d, now)
    per_run = max(1, -(-lim["hourly"] * config.EMAIL_BATCH_SECONDS // 3600)) if lim["hourly"] else 0
    left = min(lim["hourly"] - domains.sent_since(db, d.id, now - timedelta(hours=1)), per_run,
               config.EMAIL_BATCH_SIZE)
    window = timedelta(hours=1)
    if lim["daily"] is not None:
        day_left = lim["daily"] - domains.sent_since(db, d.id, now - timedelta(days=1))
        if day_left < left:
            left, window = day_left, timedelta(days=1)
    if left > 0:
        return left, None
    if lim["hourly"] == 0:
        return 0, now + timedelta(hours=1)  # not verified (no warm-up yet): look again in an hour
    oldest = db.scalar(select(func.min(EmailSend.claimed_at)).where(
        EmailSend.domain_id == d.id, EmailSend.claimed_at >= now - window))
    if oldest is None:
        return 0, now + timedelta(seconds=config.EMAIL_BATCH_SECONDS)
    return 0, oldest + window + timedelta(seconds=1)


def reap(db: Session, campaign_id: uuid.UUID, now: datetime) -> None:
    db.execute(update(EmailSend).where(EmailSend.campaign_id == campaign_id, EmailSend.status == "sending",
                                       EmailSend.claimed_at < now - LEASE)
               .values(status="uncertain", reason="The worker stopped while sending: it may have gone out, so it is "
                                                  "not sent again"))


def claim(db: Session, campaign_id: uuid.UUID, n: int) -> list[uuid.UUID]:
    due = (select(EmailSend.id).where(EmailSend.campaign_id == campaign_id, EmailSend.status == "queued",
                                      (EmailSend.next_attempt_at.is_(None)) | (EmailSend.next_attempt_at <= func.now()))
           .order_by(EmailSend.phase.desc(), EmailSend.id).limit(n).with_for_update(skip_locked=True))
    return list(db.scalars(update(EmailSend).where(EmailSend.id.in_(due.scalar_subquery()))
                           .values(status="sending", claimed_at=func.now(), attempts=EmailSend.attempts + 1)
                           .returning(EmailSend.id)))


@jobs.handler("email.campaign.batch")
def batch(db: Session, payload: dict) -> None:
    campaign_id = uuid.UUID(payload["campaign_id"])
    now = clock()
    reap(db, campaign_id, now)
    db.commit()
    c = db.get(EmailCampaign, campaign_id)
    if c is None or c.status != "sending":
        return
    d = db.get(EmailDomain, c.domain_id, with_for_update=True, populate_existing=True)  # one throttle per domain
    if not usage.allowed(db, c.workspace_id, 1):
        db.rollback()
        return pause(db, c, "The workspace reached its usage cap")
    left, wait = room(db, d, now)
    if left <= 0:
        enqueue(db, "email.campaign.batch", c.id, run_at=wait)
        return db.commit()
    claimed = claim(db, c.id, left)
    db.commit()  # the claim is visible (and the domain unlocked) before any provider is called
    if claimed:
        ctx = Sending.load(db, c)
        for send_id in claimed:
            deliver(db, ctx, send_id)
    # a batch the pace cut short waits for the next slot; a full one (a fast domain) goes on at once
    follow_up(db, c.id, paced=len(claimed) < config.EMAIL_BATCH_SIZE)


def follow_up(db: Session, campaign_id: uuid.UUID, paced: bool = True) -> None:
    """After a batch: queue the next one, start the A/B wait, or finish."""
    c = db.get(EmailCampaign, campaign_id, with_for_update=True, populate_existing=True)
    if c.status != "sending":
        return db.commit()
    counts = dict(db.execute(select(EmailSend.status, func.count()).where(EmailSend.campaign_id == c.id)
                             .group_by(EmailSend.status)).all())
    if counts.get("queued"):
        retry_at = db.scalar(select(func.min(EmailSend.next_attempt_at)).where(
            EmailSend.campaign_id == c.id, EmailSend.status == "queued"))
        ready_now = db.scalar(select(exists().where(
            EmailSend.campaign_id == c.id, EmailSend.status == "queued",
            (EmailSend.next_attempt_at.is_(None)) | (EmailSend.next_attempt_at <= func.now()))))
        later = clock() + timedelta(seconds=config.EMAIL_BATCH_SECONDS)
        enqueue(db, "email.campaign.batch", c.id,
                run_at=(later if paced else None) if ready_now else min(filter(None, [retry_at, later])))
    elif counts.get("sending"):
        enqueue(db, "email.campaign.batch", c.id, run_at=clock() + LEASE + timedelta(seconds=5))  # wait out the lease
    elif counts.get("held"):
        c.status = "testing"
        emit(db, "email_campaign.testing", c, test_ends_at=c.test_ends_at)
        enqueue(db, "email.campaign.decide", c.id, run_at=c.test_ends_at)
    else:
        c.status, c.finished_at = "sent", clock()
        emit(db, "email_campaign.completed", c, totals=counts)
    db.commit()


class Sending:
    """What every send of one batch shares: the campaign, its channel, domain, settings, links and the contact
    fields, read once."""

    def __init__(self, c, channel, domain, settings, links, fields, dkim_key):
        self.c, self.channel, self.domain, self.settings = c, channel, domain, settings
        self.links, self.fields, self.dkim_key = links, fields, dkim_key
        self.docs: dict[str | None, tuple] = {}

    @classmethod
    def load(cls, db: Session, c: EmailCampaign) -> "Sending":
        channel, domain = db.get(Channel, c.channel_id), db.get(EmailDomain, c.domain_id)
        links = {url: idx for idx, url in db.execute(select(EmailLink.idx, EmailLink.url).where(
            EmailLink.campaign_id == c.id)).all()}
        contact_object = db.scalar(text("SELECT id FROM objects WHERE workspace_id = :w AND key = 'contact'"),
                                   {"w": c.workspace_id})
        fields = {f.key: f for f in db.scalars(select(FieldDef).where(FieldDef.object_id == contact_object,
                                                                      FieldDef.archived_at.is_(None)))}
        key = None
        if domain.dkim_mode == "managed" and channel.provider in ("smtp", "ses") and domain.dkim_secret_ref:
            key = vault.reveal(domain.dkim_secret_ref).get("dkim_private_key")
        db.commit()
        return cls(c, channel, domain, settings_of(db, c.workspace_id), links, fields, key)

    def content(self, variant: str | None):
        if variant not in self.docs:
            self.docs[variant] = content(self.c, variant)
        return self.docs[variant]


def refusal(db: Session, s: EmailSend, c: EmailCampaign, contact: Record | None) -> str | None:
    """Why this send must not go now, or None: checked right before the provider is called."""
    if contact is None or contact.deleted_at is not None:
        return "The contact was deleted"
    if (contact.email_norm or "") != s.email:
        return "The contact's address changed since the campaign started"
    if why := suppressed(db, s.email):
        return f"On the suppression list ({why.replace('_', ' ')})"
    consent = db.get(Consent, (s.contact_id, "email"))
    if consent is not None and consent.status in ("opted_out", "dnd"):
        return "Unsubscribed or do not disturb"
    if c.topic_id:
        pref = db.get(EmailPreference, (s.contact_id, c.topic_id))
        if pref is not None and not pref.subscribed:
            return "Unsubscribed from this topic"
    return None


def outbound(ctx: Sending, s: EmailSend, contact: Record) -> Outbound:
    c, st = ctx.c, ctx.settings
    subject, preheader, doc = ctx.content(s.variant)

    def link(url: str) -> str:
        return tokens.click_url(s.id, ctx.links[url]) if st.track_clicks and url in ctx.links else url
    recipient = document.Recipient(
        values=values_of(ctx.fields, contact), unsubscribe_url=tokens.unsubscribe_url(s.id),
        preferences_url=tokens.preferences_url(s.id), link=link,
        open_pixel=tokens.open_url(s.id) if st.track_opens else None, company=st.company_name,
        address=st.postal_address)
    out = document.render(doc, subject, preheader, recipient)
    dkim = (ctx.domain.domain, ctx.domain.dkim_selector, ctx.dkim_key) if ctx.dkim_key else None
    return Outbound(
        to=s.email, from_=formataddr((c.from_name, c.from_email)) if c.from_name else c.from_email, body=out.text,
        subject=out.subject, html=out.html, reply_to=c.reply_to or ctx.channel.config.get("reply_to"),
        idempotency_key=str(s.id), unsubscribe_url=recipient.unsubscribe_url, dkim=dkim,
        # Gmail groups complaints by this id (its feedback loop): campaign, workspace, kind, sender
        headers={"Feedback-ID": f"{c.id.hex[:16]}:{c.workspace_id.hex[:16]}:campaign:gohigh"})


def settle(db: Session, send_id: uuid.UUID, **values) -> None:
    db.execute(update(EmailSend).where(EmailSend.id == send_id, EmailSend.status == "sending").values(**values))


def deliver(db: Session, ctx: Sending, send_id: uuid.UUID) -> None:
    """One claimed send, start to end, in its own transactions."""
    s = db.get(EmailSend, send_id, populate_existing=True)
    if s is None or s.status != "sending":
        return
    contact = db.get(Record, s.contact_id)
    try:
        if why := refusal(db, s, ctx.c, contact):
            settle(db, s.id, status="skipped", reason=why, claimed_at=None)  # a skip does not use the domain's room
            return db.commit()
        message = outbound(ctx, s, contact)
    except Exception as e:  # noqa: BLE001  (nothing has left yet: fail this send, keep the batch going)
        db.rollback()
        log.exception("could not build send %s", send_id)
        settle(db, send_id, status="failed", reason=f"Could not build the email: {e}"[:300])
        return db.commit()
    db.commit()
    try:
        result = gateway.send(ctx.channel, message)
    except ChannelError as e:
        db.rollback()
        return refused(db, ctx, s, e)
    except Exception as e:  # noqa: BLE001  (a bug or a crash in the adapter: the provider may have the message)
        db.rollback()
        log.exception("send %s failed in the adapter", send_id)
        settle(db, send_id, status="uncertain", reason=f"The send stopped unexpectedly ({type(e).__name__}): it may "
                                                       "have gone out, so it is not sent again")
        return db.commit()
    settle(db, send_id, status="sent", provider_message_id=result.provider_message_id, sent_at=func.now(),
           reason=None)
    usage.record(db, s.workspace_id, s.id)
    db.commit()


def refused(db: Session, ctx: Sending, s: EmailSend, e: ChannelError) -> None:
    reason = str(e)[:300]
    if e.ambiguous:
        settle(db, s.id, status="uncertain", reason=f"No answer from the provider after the email was handed over "
                                                    f"({reason}): it may have gone out, so it is not sent again"[:300])
    elif e.retryable and s.attempts < MAX_ATTEMPTS:
        settle(db, s.id, status="queued", reason=reason,
               next_attempt_at=func.now() + jobs.backoff(s.attempts) * 3)  # 30 s, 60 s, 2 min...
    elif e.code[:3] in BOUNCE_CODES:
        settle(db, s.id, status="bounced", reason=reason)
        bounced(db, s, ctx.c, reason)
    else:
        settle(db, s.id, status="failed", reason=reason)
    db.commit()


def bounced(db: Session, s: EmailSend, c: EmailCampaign, reason: str) -> None:
    db.add(EmailEvent(workspace_id=s.workspace_id, campaign_id=s.campaign_id, send_id=s.id, type="bounce",
                      detail=reason[:300]))
    suppress(db, s.workspace_id, s.email, "hard_bounce", reason, c.id)
    events.emit(db, "email.bounced", "record", s.contact_id,
                {"contact_id": s.contact_id, "campaign_id": c.id, "send_id": s.id, "reason": reason},
                workspace_id=s.workspace_id)


# --- A/B decision, pause and resume -----------------------------------------------------------------------------

def variant_rates(db: Session, c: EmailCampaign) -> list[dict]:
    """Per variant of the test phase (or of everyone, for a test of 100 %): sent, human opens and clicks, rates."""
    sent_statuses = ("sent", "delivered", "bounced", "complained")
    rows = db.execute(select(
        EmailSend.variant, func.count().filter(EmailSend.status.in_(sent_statuses)),
        func.count().filter(EmailSend.opened_at.is_not(None)), func.count().filter(EmailSend.clicked_at.is_not(None)))
        .where(EmailSend.campaign_id == c.id, EmailSend.phase.in_(("test", "all")), EmailSend.variant.is_not(None))
        .group_by(EmailSend.variant)).all()
    found = {r[0]: r for r in rows}
    out = []
    for key in variant_keys(c):
        _, sent, opened, clicked = found.get(key, (key, 0, 0, 0))
        out.append({"variant": key, "sent": sent, "opened": opened, "clicked": clicked,
                    "open_rate": opened / sent if sent else 0.0, "click_rate": clicked / sent if sent else 0.0})
    return out


def pick(c: EmailCampaign, rates: list[dict]) -> str:
    metric = "click_rate" if (c.ab or {}).get("metric") == "clicks" else "open_rate"
    best = max(r[metric] for r in rates)
    return next(r["variant"] for r in rates if r[metric] == best)  # a tie goes to the first variant


@jobs.handler("email.campaign.decide")
def decide(db: Session, payload: dict) -> None:
    c = db.get(EmailCampaign, uuid.UUID(payload["campaign_id"]), with_for_update=True)
    if c is None or c.status != "testing":
        return
    if c.test_ends_at and c.test_ends_at > clock() + timedelta(seconds=5):
        enqueue(db, "email.campaign.decide", c.id, run_at=c.test_ends_at)
        return db.commit()
    rates = variant_rates(db, c)
    c.winner = pick(c, rates)
    db.execute(update(EmailSend).where(EmailSend.campaign_id == c.id, EmailSend.status == "held")
               .values(status="queued", variant=c.winner))
    c.status = "sending"
    emit(db, "email_campaign.winner_chosen", c, winner=c.winner, rates=rates)
    enqueue(db, "email.campaign.batch", c.id)
    db.commit()


def pause(db: Session, c: EmailCampaign, reason: str | None = None, actor=None) -> None:
    c = db.get(EmailCampaign, c.id, with_for_update=True, populate_existing=True)
    if c.status not in ("scheduled", "sending", "testing"):
        return db.commit()
    c.paused_from, c.status, c.error = c.status, "paused", reason
    emit(db, "email_campaign.paused", c, actor=actor, reason=reason)
    db.commit()


def resume(db: Session, c: EmailCampaign, actor=None) -> None:
    """Back to what the campaign was doing; the next job picks up where the last one stopped. Runs in a request."""
    c.status, back = c.paused_from or "scheduled", c.paused_from
    c.paused_from, c.error = None, None
    if back == "testing":
        enqueue(db, "email.campaign.decide", c.id, run_at=c.test_ends_at, request=True)
    elif back == "sending":
        enqueue(db, "email.campaign.batch", c.id, request=True)
    else:
        c.status = "scheduled"
        enqueue(db, "email.campaign.start", c.id, run_at=max(c.scheduled_at or clock(), clock()), request=True)
    emit(db, "email_campaign.resumed", c, actor=actor)
