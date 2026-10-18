"""Spam protection of the public endpoints, on by default: a rate limit per form and visitor (a Postgres counter), a
maximum body size per form, a honeypot field, and a minimum fill time measured from a signed token handed out when the
page was opened. Nothing here needs JavaScript from a third party or a challenge the visitor can see."""
import json
import time
import uuid

from fastapi import Request
from pydantic import BaseModel, ValidationError
from sqlalchemy import delete
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from .. import config
from ..api import ApiError, seal, sign, unseal
from ..security import client_ip
from .definition import Settings
from .models import Form, FormRate

TOKEN_DAYS = 7  # a page left open longer than this has to be reloaded
VIEW_LIMIT = 60  # page views counted per visitor and form per minute; more are served but not counted
KEEP_MINUTES = 60  # how long the per-minute counters live


def minute() -> int:
    return int(time.time() // 60)


def visitor(request: Request) -> str:
    """A keyed hash of the address: stable enough to rate limit and to show as evidence, useless without the key."""
    return sign(f"ip:{client_ip(request)}")


def view_token(form_id: uuid.UUID) -> str:
    return seal([str(form_id), int(time.time())])


def opened(token: str | None, form: Form, s: Settings, *, waited: bool = False) -> int | None:
    """When the visitor opened the page (unix seconds), from the token. A form with spam protection refuses a missing
    or foreign token and, with `waited`, a visitor who answered faster than a person could."""
    if not token:
        if s.spam_protection:
            raise ApiError(400, "invalid_view_token", "Reload the page and try again")
        return None
    try:
        form_id, issued = unseal(token)
        if form_id != str(form.id) or isinstance(issued, bool) or not isinstance(issued, int):
            raise ValueError
    except (ApiError, ValueError):
        raise ApiError(400, "invalid_view_token", "Reload the page and try again") from None
    now = time.time()
    if issued > now + 5 or now - issued > TOKEN_DAYS * 86400:
        raise ApiError(400, "invalid_view_token", "This page was open for too long, reload it and try again")
    if waited and s.spam_protection and now - issued < config.FORM_MIN_FILL_SECONDS:
        wait = max(1, config.FORM_MIN_FILL_SECONDS - int(now - issued))
        raise ApiError(429, "too_fast", "That was quick. Check your answers and send again.",
                       headers={"Retry-After": str(wait)})
    return issued


def hit(db: Session, form: Form, who: str, kind: str, limit: int) -> bool:
    """Counts one request of `who` this minute and says whether it is within `limit`. Commits, so a refused request
    still counts (an error response would roll the counter back)."""
    now = minute()
    key = dict(form_id=form.id, ip_hash=who, kind=kind, bucket=now)
    n = db.scalar(insert(FormRate).values(**key, workspace_id=form.workspace_id, count=1).on_conflict_do_update(
        index_elements=list(key), set_={"count": FormRate.count + 1}).returning(FormRate.count))
    db.execute(delete(FormRate).where(FormRate.form_id == form.id, FormRate.bucket < now - KEEP_MINUTES))
    db.commit()
    return n <= limit


def throttle(db: Session, form: Form, who: str, s: Settings) -> None:
    if not hit(db, form, who, "write", s.rate_limit_per_minute):
        raise ApiError(429, "rate_limited", "Too many requests. Try again in a minute.",
                       headers={"Retry-After": str(60 - int(time.time()) % 60)})


async def read[M: BaseModel](request: Request, model: type[M], limit_kb: int) -> M:
    """The JSON body as `model`, refusing more than `limit_kb` before it is all in memory."""
    limit = limit_kb * 1024
    too_big = ApiError(413, "payload_too_large", f"The request is larger than {limit_kb} KB")
    declared = request.headers.get("content-length", "")
    if declared.isdigit() and int(declared) > limit:
        raise too_big
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise too_big
        chunks.append(chunk)
    try:
        data = json.loads(b"".join(chunks) or b"{}")
        if not isinstance(data, dict):
            raise ValueError
    except ValueError:
        raise ApiError(400, "invalid_json", "The body must be a JSON object") from None
    try:
        return model.model_validate(data)
    except ValidationError as e:
        fields = {".".join(map(str, err["loc"])): err["msg"].removeprefix("Value error, ") for err in e.errors()}
        raise ApiError(422, "validation_failed", "The request is not valid", fields) from None
