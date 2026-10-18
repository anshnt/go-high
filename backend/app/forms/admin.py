"""Forms API for the workspace (`/api/v1/forms`): create, edit, version, publish, duplicate, close and trash. Any member
of the workspace may use it until roles arrive (ADR 0004). Saving the definition is a new, immutable version; a form
shows visitors its published version only, and a response keeps the version it began on."""
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import events
from ..api import ApiError, Idem, idempotency, paginate
from ..records.schema import Catalog
from ..security import Ctx, in_workspace
from .definition import (
    DefinitionError,
    Settings,
    check_mapping,
    public_key,
    slugify,
    starter,
    validate_definition,
)
from .logic import ANSWERABLE
from .models import Form, FormVersion, Submission
from .state import closed_reason

router = APIRouter(prefix="/api/v1/forms")
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Slug = Annotated[str, StringConstraints(pattern=r"^[a-z0-9][a-z0-9-]{0,78}$")]


class NewForm(BaseModel):
    name: Name
    kind: Literal["form", "survey", "quiz"] = "form"
    slug: Slug | None = None
    definition: dict | None = None  # default: a starter for the kind
    settings: Settings | None = None


class PatchForm(BaseModel):
    name: Name | None = None
    slug: Slug | None = None
    settings: Settings | None = None
    status: Literal["draft", "closed"] | None = None  # draft: take it offline; publish brings it back


class SaveVersion(BaseModel):
    definition: dict


class Publish(BaseModel):
    version_id: uuid.UUID | None = None  # default: the newest version


class Duplicate(BaseModel):
    name: Name | None = None


def form_or_404(c: Ctx, form_id: uuid.UUID, *, trashed: bool = False) -> Form:
    form = c.db.get(Form, form_id)  # row level security: this workspace's forms only
    if form is None or (form.deleted_at is not None) != trashed:
        raise HTTPException(404, "Form not found")
    return form


def newest(db: Session, form_id: uuid.UUID) -> FormVersion:
    return db.scalars(select(FormVersion).where(FormVersion.form_id == form_id)
                      .order_by(FormVersion.number.desc()).limit(1)).one()


def version_json(v: FormVersion, form: Form, definition: bool = False) -> dict:
    return {"id": v.id, "number": v.number, "created_at": v.created_at, "created_by": v.created_by,
            "published": form.published_version_id == v.id, **({"definition": v.definition} if definition else {})}


def form_json(db: Session, forms: list[Form]) -> list[dict]:
    """The API shape of each form, with its counts and version numbers read in a few queries for all of them."""
    ids = [f.id for f in forms]
    latest = dict(db.execute(select(FormVersion.form_id, func.max(FormVersion.number))
                             .where(FormVersion.form_id.in_(ids)).group_by(FormVersion.form_id)).all())
    published = dict(db.execute(select(FormVersion.id, FormVersion.number).where(
        FormVersion.id.in_([f.published_version_id for f in forms if f.published_version_id]))).all())
    counts = {fid: (starts, done) for fid, starts, done in db.execute(
        select(Submission.form_id, func.count(), func.count().filter(Submission.status == "complete"))
        .where(Submission.form_id.in_(ids)).group_by(Submission.form_id)).all()}
    out = []
    for f in forms:
        s, (starts, done) = Settings.model_validate(f.settings), counts.get(f.id, (0, 0))
        why = closed_reason(db, f, s, done)
        out.append({
            "id": f.id, "name": f.name, "kind": f.kind, "slug": f.slug, "public_key": f.public_key,
            "status": "closed" if why else f.status, "closed_reason": why, "settings": s.model_dump(mode="json"),
            "published_version_id": f.published_version_id, "published_version": published.get(f.published_version_id),
            "latest_version": latest[f.id], "has_draft_changes": f.status != "draft" and latest[f.id] != published.get(
                f.published_version_id),
            "starts": starts, "responses": done, "completion_rate": round(done / starts, 4) if starts else None,
            "created_by": f.created_by, "created_at": f.created_at, "updated_at": f.updated_at,
            "deleted_at": f.deleted_at})
    return out


def check_definition(cat: Catalog, definition: dict, kind: str, *, mapping: bool = True) -> dict:
    """The normalized definition, or a 422 whose `fields` point into it (`definition.steps.0.fields.1.key`)."""
    try:
        clean = validate_definition(definition, kind)
    except DefinitionError as e:
        raise ApiError(422, "validation_failed", "The form is not valid",
                       {f"definition.{k}": v for k, v in e.fields.items()}) from None
    contact = cat.object("contact")
    errors = check_mapping(clean, cat.fields(contact) if contact else {}) if mapping else {}
    if errors:
        raise ApiError(422, "validation_failed", "The form is not valid", {f"definition.{k}": v
                                                                           for k, v in errors.items()})
    return clean


