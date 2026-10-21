"""What providers report about mail after it left (module 20): delivery, hard bounces, spam complaints and their own
unsubscribe handling. The inbox's webhook endpoint (`/api/hooks/{provider}/{channel}`) verifies and parses the report
and hands any email report that is not about one of its own messages here. A hard bounce or a complaint puts the
address on the suppression list, so no campaign mails it again; a complaint and an unsubscribe also opt the contact
out of email, as the inbox already does for its own messages.

A campaign send is found by the provider's id, or by its Message-ID, whose left part is the send id (the adapters
derive it from the idempotency key). A report only moves a send forward: a late `delivered` never undoes a bounce."""
import logging
import uuid

from sqlalchemy import or_, select, update
from sqlalchemy.orm import Session

from .. import events
from ..channels.base import Inbound
from ..inbox import consent
from ..inbox.models import Channel
from .models import EmailCampaign, EmailEvent, EmailSend
from .settings import suppress

log = logging.getLogger("marketing")
RANK = {"queued": 0, "sending": 1, "uncertain": 1, "sent": 2, "delivered": 3, "bounced": 4, "complained": 5}


def find(db: Session, provider_id: str) -> EmailSend | None:
    keys = [EmailSend.provider_message_id == provider_id]
    local = provider_id.partition("@")[0]
    try:
        keys.append(EmailSend.id == uuid.UUID(local))
    except ValueError:
        pass
    return db.scalar(select(EmailSend).where(or_(*keys)).limit(1).with_for_update())


def report(db: Session, channel: Channel, item: Inbound) -> bool:
    """Applies one email delivery report to a campaign send. False when it is not about one (the caller logs it)."""
    s = find(db, item.provider_message_id)
    if s is None:
        return False
    c = db.get(EmailCampaign, s.campaign_id)
    if c is None or c.channel_id != channel.id:
        return False  # another channel's report naming this id: not ours to act on
    data = {"contact_id": s.contact_id, "campaign_id": s.campaign_id, "send_id": s.id}
    if item.status == "delivered":
        if RANK.get(s.status, 0) < RANK["delivered"]:
            s.status, s.delivered_at = "delivered", item.occurred_at or s.sent_at
            db.add(EmailEvent(workspace_id=s.workspace_id, campaign_id=s.campaign_id, send_id=s.id, type="delivered"))
    elif item.status == "failed":  # Mailgun reports permanent failures only: a hard bounce
        reason = (item.error or "The receiving server refused the address")[:300]
        if RANK.get(s.status, 0) < RANK["bounced"]:
            s.status, s.reason = "bounced", reason
            db.add(EmailEvent(workspace_id=s.workspace_id, campaign_id=s.campaign_id, send_id=s.id, type="bounce",
                              detail=reason))
            events.emit(db, "email.bounced", "record", s.contact_id, {**data, "reason": reason},
                        workspace_id=s.workspace_id)
        suppress(db, s.workspace_id, s.email, "hard_bounce", reason, s.campaign_id)
    elif item.status == "complained":
        if s.status != "complained":
            s.status = "complained"
            db.add(EmailEvent(workspace_id=s.workspace_id, campaign_id=s.campaign_id, send_id=s.id, type="complaint"))
            events.emit(db, "email.complained", "record", s.contact_id, data, workspace_id=s.workspace_id)
        suppress(db, s.workspace_id, s.email, "complaint", "Marked as spam", s.campaign_id)
        consent.record(db, s.workspace_id, s.contact_id, "email", "opted_out", "complaint")
    elif item.status == "unsubscribed":
        unsubscribe(db, s, None, "provider")
    db.flush()
    return True


def unsubscribe(db: Session, s: EmailSend, topic_id: uuid.UUID | None, source: str) -> bool:
    """The recipient unsubscribes from a topic, or from all marketing email (topic None): the contact is opted out
    of email and the address suppressed. True when something changed."""
    from .preferences import set_topic  # the preference center owns topic choices
    changed = set_topic(db, s.workspace_id, s.contact_id, topic_id, False, source) if topic_id else False
    if topic_id is None:
        changed = consent.record(db, s.workspace_id, s.contact_id, "email", "opted_out", "unsubscribe",
                                 reason=f"Unsubscribed from a campaign ({source})")
        changed = suppress(db, s.workspace_id, s.email, "unsubscribe", f"Unsubscribed ({source})",
                           s.campaign_id) or changed
    if s.unsubscribed_at is None:
        db.execute(update(EmailSend).where(EmailSend.id == s.id).values(unsubscribed_at=consent.clock()))
        db.add(EmailEvent(workspace_id=s.workspace_id, campaign_id=s.campaign_id, send_id=s.id, type="unsubscribe",
                          detail=source))
    if changed:
        events.emit(db, "email.unsubscribed", "record", s.contact_id,
                    {"contact_id": s.contact_id, "campaign_id": s.campaign_id, "send_id": s.id,
                     "topic_id": topic_id, "source": source}, workspace_id=s.workspace_id)
    return changed
