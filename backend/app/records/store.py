"""The write path of records (ADR 0002): validate through the field types, derive the display name and identity
columns, save, emit the event in the same transaction. Every read of a single record goes through `get`, which
applies the permission scope; the API, imports, forms and workflows share this module."""
import uuid
from collections import defaultdict

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy import update as update_rows

from .. import events, permissions
from ..api import ApiError
from ..models import OrgMember, WorkspaceMember
from ..security import Ctx
from . import filters, types
from .models import ObjectDef, Record
from .schema import Catalog

NAME_CAP = 300
UNSET = object()


def scope(cat: Catalog, obj: ObjectDef, entity=Record):
    """What the caller may see of `obj`: the permission scope as a SQL condition (ADR 0004 fills the hook)."""
    return filters.compile(cat, obj, permissions.scope_filter(cat.c, obj), entity=entity, root="scope")


def live(cat: Catalog, obj: ObjectDef):
    """The condition every read of live records starts from."""
    return (Record.workspace_id == cat.c.workspace.id, Record.object_id == obj.id, Record.deleted_at.is_(None),
            scope(cat, obj))


def get(cat: Catalog, obj: ObjectDef, record_id: uuid.UUID, *, trashed: bool | None = False,
        lock: bool = False) -> Record:
    """A record of `obj` the caller may see: a live one, a trashed one (`trashed=True`) or either (None). Anything
    else, another workspace's included, is a 404."""
    where = [Record.workspace_id == cat.c.workspace.id, Record.object_id == obj.id, Record.id == record_id,
             scope(cat, obj)]
    if trashed is not None:
        where.append(Record.deleted_at.is_not(None) if trashed else Record.deleted_at.is_(None))
    stmt = select(Record).where(*where)
    rec = cat.db.scalar(stmt.with_for_update() if lock else stmt)
    if rec is None:
        raise HTTPException(404, "Record not found")
    return rec


def find(cat: Catalog, record_id: uuid.UUID, *, trashed: bool | None = False,
         lock: bool = False) -> tuple[Record, ObjectDef]:
    """`get` for a caller that has only the id: the record and its object."""
    object_id = cat.db.scalar(select(Record.object_id).where(Record.id == record_id))
    obj = cat.by_id(object_id) if object_id else None
    if obj is None:
        raise HTTPException(404, "Record not found")
    return get(cat, obj, record_id, trashed=trashed, lock=lock), obj


def member_ids(c: Ctx, ids: set[str]) -> set[str]:
    """Those of `ids` that are people of this workspace: its members, and the admins of its organization."""
    wanted = [uuid.UUID(i) for i in ids]
    members = select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == c.workspace.id,
                                                    WorkspaceMember.user_id.in_(wanted))
    admins = select(OrgMember.user_id).where(OrgMember.org_id == c.workspace.org_id,
                                             OrgMember.role.in_(("owner", "admin")), OrgMember.user_id.in_(wanted))
    return {str(u) for u in c.db.scalars(members.union(admins))}


def check_links(cat: Catalog, fields: dict, changed: dict, owner_id: uuid.UUID | None) -> dict[str, str]:
    """Errors for user and record values that point at nobody: the ids must be people of this workspace and live
    records of the linked object that the caller may see."""
    errors: dict[str, str] = {}
    people: dict[str, list[str]] = defaultdict(list)
    linked: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    for key, value in changed.items():
        if fields[key].type == "user":
            people[value].append(f"values.{key}")
        elif fields[key].type == "record":
            linked[fields[key].options["object"]][value].append(key)
    if owner_id:
        people[str(owner_id)].append("owner_id")
    if people:
        found = member_ids(cat.c, set(people))
        errors |= {where: "is not a member of this workspace" for who, wheres in people.items() if who not in found
                   for where in wheres}
    for object_key, ids in linked.items():
        target = cat.object(object_key)
        found = set() if target is None else {str(i) for i in cat.db.scalars(select(Record.id).where(
            *live(cat, target), Record.id.in_([uuid.UUID(i) for i in ids])))}
        errors |= {f"values.{key}": f"is not a {object_key} record" for who, keys in ids.items() if who not in found
                   for key in keys}
    return errors


def display_name(obj: ObjectDef, fields: dict, values: dict) -> str:
    """The primary fields joined (a contact's first and last name), else the first email, else the first phone."""
    name = " ".join(str(values[k]) for k in obj.primary_fields if values.get(k))
    for kind in ("email", "phone"):
        name = name or next((str(values[f.key]) for f in fields.values() if f.type == kind and values.get(f.key)), "")
    return name[:NAME_CAP]


def rename_all(cat: Catalog, obj: ObjectDef) -> None:
    """Recomputes the display name of every record of an object once its primary fields have changed, by the same
    rule as `display_name` (a record left without any name keeps its old one).
    ponytail: one UPDATE; for millions of records run it as a job in batches, so the transaction stays short."""
    names = func.concat_ws(" ", *[Record.values[k].astext for k in obj.primary_fields])
    name = func.coalesce(func.nullif(names, ""), Record.email_norm, Record.phone_e164, Record.display_name)
    cat.db.execute(update_rows(Record).where(Record.object_id == obj.id).values(display_name=func.left(name, NAME_CAP)))


def identity(fields: dict, values: dict) -> tuple[str | None, str | None]:
    """The lookup keys inbound email, SMS and calls match on: the first email and phone field with a value."""
    first = {kind: next((values[f.key] for f in fields.values() if f.type == kind and values.get(f.key)), None)
             for kind in ("email", "phone")}
    return first["email"], first["phone"]


