"""Saved email templates and the render preview (module 20). A template is a subject, a preheader and a block document
(document.py); saving checks the document and every merge field against the contact fields the author may read.
`POST /email/render` is what the builder's live preview calls: the same renderer as a real send, with a sample contact's
values when one is named, and the deliverability lint of the content. Reading is `marketing.read`, writing
`marketing.write`; templates are archived, never deleted, so a campaign that copied one keeps its history."""
import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select

from .. import events, permissions
from ..api import ApiError, Idem, idempotency, paginate
from ..permissions import requires
from ..records import store
from ..records.models import FieldDef, Record
from ..records.schema import Catalog
from ..security import Ctx
from . import document, lint
from .models import EmailTemplate
from .settings import settings_of

router = APIRouter(prefix="/api/v1/email")
read, write = requires("marketing.read"), requires("marketing.write")
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Subject = Annotated[str, StringConstraints(max_length=500)]
Preheader = Annotated[str, StringConstraints(max_length=300)]
STARTER = {"version": 1, "blocks": [
    {"type": "heading", "id": "title", "text": "Hello {{first_name|there}}", "level": 1},
    {"type": "text", "id": "intro", "text": "Write what this email is about. **Bold** and _italic_ work, and so do "
                                            "[links](https://example.com)."},
    {"type": "button", "id": "cta", "label": "Read more", "url": "https://example.com"}]}


class NewTemplate(BaseModel):
    name: Name
    subject: Subject = ""
    preheader: Preheader = ""
    document: dict | None = None


class PatchTemplate(BaseModel):
    name: Name | None = None
    subject: Subject | None = None
    preheader: Preheader | None = None
    document: dict | None = None
    archived: bool | None = None


class RenderBody(BaseModel):
    subject: Subject = ""
    preheader: Preheader = ""
    document: dict = {}
    contact_id: uuid.UUID | None = None


# --- merge values -----------------------------------------------------------------------------------------------

def merge_fields(c: Ctx) -> dict[str, FieldDef]:
    """The contact fields an author may use in merge fields: the ones their role can read."""
    cat = Catalog(c)
    obj = cat.need("contact")
    hidden = permissions.hidden(c, obj)
    return {k: f for k, f in cat.fields(obj).items() if k not in hidden}


def known_keys(c: Ctx) -> set[str]:
    return {*merge_fields(c), "display_name"}


def as_text(field: FieldDef | None, value) -> str:
    """A field value as the words a mail shows: a choice's label, an amount with its currency, yes or no."""
    if value is None or value == "" or value == []:
        return ""
    if field is not None and field.type in ("select", "multi_select"):
        labels = {c["id"]: c.get("label", c["id"]) for c in field.options.get("choices", [])}
        ids = value if isinstance(value, list) else [value]
        return ", ".join(labels.get(i, str(i)) for i in ids)
    if isinstance(value, dict) and {"amount", "currency"} <= value.keys():
        return f"{value['amount'] / 100:,.2f} {value['currency']}"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def values_of(fields: dict[str, FieldDef], rec: Record) -> dict[str, str]:
    out = {k: as_text(fields.get(k), v) for k, v in (rec.values or {}).items() if k in fields}
    out["display_name"] = rec.display_name or ""
    return out


def checked(c: Ctx, raw: dict | None, subject: str, preheader: str) -> dict:
    """The document as stored, after the checks; a 422 naming every problem otherwise."""
    try:
        doc = document.parse(raw or {})
        document.check_merge(doc, subject, preheader, known_keys(c))
    except document.Invalid as e:
        raise ApiError(422, "validation_failed", "The email is not valid", e.fields) from None
    return doc.model_dump(exclude_none=True)


# --- routes -----------------------------------------------------------------------------------------------------

def template_json(t: EmailTemplate, full: bool = True) -> dict:
    out = {"id": t.id, "name": t.name, "subject": t.subject, "preheader": t.preheader,
           "archived": t.archived_at is not None, "created_by": t.created_by, "created_at": t.created_at,
           "updated_at": t.updated_at, "blocks": len((t.document or {}).get("blocks", []))}
    if full:
        out["document"] = t.document
    return out


def template_or_404(c: Ctx, template_id: uuid.UUID) -> EmailTemplate:
    t = c.db.get(EmailTemplate, template_id)
    if t is None:
        raise HTTPException(404, "Template not found")
    return t


@router.get("/templates")
def list_templates(q: Annotated[str, StringConstraints(max_length=200)] | None = None, archived: bool = False,
                   limit: int = Query(50, ge=1, le=200), cursor: str | None = None, c: Ctx = Depends(read)):
    stmt = select(EmailTemplate).where(EmailTemplate.archived_at.is_not(None) if archived
                                       else EmailTemplate.archived_at.is_(None))
    if q:
        stmt = stmt.where(EmailTemplate.name.icontains(q.strip(), autoescape=True))
    rows, next_cursor = paginate(c.db, stmt, EmailTemplate, limit, cursor, by="updated_at")
    return {"data": [template_json(t, full=False) for (t,) in rows], "next_cursor": next_cursor}


