"""Tags (ADR 0002): named labels with a group, color and description, applied to records of any object. They have
their own tables, so usage counts, rename and merge across thousands of records stay one statement. Creating and
applying tags is the `tags.write` capability; renaming, merging and deleting change what everyone sees, so those are
`tags.manage`. A tag's usage counts the records the caller may see."""
import uuid
from collections import defaultdict
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import delete, func, literal, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import events
from ..api import ApiError, Idem, idempotency, paginate
from ..permissions import requires
from ..security import Ctx
from . import store
from .models import Record, RecordTag, Tag
from .schema import Catalog

router = APIRouter(prefix="/api/v1")
MAX_BULK = 1000
MAX_TAGS_PER_CALL = 10  # each (record, tag) change is an event
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Short = Annotated[str, StringConstraints(strip_whitespace=True, max_length=100)]


class NewTag(BaseModel):
    name: Name
    color: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None
    group: Short | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class PatchTag(BaseModel):
    name: Name | None = None
    color: Annotated[str, StringConstraints(strip_whitespace=True, max_length=20)] | None = None
    group: Short | None = None
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] | None = None


class Merge(BaseModel):
    into: uuid.UUID
    preview: bool = False


class Tagging(BaseModel):
    add: list[uuid.UUID] = Field(default=[], max_length=MAX_TAGS_PER_CALL)
    remove: list[uuid.UUID] = Field(default=[], max_length=MAX_TAGS_PER_CALL)


class BulkTagging(Tagging):
    record_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_BULK)


def tag_json(t: Tag, count: int | None = None) -> dict:
    return {"id": t.id, "name": t.name, "color": t.color, "group": t.group_name, "description": t.description,
            "created_at": t.created_at, **({"count": count} if count is not None else {})}


def tag_data(t: Tag) -> dict:
    return {k: v for k, v in tag_json(t).items() if k != "created_at"}


def tag_or_404(c: Ctx, tag_id: uuid.UUID) -> Tag:
    tag = c.db.get(Tag, tag_id)  # row level security: this workspace's tags only
    if tag is None:
        raise HTTPException(404, "Tag not found")
    return tag


def exists_error(name: str) -> ApiError:
    return ApiError(409, "tag_exists", f"A tag named {name!r} already exists", {"name": "is already used"})


