"""The preference center (module 20): the page behind every campaign's unsubscribe and preferences links. It names
the sender, lists the workspace's topics with the recipient's choice for each, and offers to unsubscribe from
everything, or to subscribe again after an unsubscribe or a spam complaint (only the person can undo those, here).
The page is plain server-rendered HTML with no script, a strict Content-Security-Policy and no referrer, because its
address holds the token that acts for the recipient."""
import html
import uuid

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .. import events
from ..inbox import consent
from ..inbox.models import Consent
from ..models import Workspace
from .models import EmailPreference, EmailSend, EmailSuppression, EmailTopic
from .settings import settings_of

CSP = ("default-src 'none'; style-src 'unsafe-inline'; form-action 'self'; frame-ancestors 'none'; "
       "base-uri 'none'")
HEADERS = {"Content-Security-Policy": CSP, "Referrer-Policy": "no-referrer", "Cache-Control": "no-store",
           "X-Content-Type-Options": "nosniff", "X-Robots-Tag": "noindex"}
UNDOABLE = ("unsubscribe", "complaint")  # what the person may undo; a bounce is not theirs to clear


def set_topic(db: Session, workspace_id: uuid.UUID, contact_id: uuid.UUID, topic_id: uuid.UUID, subscribed: bool,
              source: str) -> bool:
    """Records a contact's choice for a topic; True when it changed."""
    row = db.get(EmailPreference, (contact_id, topic_id), with_for_update=True)
    if (row.subscribed if row else True) == subscribed:
        return False
    db.execute(insert(EmailPreference).values(
        contact_id=contact_id, topic_id=topic_id, workspace_id=workspace_id, subscribed=subscribed, source=source)
        .on_conflict_do_update(index_elements=["contact_id", "topic_id"],
                               set_={"subscribed": subscribed, "source": source, "changed_at": consent.clock()}))
    return True


def state(db: Session, s: EmailSend) -> dict:
    """What the page shows: the topics and the recipient's choice for each, and whether they are opted out."""
    topics = list(db.scalars(select(EmailTopic).where(EmailTopic.archived_at.is_(None)).order_by(EmailTopic.name)))
    prefs = {p.topic_id: p.subscribed for p in db.scalars(select(EmailPreference).where(
        EmailPreference.contact_id == s.contact_id))}
    row = db.get(Consent, (s.contact_id, "email"))
    blocked = db.scalar(select(EmailSuppression.reason).where(EmailSuppression.email == s.email))
    return {"topics": [(t, prefs.get(t.id, True)) for t in topics],
            "opted_out": (row is not None and row.status == "opted_out") or blocked in UNDOABLE,
            "bounced": blocked == "hard_bounce"}


def resubscribe(db: Session, s: EmailSend) -> bool:
    """The person asks for email again: their own unsubscribe or complaint is lifted (a bounce stays)."""
    changed = db.execute(delete(EmailSuppression).where(EmailSuppression.email == s.email,
                                                        EmailSuppression.reason.in_(UNDOABLE))).rowcount > 0
    row = db.get(Consent, (s.contact_id, "email"))
    if row is not None and row.status == "opted_out":
        changed = consent.record(db, s.workspace_id, s.contact_id, "email", "opted_in", "resubscribe",
                                 reason="Subscribed again on the preference page") or changed
    if changed:
        events.emit(db, "email.resubscribed", "record", s.contact_id,
                    {"contact_id": s.contact_id, "campaign_id": s.campaign_id, "send_id": s.id},
                    workspace_id=s.workspace_id)
    return changed


def save_topics(db: Session, s: EmailSend, chosen: set[str]) -> bool:
    changed = []
    for topic, before in state(db, s)["topics"]:
        wanted = str(topic.id) in chosen
        if wanted != before and set_topic(db, s.workspace_id, s.contact_id, topic.id, wanted, "preference_center"):
            changed.append({"topic_id": topic.id, "subscribed": wanted})
    if changed:
        events.emit(db, "email.preferences_changed", "record", s.contact_id,
                    {"contact_id": s.contact_id, "send_id": s.id, "changes": changed}, workspace_id=s.workspace_id)
    return bool(changed)


