"""The public side of forms: no session, found by a form's public key. A visitor loads the published definition, is
counted as a view (and given a signed token that says when the page was opened), saves answers as they go, and
completes. Every request starts in the narrow system scope, reads the form by its key, and moves to the form's
workspace before touching anything else, so row level security confines the rest. See spam.py for the protections.
Also the hosted page (`/f/{key}`), the embed script (`/embed.js`) and CORS: any origin may call these endpoints, and
they never send credentials."""
import html
import logging
import secrets
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Path, Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, StringConstraints
from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .. import config, events
from ..api import ApiError
from ..db import rescope
from ..models import Workspace
from ..records import timeline
from ..records.schema import Catalog
from ..security import Ctx, system_db, token_hash
from . import answers, contact, logic, spam
from .definition import Settings, public
from .models import Form, FormVersion, FormViews, Submission
from .state import closed_reason

log = logging.getLogger("forms")
router = APIRouter(prefix="/api/public/forms")
pages = APIRouter(include_in_schema=False)
PublicKey = Annotated[str, Path(pattern=r"^[A-Za-z0-9_-]{8,64}$")]
UTM = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")
CORS = {"Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "86400"}
NO_STORE = {"Cache-Control": "no-store"}


async def cors(request: Request, call_next):
    """Any origin, never credentials: these endpoints know nothing about the visitor's cookies and must not."""
    if not request.url.path.startswith("/api/public/forms/"):
        return await call_next(request)
    if request.method == "OPTIONS":
        return Response(status_code=204, headers=CORS)
    response = await call_next(request)
    response.headers.update(CORS)
    return response


Token = Annotated[str, StringConstraints(max_length=300)]
Link = Annotated[str, StringConstraints(max_length=2000)]


class Body(BaseModel):
    answers: dict = {}
    view_token: Token | None = None
    resume_token: Token | None = None
    step: Annotated[str, StringConstraints(max_length=40)] | None = None
    hp: Annotated[str, StringConstraints(max_length=1000)] | None = None  # the honeypot: people leave it empty
    url: Link | None = None
    referrer: Link | None = None
    utm: dict[str, Annotated[str, StringConstraints(max_length=200)]] = {}


def web_link(value: str | None) -> str | None:
    return value if value and value.startswith(("http://", "https://")) and "\x00" not in value else None


def open_form(db: Session, key: str) -> tuple[Form, Workspace, Settings]:
    """The form with this public key, which must have been published at some point; then the session moves to its
    workspace. A trashed form, an unknown key and an internal id are all the same 404."""
    form = db.scalar(select(Form).where(Form.public_key == key, Form.deleted_at.is_(None)))
    if form is None or form.status == "draft":
        raise ApiError(404, "not_found", "This form does not exist")
    ws = db.get(Workspace, form.workspace_id)
    rescope(db, org_id=ws.org_id, workspace_id=ws.id)
    s = Settings.model_validate(form.settings)
    return form, ws, s


def ensure_open(db: Session, form: Form, s: Settings) -> None:
    if closed_reason(db, form, s):
        raise ApiError(410, "form_closed", s.closed_message or "This form is no longer taking responses.")


def payload(form: Form, version: FormVersion, s: Settings) -> dict:
    return {"key": form.public_key, "kind": form.kind, "name": form.name, "version": version.number,
            "definition": public(version.definition),
            "settings": {"success_message": s.success_message, "redirect_url": s.redirect_url}}


def by_token(db: Session, form: Form, token: str | None, submission_id: uuid.UUID | None = None) -> Submission:
    """The response a resume token belongs to (and, when given, whose id it is). Anything else is a 404."""
    where = [Submission.form_id == form.id, Submission.resume_token_hash == token_hash(token or "")]
    if submission_id:
        where.append(Submission.id == submission_id)
    sub = db.scalar(select(Submission).where(*where).with_for_update())
    if sub is None:
        raise ApiError(404, "not_found", "This link is not valid")
    return sub


def done(form: Form, s: Settings, sub: Submission | None, defn: dict | None) -> dict:
    """The answer to a completed response; the same again for a repeated request, since the quiz result is a pure
    function of the stored answers."""
    result = None
    if sub is not None and form.kind == "quiz":
        result = answers.score(defn, logic.flow(defn, sub.answers), sub.answers)
    return {"id": sub.id if sub else uuid.uuid4(), "status": "complete", "message": s.success_message,
            "redirect_url": s.redirect_url, "result": result}


@router.get("/{public_key}")
def get_form(public_key: PublicKey, db: Session = Depends(system_db)):
    form, _, s = open_form(db, public_key)
    ensure_open(db, form, s)
    version = db.get(FormVersion, form.published_version_id)
    return JSONResponse(jsonable_encoder(payload(form, version, s)), headers=NO_STORE)


@router.post("/{public_key}/views")
def count_view(public_key: PublicKey, request: Request, db: Session = Depends(system_db)):
    form, ws, s = open_form(db, public_key)
    ensure_open(db, form, s)
    if spam.hit(db, form, spam.visitor(request), "view", spam.VIEW_LIMIT):
        db.execute(insert(FormViews).values(form_id=form.id, workspace_id=ws.id, day=datetime.now(UTC).date(), count=1)
                   .on_conflict_do_update(index_elements=["form_id", "day"], set_={"count": FormViews.count + 1}))
        db.commit()
    return JSONResponse({"view_token": spam.view_token(form.id)}, headers=NO_STORE)


@router.post("/{public_key}/submissions")
async def save(public_key: PublicKey, request: Request, db: Session = Depends(system_db)):
    """Starts a response, or with `resume_token` updates it, with the answers so far (not validated yet). The token
    comes back once, when the response starts: whoever holds it can continue and complete it."""
    form, ws, s = open_form(db, public_key)
    ensure_open(db, form, s)
    body = await spam.read(request, Body, s.max_body_kb)
    who = spam.visitor(request)
    spam.throttle(db, form, who, s)
    if body.hp and s.spam_protection:  # a bot is told it worked
        return JSONResponse({"id": str(uuid.uuid4()), "status": "partial", "resume_token": secrets.token_urlsafe(24)},
                            status_code=201)
    issued = spam.opened(body.view_token, form, s)
    token = None
    if body.resume_token:
        sub = by_token(db, form, body.resume_token)
        if sub.status == "complete":
            raise ApiError(409, "already_completed", "This response was already sent")
        version = db.get(FormVersion, sub.version_id)
    else:
        version = db.get(FormVersion, form.published_version_id)
        token = secrets.token_urlsafe(24)
        sub = Submission(
            workspace_id=ws.id, form_id=form.id, version_id=version.id, resume_token_hash=token_hash(token),
            source_url=web_link(body.url), referrer=web_link(body.referrer), steps_seen=[],
            utm={k: v for k, v in body.utm.items() if k in UTM and "\x00" not in v}, ip_hash=who,
            user_agent=(request.headers.get("user-agent", "").replace("\x00", "")[:300] or None),
            **({"started_at": datetime.fromtimestamp(issued, UTC)} if issued else {}))
        db.add(sub)
    defn = version.definition
    sub.answers = answers.partial(defn, body.answers)
    sub.last_field = answers.last_answered(defn, sub.answers)
    keys = [st["key"] for st in defn["steps"]]
    step = body.step if body.step in keys else (keys[0] if not sub.steps_seen else None)
    if step and step not in sub.steps_seen:
        sub.steps_seen = [*sub.steps_seen, step]
    sub.updated_at = func.now()
    db.commit()
    out = {"id": sub.id, "status": "partial", **({"resume_token": token} if token else {})}
    return JSONResponse(jsonable_encoder(out), status_code=201 if token else 200)


@router.post("/{public_key}/resume")
async def resume(public_key: PublicKey, request: Request, db: Session = Depends(system_db)):
    """What a resume link needs: the answers saved so far and the version of the form the response began on, which
    may no longer be the published one."""
    form, _, s = open_form(db, public_key)
    ensure_open(db, form, s)
    body = await spam.read(request, Body, s.max_body_kb)
    spam.throttle(db, form, spam.visitor(request), s)
    sub = by_token(db, form, body.resume_token)
    if sub.status == "complete":
        raise ApiError(409, "already_completed", "This response was already sent")
    version = db.get(FormVersion, sub.version_id)
    return JSONResponse(jsonable_encoder({"id": sub.id, "answers": sub.answers,
                                          "step": sub.steps_seen[-1] if sub.steps_seen else None,
                                          **payload(form, version, s)}), headers=NO_STORE)


@router.post("/{public_key}/submissions/{submission_id}/complete")
async def complete(public_key: PublicKey, submission_id: uuid.UUID, request: Request,
                   db: Session = Depends(system_db)):
    """Validates every visible answer on the version the response began on, applies the logic and scoring on the
    server (the browser's copy is a convenience), writes the contact, and emits `form.submitted`. Completing twice is
    harmless: the second call answers like the first and changes nothing."""
    form, ws, s = open_form(db, public_key)
    body = await spam.read(request, Body, s.max_body_kb)
    who = spam.visitor(request)
    spam.throttle(db, form, who, s)
    db.execute(select(Form.id).where(Form.id == form.id).with_for_update())  # completions of one form take turns
    sub = by_token(db, form, body.resume_token, submission_id)
    version = db.get(FormVersion, sub.version_id)
    defn = version.definition
    if sub.status == "complete":
        return done(form, s, sub, defn)
    if body.hp and s.spam_protection:
        return done(form, s, None, None)
    ensure_open(db, form, s)
    spam.opened(body.view_token, form, s, waited=True)

    cat = Catalog(Ctx(db, None, None, "", workspace=ws))
    contact_obj = cat.object("contact")
    contact_fields = cat.fields(contact_obj) if contact_obj else {}
    given = body.answers or sub.answers
    fl = logic.flow(defn, given)
    clean, errors = answers.validate(defn, given, fl, contact_fields)
    if errors:
        raise ApiError(422, "validation_failed", "Some answers need fixing", errors)

    values = answers.contact_values(defn, clean, contact_fields) if s.contact.create and contact_obj else {}
    if values and s.double_submission == "block":
        known = contact.find(cat, contact_obj, values)
        if known is not None and db.scalar(select(exists().where(
                Submission.form_id == form.id, Submission.status == "complete", Submission.contact_id == known.id))):
            raise ApiError(409, "already_submitted", "You already sent this form.")
    contact_id, created, note = None, False, None
    if values:
        try:
            with db.begin_nested():
                contact_id, created = contact.upsert(cat, values, s.contact.existing)
        except ApiError as e:  # the answer is kept even when the CRM refuses the contact (a required field it lacks)
            note = (next(iter(e.fields.values())) if e.fields else str(e.detail))[:300]

    when = datetime.now(UTC)
    quiz = answers.score(defn, fl, clean) if form.kind == "quiz" else None
    sub.answers, sub.status, sub.completed_at, sub.updated_at = clean, "complete", when, when
    sub.steps_seen, sub.last_field = [st["key"] for st in fl.steps], answers.last_answered(defn, clean)
    sub.contact_id, sub.contact_error = contact_id, note
    sub.consent = answers.consent_evidence(defn, fl, clean, when.isoformat(), str(form.id), who)
    if quiz:
        sub.score, sub.max_score = quiz["score"], quiz["max_score"]
    event = events.emit(db, "form.submitted", "form_submission", sub.id, {
        "id": sub.id, "form_id": form.id, "form_name": form.name, "kind": form.kind, "version": version.number,
        "answers": clean, "score": sub.score, "max_score": sub.max_score, "passed": quiz["passed"] if quiz else None,
        "contact_id": contact_id, "contact_created": created, "source_url": sub.source_url, "referrer": sub.referrer,
        "utm": sub.utm, "consent": {k: {"text": v["text"], "at": v["at"]} for k, v in sub.consent.items()}})
    if contact_id:
        timeline.link(db, event, [contact_id])  # the response shows on the contact's timeline
    db.commit()
    if s.notify_emails:
        # ponytail: the notification is a log line until the email module exists (module 13).
        log.info("form %s has a new response %s: would notify %s", form.id, sub.id, ", ".join(s.notify_emails))
    return done(form, s, sub, defn)


def shell(name: str, key: str, theme: str) -> str:
    dark = theme == "dark"
    return f"""<!doctype html>
<html lang="en" data-theme="{theme}">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>{html.escape(name)}</title>
<style>html,body{{margin:0;min-height:100%;background:{"#0e0e11" if dark else "#ffffff"}}}</style>
</head>
<body>
<script src="/embed.js" data-form="{html.escape(key)}" data-mode="page"></script>
<noscript>This form needs JavaScript.</noscript>
</body>
</html>
"""


# ponytail: the runtime is a static file of the web build, served from FRONTEND_DIST; behind a CDN, cache it there.
@pages.get("/f/{public_key}")
def hosted(public_key: PublicKey, theme: str = "light", db: Session = Depends(system_db)):
    name = db.scalar(select(Form.name).where(Form.public_key == public_key, Form.deleted_at.is_(None),
                                            Form.status != "draft"))
    if name is None:
        return HTMLResponse("<!doctype html><title>Not found</title><p>This form does not exist.", status_code=404)
    return HTMLResponse(shell(name, public_key, "dark" if theme == "dark" else "light"), headers={
        "Content-Security-Policy": "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
                                   "connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'none'",
        "Referrer-Policy": "strict-origin-when-cross-origin", **NO_STORE})


@pages.get("/embed.js")
def embed_script():
    file = config.FRONTEND_DIST / "embed.js"
    if not file.is_file():
        return JSONResponse({"detail": "The forms runtime is not built; run `npm run build` in frontend/."},
                            status_code=404)
    # five minutes: an embed picks up a new runtime soon, without a request per page view
    return FileResponse(file, media_type="text/javascript", headers={"Cache-Control": "public, max-age=300"})
