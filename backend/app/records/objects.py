"""Objects and their fields (ADR 0002). Both are rows, so creating a custom object or a field is an API call and
never a migration; there is no cap on objects. Archiving hides an object or a field everywhere and keeps its data.
Reading is the `schema.read` capability, changing objects `objects.manage` and fields `fields.manage`; every
change is an event. A field the caller's role hides is not listed."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .. import events, permissions
from ..api import ApiError, Idem, idempotency, paginate
from ..permissions import requires
from ..security import Ctx
from . import store, types
from .models import FieldDef, ObjectDef
from .schema import MAX_FIELDS, RESERVED, Catalog, FieldKey, Key, Label

router = APIRouter(prefix="/api/v1/objects")
FieldType = Literal[*types.TYPES]
Icon = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_-]{1,50}$")]
NAME_FIELDS = ("text", "long_text", "email", "phone", "url")  # what can name a record
RESERVED_OBJECTS = {"tags"}  # `include=tags` would be ambiguous


class NewObject(BaseModel):
    key: Key
    singular: Label
    plural: Label
    icon: Icon = "box"


class PatchObject(BaseModel):
    singular: Label | None = None
    plural: Label | None = None
    icon: Icon | None = None
    primary_fields: Annotated[list[FieldKey], Field(min_length=1, max_length=3)] | None = None
    archived: bool | None = None


class NewField(BaseModel):
    key: FieldKey
    label: Label
    type: FieldType
    options: dict = {}
    rules: dict = {}
    position: int | None = Field(default=None, ge=0, le=10000)


class PatchField(BaseModel):
    label: Label | None = None
    options: dict | None = None
    rules: dict | None = None
    position: int | None = Field(default=None, ge=0, le=10000)
    archived: bool | None = None


def object_json(o: ObjectDef) -> dict:
    return {"id": o.id, "key": o.key, "singular": o.singular, "plural": o.plural, "icon": o.icon,
            "is_system": o.is_system, "primary_fields": o.primary_fields, "archived_at": o.archived_at,
            "created_at": o.created_at}


def object_state(o: ObjectDef) -> dict:
    return {"singular": o.singular, "plural": o.plural, "icon": o.icon, "primary_fields": list(o.primary_fields)}


def object_data(o: ObjectDef) -> dict:
    return {"id": o.id, "key": o.key, **object_state(o)}


def field_data(obj: ObjectDef, f: FieldDef) -> dict:
    return {"id": f.id, "object": obj.key, "key": f.key}


def field_state(f: FieldDef) -> dict:
    return {"label": f.label, "options": f.options, "rules": f.rules, "position": f.position}


def field_json(f: FieldDef) -> dict:
    return {"id": f.id, "key": f.key, "label": f.label, "type": f.type, "options": f.options, "rules": f.rules,
            "is_system": f.is_system, "position": f.position, "archived_at": f.archived_at, "created_at": f.created_at}


def object_any(c: Ctx, key: str) -> ObjectDef:
    obj = c.db.scalar(select(ObjectDef).where(ObjectDef.key == key))  # archived ones too, to bring them back
    if obj is None:
        raise HTTPException(404, "Object not found")
    return obj


def field_any(c: Ctx, obj: ObjectDef, key: str) -> FieldDef:
    field = c.db.scalar(select(FieldDef).where(FieldDef.object_id == obj.id, FieldDef.key == key))
    if field is None:
        raise HTTPException(404, "Field not found")
    return field


def invalid(**fields: str) -> ApiError:
    return ApiError(422, "validation_failed", "The request is not valid", fields)


def settings(cat: Catalog, type_: str, options: dict, rules: dict) -> tuple[dict, dict]:
    """A field's options and rules, checked for its type; a record link must name an object that exists."""
    try:
        options = types.check_options(type_, options)
    except ValueError as e:
        raise invalid(options=str(e)) from None
    try:
        rules = types.check_rules(type_, rules)
    except ValueError as e:
        raise invalid(rules=str(e)) from None
    if type_ == "record" and cat.object(options["object"]) is None:
        raise invalid(options=f"there is no object {options['object']!r}")
    return options, rules


@router.get("")
def list_objects(archived: bool = False, limit: int = Query(50, ge=1, le=200), cursor: str | None = None,
                 c: Ctx = Depends(requires("schema.read"))):
    stmt = select(ObjectDef).where(ObjectDef.archived_at.is_not(None) if archived else ObjectDef.archived_at.is_(None))
    rows, next_cursor = paginate(c.db, stmt, ObjectDef, limit, cursor)
    return {"data": [object_json(o) for (o,) in rows], "next_cursor": next_cursor}