def of(db: Session, record_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
    """The tags of each record, for `include=tags`."""
    out: dict[uuid.UUID, list[dict]] = defaultdict(list)
    for record_id, tag in db.execute(select(RecordTag.record_id, Tag).join(Tag, Tag.id == RecordTag.tag_id)
                                     .where(RecordTag.record_id.in_(record_ids)).order_by(func.lower(Tag.name))):
        out[record_id].append({"id": tag.id, "name": tag.name, "color": tag.color})
    return out


def usage(c: Ctx, tag_id: uuid.UUID) -> int:
    """How many live records with the tag the caller may see."""
    return c.db.scalar(select(func.count()).select_from(RecordTag).join(Record, Record.id == RecordTag.record_id)
                       .where(RecordTag.tag_id == tag_id, Record.deleted_at.is_(None), store.anywhere(Catalog(c))))


@router.get("/tags")
def list_tags(q: Annotated[str | None, Query(max_length=100)] = None, limit: int = Query(50, ge=1, le=200),
              cursor: str | None = None, c: Ctx = Depends(requires("schema.read"))):
    counts = (select(RecordTag.tag_id, func.count().label("n")).join(Record, Record.id == RecordTag.record_id)
              .where(Record.deleted_at.is_(None), store.anywhere(Catalog(c))).group_by(RecordTag.tag_id).subquery())
    stmt = select(Tag, func.coalesce(counts.c.n, 0)).outerjoin(counts, counts.c.tag_id == Tag.id)
    if q:
        stmt = stmt.where(func.lower(Tag.name).like(q.strip().lower().replace("%", r"\%").replace("_", r"\_") + "%",
                                                    escape="\\"))
    rows, next_cursor = paginate(c.db, stmt, Tag, limit, cursor)
    return {"data": [tag_json(tag, n) for tag, n in rows], "next_cursor": next_cursor}


@router.post("/tags", status_code=201)
def create_tag(body: NewTag, c: Ctx = Depends(requires("tags.write")), idem: Idem = Depends(idempotency)):
    tag = Tag(workspace_id=c.workspace.id, name=body.name, color=body.color, group_name=body.group,
              description=body.description)
    try:
        with c.db.begin_nested():
            c.db.add(tag)
    except IntegrityError:
        raise exists_error(body.name) from None
    events.emit(c.db, "tag.created", "tag", tag.id, tag_data(tag), actor=store.actor(c))
    return idem.commit(201, tag_json(tag, 0))


@router.patch("/tags/{tag_id}")
def update_tag(tag_id: uuid.UUID, body: PatchTag, c: Ctx = Depends(requires("tags.manage"))):
    tag = tag_or_404(c, tag_id)
    sent = body.model_dump(exclude_unset=True)
    if "name" in sent and sent["name"] is None:
        raise ApiError(422, "validation_failed", "The request is not valid", {"name": "cannot be empty"})
    before = tag_data(tag)
    try:
        with c.db.begin_nested():  # the changes flush when the savepoint is released, so a clash rolls back to it
            for name, value in sent.items():
                setattr(tag, "group_name" if name == "group" else name, value)
    except IntegrityError:
        raise exists_error(sent.get("name") or "") from None
    changes = {k: {"old": before[k], "new": v} for k, v in tag_data(tag).items() if before[k] != v}
    if changes:
        events.emit(c.db, "tag.updated", "tag", tag.id, {**tag_data(tag), "changes": changes}, actor=store.actor(c))
    c.db.commit()
    return tag_json(tag, usage(c, tag.id))


@router.delete("/tags/{tag_id}", status_code=204)
def delete_tag(tag_id: uuid.UUID, c: Ctx = Depends(requires("tags.manage"))):
    tag = tag_or_404(c, tag_id)
    events.emit(c.db, "tag.deleted", "tag", tag.id, {**tag_data(tag), "records": usage(c, tag.id)},
                actor=store.actor(c))
    c.db.delete(tag)  # its links go with it (foreign key cascade)
    c.db.commit()


@router.post("/tags/{tag_id}/merge")
def merge_tag(tag_id: uuid.UUID, body: Merge, c: Ctx = Depends(requires("tags.manage")),
              idem: Idem = Depends(idempotency)):
    """Moves every record of this tag to another and deletes this one. `preview: true` only counts: how many live
    records have the tag, and how many of them do not have the other tag yet.
    ponytail: saved views that name the merged tag by name or id match nothing afterwards; edit them."""
    source, target = tag_or_404(c, tag_id), tag_or_404(c, body.into)
    if source.id == target.id:
        raise ApiError(422, "validation_failed", "The request is not valid", {"into": "must be another tag"})
    mine = select(Record.id).join(RecordTag, RecordTag.record_id == Record.id).where(
        RecordTag.tag_id == source.id, Record.deleted_at.is_(None))
    has_target = select(RecordTag.record_id).where(RecordTag.tag_id == target.id)
    records = c.db.scalar(select(func.count()).select_from(mine.subquery()))
    gaining = c.db.scalar(select(func.count()).select_from(mine.where(Record.id.not_in(has_target)).subquery()))
    result = {"source": tag_json(source), "into": tag_json(target), "records": records, "gaining": gaining}
    if body.preview:
        return idem.commit(200, {**result, "preview": True})
    c.db.execute(pg_insert(RecordTag).from_select(
        ["record_id", "tag_id", "workspace_id"],
        select(RecordTag.record_id, literal(target.id), RecordTag.workspace_id).where(RecordTag.tag_id == source.id))
        .on_conflict_do_nothing())
    events.emit(c.db, "tag.merged", "tag", target.id,
                {"source_id": source.id, "source_name": source.name, "id": target.id, "name": target.name,
                 "records": records}, actor=store.actor(c))
    c.db.delete(source)
    return idem.commit(200, {**result, "preview": False})


def apply(cat: Catalog, record_ids: list[uuid.UUID], add: list[uuid.UUID], remove: list[uuid.UUID]) -> dict:
    """Adds and removes tags on records the caller may see; an event per record and tag that really changed."""
    c, ids, wanted = cat.c, list(dict.fromkeys(record_ids)), set(add) | set(remove)
    found = set(c.db.scalars(select(Tag.id).where(Tag.id.in_(wanted)))) if wanted else set()
    if found != wanted:
        raise HTTPException(404, "Tag not found")
    if set(add) & set(remove):
        raise ApiError(422, "validation_failed", "The request is not valid", {"remove": "cannot also be in add"})
    by_object: dict[uuid.UUID, list[uuid.UUID]] = defaultdict(list)
    for record_id, object_id in c.db.execute(select(Record.id, Record.object_id).where(
            Record.id.in_(ids), Record.workspace_id == c.workspace.id, Record.deleted_at.is_(None))):
        by_object[object_id].append(record_id)
    visible = {}  # record id -> its object, for the records of live objects that the caller may see
    for object_id, rids in by_object.items():
        if obj := cat.by_id(object_id):
            allowed = c.db.scalars(select(Record.id).where(*store.live(cat, obj), Record.id.in_(rids)))
            visible |= {r: obj for r in allowed}
    if len(visible) != len(ids):
        raise HTTPException(404, "Record not found")
    tags = {t.id: t for t in c.db.scalars(select(Tag).where(Tag.id.in_(wanted)))} if wanted else {}
    added = c.db.execute(pg_insert(RecordTag).values(
        [{"record_id": r, "tag_id": t, "workspace_id": c.workspace.id} for r in ids for t in add])
        .on_conflict_do_nothing().returning(RecordTag.record_id, RecordTag.tag_id)).all() if add else []
    removed = c.db.execute(delete(RecordTag).where(RecordTag.record_id.in_(ids), RecordTag.tag_id.in_(remove))
                           .returning(RecordTag.record_id, RecordTag.tag_id)).all() if remove else []

    def change(rows):
        return [(r, {"record_id": r, "object": visible[r].key, "tag_id": t, "name": tags[t].name}) for r, t in rows]

    events.emit_many(c.db, "tag.added", "record", change(added), actor=store.actor(c))
    events.emit_many(c.db, "tag.removed", "record", change(removed), actor=store.actor(c))
    return {"added": len(added), "removed": len(removed)}


@router.post("/records/{record_id}/tags")
def tag_record(record_id: uuid.UUID, body: Tagging, c: Ctx = Depends(requires("tags.write")),
               idem: Idem = Depends(idempotency)):
    return idem.commit(200, apply(Catalog(c), [record_id], body.add, body.remove))


@router.post("/records/tags")
def tag_records(body: BulkTagging, c: Ctx = Depends(requires("tags.write")), idem: Idem = Depends(idempotency)):
    """Adds and removes tags on up to 1000 records in one transaction."""
    return idem.commit(200, apply(Catalog(c), body.record_ids, body.add, body.remove))