@router.post("/templates", status_code=201)
def create_template(body: NewTemplate, c: Ctx = Depends(write), idem: Idem = Depends(idempotency)):
    """A new template; without a document it starts from a small working example."""
    doc = checked(c, body.document if body.document is not None else STARTER, body.subject, body.preheader)
    t = EmailTemplate(workspace_id=c.workspace.id, name=body.name, subject=body.subject, preheader=body.preheader,
                      document=doc, created_by=c.user_id)
    c.db.add(t)
    c.db.flush()
    c.db.refresh(t, ["created_at", "updated_at"])
    events.emit(c.db, "email_template.created", "email_template", t.id, {"id": t.id, "name": t.name},
                actor=("user", c.user_id))
    return idem.commit(201, template_json(t))


@router.get("/templates/{template_id}")
def get_template(template_id: uuid.UUID, c: Ctx = Depends(read)):
    return template_json(template_or_404(c, template_id))


@router.patch("/templates/{template_id}")
def update_template(template_id: uuid.UUID, body: PatchTemplate, c: Ctx = Depends(write)):
    t = template_or_404(c, template_id)
    subject = t.subject if body.subject is None else body.subject
    preheader = t.preheader if body.preheader is None else body.preheader
    changed = []
    if body.document is not None or body.subject is not None or body.preheader is not None:
        doc = checked(c, t.document if body.document is None else body.document, subject, preheader)
        for key, value in (("document", doc), ("subject", subject), ("preheader", preheader)):
            if getattr(t, key) != value:
                setattr(t, key, value)
                changed.append(key)
    if body.name is not None and body.name != t.name:
        t.name = body.name
        changed.append("name")
    if body.archived is not None and body.archived != (t.archived_at is not None):
        t.archived_at = datetime.now(UTC) if body.archived else None
        changed.append("archived")
    if changed:
        t.updated_at = func.now()
        c.db.flush()
        c.db.refresh(t, ["updated_at"])
        events.emit(c.db, "email_template.updated", "email_template", t.id,
                    {"id": t.id, "name": t.name, "changed": changed}, actor=("user", c.user_id))
    c.db.commit()
    return template_json(t)


@router.post("/templates/{template_id}/duplicate", status_code=201)
def duplicate_template(template_id: uuid.UUID, c: Ctx = Depends(write), idem: Idem = Depends(idempotency)):
    t = template_or_404(c, template_id)
    copy = EmailTemplate(workspace_id=c.workspace.id, name=f"{t.name} (copy)"[:200], subject=t.subject,
                         preheader=t.preheader, document=t.document, created_by=c.user_id)
    c.db.add(copy)
    c.db.flush()
    c.db.refresh(copy, ["created_at", "updated_at"])
    events.emit(c.db, "email_template.created", "email_template", copy.id, {"id": copy.id, "name": copy.name},
                actor=("user", c.user_id))
    return idem.commit(201, template_json(copy))


@router.get("/merge-fields")
def list_merge_fields(c: Ctx = Depends(read)):
    """What `{{...}}` may name: the contact fields the caller can read, the display name and the two system links."""
    fields = [{"key": k, "label": f.label, "type": f.type} for k, f in merge_fields(c).items()]
    return {"data": [{"key": "display_name", "label": "Full name", "type": "text"}, *fields,
                     {"key": "unsubscribe_url", "label": "Unsubscribe link", "type": "url"},
                     {"key": "preferences_url", "label": "Preferences link", "type": "url"}]}


@router.post("/render")
def render_preview(body: RenderBody, c: Ctx = Depends(read)):
    """The HTML and plain text a document renders to, for the builder's preview, with what the lint finds. A
    `contact_id` fills merge fields with that contact's values (if the caller may see the contact)."""
    try:
        doc = document.parse(body.document)
    except document.Invalid as e:
        raise ApiError(422, "validation_failed", "The email is not valid", e.fields) from None
    values: dict[str, str] = {}
    if body.contact_id:
        cat = Catalog(c)
        rec = store.get(cat, cat.need("contact"), body.contact_id)
        values = values_of(merge_fields(c), rec)
    s = settings_of(c.db, c.workspace.id)
    out = document.render(doc, body.subject, body.preheader,
                          document.Recipient(values=values, company=s.company_name, address=s.postal_address))
    try:
        document.check_merge(doc, body.subject, body.preheader, known_keys(c))
        merge_errors = {}
    except document.Invalid as e:
        merge_errors = e.fields
    return {"subject": out.subject, "html": out.html, "text": out.text, "size": len(out.html.encode()),
            "issues": [i._asdict() for i in lint.content(doc, body.subject, out)], "merge_errors": merge_errors}