@router.post("", status_code=201)
def create_object(body: NewObject, c: Ctx = Depends(requires("objects.manage")), idem: Idem = Depends(idempotency)):
    """A new object starts with one required text field, `name`, that names its records."""
    if body.key in RESERVED_OBJECTS:
        raise invalid(key=f"{body.key!r} is reserved")
    obj = ObjectDef(workspace_id=c.workspace.id, key=body.key, singular=body.singular, plural=body.plural,
                    icon=body.icon, primary_fields=["name"])
    try:
        with c.db.begin_nested():
            c.db.add(obj)
    except IntegrityError:
        raise ApiError(409, "conflict", f"An object with the key {body.key!r} exists (it may be archived)") from None
    c.db.add(FieldDef(workspace_id=c.workspace.id, object_id=obj.id, key="name", label="Name", type="text",
                      rules={"required": True}, options={}))
    c.db.flush()
    events.emit(c.db, "object.created", "object", obj.id, object_data(obj), actor=("user", c.user_id))
    return idem.commit(201, object_json(obj))


@router.get("/{key}")
def get_object(key: str, c: Ctx = Depends(requires("schema.read"))):
    cat = Catalog(c)
    obj = cat.need(key)
    hide = permissions.hidden(c, obj)
    return {**object_json(obj), "fields": [field_json(f) for f in cat.fields(obj).values() if f.key not in hide]}


@router.patch("/{key}")
def update_object(key: str, body: PatchObject, c: Ctx = Depends(requires("objects.manage"))):
    cat, obj, sent = Catalog(c), object_any(c, key), body.model_dump(exclude_unset=True)
    before, was_archived = object_state(obj), obj.archived_at is not None
    if nulls := [k for k, v in sent.items() if v is None]:
        raise invalid(**{k: "cannot be null" for k in nulls})
    if obj.archived_at is not None and sent.get("archived") is not False:
        raise HTTPException(404, "Object not found")
    if "archived" in sent:
        if sent.pop("archived"):
            if obj.is_system:
                raise ApiError(409, "conflict", "Built-in objects cannot be archived")
            obj.archived_at = func.now()
        else:
            obj.archived_at = None
    if "primary_fields" in sent:
        fields = cat.fields(obj)
        bad = [k for k in sent["primary_fields"] if k not in fields or fields[k].type not in NAME_FIELDS]
        if bad:
            raise invalid(primary_fields=f"{bad[0]!r} is not a live text, email, phone or url field of {obj.key}")
    renamed = "primary_fields" in sent and sent["primary_fields"] != obj.primary_fields
    for name, value in sent.items():
        setattr(obj, name, value)
    c.db.flush()
    if renamed:
        store.rename_all(cat, obj)
    c.db.refresh(obj, ["archived_at"])
    audit_object(c, obj, before, was_archived)
    c.db.commit()
    return object_json(obj)


def audit_object(c: Ctx, obj: ObjectDef, before: dict, was_archived: bool) -> None:
    """The events of a change to an object: what changed, and whether it was archived or brought back."""
    actor = ("user", c.user_id)
    if changed := events.changes(before, object_state(obj)):
        events.emit(c.db, "object.updated", "object", obj.id, {"id": obj.id, "key": obj.key, "changes": changed},
                    actor=actor)
    if obj.archived_at is not None and not was_archived:
        events.emit(c.db, "object.archived", "object", obj.id, {"id": obj.id, "key": obj.key}, actor=actor)
    elif obj.archived_at is None and was_archived:
        events.emit(c.db, "object.restored", "object", obj.id, {"id": obj.id, "key": obj.key}, actor=actor)


@router.delete("/{key}", status_code=204)
def archive_object(key: str, c: Ctx = Depends(requires("objects.manage"))):
    obj = Catalog(c).need(key)
    if obj.is_system:
        raise ApiError(409, "conflict", "Built-in objects cannot be archived")
    obj.archived_at = func.now()
    c.db.flush()
    c.db.refresh(obj, ["archived_at"])
    audit_object(c, obj, object_state(obj), False)
    c.db.commit()


@router.get("/{key}/fields")
def list_fields(key: str, archived: bool = False, c: Ctx = Depends(requires("schema.read"))):
    """Every field of the object in display order (an object has at most 200)."""
    obj = Catalog(c).need(key)
    hide = permissions.hidden(c, obj)
    stmt = select(FieldDef).where(FieldDef.object_id == obj.id, FieldDef.archived_at.is_not(None) if archived
                                  else FieldDef.archived_at.is_(None)).order_by(FieldDef.position, FieldDef.created_at)
    return {"data": [field_json(f) for f in c.db.scalars(stmt) if f.key not in hide], "next_cursor": None}


