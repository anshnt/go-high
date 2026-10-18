"""Saved views (ADR 0002, module 08): an object, a filter AST, columns and a sort, kept on the server. A shared view
is visible to the whole workspace, a private one only to its owner (a row level security policy, not a check here).
Open one with `?view=<id>` on the record list, and read its live count with `?counts=true`. Saving views is
`views.write`; changing someone else's shared view is `views.manage`. A view that uses a field the caller's role hides
does not exist for them."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import select
from sqlalchemy.sql import func

from .. import permissions
from ..api import ApiError, Idem, idempotency, paginate
from ..permissions import requires
from ..security import Ctx
from . import query
from .filters import BUILTIN
from .models import ObjectDef, SavedView
from .schema import Catalog, object_keys

router = APIRouter(prefix="/api/v1/views")
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
Columns = Annotated[list[str], Field(max_length=50)]
Sort = Annotated[list[str], Field(max_length=query.MAX_SORTS)]


class NewView(BaseModel):
    object: str
    name: Name
    filter: dict = {}
    columns: Columns = []
    sort: Sort = []
    shared: bool = False


class PatchView(BaseModel):
    name: Name | None = None
    filter: dict | None = None
    columns: Columns | None = None
    sort: Sort | None = None
    shared: bool | None = None


def view_json(v: SavedView, keys: dict[uuid.UUID, str], count: int | None = None) -> dict:
    return {"id": v.id, "object": keys[v.object_id], "name": v.name, "filter": v.filter, "columns": v.columns,
            "sort": v.sort, "shared": v.shared, "owner_id": v.owner_id, "created_at": v.created_at,
            "updated_at": v.updated_at, **({"count": count} if count is not None else {})}


def check(cat: Catalog, obj: ObjectDef, filter_: dict | None, columns: list[str] | None, sort: list[str] | None):
    """A view is saved only if it runs: its filter compiles, its columns and sort name real fields."""
    if filter_:
        query.where_of(cat, obj, filter_)
    known = {*cat.fields(obj), *BUILTIN, "tags"}  # tags: a list shows them as a column (`include=tags`)
    bad = {f"columns.{i}": f"unknown field {k!r}" for i, k in enumerate(columns or []) if k not in known}
    if bad:
        raise ApiError(422, "validation_failed", "The view is not valid", bad)
    if sort:
        query.sort_keys(cat, obj, sort, None)


def paths(ast) -> list[str]:
    """The field keys a filter names, `company.name` style paths included."""
    if isinstance(ast, list):
        return [k for item in ast for k in paths(item)]
    if not isinstance(ast, dict):
        return []
    own = [ast["field"]] if isinstance(ast.get("field"), str) else []
    return own + [k for v in ast.values() if isinstance(v, dict | list) for k in paths(v)]


def uses_hidden(cat: Catalog, v: SavedView) -> bool:
    """Whether the view's filter, columns or sort name a field the caller may not see."""
    if not permissions.restricted(cat.c):
        return False
    obj = cat.by_id(v.object_id)
    if obj is None:
        return False
    for path in [*paths(v.filter), *v.columns, *(s.removeprefix("-") for s in v.sort)]:
        head, dot, rest = path.partition(".")
        target, key = (cat.object(head), rest) if dot else (obj, head)
        if target is not None and key in permissions.hidden(cat.c, target):
            return True
    return False


def view_or_404(c: Ctx, view_id: uuid.UUID) -> SavedView:
    view = c.db.get(SavedView, view_id)  # row level security: this workspace's shared views and my private ones
    if view is None or uses_hidden(Catalog(c), view):
        raise HTTPException(404, "View not found")
    return view


def count_of(cat: Catalog, v: SavedView) -> int | None:
    obj = cat.by_id(v.object_id)
    try:
        return query.total(cat, obj, v.filter) if obj else None
    except ApiError:
        return None  # the filter names something that no longer exists; the view still lists and can be edited


def editable(c: Ctx, v: SavedView) -> SavedView:
    permissions.require(c, "views.write")
    if v.owner_id != c.user_id:
        permissions.require(c, "views.manage")
    return v


@router.get("")
def list_views(object: str | None = None, counts: bool = False, limit: int = Query(50, ge=1, le=200),
               cursor: str | None = None, c: Ctx = Depends(requires("schema.read"))):
    cat = Catalog(c)
    stmt = select(SavedView)
    if object:
        stmt = stmt.where(SavedView.object_id == cat.need(object).id)
    rows, next_cursor = paginate(c.db, stmt, SavedView, limit, cursor)
    keys = object_keys(c)
    # ponytail: views a role cannot use are dropped after the page is cut, so a page can hold fewer than `limit`
    # (the cursor still walks them all); filter in SQL when roles with hidden fields meet many shared views.
    return {"data": [view_json(v, keys, count_of(cat, v) if counts else None) for (v,) in rows
                     if not uses_hidden(cat, v)], "next_cursor": next_cursor}


@router.post("", status_code=201)
def create_view(body: NewView, c: Ctx = Depends(requires("views.write")), idem: Idem = Depends(idempotency)):
    cat = Catalog(c)
    obj = cat.need(body.object)
    check(cat, obj, body.filter, body.columns, body.sort)
    view = SavedView(workspace_id=c.workspace.id, object_id=obj.id, name=body.name, filter=body.filter,
                     columns=body.columns, sort=body.sort, owner_id=c.user_id, shared=body.shared)
    c.db.add(view)
    c.db.flush()
    return idem.commit(201, view_json(view, {obj.id: obj.key}))


@router.get("/{view_id}")
def get_view(view_id: uuid.UUID, c: Ctx = Depends(requires("schema.read"))):
    cat, view = Catalog(c), view_or_404(c, view_id)
    return view_json(view, object_keys(c), count_of(cat, view))


@router.patch("/{view_id}")
def update_view(view_id: uuid.UUID, body: PatchView, c: Ctx = Depends(requires("views.write"))):
    cat, view = Catalog(c), editable(c, view_or_404(c, view_id))
    sent = body.model_dump(exclude_unset=True)
    if nulls := [k for k, v in sent.items() if v is None]:
        raise ApiError(422, "validation_failed", "The request is not valid", {k: "cannot be null" for k in nulls})
    if sent.get("shared") is False and view.owner_id != c.user_id:
        raise HTTPException(403, "Only the owner can make a shared view private")
    check(cat, cat.by_id(view.object_id), sent.get("filter"), sent.get("columns"), sent.get("sort"))
    for name, value in sent.items():
        setattr(view, name, value)
    view.updated_at = func.now()
    c.db.flush()
    c.db.refresh(view, ["updated_at"])
    c.db.commit()
    return view_json(view, object_keys(c))


@router.delete("/{view_id}", status_code=204)
def delete_view(view_id: uuid.UUID, c: Ctx = Depends(requires("views.write"))):
    c.db.delete(editable(c, view_or_404(c, view_id)))
    c.db.commit()
