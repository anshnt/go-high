"""Roles, capabilities and record permissions (ADR 0004). The one place that answers what a user may do in a workspace:
which actions (`require`), which records (`scope_filter`), which fields (`hidden`, `redact`, `check_write`). The record
engine calls the hooks at the bottom on every list, read, write, association expansion and count, so the API,
workflows and AI tools cannot disagree. What a request works out is kept in `ctx.cache` and lives as long as the
request, so a change to a role, a membership or a team applies on the next one."""
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from .api import ApiError
from .models import Role, RoleObjectRule, Team, TeamMember
from .records.models import FieldDef
from .security import Ctx, in_workspace

# Objects of one kind share the capabilities of their family; every custom object is in `records`.
FAMILIES = {"contact": "contacts", "company": "companies", "deal": "deals"}
CUSTOM = "records"
ACTIONS = {"read": "See", "write": "Create and edit", "delete": "Delete and restore", "export": "Export"}
KINDS = {"contacts": "contacts", "companies": "companies", "deals": "deals", CUSTOM: "records of custom objects"}

# (module, capability, what it allows): the one list. The UI groups it by module; a role may hold nothing else.
CATALOG = [
    *[("Records", f"{family}.{action}", f"{verb} {kind}")
      for family, kind in KINDS.items() for action, verb in ACTIONS.items()],
    ("Data model", "schema.read", "See objects, fields, association types, tags and saved views"),
    ("Data model", "objects.manage", "Create, change and archive objects and association types"),
    ("Data model", "fields.manage", "Add, change and archive fields"),
    ("Tags and views", "tags.write", "Create tags and put them on records"),
    ("Tags and views", "tags.manage", "Rename, merge and delete tags"),
    ("Tags and views", "views.write", "Save views"),
    ("Tags and views", "views.manage", "Change and delete other people's shared views"),
    ("Pipelines", "pipelines.manage", "Create and change pipelines and stages"),
    ("Workflows", "workflows.publish", "Publish and turn off workflows"),
    ("Messaging", "messages.send", "Send messages to contacts"),
    ("Billing", "billing.manage", "Change the plan, the wallet and payment methods"),
    ("Developer", "webhooks.manage", "Manage webhooks and replay their deliveries"),
    ("People", "members.read", "See members, teams and roles"),
    ("People", "members.manage", "Assign roles, manage teams and ask what a user can see"),
    ("People", "roles.manage", "Create, change and delete roles (organization owners and admins)"),
    ("Audit", "audit.read", "Read and export the audit log"),
]
CAPABILITIES = frozenset(cap for _, cap, _ in CATALOG)
assert len(CAPABILITIES) == len(CATALOG), "a capability is listed twice"

EVERYTHING: dict = {"and": []}
NOTHING: dict = {"or": []}
# ponytail: a team scope names its teams in the filter itself, so it is capped; a user in more teams than this
# (sub-teams included) loses the rest. Compile membership into SQL when that happens.
MAX_TEAMS = 1000


def family(object_key: str) -> str:
    return FAMILIES.get(object_key, CUSTOM)


def known(capability: str) -> str:
    if capability not in CAPABILITIES:
        raise ValueError(f"unknown capability {capability!r}")
    return capability


@dataclass(frozen=True)
class Rule:
    """What one role sees of one object."""
    scope: str = "none"
    hidden: frozenset[str] = frozenset()
    readonly: frozenset[str] = frozenset()


@dataclass(frozen=True)
class Grants:
    role: Role | None
    capabilities: frozenset[str]
    rules: dict[str, Rule]

    def rule(self, object_key: str) -> Rule:
        """The role's rule for the object, else its `*` rule, else nothing: a role with no rule sees no records."""
        return self.rules.get(object_key) or self.rules.get("*") or Rule()