def free_slug(db: Session, wanted: str, *, exact: bool) -> str:
    """`wanted` if free; otherwise a 409 when the caller chose it, or the next free `wanted-2`, `wanted-3`."""
    taken = set(db.scalars(select(Form.slug).where(Form.slug.like(f"{wanted}%"))))
    if wanted not in taken:
        return wanted
    if exact:
        raise ApiError(409, "conflict", f"The link name {wanted!r} is used by another form")
    return next(f"{wanted}-{n}" for n in range(2, 10**6) if f"{wanted}-{n}" not in taken)


def state(form: Form) -> dict:
    return {"id": form.id, "name": form.name, "kind": form.kind, "slug": form.slug, "status": form.status}


def create(c: Ctx, name: str, kind: str, slug: str | None, definition: dict, settings: Settings) -> Form:
    form = Form(workspace_id=c.workspace.id, public_key=public_key(), kind=kind, name=name, created_by=c.user_id,
                slug=free_slug(c.db, slug or slugify(name), exact=slug is not None),
                settings=settings.model_dump(mode="json"))
    c.db.add(form)
    c.db.flush()
    c.db.add(FormVersion(workspace_id=c.workspace.id, form_id=form.id, number=1, definition=definition,
                         created_by=c.user_id))
    c.db.flush()
    events.emit(c.db, "form.created", "form", form.id, state(form), actor=("user", c.user_id))
    return form


@router.get("")
def list_forms(status: Literal["draft", "published", "closed"] | None = None,
               kind: Literal["form", "survey", "quiz"] | None = None,
               q: Annotated[str | None, Query(max_length=100)] = None, trashed: bool = False,
               limit: int = Query(50, ge=1, le=200), cursor: str | None = None, c: Ctx = Depends(in_workspace)):
    """Most recently changed first. `status` filters by the stored status; each row's `status` also shows `closed` for
    a published form past its close date or response limit."""
    stmt = select(Form).where(Form.deleted_at.is_not(None) if trashed else Form.deleted_at.is_(None))
    if status:
        stmt = stmt.where(Form.status == status)
    if kind:
        stmt = stmt.where(Form.kind == kind)
    if q:
        stmt = stmt.where(Form.name.icontains(q, autoescape=True))
    rows, next_cursor = paginate(c.db, stmt, Form, limit, cursor, by="updated_at")
    return {"data": form_json(c.db, [r[0] for r in rows]) if rows else [], "next_cursor": next_cursor}


@router.post("", status_code=201)
def create_form(body: NewForm, c: Ctx = Depends(in_workspace), idem: Idem = Depends(idempotency)):
    cat = Catalog(c)
    definition = check_definition(cat, body.definition or starter(body.kind), body.kind,
                                  mapping=body.definition is not None)  # the starter names fields every contact has
    try:
        form = create(c, body.name, body.kind, body.slug, definition, body.settings or Settings())
    except IntegrityError:
        raise ApiError(409, "conflict", "A form with this link name was just created") from None
    return idem.commit(201, {**form_json(c.db, [form])[0], "definition": definition})


@router.get("/{form_id}")
def get_form(form_id: uuid.UUID, c: Ctx = Depends(in_workspace)):
    """The form with the definition of its newest version, which is what the builder edits."""
    form = form_or_404(c, form_id)
    return {**form_json(c.db, [form])[0], "definition": newest(c.db, form.id).definition}


@router.patch("/{form_id}")
def update_form(form_id: uuid.UUID, body: PatchForm, c: Ctx = Depends(in_workspace)):
    form = form_or_404(c, form_id)
    sent = body.model_dump(exclude_unset=True, mode="json")
    if nulls := [k for k, v in sent.items() if v is None]:
        raise ApiError(422, "validation_failed", "The request is not valid", {k: "cannot be null" for k in nulls})
    old = {"name": form.name, "slug": form.slug, "settings": form.settings, "status": form.status}
    if "slug" in sent and sent["slug"] != form.slug:
        form.slug = free_slug(c.db, sent["slug"], exact=True)
    if "name" in sent:
        form.name = sent["name"]
    if "settings" in sent:
        form.settings = sent["settings"]
    if (status := sent.get("status")) and status != form.status:
        if status == "closed" and form.status != "published":
            raise ApiError(409, "conflict", "Only a published form can be closed")
        form.status = status
        if status == "draft":
            form.published_version_id = None  # offline; publishing puts a version back
    changes = {k: {"old": old[k], "new": v} for k, v in {"name": form.name, "slug": form.slug,
                                                         "settings": form.settings, "status": form.status}.items()
               if old[k] != v}
    if changes:
        form.updated_at = func.now()
        c.db.flush()
        events.emit(c.db, "form.updated", "form", form.id, {**state(form), "changes": changes},
                    actor=("user", c.user_id))
    c.db.commit()
    return form_json(c.db, [form])[0]


