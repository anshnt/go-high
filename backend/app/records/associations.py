"""Associations (ADR 0002): typed links between records of any two objects. A type has a label for each direction
("works at" / "employs"); one row per link serves both. Types are workspace data, so a custom object links to
contacts and deals by adding a type. Creating and removing a link emits an event that shows on both timelines."""
import uuid
from collections import defaultdict
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import and_, case, exists, false, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased

from .. import events
from ..api import ApiError, Idem, idempotency, paginate
from ..security import Ctx, in_workspace, workspace_admin
from . import store, timeline
from .models import Association, AssociationType, ObjectDef, Record
from .schema import Catalog, Label, object_keys

router = APIRouter(prefix="/api/v1")


class NewType(BaseModel):
    from_object: str
    to_object: str
    label: Label
    inverse_label: Label
    cardinality: Literal["one_to_one", "one_to_many", "many_to_many"] = "many_to_many"


class NewLink(BaseModel):
    type_id: uuid.UUID
    other_id: uuid.UUID
    direction: Literal["forward", "inverse"] | None = None  # needed only for a type between an object and itself


def type_json(t: AssociationType, keys: dict[uuid.UUID, str]) -> dict:
    return {"id": t.id, "from_object": keys[t.from_object_id], "to_object": keys[t.to_object_id], "label": t.label,
            "inverse_label": t.inverse_label, "cardinality": t.cardinality, "is_system": t.is_system,
            "created_at": t.created_at}


def link_data(a: Association, t: AssociationType) -> dict:
    return {"id": a.id, "type_id": t.id, "from_record_id": a.from_record_id, "to_record_id": a.to_record_id,
            "label": t.label, "inverse_label": t.inverse_label}


@router.get("/association-types")
def list_types(object: str | None = None, c: Ctx = Depends(in_workspace)):
    """Every type, or those that start or end at one object (`?object=contact`). A workspace has few."""
    stmt = select(AssociationType).order_by(AssociationType.created_at, AssociationType.id)
    if object:
        obj = Catalog(c).need(object)
        stmt = stmt.where(or_(AssociationType.from_object_id == obj.id, AssociationType.to_object_id == obj.id))
    keys = object_keys(c)
    return {"data": [type_json(t, keys) for t in c.db.scalars(stmt)], "next_cursor": None}


@router.post("/association-types", status_code=201)
def create_type(body: NewType, c: Ctx = Depends(workspace_admin), idem: Idem = Depends(idempotency)):
    cat = Catalog(c)
    a, b = cat.need(body.from_object), cat.need(body.to_object)
    t = AssociationType(workspace_id=c.workspace.id, from_object_id=a.id, to_object_id=b.id, label=body.label,
                        inverse_label=body.inverse_label, cardinality=body.cardinality)
    try:
        with c.db.begin_nested():
            c.db.add(t)
    except IntegrityError:
        raise ApiError(409, "conflict", f"{a.key} to {b.key} already has a {body.label!r} association") from None
    return idem.commit(201, type_json(t, {a.id: a.key, b.id: b.key}))


@router.delete("/association-types/{type_id}", status_code=204)
def delete_type(type_id: uuid.UUID, c: Ctx = Depends(workspace_admin)):
    t = c.db.get(AssociationType, type_id)
    if t is None:
        raise HTTPException(404, "Association type not found")
    if t.is_system:
        raise ApiError(409, "conflict", "Built-in association types cannot be deleted")
    if c.db.scalar(select(func.count()).select_from(Association).where(Association.type_id == t.id)):
        raise ApiError(409, "conflict", "Remove the links of this type first")
    c.db.delete(t)
    c.db.commit()


def expand(cat: Catalog, obj: ObjectDef, other: ObjectDef, ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict]]:
    """For `include=`: per record id, the live records of `other` it is linked to, labeled as seen from the record.
    ponytail: not capped; a record with thousands of links should be paged with GET /records/{id}/associations."""
    out: dict[uuid.UUID, list[dict]] = defaultdict(list)
    linked = aliased(Record)
    for mine, theirs, forward in ((Association.from_record_id, Association.to_record_id, True),
                                  (Association.to_record_id, Association.from_record_id, False)):
        types = {t.id: t for t, fwd in cat.links(obj, other) if fwd is forward}
        if not types:
            continue
        stmt = (select(mine, Association, linked).join(linked, linked.id == theirs)
                .where(mine.in_(ids), Association.type_id.in_(types), linked.deleted_at.is_(None),
                       linked.object_id == other.id, store.scope(cat, other, linked))
                .order_by(Association.created_at, Association.id))
        for record_id, link, record in cat.db.execute(stmt):
            t = types[link.type_id]
            out[record_id].append({"id": link.id, "type_id": t.id, "label": t.label if forward else t.inverse_label,
                                   "record": store.brief(other, record)})
    return out