@router.post("/{key}/fields", status_code=201)
def create_field(key: str, body: NewField, c: Ctx = Depends(requires("fields.manage")),
                 idem: Idem = Depends(idempotency)):
    cat = Catalog(c)
    obj = cat.need(key)
    if body.key in RESERVED:
        raise invalid(key=f"{body.key!r} is reserved")
    options, rules = settings(cat, body.type, body.options, body.rules)
    count, last = c.db.execute(select(func.count(), func.max(FieldDef.position))
                               .where(FieldDef.object_id == obj.id)).one()
    if count >= MAX_FIELDS:
        raise ApiError(409, "conflict", f"An object has at most {MAX_FIELDS} fields")
    field = FieldDef(workspace_id=c.workspace.id, object_id=obj.id, key=body.key, label=body.label, type=body.type,
                     options=options, rules=rules,
                     position=body.position if body.position is not None else (last or 0) + 1)
    try:
        with c.db.begin_nested():
            c.db.add(field)
    except IntegrityError:
        raise ApiError(409, "conflict", f"{obj.key} already has a field {body.key!r} (it may be archived)") from None
    events.emit(c.db, "field.created", "field", field.id,
                {**field_data(obj, field), "label": field.label, "type": field.type, "options": field.options,
                 "rules": field.rules, "position": field.position}, actor=("user", c.user_id))
    return idem.commit(201, field_json(field))


class Reorder(BaseModel):
    keys: Annotated[list[FieldKey], Field(min_length=1, max_length=MAX_FIELDS)]


@router.post("/{key}/fields/reorder")
def reorder_fields(key: str, body: Reorder, c: Ctx = Depends(requires("fields.manage"))):
    """Puts the live fields in the order of `keys`, which names each of them once (the fields the caller's role hides
    keep their places). One `field.updated` per field that moved; answers the fields in their new order."""
    cat = Catalog(c)
    obj = cat.need(key)
    hide = permissions.hidden(c, obj)
    shown = [f for f in cat.fields(obj).values() if f.key not in hide]
    if len(set(body.keys)) != len(body.keys) or set(body.keys) != {f.key for f in shown}:
        raise invalid(keys=f"must name every live field of {obj.key} once")
    by_key = {f.key: f for f in shown}
    slots, at = [], -1
    for p in sorted(f.position for f in shown):  # the places these fields hold now, made distinct
        at = max(p, at + 1)
        slots.append(at)
    moved = []
    for k, slot in zip(body.keys, slots, strict=True):
        field = by_key[k]
        if field.position != slot:
            moved.append((field, field.position))
            field.position = slot
    c.db.flush()
    for field, old in moved:
        events.emit(c.db, "field.updated", "field", field.id,
                    {**field_data(obj, field), "changes": {"position": {"old": old, "new": field.position}}},
                    actor=("user", c.user_id))
    c.db.commit()
    return {"data": [field_json(by_key[k]) for k in body.keys], "next_cursor": None}


@router.patch("/{key}/fields/{field_key}")
def update_field(key: str, field_key: str, body: PatchField, c: Ctx = Depends(requires("fields.manage"))):
    """Label, options, rules and position change; key and type never do, because records hold values of that type.
    `archived: false` brings an archived field back with its values."""
    cat = Catalog(c)
    obj = cat.need(key)
    field, sent = field_any(c, obj, field_key), body.model_dump(exclude_unset=True)
    before, was_archived = field_state(field), field.archived_at is not None
    if nulls := [k for k, v in sent.items() if v is None]:
        raise invalid(**{k: "cannot be null" for k in nulls})
    if "options" in sent or "rules" in sent:
        sent["options"], sent["rules"] = settings(cat, field.type, sent.get("options", field.options),
                                                  sent.get("rules", field.rules))
    if "archived" in sent:
        if sent.pop("archived"):
            if field.is_system or field.key in obj.primary_fields:
                raise ApiError(409, "conflict", "Built-in fields and the fields that name a record cannot be archived")
            field.archived_at = func.now()
        else:
            field.archived_at = None
    for name, value in sent.items():
        setattr(field, name, value)
    c.db.flush()
    c.db.refresh(field, ["archived_at"])
    actor, data = ("user", c.user_id), field_data(obj, field)
    if changed := events.changes(before, field_state(field)):
        events.emit(c.db, "field.updated", "field", field.id, {**data, "changes": changed}, actor=actor)
    if field.archived_at is not None and not was_archived:
        events.emit(c.db, "field.archived", "field", field.id, data, actor=actor)
    elif field.archived_at is None and was_archived:
        events.emit(c.db, "field.restored", "field", field.id, data, actor=actor)
    c.db.commit()
    return field_json(field)


@router.delete("/{key}/fields/{field_key}", status_code=204)
def archive_field(key: str, field_key: str, c: Ctx = Depends(requires("fields.manage"))):
    update_field(key, field_key, PatchField(archived=True), c)  # the same checks as PATCH, and no body back

