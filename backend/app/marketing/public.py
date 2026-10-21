"""The public side of campaigns (module 20): the open pixel, click redirects and the unsubscribe and preference page,
found by the signed token in each link (tokens.py). No session. A token that does not verify gets nothing: the pixel
still answers with an image (a mail client shows nothing broken), a click or a page gets a 404 that redirects nowhere.
Only a verified token reads its send, in the system scope, and everything after runs in the send's workspace.

Click redirects only ever go to an address the campaign itself links to: the token carries the link's number, and the
address comes from the campaign's own link table, so the endpoint cannot be used as an open redirect.

Machines open and click too. An open by Apple's privacy proxy (Mail Privacy Protection preloads every image), a
known crawler, or within seconds of sending is counted as a machine open; a click by a security scanner (a known
agent, a HEAD request, a click seconds after sending, or several links of one email within a few seconds) is a machine
click. Both are kept in the log and left out of the rates."""
import re
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Path, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from .. import events
from ..channels.base import Request as Raw
from ..db import rescope, scoped
from ..models import Workspace
from . import preferences, tokens
from .feedback import unsubscribe
from .models import EmailCampaign, EmailEvent, EmailLink, EmailSend

router = APIRouter(prefix="/api/public/email", include_in_schema=False)
Token = Path(pattern=r"^[A-Za-z0-9_-]{20,64}$")
GIF = (b"GIF89a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00\x00\x00"
       b"\x01\x00\x01\x00\x00\x02\x02D\x01\x00;")
