"""Roles (ADR 0004): a role belongs to the organization, so an agency defines "Account manager" once and uses it in
every client workspace. Seeing roles is `members.read`; creating, changing and deleting them is `roles.manage` and
needs an organization owner or admin, because a change reaches every workspace of the org. The system roles
(roles_seed.py) cannot be deleted, Owner and Admin cannot be changed, and a custom role starts as a copy of another."""
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import AfterValidator, BaseModel, Field, StringConstraints
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from . import events, permissions
from .api import ApiError, Idem, idempotency
from .models import SCOPES, Role, RoleObjectRule
from .permissions import requires
from .records.schema import RESERVED, FieldKey
from .records.types import slug
from .roles_seed import LOCKED
from .security import Ctx

router = APIRouter(prefix="/api/v1/roles")
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Description = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]
RoleKey = Annotated[str, StringConstraints(pattern=r"^[a-z0-9_]{1,40}$")]
Capabilities = Annotated[list[Annotated[str, AfterValidator(permissions.known)]], Field(max_length=100)]


def custom_field(key: str) -> str:
    if key in RESERVED:
        raise ValueError(f"{key!r} is a built-in column of every record and cannot be hidden or locked")
    return key


RuleField = Annotated[FieldKey, AfterValidator(custom_field)]


class ObjectRule(BaseModel):
    object_key: Annotated[str, StringConstraints(pattern=r"^(\*|[a-z][a-z0-9_]{0,39})$")]  # `*`: any other object
    scope: Literal[*SCOPES]
    hidden_fields: Annotated[list[RuleField], Field(max_length=100)] = []
    readonly_fields: Annotated[list[RuleField], Field(max_length=100)] = []


Rules = Annotated[list[ObjectRule], Field(max_length=200)]


class NewRole(BaseModel):
    name: Name
    description: Description = ""
    copy_from: RoleKey  # the key of the role whose capabilities and rules this one starts with


class PatchRole(BaseModel):
    name: Name | None = None
    description: Description | None = None
    capabilities: Capabilities | None = None
    object_rules: Rules | None = None  # replaces every rule of the role


def rule_json(r: RoleObjectRule) -> dict:
    return {"object_key": r.object_key, "scope": r.scope, "hidden_fields": sorted(r.hidden_fields),
            "readonly_fields": sorted(r.readonly_fields)}


def role_json(role: Role, rules: list[RoleObjectRule]) -> dict:
    return {"id": role.id, "key": role.key, "name": role.name, "description": role.description,
            "is_system": role.is_system, "locked": locked(role), "capabilities": sorted(role.capabilities),
            "object_rules": [rule_json(r) for r in sorted(rules, key=lambda r: r.object_key)],
            "created_at": role.created_at}


def locked(role: Role) -> bool:
    return role.is_system and role.key in LOCKED


def rules_of(c: Ctx, role: Role) -> list[RoleObjectRule]:
    return list(c.db.scalars(select(RoleObjectRule).where(RoleObjectRule.role_id == role.id)))


def role_or_404(c: Ctx, role_id: uuid.UUID) -> Role:
    role = c.db.get(Role, role_id)  # row level security: this organization's roles only
    if role is None:
        raise HTTPException(404, "Role not found")
    return role


def state(role: Role, rules: list[RoleObjectRule]) -> dict:
    """What a change to a role is reported against."""
    return {"name": role.name, "description": role.description, "capabilities": sorted(role.capabilities),
            "object_rules": [rule_json(r) for r in sorted(rules, key=lambda r: r.object_key)]}


@router.get("")
def list_roles(c: Ctx = Depends(requires("members.read"))):
    """Every role of the organization: the system roles first.
    ponytail: not paged, an organization has dozens of roles; add the cursor when one has hundreds."""
    roles = c.db.scalars(select(Role).order_by(Role.is_system.desc(), Role.name, Role.id)).all()
    rules: dict[uuid.UUID, list[RoleObjectRule]] = {r.id: [] for r in roles}
    for rule in c.db.scalars(select(RoleObjectRule)):
        rules[rule.role_id].append(rule)
    return {"data": [role_json(r, rules[r.id]) for r in roles], "next_cursor": None}


