"""The "what can this user see?" simulator (ADR 0004): `GET /api/v1/permissions/explain?user_id=&record_id=`
answers with the user's role, capabilities and the rule per object and, for one record, whether they see it and
why. It runs the functions enforcement runs (`permissions.scope_filter` compiled by the record engine, `hidden`,
`grants`) on a copy of the request with the user swapped in, so it cannot drift from what the API does; only the
sentence is written here. Needs `members.manage`: it tells the existence and owner of records the asker may not see.

`GET /api/v1/me/capabilities` is the same summary for the caller, with no capability needed (it says nothing about
anyone else): the web app reads it once per workspace to hide what the role cannot do. `/api/me` is not workspace
scoped (one user, many workspaces, one role in each), so this lives under `/api/v1` with the workspace header. The
server stays the judge: the screen only avoids offering what would be refused."""
import uuid
from dataclasses import replace

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import exists, select

from . import permissions
from .models import SCOPES, Team, TeamMember, User
from .permissions import ACTIONS, requires
from .records.models import Record
from .records.schema import Catalog
from .records.store import scope
from .security import Ctx, in_workspace
from .tenancy import effective_role

router = APIRouter(prefix="/api/v1/permissions")
mine = APIRouter(prefix="/api/v1/me")


def reason(ctx: Ctx, obj, rec, visible: bool) -> str:
    """One sentence for the decision. The decision itself comes from the database; this only says why."""
    g, family = permissions.grants(ctx), permissions.family(obj.key)
    if f"{family}.read" not in g.capabilities:
        return f"not visible: the {g.role.name} role lacks {family}.read"
    kind, verdict = permissions.scope_of(ctx, obj), "visible" if visible else "not visible"
    if kind in ("all", "none"):
        return f"{verdict}: scope {kind}"
    if rec.owner_id == ctx.user_id:
        return f"{verdict}: the user is the owner, scope {kind}"
    for key in permissions.assignee_fields(ctx, obj):
        if rec.values.get(key) == str(ctx.user_id):
            return f"{verdict}: the user is assigned in {key}, scope {kind}"
    if rec.owner_id is None:
        return f"{verdict}: the record has no owner, scope {kind}"
    if kind == "team":
        teams = ctx.db.scalars(select(Team.name).join(TeamMember, TeamMember.team_id == Team.id).where(
            TeamMember.user_id == rec.owner_id, Team.id.in_(permissions.team_ids(ctx))).order_by(Team.name)).all()
        if teams:
            return f"{verdict}: owner is in team {teams[0]}, scope team"
        return f"{verdict}: owner is in none of the user's teams, scope team"
    return f"{verdict}: the record is owned by someone else, scope {kind}"


def summary(ctx: Ctx, implicit: bool) -> dict:
    """The role, capabilities, teams and, per object, the scope and what the role may do, as `ctx` is."""
    cat, g = Catalog(ctx), permissions.grants(ctx)
    in_tree = permissions.team_ids(ctx)
    direct = set(ctx.db.scalars(select(TeamMember.team_id).where(TeamMember.user_id == ctx.user_id)))
    teams = ctx.db.execute(select(Team.id, Team.name).where(Team.id.in_([uuid.UUID(t) for t in in_tree]))
                           .order_by(Team.name)).all()
    role = g.role
    return {
        "role": role and {"id": role.id, "key": role.key, "name": role.name,
                          "source": "organization" if implicit else "workspace"},
        "capabilities": sorted(g.capabilities),
        "teams": [{"id": i, "name": n, "direct": i in direct} for i, n in teams],
        "objects": {obj.key: {
            "scope": permissions.scope_of(ctx, obj), "rule_scope": g.rule(obj.key).scope,
            "hidden_fields": sorted(g.rule(obj.key).hidden), "readonly_fields": sorted(g.rule(obj.key).readonly),
            "can": {action: f"{permissions.family(obj.key)}.{action}" in g.capabilities for action in ACTIONS}}
            for obj in cat.objects()},
    }


@mine.get("/capabilities")
def my_capabilities(c: Ctx = Depends(in_workspace)):
    """What the caller's role allows in this workspace: capabilities (the strings of `permissions.CATALOG`), the
    scope and hidden and read-only fields per object, and their teams."""
    return summary(c, c.org_admin)


@router.get("/catalog")
def catalog(c: Ctx = Depends(requires("members.read"))):
    """What a role is made of, for the role editor: every capability with its module and what it allows (in the order
    of `permissions.CATALOG`), and the record scopes a rule can have."""
    return {"capabilities": [{"module": m, "capability": cap, "description": d} for m, cap, d in permissions.CATALOG],
            "scopes": list(SCOPES)}


@router.get("/explain")
def explain(user_id: uuid.UUID | None = None, record_id: uuid.UUID | None = None,
            c: Ctx = Depends(requires("members.manage"))):
    who = user_id or c.user_id
    found = effective_role(c.db, who, c.workspace)
    if found is None:
        raise HTTPException(404, "Member not found")
    role, implicit = found
    ctx = replace(c, user_id=who, role=role, org_admin=implicit, cache={})  # the same request, as that user
    cat = Catalog(ctx)
    account = c.db.get(User, who)
    out = {"user": {"id": who, "name": account.name if account else None, "email": account.email if account else None},
           **summary(ctx, implicit)}
    if record_id:
        rec = c.db.get(Record, record_id)
        obj = cat.by_id(rec.object_id) if rec else None
        if obj is None:
            raise HTTPException(404, "Record not found")
        visible = bool(c.db.scalar(select(exists().where(Record.id == rec.id, scope(cat, obj)))))  # as store.get asks
        out["record"] = {"id": rec.id, "object": obj.key, "visible": visible, "in_trash": rec.deleted_at is not None,
                         "reason": reason(ctx, obj, rec, visible)}
    return out