@router.get("/records/{record_id}/associations")
def list_links(record_id: uuid.UUID, limit: int = Query(50, ge=1, le=200), cursor: str | None = None,
               c: Ctx = Depends(in_workspace)):
    """Links in both directions, newest first, each labeled as seen from this record."""
    cat = Catalog(c)
    rec, obj = store.find(cat, record_id)
    types = {t.id: t for t in c.db.scalars(select(AssociationType).where(
        or_(AssociationType.from_object_id == obj.id, AssociationType.to_object_id == obj.id)))}
    linked = aliased(Record)
    others = {o.id: o for o in (cat.by_id(i) for i in ({t.from_object_id for t in types.values()}
                                                       | {t.to_object_id for t in types.values()})) if o}
    other_id = case((Association.from_record_id == rec.id, Association.to_record_id), else_=Association.from_record_id)
    stmt = (select(Association).join(linked, linked.id == other_id)
            .where(or_(Association.from_record_id == rec.id, Association.to_record_id == rec.id),
                   Association.type_id.in_(types), linked.deleted_at.is_(None),
                   or_(false(), *[and_(linked.object_id == o.id, store.scope(cat, o, linked))
                                  for o in others.values()])))
    rows, next_cursor = paginate(c.db, stmt, Association, limit, cursor)
    links = [r[0] for r in rows]
    records = {r.id: r for r in c.db.scalars(select(Record).where(Record.id.in_(
        [lk.to_record_id if lk.from_record_id == rec.id else lk.from_record_id for lk in links])))}
    data = []
    for lk in links:
        forward = lk.from_record_id == rec.id
        other = records[lk.to_record_id if forward else lk.from_record_id]
        t = types[lk.type_id]
        data.append({"id": lk.id, "type_id": t.id, "label": t.label if forward else t.inverse_label,
                     "direction": "forward" if forward else "inverse", "created_at": lk.created_at,
                     "record": store.brief(others[other.object_id], other)})
    return {"data": data, "next_cursor": next_cursor}


def crowded(c: Ctx, t: AssociationType, a: Record, b: Record) -> bool:
    """Whether a link from `a` to `b` would break the type's cardinality: one to one means neither record has a link
    of this type on its side yet, one to many means the `to` record has none.
    ponytail: checked, not locked, so two requests at once can both pass; a unique index per type fixes that."""
    if t.cardinality == "many_to_many":
        return False
    clash = Association.to_record_id == b.id
    if t.cardinality == "one_to_one":
        clash = or_(Association.from_record_id == a.id, clash)
    return c.db.scalar(select(exists().where(Association.type_id == t.id, clash)))


@router.post("/records/{record_id}/associations", status_code=201)
def create_link(record_id: uuid.UUID, body: NewLink, c: Ctx = Depends(in_workspace), idem: Idem = Depends(idempotency)):
    cat = Catalog(c)
    rec, obj = store.find(cat, record_id)
    other, other_obj = store.find(cat, body.other_id)
    t = c.db.get(AssociationType, body.type_id)
    if t is None:
        raise HTTPException(404, "Association type not found")
    forward = (obj.id, other_obj.id) == (t.from_object_id, t.to_object_id)
    backward = (other_obj.id, obj.id) == (t.from_object_id, t.to_object_id)
    if not (forward or backward):
        raise ApiError(422, "validation_failed", "The link is not valid",
                       {"type_id": f"links {cat.by_id(t.from_object_id).key} to {cat.by_id(t.to_object_id).key}, "
                                   f"not {obj.key} and {other_obj.key}"})
    if forward and backward:  # a type between an object and itself: the caller says which end this record is
        forward = body.direction != "inverse"
    a, b = (rec, other) if forward else (other, rec)
    if a.id == b.id:
        raise ApiError(422, "validation_failed", "The link is not valid", {"other_id": "cannot be the record itself"})
    if crowded(c, t, a, b):
        raise ApiError(409, "cardinality_violated", f"This {t.cardinality.replace('_', ' ')} association is taken")
    link = Association(workspace_id=c.workspace.id, type_id=t.id, from_record_id=a.id, to_record_id=b.id)
    try:
        with c.db.begin_nested():
            c.db.add(link)
    except IntegrityError:
        raise ApiError(409, "already_associated", "These records are already linked this way") from None
    timeline.link(c.db, events.emit(c.db, "association.created", "association", link.id, link_data(link, t),
                                    actor=store.actor(c)), [a.id, b.id])
    return idem.commit(201, {**link_data(link, t), "created_at": link.created_at})


@router.delete("/associations/{association_id}", status_code=204)
def delete_link(association_id: uuid.UUID, c: Ctx = Depends(in_workspace)):
    cat = Catalog(c)
    link = c.db.get(Association, association_id)  # row level security: this workspace's links only
    if link is None:
        raise HTTPException(404, "Association not found")
    for end in (link.from_record_id, link.to_record_id):
        store.find(cat, end, trashed=None)  # the caller must be allowed to see both ends
    t = c.db.get(AssociationType, link.type_id)
    timeline.link(c.db, events.emit(c.db, "association.deleted", "association", link.id, link_data(link, t),
                                    actor=store.actor(c)), [link.from_record_id, link.to_record_id])
    c.db.delete(link)
    c.db.commit()