@router.post("", status_code=201)
def create_role(body: NewRole, c: Ctx = Depends(requires("roles.manage", org=True)), idem: Idem = Depends(idempotency)):
    source = c.db.scalar(select(Role).where(Role.key == body.copy_from))
    if source is None:
        raise ApiError(422, "validation_failed", "The request is not valid",
                       {"copy_from": "is not a role of this organization"})
    role = Role(org_id=c.workspace.org_id, key=slug(body.name), name=body.name, description=body.description,
                capabilities=list(source.capabilities))
    try:
        with c.db.begin_nested():
            c.db.add(role)
    except IntegrityError:
        raise ApiError(409, "conflict", f"A role named {body.name!r} exists", {"name": "is already used"}) from None
    rules = [RoleObjectRule(org_id=role.org_id, role_id=role.id, object_key=r.object_key, scope=r.scope,
                            hidden_fields=list(r.hidden_fields), readonly_fields=list(r.readonly_fields))
             for r in rules_of(c, source)]
    c.db.add_all(rules)
    c.db.flush()
    events.emit(c.db, "role.created", "role", role.id,
                {"id": role.id, "key": role.key, "name": role.name, "description": role.description,
                 "capabilities": sorted(role.capabilities), "copied_from": source.key}, actor=("user", c.user_id))
    return idem.commit(201, role_json(role, rules))


@router.get("/{role_id}")
def get_role(role_id: uuid.UUID, c: Ctx = Depends(requires("members.read"))):
    role = role_or_404(c, role_id)
    return role_json(role, rules_of(c, role))


@router.patch("/{role_id}")
def update_role(role_id: uuid.UUID, body: PatchRole, c: Ctx = Depends(requires("roles.manage", org=True))):
    """The change applies to the next request of everyone who holds the role, in every workspace."""
    role = role_or_404(c, role_id)
    if locked(role):
        raise ApiError(409, "conflict", f"The {role.name} role cannot be changed; copy it to make a custom role")
    sent = body.model_dump(exclude_unset=True)
    if nulls := [k for k, v in sent.items() if v is None]:
        raise ApiError(422, "validation_failed", "The request is not valid", {k: "cannot be null" for k in nulls})
    rules = rules_of(c, role)
    before = state(role, rules)
    for name in ("name", "description"):
        if name in sent:
            setattr(role, name, sent[name])
    if "capabilities" in sent:
        role.capabilities = sorted(set(sent["capabilities"]))
    if "object_rules" in sent:
        keys = [r["object_key"] for r in sent["object_rules"]]
        dupes = {f"object_rules.{i}.object_key": "is listed twice" for i, k in enumerate(keys) if keys.index(k) < i}
        if dupes:
            raise ApiError(422, "validation_failed", "The request is not valid", dupes)
        c.db.execute(delete(RoleObjectRule).where(RoleObjectRule.role_id == role.id))
        rules = [RoleObjectRule(org_id=role.org_id, role_id=role.id, **r) for r in sent["object_rules"]]
        c.db.add_all(rules)
    c.db.flush()
    if changed := events.changes(before, state(role, rules)):
        events.emit(c.db, "role.updated", "role", role.id,
                    {"id": role.id, "key": role.key, "name": role.name, "changes": changed}, actor=("user", c.user_id))
    c.db.commit()
    return role_json(role, rules)


@router.delete("/{role_id}", status_code=204)
def delete_role(role_id: uuid.UUID, c: Ctx = Depends(requires("roles.manage", org=True))):
    role = role_or_404(c, role_id)
    if role.is_system:
        raise ApiError(409, "conflict", "System roles cannot be deleted")
    try:
        with c.db.begin_nested():
            c.db.delete(role)
    except IntegrityError:
        raise ApiError(409, "role_in_use", "Give the people who hold this role another one first") from None
    events.emit(c.db, "role.deleted", "role", role.id, {"id": role.id, "key": role.key, "name": role.name},
                actor=("user", c.user_id))
    c.db.commit()