NO_STORE = {"Cache-Control": "no-store, private", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex"}
BOTS = re.compile(r"bot|crawl|spider|slurp|scan|preview|proofpoint|mimecast|barracuda|urldefense|safelinks|"
                  r"python|curl|wget|java/|go-http|okhttp|headless|phantom|libwww|httpclient|http-client|axios|"
                  r"node-fetch|ruby|perl|php|monitor|check|fetch|validator|virustotal|symantec|trendmicro|sophos|"
                  r"fortinet|cisco|forcepoint|zscaler|paloalto|websense", re.I)
APPLE_PROXY = "Mozilla/5.0"  # Mail Privacy Protection fetches images with this agent and nothing else
OPEN_GRACE = timedelta(seconds=2)  # an image fetched sooner than this after sending was a prefetch
CLICK_GRACE = timedelta(seconds=10)  # nobody reads an email and clicks it this fast; scanners do
BURST = (timedelta(seconds=5), 3)  # this many different links of one email within this long: a scanner
MAX_LOGGED = 500  # opens or clicks of one send kept in the log; more are counted, not stored


def clock() -> datetime:
    return datetime.now(UTC)


def machine_open(agent: str, sent_at: datetime | None, now: datetime) -> str | None:
    """Why an open was not a person ('privacy_proxy', 'bot', 'prefetch'), or None."""
    agent = agent.strip()
    if agent == APPLE_PROXY:
        return "privacy_proxy"
    if not agent or BOTS.search(agent):
        return "bot"
    if sent_at and now - sent_at < OPEN_GRACE:
        return "prefetch"
    return None


def machine_click(agent: str, method: str, sent_at: datetime | None, now: datetime,
                  recent_links: set[int]) -> str | None:
    """Why a click was not a person ('head', 'bot', 'too_fast', 'burst'), or None. `recent_links` are the other links
    of this email clicked within the burst window."""
    if method == "HEAD":
        return "head"
    if not agent.strip() or BOTS.search(agent):
        return "bot"
    if sent_at and now - sent_at < CLICK_GRACE:
        return "too_fast"
    if len(recent_links) + 1 >= BURST[1]:
        return "burst"
    return None


def load(token: str, kind: tokens.Kind) -> tuple[Session, EmailSend, tokens.Token] | None:
    """The send of a genuine token, with a session moved into its workspace (the caller closes it)."""
    found = tokens.read(token, kind)
    if found is None:
        return None
    db = scoped(system="on")
    s = db.get(EmailSend, found.send_id)
    ws = db.get(Workspace, s.workspace_id) if s else None
    if s is None or ws is None:
        db.close()
        return None
    db.commit()
    rescope(db, workspace_id=ws.id, org_id=ws.org_id)
    return db, db.get(EmailSend, found.send_id, populate_existing=True), found


def about(s: EmailSend) -> dict:
    """The data of the first open or click by a person: an event about the contact (timeline, webhooks, workflows)."""
    return {"contact_id": s.contact_id, "campaign_id": s.campaign_id, "send_id": s.id}


@router.get("/o/{token}.gif")
def opened(request: Request, token: str = Token):
    loaded = load(token, "open")
    if loaded:
        db, s, _ = loaded
        with db:
            now = clock()
            why = machine_open(request.headers.get("user-agent", ""), s.sent_at, now)
            if s.opens < MAX_LOGGED:
                db.add(EmailEvent(workspace_id=s.workspace_id, campaign_id=s.campaign_id, send_id=s.id, type="open",
                                  machine=why is not None, detail=why))
            values = {"opens": EmailSend.opens + 1}
            if why is None and s.opened_at is None:
                values["opened_at"] = now
                events.emit(db, "email.opened", "record", s.contact_id, about(s), workspace_id=s.workspace_id)
            db.execute(update(EmailSend).where(EmailSend.id == s.id).values(**values))
            db.commit()
    return Response(GIF, media_type="image/gif", headers=NO_STORE)


@router.api_route("/c/{token}", methods=["GET", "HEAD"])
def clicked(request: Request, token: str = Token):
    loaded = load(token, "click")
    if not loaded:
        return HTMLResponse(preferences.missing(), status_code=404, headers={**preferences.HEADERS})
    db, s, found = loaded
    with db:
        url = db.scalar(select(EmailLink.url).where(EmailLink.campaign_id == s.campaign_id,
                                                     EmailLink.idx == found.link))
        if url is None:
            return HTMLResponse(preferences.missing(), status_code=404, headers={**preferences.HEADERS})
        if request.method == "HEAD":  # a scanner checking where the link goes: answer, count nothing
            return RedirectResponse(url, status_code=302, headers=NO_STORE)
        now = clock()
        recent = set(db.scalars(select(EmailEvent.link_idx).where(
            EmailEvent.send_id == s.id, EmailEvent.type == "click", EmailEvent.occurred_at > now - BURST[0],
            EmailEvent.link_idx != found.link)))
        why = machine_click(request.headers.get("user-agent", ""), request.method, s.sent_at, now, recent)
        if s.clicks < MAX_LOGGED:
            db.add(EmailEvent(workspace_id=s.workspace_id, campaign_id=s.campaign_id, send_id=s.id, type="click",
                              link_idx=found.link, machine=why is not None, detail=why))
        values = {"clicks": EmailSend.clicks + 1}
        if why is None:
            if s.clicked_at is None:
                values["clicked_at"] = now
                events.emit(db, "email.clicked", "record", s.contact_id, about(s), workspace_id=s.workspace_id)
            if s.opened_at is None:  # a click means it was opened, whatever the pixel did (images off, MPP)
                values["opened_at"] = now
                events.emit(db, "email.opened", "record", s.contact_id, about(s), workspace_id=s.workspace_id)
        db.execute(update(EmailSend).where(EmailSend.id == s.id).values(**values))
        db.commit()
    return RedirectResponse(url, status_code=302, headers=NO_STORE)


def page(db: Session, s: EmailSend, message: str | None = None, status: int = 200) -> HTMLResponse:
    return HTMLResponse(preferences.page(db, s, message), status_code=status, headers=preferences.HEADERS)


@router.get("/u/{token}")
def preference_page(token: str = Token):
    loaded = load(token, "unsubscribe")
    if not loaded:
        return HTMLResponse(preferences.missing(), status_code=404, headers=preferences.HEADERS)
    db, s, _ = loaded
    with db:
        return page(db, s)


@router.post("/u/{token}")
async def unsubscribe_post(request: Request, token: str = Token):
    """RFC 8058 one-click unsubscribe (a body of `List-Unsubscribe=One-Click`, sent by the mail client with no
    cookie and no page) and the preference page's own forms (`action` save, unsubscribe or resubscribe)."""
    raw = Raw(str(request.url), dict(request.headers), await request.body())
    try:
        pairs = raw.pairs()
    except (ValueError, UnicodeError):
        pairs = []
    from starlette.concurrency import run_in_threadpool
    return await run_in_threadpool(act, token, pairs)


def act(token: str, pairs: list[tuple[str, str]]):
    loaded = load(token, "unsubscribe")
    if not loaded:
        return HTMLResponse(preferences.missing(), status_code=404, headers=preferences.HEADERS)
    db, s, _ = loaded
    form = dict(pairs)
    with db:
        campaign = db.get(EmailCampaign, s.campaign_id)
        if form.get("List-Unsubscribe") == "One-Click" and "action" not in form:
            # from the list header: the list this mail came from, which is its topic when it has one
            unsubscribe(db, s, campaign.topic_id if campaign else None, "one_click")
            db.commit()
            return PlainTextResponse("You are unsubscribed.", headers=NO_STORE)
        action = form.get("action")
        if action == "unsubscribe":
            unsubscribe(db, s, None, "preference_center")
            message = "You are unsubscribed from all marketing email."
        elif action == "resubscribe":
            preferences.resubscribe(db, s)
            message = "You are subscribed again."
        elif action == "save":
            preferences.save_topics(db, s, {v for k, v in pairs if k == "topic"})
            message = "Your choices are saved."
        else:
            return page(db, s, status=400)
        db.commit()
        return page(db, s, message)


def opens_by_link(db: Session, campaign_id: uuid.UUID) -> dict[int, tuple[int, int, int]]:
    """Per link number: human clicks, distinct people who clicked, machine clicks."""
    rows = db.execute(select(EmailEvent.link_idx, func.count().filter(EmailEvent.machine.is_(False)),
                             func.count(func.distinct(EmailEvent.send_id)).filter(EmailEvent.machine.is_(False)),
                             func.count().filter(EmailEvent.machine.is_(True)))
                      .where(EmailEvent.campaign_id == campaign_id, EmailEvent.type == "click")
                      .group_by(EmailEvent.link_idx)).all()
    return {r[0]: (r[1], r[2], r[3]) for r in rows}
