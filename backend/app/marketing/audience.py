"""Who a campaign goes to (module 20): a saved view of contacts, a filter (ADR 0002), or every contact, always
evaluated through the record engine with the permission scope of the person who schedules the send, so nobody can
mail contacts their role does not show them. The preview counts exactly who would receive it now and why the rest
would not; the snapshot, taken by the worker when the send starts (the segment is evaluated at send time), writes one
`email_sends` row per address in one statement, then marks what consent, the suppression list and the campaign's topic
rule out."""
import uuid

from sqlalchemy import Select, Uuid, and_, exists, func, literal, select
from sqlalchemy.dialects.postgresql import distinct_on, insert
from sqlalchemy.orm import Session

from ..api import ApiError
from ..inbox.models import Consent
from ..records import store
from ..records.models import ObjectDef, Record, SavedView
from ..records.query import where_of
from ..records.schema import Catalog
from .models import EmailCampaign, EmailPreference, EmailSend, EmailSuppression

SAMPLE = 5


def spec_of(raw: dict) -> dict:
    """The stored form of an audience: `{"view_id"}`, `{"filter"}` (both may be given: they are ANDed) or
    `{"all": true}`."""
    raw = raw or {}
    unknown = set(raw) - {"view_id", "filter", "all"}
    if unknown:
        raise ApiError(422, "validation_failed", "The audience is not valid",
                       {f"audience.{sorted(unknown)[0]}": "is not part of an audience"})
    out = {}
    if raw.get("view_id"):
        try:
            out["view_id"] = str(uuid.UUID(str(raw["view_id"])))
        except ValueError:
            raise ApiError(422, "validation_failed", "The audience is not valid",
                           {"audience.view_id": "must be a view id"}) from None
    if raw.get("filter"):
        if not isinstance(raw["filter"], dict):
            raise ApiError(422, "validation_failed", "The audience is not valid",
                           {"audience.filter": "must be a filter"})
        out["filter"] = raw["filter"]
    if raw.get("all") is True and not out:
        out["all"] = True
    return out


def chosen(spec: dict) -> bool:
    return bool(spec.get("view_id") or spec.get("filter") or spec.get("all"))


def conditions(cat: Catalog, spec: dict, with_email: bool = True) -> tuple[ObjectDef, list]:
    """The contact object and the SQL conditions of the audience for the catalog's caller (only contacts with an
    address, unless `with_email` is False); 422 when the view is gone or the filter no longer compiles."""
    obj = cat.need("contact")
    where = [*store.live(cat, obj), *([Record.email_norm.is_not(None)] if with_email else [])]
    if spec.get("view_id"):
        view = cat.db.get(SavedView, uuid.UUID(spec["view_id"]))
        if view is None or view.object_id != obj.id:
            raise ApiError(422, "audience_missing", "The saved view of this audience is gone or not a contact view",
                           {"audience.view_id": "is not a saved view of contacts you can see"})
        if view.filter:
            where.append(where_of(cat, obj, view.filter, root="audience.view"))
    if spec.get("filter"):
        where.append(where_of(cat, obj, spec["filter"], root="audience.filter"))
    return obj, where


def candidates(cat: Catalog, spec: dict) -> Select:
    """One row per address: the oldest live contact with it (duplicates share one send)."""
    _, where = conditions(cat, spec)
    return (select(Record.id, Record.email_norm, Record.display_name).where(*where)
            .ext(distinct_on(Record.email_norm)).order_by(Record.email_norm, Record.created_at, Record.id))


def blocked(db: Session, topic_id: uuid.UUID | None):
    """Conditions on (contact id, address) columns that rule a recipient out, by reason."""
    def rules(contact_id, email):
        out = {
            "suppressed": exists().where(EmailSuppression.email == email),
            "unsubscribed": exists().where(Consent.contact_id == contact_id, Consent.kind == "email",
                                           Consent.status.in_(("opted_out", "dnd"))),
        }
        if topic_id:
            out["topic_unsubscribed"] = exists().where(EmailPreference.contact_id == contact_id,
                                                       EmailPreference.topic_id == topic_id,
                                                       EmailPreference.subscribed.is_(False))
        return out
    return rules


def preview(cat: Catalog, spec: dict, topic_id: uuid.UUID | None) -> dict:
    """Exactly who would receive the campaign if it started now: the count, how many matched but are ruled out and
    why, and a few of the recipients."""
    if not chosen(spec):
        return {"matched": 0, "with_email": 0, "duplicates": 0, "excluded": {}, "recipients": 0, "sample": []}
    db = cat.db
    matched = db.scalar(select(func.count()).select_from(Record).where(*conditions(cat, spec, False)[1]))
    with_email = db.scalar(select(func.count()).select_from(Record).where(*conditions(cat, spec)[1]))
    rows = candidates(cat, spec).subquery()
    rules = blocked(db, topic_id)(rows.c.id, rows.c.email_norm)
    counts = db.execute(select(func.count(), *[func.count().filter(rule) for rule in rules.values()])
                        .select_from(rows)).one()
    unique = counts[0]
    excluded = {k: n for k, n in zip(rules, counts[1:], strict=True) if n}
    any_rule = rules["suppressed"] | rules["unsubscribed"] | rules.get("topic_unsubscribed", literal(False))
    recipients = db.scalar(select(func.count()).select_from(rows).where(~any_rule))
    sample = db.execute(select(rows.c.id, rows.c.display_name, rows.c.email_norm).where(~any_rule)
                        .order_by(rows.c.email_norm).limit(SAMPLE)).all()
    return {"matched": matched, "with_email": with_email, "duplicates": with_email - unique, "excluded": excluded,
            "recipients": recipients,
            "sample": [{"id": r.id, "display_name": r.display_name, "email": r.email_norm} for r in sample]}


def snapshot(cat: Catalog, campaign: EmailCampaign) -> int:
    """Writes the campaign's sends (inside `acting`, as the scheduler's role), marks the ones consent, the suppression
    list or the topic rule out as skipped, and returns how many are left to send. Running it twice adds nothing: a
    send is unique per campaign and contact, and per campaign and address."""
    db = cat.db
    rows = candidates(cat, campaign.audience).subquery()
    fixed = [literal(campaign.workspace_id, Uuid), literal(campaign.id, Uuid), rows.c.id,
             literal(campaign.domain_id, Uuid), rows.c.email_norm]
    db.execute(insert(EmailSend).from_select(
        ["workspace_id", "campaign_id", "contact_id", "domain_id", "email"], select(*fixed), include_defaults=False)
        .on_conflict_do_nothing())
    reasons = [("suppressed", "On the suppression list"), ("unsubscribed", "Unsubscribed or do not disturb"),
               ("topic_unsubscribed", "Unsubscribed from this topic")]
    rules = blocked(db, campaign.topic_id)(EmailSend.contact_id, EmailSend.email)
    for key, reason in reasons:
        if key in rules:
            db.execute(EmailSend.__table__.update().where(
                EmailSend.campaign_id == campaign.id, EmailSend.status == "queued", rules[key])
                .values(status="skipped", reason=reason))
    return db.scalar(select(func.count()).select_from(EmailSend).where(
        and_(EmailSend.campaign_id == campaign.id, EmailSend.status == "queued"))) or 0