@router.delete("/{form_id}", status_code=204)
def delete_form(form_id: uuid.UUID, c: Ctx = Depends(in_workspace)):
    """Moves the form to the trash: its link stops working, its responses are kept, and it can be restored."""
    form = form_or_404(c, form_id)
    form.deleted_at, form.updated_at = func.now(), func.now()
    c.db.flush()
    events.emit(c.db, "form.deleted", "form", form.id, {"id": form.id, "name": form.name}, actor=("user", c.user_id))
    c.db.commit()


@router.post("/{form_id}/restore")
def restore_form(form_id: uuid.UUID, c: Ctx = Depends(in_workspace), idem: Idem = Depends(idempotency)):
    form = form_or_404(c, form_id, trashed=True)
    form.deleted_at, form.updated_at = None, func.now()
    c.db.flush()
    events.emit(c.db, "form.restored", "form", form.id, {"id": form.id, "name": form.name}, actor=("user", c.user_id))
    return idem.commit(200, form_json(c.db, [form])[0])


@router.post("/{form_id}/duplicate", status_code=201)
def duplicate_form(form_id: uuid.UUID, body: Duplicate | None = None, c: Ctx = Depends(in_workspace),
                   idem: Idem = Depends(idempotency)):
    """A draft copy of the newest version and the settings, with its own link name and public key."""
    form = form_or_404(c, form_id)
    name = (body.name if body and body.name else f"{form.name} (copy)")[:200]
    definition = newest(c.db, form.id).definition
    copy = create(c, name, form.kind, None, definition, Settings.model_validate(form.settings))
    return idem.commit(201, {**form_json(c.db, [copy])[0], "definition": definition})


@router.get("/{form_id}/versions")
def list_versions(form_id: uuid.UUID, limit: int = Query(50, ge=1, le=200), cursor: str | None = None,
                  c: Ctx = Depends(in_workspace)):
    form = form_or_404(c, form_id)
    rows, next_cursor = paginate(c.db, select(FormVersion).where(FormVersion.form_id == form.id), FormVersion, limit,
                                 cursor)
    return {"data": [version_json(v, form) for (v,) in rows], "next_cursor": next_cursor}


@router.get("/{form_id}/versions/{version_id}")
def get_version(form_id: uuid.UUID, version_id: uuid.UUID, c: Ctx = Depends(in_workspace)):
    form = form_or_404(c, form_id)
    version = c.db.scalar(select(FormVersion).where(FormVersion.form_id == form.id, FormVersion.id == version_id))
    if version is None:
        raise HTTPException(404, "Version not found")
    return version_json(version, form, definition=True)


# ponytail: every changed save is a new row, never pruned; drop old versions that were never published and have no
# responses when a form's history gets long.
@router.post("/{form_id}/versions")
def save_version(form_id: uuid.UUID, body: SaveVersion, c: Ctx = Depends(in_workspace)):
    """Saving a draft is a new version; the published one is not touched until `publish`. Saving what the newest
    version already holds changes nothing and returns it. A response keeps the version it began on."""
    form = c.db.scalar(select(Form).where(Form.id == form_id, Form.deleted_at.is_(None)).with_for_update())
    if form is None:
        raise HTTPException(404, "Form not found")
    definition = check_definition(Catalog(c), body.definition, form.kind)
    last = newest(c.db, form.id)
    if last.definition == definition:
        return version_json(last, form, definition=True)
    version = FormVersion(workspace_id=c.workspace.id, form_id=form.id, number=last.number + 1,
                          definition=definition, created_by=c.user_id)
    c.db.add(version)
    form.updated_at = func.now()
    c.db.commit()
    return version_json(version, form, definition=True)


@router.post("/{form_id}/publish")
def publish_form(form_id: uuid.UUID, body: Publish | None = None, c: Ctx = Depends(in_workspace)):
    """Makes a version (the newest, unless `version_id` is given) what visitors see, and opens a closed form again.
    The version is checked once more, because the contact fields it writes to may have changed since it was saved."""
    form = form_or_404(c, form_id)
    version = (c.db.scalar(select(FormVersion).where(FormVersion.form_id == form.id,
                                                     FormVersion.id == body.version_id))
               if body and body.version_id else newest(c.db, form.id))
    if version is None:
        raise HTTPException(404, "Version not found")
    check_definition(Catalog(c), version.definition, form.kind)
    if not any(f["type"] in ANSWERABLE for s in version.definition["steps"] for f in s["fields"]):
        raise ApiError(422, "validation_failed", "The form is not valid", {"definition.steps": "add a question first"})
    if form.published_version_id != version.id or form.status != "published":
        form.published_version_id, form.status, form.updated_at = version.id, "published", func.now()
        c.db.flush()
        events.emit(c.db, "form.published", "form", form.id,
                    {"id": form.id, "name": form.name, "version": version.number, "version_id": version.id},
                    actor=("user", c.user_id))
    c.db.commit()
    return form_json(c.db, [form])[0]
