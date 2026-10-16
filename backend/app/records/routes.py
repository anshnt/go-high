"""Records API: the same routes for contacts, companies, deals and every custom object
(`/api/v1/objects/{key}/records`), plus the trash. List with `filter` (JSON, ADR 0002), `sort`, `q` (full text,
prefix matching), `include` and `view`; a long filter can be POSTed to `/records/query` instead. Deleting moves a
record to the trash for 30 days."""
import json
import uuid
from datetime import timedelta
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select

from ..api import ApiError, Idem, idempotency, paginate
from ..security import Ctx, in_workspace
from . import query, store
from .models import Record
from .schema import Catalog
from .views import view_or_404

router = APIRouter(prefix="/api/v1")
TRASH_DAYS = 30


class NewRecord(BaseModel):
    values: dict[str, Any] = {}
    owner_id: uuid.UUID | None = None


class PatchRecord(BaseModel):
    values: dict[str, Any] = {}
    owner_id: uuid.UUID | None = None  # send null to unassign


class RecordQuery(BaseModel):
    filter: dict = {}
    sort: str | list[str] | None = None
    q: Annotated[str, Field(max_length=200)] | None = None
    limit: int = Field(50, ge=1, le=200)
    cursor: str | None = None
    include: list[str] = []
    count: bool = False
    view: uuid.UUID | None = None


def parse_filter(raw: str | None) -> dict:
    if not raw:
        return {}
    try:
        ast = json.loads(raw)
    except ValueError:
        ast = None
    if not isinstance(ast, dict):
        raise ApiError(400, "validation_failed", "The filter is not valid", {"filter": "must be a JSON object"})
    return ast


def search(c: Ctx, key: str, body: RecordQuery) -> dict:
    cat = Catalog(c)
    obj = cat.need(key)
    ast, sort = body.filter, body.sort
    if body.view:  # the view's filter and sort, narrowed by the request's own
        view = view_or_404(c, body.view)
        if view.object_id != obj.id:
            raise ApiError(400, "validation_failed", "The view is not valid", {"view": f"is not a view of {obj.key}"})
        ast = {"and": [view.filter, ast]} if view.filter and ast else view.filter or ast
        sort = sort or view.sort
    return query.run(cat, obj, ast=ast, sort=sort, q=body.q, limit=body.limit, cursor=body.cursor,
                     include=body.include, count=body.count)


@router.get("/objects/{key}/records")
def list_records(key: str, filter: Annotated[str | None, Query(max_length=8000)] = None, sort: str | None = None,
                 q: Annotated[str | None, Query(max_length=200)] = None, limit: int = Query(50, ge=1, le=200),
                 cursor: str | None = None, include: str | None = None, count: bool = False,
                 view: uuid.UUID | None = None, c: Ctx = Depends(in_workspace)):
    body = RecordQuery(filter=parse_filter(filter), sort=sort, q=q, limit=limit, cursor=cursor,
                       include=[i for i in (include or "").split(",") if i], count=count, view=view)
    return search(c, key, body)


@router.post("/objects/{key}/records/query")
def query_records(key: str, body: RecordQuery, c: Ctx = Depends(in_workspace)):
    return search(c, key, body)


@router.post("/objects/{key}/records", status_code=201)
def create_record(key: str, body: NewRecord, c: Ctx = Depends(in_workspace), idem: Idem = Depends(idempotency)):
    cat = Catalog(c)
    obj = cat.need(key)
    rec = store.create(cat, obj, body.values, body.owner_id)
    return idem.commit(201, store.record_json(cat, obj, rec))


@router.get("/objects/{key}/records/{record_id}")
def get_record(key: str, record_id: uuid.UUID, include: str | None = None, c: Ctx = Depends(in_workspace)):
    cat = Catalog(c)
    obj = cat.need(key)
    rec = store.get(cat, obj, record_id)
    expand = query.include_names(cat, obj, [i for i in (include or "").split(",") if i])
    return query.decorate(cat, obj, [rec], expand)[0]


@router.patch("/objects/{key}/records/{record_id}")
def update_record(key: str, record_id: uuid.UUID, body: PatchRecord, c: Ctx = Depends(in_workspace)):
    """Sets the values sent and leaves the rest; a null value clears a field. Nothing changed, no event."""
    cat = Catalog(c)
    obj = cat.need(key)
    rec = store.get(cat, obj, record_id, lock=True)
    store.update(cat, obj, rec, body.values, body.owner_id if "owner_id" in body.model_fields_set else store.UNSET)
    c.db.commit()
    return store.record_json(cat, obj, rec)


@router.delete("/objects/{key}/records/{record_id}", status_code=204)
def delete_record(key: str, record_id: uuid.UUID, c: Ctx = Depends(in_workspace)):
    cat = Catalog(c)
    obj = cat.need(key)
    store.trash(cat, obj, store.get(cat, obj, record_id, lock=True))
    c.db.commit()


@router.post("/objects/{key}/records/{record_id}/restore")
def restore_record(key: str, record_id: uuid.UUID, c: Ctx = Depends(in_workspace), idem: Idem = Depends(idempotency)):
    cat = Catalog(c)
    obj = cat.need(key)
    rec = store.get(cat, obj, record_id, trashed=True, lock=True)
    store.restore(cat, obj, rec)
    return idem.commit(200, store.record_json(cat, obj, rec))


# ponytail: nothing purges the trash yet (the job arrives with data rights, module 09); restore therefore works at
# any age, and `restorable_until` is when the purge will start to take it.
@router.get("/trash")
def list_trash(object: str, limit: int = Query(50, ge=1, le=200), cursor: str | None = None,
               c: Ctx = Depends(in_workspace)):
    """Trashed records of one object, most recently deleted first."""
    cat = Catalog(c)
    obj = cat.need(object)
    stmt = select(Record).where(Record.workspace_id == c.workspace.id, Record.object_id == obj.id,
                                Record.deleted_at.is_not(None), store.scope(cat, obj))
    rows, next_cursor = paginate(c.db, stmt, Record, limit, cursor, by="deleted_at")
    return {"data": [{**store.record_json(cat, obj, r), "restorable_until": r.deleted_at + timedelta(days=TRASH_DAYS)}
                     for (r,) in rows], "next_cursor": next_cursor}