def load(db: Session, role: Role | None) -> Grants:
    if role is None:
        return Grants(None, frozenset(), {})
    rules = {r.object_key: Rule(r.scope, frozenset(r.hidden_fields), frozenset(r.readonly_fields))
             for r in db.scalars(select(RoleObjectRule).where(RoleObjectRule.role_id == role.id))}
    return Grants(role, frozenset(role.capabilities) & CAPABILITIES, rules)  # a retired capability grants nothing


def cached(ctx: Ctx, key, make):
    if key not in ctx.cache:
        ctx.cache[key] = make()
    return ctx.cache[key]


def grants(ctx: Ctx) -> Grants:
    return cached(ctx, "grants", lambda: load(ctx.db, ctx.role))


# --- actions ----------------------------------------------------------------------------------------------------

def require(ctx: Ctx, capability: str) -> None:
    """403 naming the capability the role lacks."""
    known(capability)
    if capability not in grants(ctx).capabilities:
        raise ApiError(403, "forbidden", f"Your role does not allow this: it needs the capability {capability}")


def require_object(ctx: Ctx, obj, action: str) -> None:
    require(ctx, f"{family(obj.key)}.{action}")


def requires(capability: str, *, org: bool = False):
    """A route dependency: the user needs `capability` in the workspace. `org=True` also needs an organization
    owner or admin, for what changes every workspace of the org (roles). The route walk in the tests reads
    `.capability`, so every /api/v1 route declares one."""
    known(capability)

    def dependency(c: Ctx = Depends(in_workspace)) -> Ctx:
        require(c, capability)
        if org and not c.org_admin:
            raise ApiError(403, "forbidden", "Only organization owners and admins can do this")
        return c

    dependency.capability = capability
    return dependency


def requires_object(action: str):
    """For routes of one object (`/objects/{key}/...`): the action on that object's family of records."""
    def dependency(key: str, c: Ctx = Depends(in_workspace)) -> Ctx:
        require(c, f"{family(key)}.{action}")
        return c

    dependency.capability = f"<family>.{action}"
    return dependency


def requires_trash(action: str):
    """The same for `?object=<key>`."""
    def dependency(object: Annotated[str, Query()], c: Ctx = Depends(in_workspace)) -> Ctx:
        require(c, f"{family(object)}.{action}")
        return c

    dependency.capability = f"<family>.{action}"
    return dependency


def requires_records(action: str):
    """For routes that start from a record id (`/records/{id}/...`): the record's object is not known until it is
    found, and a record out of scope must be a 404 before it can be a 403. A read is then decided by the scope (no
    read capability means scope `none`), a write by the handler calling `require_object` once it has the record.
    This only turns away roles that could not do the action on any kind of record."""
    def dependency(c: Ctx = Depends(in_workspace)) -> Ctx:
        held = grants(c).capabilities
        if not any(f"{f}.{action}" in held for f in (*FAMILIES.values(), CUSTOM)):
            raise ApiError(403, "forbidden", f"Your role does not allow this: it needs {action} on some kind of record")
        return c

    dependency.capability = f"<family>.{action}"
    return dependency


# --- records: the hooks of the engine ---------------------------------------------------------------------------

def scope_of(ctx: Ctx, obj) -> str:
    """The scope that applies to `obj`: the role's rule, but `none` without the read capability."""
    g = grants(ctx)
    return g.rule(obj.key).scope if f"{family(obj.key)}.read" in g.capabilities else "none"


def sees_unowned(ctx: Ctx, obj) -> bool:
    return scope_of(ctx, obj) in ("all", "own_and_unassigned")


def assignee_fields(ctx: Ctx, obj) -> list[str]:
    """The user fields of the object: whoever one of them names is assigned to the record."""
    return cached(ctx, ("assignees", obj.id), lambda: list(ctx.db.scalars(select(FieldDef.key).where(
        FieldDef.object_id == obj.id, FieldDef.type == "user", FieldDef.archived_at.is_(None))
        .order_by(FieldDef.position, FieldDef.key))))


