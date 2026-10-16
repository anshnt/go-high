"""Objects and their fields (ADR 0002). Both are rows, so creating a custom object or a field is an API call and
never a migration; there is no cap on objects. Archiving hides an object or a field everywhere and keeps its data.
Reading is for everyone in the workspace; changing the schema is for workspace admins."""
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from ..api import ApiError, Idem, idempotency, paginate
from ..security import Ctx, in_workspace, workspace_admin
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
                 c: Ctx = Depends(in_workspace)):
    stmt = select(ObjectDef).where(ObjectDef.archived_at.is_not(None) if archived else ObjectDef.archived_at.is_(None))
    rows, next_cursor = paginate(c.db, stmt, ObjectDef, limit, cursor)
    return {"data": [object_json(o) for (o,) in rows], "next_cursor": next_cursor}


@router.post("", status_code=201)
def create_object(body: NewObject, c: Ctx = Depends(workspace_admin), idem: Idem = Depends(idempotency)):
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
    return idem.commit(201, object_json(obj))


@router.get("/{key}")
def get_object(key: str, c: Ctx = Depends(in_workspace)):
    cat = Catalog(c)
    obj = cat.need(key)
    return {**object_json(obj), "fields": [field_json(f) for f in cat.fields(obj).values()]}


@router.patch("/{key}")
def update_object(key: str, body: PatchObject, c: Ctx = Depends(workspace_admin)):
    cat, obj, sent = Catalog(c), object_any(c, key), body.model_dump(exclude_unset=True)
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
    c.db.commit()
    return object_json(obj)


@router.delete("/{key}", status_code=204)
def archive_object(key: str, c: Ctx = Depends(workspace_admin)):
    obj = Catalog(c).need(key)
    if obj.is_system:
        raise ApiError(409, "conflict", "Built-in objects cannot be archived")
    obj.archived_at = func.now()
    c.db.commit()


@router.get("/{key}/fields")
def list_fields(key: str, archived: bool = False, c: Ctx = Depends(in_workspace)):
    """Every field of the object in display order (an object has at most 200)."""
    obj = Catalog(c).need(key)
    stmt = select(FieldDef).where(FieldDef.object_id == obj.id, FieldDef.archived_at.is_not(None) if archived
                                  else FieldDef.archived_at.is_(None)).order_by(FieldDef.position, FieldDef.created_at)
    return {"data": [field_json(f) for f in c.db.scalars(stmt)], "next_cursor": None}


@router.post("/{key}/fields", status_code=201)
def create_field(key: str, body: NewField, c: Ctx = Depends(workspace_admin), idem: Idem = Depends(idempotency)):
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
    return idem.commit(201, field_json(field))


@router.patch("/{key}/fields/{field_key}")
def update_field(key: str, field_key: str, body: PatchField, c: Ctx = Depends(workspace_admin)):
    """Label, options, rules and position change; key and type never do, because records hold values of that type.
    `archived: false` brings an archived field back with its values."""
    cat = Catalog(c)
    obj = cat.need(key)
    field, sent = field_any(c, obj, field_key), body.model_dump(exclude_unset=True)
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
    c.db.commit()
    return field_json(field)


@router.delete("/{key}/fields/{field_key}", status_code=204)
def archive_field(key: str, field_key: str, c: Ctx = Depends(workspace_admin)):
    update_field(key, field_key, PatchField(archived=True), c)  # the same checks as PATCH, and no body back