STYLE = """
:root{color-scheme:light dark;--bg:#f4f4f5;--card:#fff;--text:#18181b;--muted:#52525b;--line:#e4e4e7;--accent:#2563eb;
--ok:#15803d;--on:#ffffff}
@media (prefers-color-scheme:dark){:root{--bg:#0b0b0e;--card:#18181b;--text:#e4e4e7;--muted:#a1a1aa;--line:#27272a;
--accent:#7aa7ff;--ok:#4ade80;--on:#0b0b0e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:16px/1.5 -apple-system,
BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}
main{max-width:520px;margin:0 auto;padding:40px 16px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:24px}
h1{font-size:22px;line-height:1.3;margin:0 0 4px}p{margin:0 0 16px;color:var(--muted)}
.note{border-radius:8px;padding:10px 12px;margin:0 0 16px;border:1px solid var(--line);color:var(--text)}
.note.ok{border-color:var(--ok)}
fieldset{border:0;padding:0;margin:0 0 16px}legend{font-weight:600;margin:0 0 8px}
label{display:flex;gap:10px;align-items:flex-start;padding:10px 0;border-top:1px solid var(--line);cursor:pointer}
label small{display:block;color:var(--muted)}input[type=checkbox]{width:18px;height:18px;margin-top:3px;
accent-color:var(--accent)}
button{font:inherit;font-weight:600;border-radius:8px;padding:10px 16px;border:1px solid var(--line);
background:var(--card);color:var(--text);cursor:pointer;min-height:44px}
button.primary{background:var(--accent);border-color:var(--accent);color:var(--on)}
button:focus-visible,input:focus-visible{outline:3px solid var(--accent);outline-offset:2px}
.row{display:flex;flex-wrap:wrap;gap:8px}hr{border:0;border-top:1px solid var(--line);margin:24px 0}
.who{font-size:14px;color:var(--muted);margin-top:16px;text-align:center}
"""


def page(db: Session, s: EmailSend, message: str | None = None) -> str:
    ws = db.get(Workspace, s.workspace_id)
    st = settings_of(db, s.workspace_id)
    sender = html.escape(st.company_name or ws.name)
    now = state(db, s)
    email = html.escape(s.email)
    note = f'<p class="note ok" role="status">{html.escape(message)}</p>' if message else ""
    if now["bounced"]:
        body = (f"<p>Mail to {email} could not be delivered, so {sender} no longer sends to it. If the address works "
                "again, ask them to add it back.</p>")
    elif now["opted_out"]:
        body = (f"<p>{email} is unsubscribed from all marketing email from {sender}.</p>"
                '<form method="post"><input type="hidden" name="action" value="resubscribe">'
                '<button class="primary" type="submit">Subscribe again</button></form>')
    else:
        topics = "".join(
            f'<label><input type="checkbox" name="topic" value="{t.id}"{" checked" if on else ""}>'
            f'<span>{html.escape(t.name)}<small>{html.escape(t.description)}</small></span></label>'
            for t, on in now["topics"])
        choose = (f'<form method="post"><input type="hidden" name="action" value="save"><fieldset>'
                  f"<legend>What you get from {sender}</legend>{topics}</fieldset>"
                  '<button class="primary" type="submit">Save choices</button></form><hr>') if topics else ""
        body = (f"<p>Choose what {sender} sends to {email}.</p>{choose}"
                '<form method="post"><input type="hidden" name="action" value="unsubscribe">'
                "<p>Or stop all marketing email. You will still get messages you asked for, such as receipts and "
                "replies.</p><button type=\"submit\">Unsubscribe from all</button></form>")
    return (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            f'content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
            f"<title>Email preferences | {sender}</title><style>{STYLE}</style></head><body><main>"
            f'<div class="card"><h1>Email preferences</h1>{note}{body}</div>'
            f'<p class="who">Sent by {sender}' + (f" &middot; {html.escape(st.postal_address)}" if st.postal_address
                                                   else "") + "</p></main></body></html>")


def missing() -> str:
    return ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" '
            'content="width=device-width,initial-scale=1"><meta name="robots" content="noindex">'
            f"<title>Link not valid</title><style>{STYLE}</style></head><body><main><div class=\"card\">"
            "<h1>This link is not valid</h1><p>It may be incomplete. Open the link from the email again, or reply "
            "to the email to ask the sender to stop.</p></div></main></body></html>")