def team_ids(ctx: Ctx) -> list[str]:
    """The teams the user is in and every team below them."""
    def find():
        tree = select(TeamMember.team_id.label("id")).where(TeamMember.user_id == ctx.user_id).cte(recursive=True)
        tree = tree.union(select(Team.id).where(Team.parent_team_id == tree.c.id))
        return [str(i) for i in ctx.db.scalars(select(tree.c.id))]
    return cached(ctx, "teams", find)


def scope_filter(ctx: Ctx, obj) -> dict:
    """A filter AST (ADR 0002) of the records of `obj` that `ctx` may see. The engine ANDs it into every query, so a
    record outside it is a 404 everywhere. `team` and `own_and_unassigned` include what the user owns."""
    def make():
        kind = scope_of(ctx, obj)
        if kind == "all":
            return EVERYTHING
        if kind == "none":
            return NOTHING
        me = str(ctx.user_id)
        mine = [{"field": key, "op": "is", "value": me} for key in ("owner_id", *assignee_fields(ctx, obj))]
        if kind == "own_and_unassigned":
            return {"or": [*mine, {"field": "owner_id", "op": "is_empty"}]}
        teams = team_ids(ctx)[:MAX_TEAMS] if kind == "team" else []
        return {"or": [*mine, *([{"team": teams}] if teams else [])]}
    return cached(ctx, ("scope", obj.id), make)


def naming_fields(ctx: Ctx, obj) -> set[str]:
    """The fields a record's display name is built from: its primary fields, and the email or phone it falls back to."""
    return cached(ctx, ("naming", obj.id), lambda: {*obj.primary_fields, *ctx.db.scalars(select(FieldDef.key).where(
        FieldDef.object_id == obj.id, FieldDef.type.in_(("email", "phone")), FieldDef.archived_at.is_(None)))})


def hidden(ctx: Ctx, obj) -> frozenset[str]:
    """What `ctx` may not see of `obj`: its hidden fields, and `display_name` when one of them is part of the name
    (the name is then rebuilt from what is left, and cannot be searched, sorted or filtered on)."""
    def make():
        keys = set(grants(ctx).rule(obj.key).hidden)
        if keys and keys & naming_fields(ctx, obj):
            keys.add("display_name")
        return frozenset(keys)
    return cached(ctx, ("hidden", obj.id), make)


def restricted(ctx: Ctx) -> bool:
    """Whether any rule of the role hides a field (a quick way out for code that checks hidden fields in bulk)."""
    return any(rule.hidden for rule in grants(ctx).rules.values())


def redact(ctx: Ctx, obj, values: dict) -> dict:
    """`values` without the fields `ctx` may not read."""
    hide = hidden(ctx, obj)
    return {k: v for k, v in values.items() if k not in hide} if hide else values


def redact_event(ctx: Ctx, obj, data: dict) -> dict:
    """Event data (a record's new state and its changes) without what `ctx` may not read."""
    hide = hidden(ctx, obj)
    if not hide:
        return data
    out = {k: v for k, v in data.items() if k not in hide}
    for key in ("values", "changes"):
        if isinstance(out.get(key), dict):
            out[key] = {k: v for k, v in out[key].items() if k not in hide}
    return out


def check_write(ctx: Ctx, obj, changes: dict) -> None:
    """Refuses a write the role may not make: 403 without the write capability or on a read-only field, and 422 on a
    hidden one, which for this role is not a field of `obj` at all."""
    require_object(ctx, obj, "write")
    hide = hidden(ctx, obj)
    if gone := {f"values.{k}": f"is not a field of {obj.key}" for k in changes if k in hide}:
        raise ApiError(422, "validation_failed", f"The {obj.singular.lower()} is not valid", gone)
    readonly = grants(ctx).rule(obj.key).readonly
    if fixed := {f"values.{k}": "is read-only for your role" for k in changes if k in readonly}:
        raise ApiError(403, "forbidden", "Your role cannot change these fields", fixed)