def prepare(cat: Catalog, obj: ObjectDef, current: dict, patch: dict, owner_id=None, *, creating: bool) -> dict:
    """`current` with `patch` merged in (a null value removes the field), every touched value validated. Raises a 422
    naming each bad field."""
    fields, errors, changed, merged = cat.fields(obj), {}, {}, dict(current)
    for key, raw in patch.items():
        field = fields.get(key)
        if field is None:
            errors[f"values.{key}"] = f"is not a field of {obj.key}"
            continue
        try:
            value = types.validate(field, raw)
        except ValueError as e:
            errors[f"values.{key}"] = f"{field.label} {e}"
            continue
        if value is None:
            merged.pop(key, None)
        else:
            merged[key] = changed[key] = value
    for key, field in fields.items():
        if field.rules.get("required") and key not in merged and (creating or key in patch):
            errors[f"values.{key}"] = f"{field.label} is required"
    if not errors:
        errors = check_links(cat, fields, changed, owner_id)
    if not errors and not display_name(obj, fields, merged):
        needs = [*obj.primary_fields, *(f.key for f in fields.values() if f.type in ("email", "phone"))]
        errors["values"] = f"A {obj.singular.lower()} needs a name: fill in one of {', '.join(needs)}"
    if errors:
        raise ApiError(422, "validation_failed", f"The {obj.singular.lower()} is not valid", errors)
    return merged


def visible_values(cat: Catalog, obj: ObjectDef, rec: Record) -> dict:
    """The values of live fields only (archiving hides a field everywhere and keeps its data), minus what the
    caller may not read."""
    fields = cat.fields(obj)
    return permissions.redact(cat.c, obj, {k: v for k, v in rec.values.items() if k in fields})


def record_json(cat: Catalog, obj: ObjectDef, rec: Record) -> dict:
    return {"id": rec.id, "object": obj.key, "display_name": rec.display_name, "values": visible_values(cat, obj, rec),
            "owner_id": rec.owner_id, "created_by": rec.created_by, "created_at": rec.created_at,
            "updated_at": rec.updated_at, "deleted_at": rec.deleted_at}


def brief(obj: ObjectDef, rec: Record) -> dict:
    return {"id": rec.id, "object": obj.key, "display_name": rec.display_name}


def state(cat: Catalog, obj: ObjectDef, rec: Record) -> dict:
    """The event data of a record: its full new state (live fields only; readers redact for themselves)."""
    fields = cat.fields(obj)
    return {"id": rec.id, "object": obj.key, "display_name": rec.display_name,
            "values": {k: v for k, v in rec.values.items() if k in fields}, "owner_id": rec.owner_id}


def actor(c: Ctx) -> tuple[str, uuid.UUID]:
    return "user", c.user_id


def create(cat: Catalog, obj: ObjectDef, values: dict, owner_id: uuid.UUID | None) -> Record:
    c = cat.c
    permissions.check_write(c, obj, values)
    clean = prepare(cat, obj, {}, values, owner_id, creating=True)
    fields = cat.fields(obj)
    email, phone = identity(fields, clean)
    rec = Record(workspace_id=c.workspace.id, object_id=obj.id, values=clean, owner_id=owner_id, created_by=c.user_id,
                 display_name=display_name(obj, fields, clean), email_norm=email, phone_e164=phone)
    c.db.add(rec)
    c.db.flush()
    events.emit(c.db, "record.created", "record", rec.id, state(cat, obj, rec), actor=actor(c))
    return rec


def update(cat: Catalog, obj: ObjectDef, rec: Record, patch: dict, owner_id=UNSET) -> bool:
    """Applies a partial change to a locked record; returns whether anything changed (no change, no event)."""
    c = cat.c
    permissions.check_write(c, obj, patch)
    new_owner = rec.owner_id if owner_id is UNSET else owner_id
    merged = prepare(cat, obj, rec.values, patch, new_owner if new_owner != rec.owner_id else None, creating=False)
    changes = {k: {"old": rec.values.get(k), "new": merged.get(k)} for k in rec.values.keys() | merged.keys()
               if rec.values.get(k) != merged.get(k)}
    if new_owner != rec.owner_id:
        changes["owner_id"] = {"old": rec.owner_id, "new": new_owner}
    if not changes:
        return False
    fields = cat.fields(obj)
    rec.values, rec.owner_id = merged, new_owner
    rec.display_name = display_name(obj, fields, merged)
    rec.email_norm, rec.phone_e164 = identity(fields, merged)
    rec.updated_at = func.now()
    c.db.flush()
    c.db.refresh(rec, ["updated_at"])
    events.emit(c.db, "record.updated", "record", rec.id, {**state(cat, obj, rec), "changes": changes}, actor=actor(c))
    return True


def trash(cat: Catalog, obj: ObjectDef, rec: Record) -> None:
    rec.deleted_at = func.now()
    cat.db.flush()
    events.emit(cat.db, "record.deleted", "record", rec.id, brief(obj, rec), actor=actor(cat.c))


def restore(cat: Catalog, obj: ObjectDef, rec: Record) -> None:
    rec.deleted_at = None
    cat.db.flush()
    events.emit(cat.db, "record.restored", "record", rec.id, brief(obj, rec), actor=actor(cat.c))
