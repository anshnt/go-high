"""Responses to a form (`/api/v1/forms/{id}/submissions`): the list with filters, one response with the questions it was
asked, and a CSV export that cannot be turned into a spreadsheet attack."""
import csv
import io
import re
import uuid
from datetime import UTC, date, datetime, time, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy import select

from ..api import paginate
from ..security import Ctx, in_workspace
from .admin import form_or_404
from .definition import fields_of
from .models import FormVersion, Submission

router = APIRouter(prefix="/api/v1/forms/{form_id}/submissions")
EXPORT_MAX = 50_000  # ponytail: built in memory; a larger export becomes a job that writes a file
PAGE = 1000
INJECTION = ("=", "+", "-", "@", "\t", "\r", "\n")  # what a spreadsheet may read as a formula
UTM = ("utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content")


def bounds(created: date | None, until: date | None) -> tuple[datetime | None, datetime | None]:
    """From the start of `created` to the end of `until` (UTC, both inclusive), as a half open range."""
    return (datetime.combine(created, time.min, UTC) if created else None,
            datetime.combine(until, time.min, UTC) + timedelta(days=1) if until else None)


def window(created: date | None, until: date | None) -> list:
    start, end = bounds(created, until)
    return [*([Submission.created_at >= start] if start else []), *([Submission.created_at < end] if end else [])]


def submission_json(s: Submission, number: int, fields: list[dict] | None = None) -> dict:
    return {"id": s.id, "status": s.status, "answers": s.answers, "score": s.score, "max_score": s.max_score,
            "contact_id": s.contact_id, "contact_error": s.contact_error, "source_url": s.source_url,
            "referrer": s.referrer, "utm": s.utm, "consent": s.consent, "version": number,
            "started_at": s.started_at, "created_at": s.created_at, "completed_at": s.completed_at,
            **({"fields": fields} if fields is not None else {})}


def cell(value) -> str:
    """One CSV cell. A text that starts with =, +, - or @ (or a tab or line break) would run as a formula when the file
    is opened in a spreadsheet, so it gets a leading apostrophe; numbers are written as they are."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, int | float):
        return str(value)
    text = str(value)
    return "'" + text if text.startswith(INJECTION) else text


def shown(f: dict, value) -> str:
    """An answer as a person reads it: choices by label, yes or no."""
    labels = {o["id"]: o["label"] for o in f.get("options", [])}
    if isinstance(value, list):
        return "; ".join(str(labels.get(v, v)) for v in value)
    if f["type"] in ("select",):
        return labels.get(value, value)
    return value


def filters(status: str | None, created: date | None, until: date | None) -> list:
    return [*([Submission.status == status] if status else []), *window(created, until)]


@router.get("")
def list_submissions(form_id: uuid.UUID, status: Literal["partial", "complete"] | None = None,
                     created: date | None = Query(None, alias="from"), until: date | None = Query(None, alias="to"),
                     limit: int = Query(50, ge=1, le=200), cursor: str | None = None, c: Ctx = Depends(in_workspace)):
    """Newest first. `from` and `to` are dates (UTC, inclusive) of when the response was started."""
    form = form_or_404(c, form_id)
    stmt = (select(Submission, FormVersion.number).join(FormVersion, FormVersion.id == Submission.version_id)
            .where(Submission.form_id == form.id, *filters(status, created, until)))
    rows, next_cursor = paginate(c.db, stmt, Submission, limit, cursor)
    return {"data": [submission_json(s, number) for s, number in rows], "next_cursor": next_cursor}


@router.get("/export.csv")
def export_submissions(form_id: uuid.UUID, status: Literal["partial", "complete"] | None = None,
                       created: date | None = Query(None, alias="from"), until: date | None = Query(None, alias="to"),
                       c: Ctx = Depends(in_workspace)):
    """Every matching response (up to 50 000, newest first) as CSV: one column per question of any version, choices
    by their label. Text that a spreadsheet could run as a formula is neutralized. `X-Export-Truncated` is `true`
    when there were more."""
    form = form_or_404(c, form_id)
    versions = c.db.scalars(select(FormVersion).where(FormVersion.form_id == form.id)
                            .order_by(FormVersion.number.desc())).all()
    defs = {v.id: fields_of(v.definition) for v in versions}
    questions: dict[str, str] = {}
    for v in versions:  # the newest version's questions first, then any that only older versions had
        for f in defs[v.id].values():
            if f["type"] not in ("heading", "paragraph"):
                questions.setdefault(f["key"], f["label"])
    out = io.StringIO(newline="")
    writer = csv.writer(out)
    writer.writerow([cell(h) for h in ["Response", "Status", "Started", "Completed", "Contact", "Score", "Max score",
                                       "Source URL", "Referrer", *(u.replace("_", " ").title() for u in UTM),
                                       *questions.values()]])
    stmt = (select(Submission).where(Submission.form_id == form.id, *filters(status, created, until))
            .order_by(Submission.created_at.desc(), Submission.id.desc()))
    written, truncated = 0, False
    while not truncated:
        page = c.db.scalars(stmt.offset(written).limit(PAGE)).all()
        for s in page:
            if written == EXPORT_MAX:
                truncated = True
                break
            known = defs[s.version_id]
            writer.writerow([cell(v) for v in [
                s.id, s.status, s.started_at.isoformat(), s.completed_at and s.completed_at.isoformat(), s.contact_id,
                s.score, s.max_score, s.source_url, s.referrer, *(s.utm.get(u) for u in UTM),
                *(shown(known[k], s.answers[k]) if k in known and k in s.answers else None for k in questions)]])
            written += 1
        if len(page) < PAGE:
            break
    name = re.sub(r"[^a-z0-9-]", "", form.slug) or "form"
    # the byte order mark makes Excel read the file as UTF-8
    return Response("\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8", headers={
        "Content-Disposition": f'attachment; filename="{name}-responses.csv"',
        "X-Export-Truncated": "true" if truncated else "false", "Cache-Control": "no-store"})


@router.get("/{submission_id}")
def get_submission(form_id: uuid.UUID, submission_id: uuid.UUID, c: Ctx = Depends(in_workspace)):
    """One response with the questions of the version it was answered on (key, type and label)."""
    form = form_or_404(c, form_id)
    row = c.db.execute(select(Submission, FormVersion).join(FormVersion, FormVersion.id == Submission.version_id)
                       .where(Submission.form_id == form.id, Submission.id == submission_id)).first()
    if row is None:
        raise HTTPException(404, "Response not found")
    sub, version = row
    fields = [{"key": f["key"], "type": f["type"], "label": f["label"], "options": f.get("options", [])}
              for f in fields_of(version.definition).values() if f["type"] not in ("heading", "paragraph")]
    return submission_json(sub, version.number, fields)
