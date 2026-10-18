"""Teams and the people of a workspace (ADR 0004). A team has members and may sit under another team; a role with
`team` scope sees the records owned by anyone in its holder's teams and the teams below them. Seeing teams and people is
`members.read`; changing teams and giving someone a role in the workspace is `members.manage`."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StringConstraints
from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError

from . import events, permissions
from .api import ApiError
from .models import OrgMember, Role, Team, TeamMember, User, WorkspaceMember
from .permissions import requires
from .records.store import member_ids
from .security import Ctx
from .tenancy import ADMIN_ORG_ROLES, effective_role

router = APIRouter(prefix="/api/v1")
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class NewTeam(BaseModel):
    name: Name
    parent_team_id: uuid.UUID | None = None


class PatchTeam(BaseModel):
    name: Name | None = None
    parent_team_id: uuid.UUID | None = None  # send null to make it a top level team


class Assign(BaseModel):
    role_id: uuid.UUID


def team_data(t: Team) -> dict:
    return {"id": t.id, "name": t.name, "parent_team_id": t.parent_team_id}


def team_json(t: Team, members: int | None = None) -> dict:
    return {**team_data(t), "created_at": t.created_at, **({"member_count": members} if members is not None else {})}


def team_or_404(c: Ctx, team_id: uuid.UUID) -> Team:
    team = c.db.get(Team, team_id)  # row level security: this workspace's teams only
    if team is None:
        raise HTTPException(404, "Team not found")
    return team


def person_or_404(c: Ctx, user_id: uuid.UUID) -> uuid.UUID:
    if str(user_id) not in member_ids(c, {str(user_id)}):
        raise HTTPException(404, "Member not found")
    return user_id


def check_parent(c: Ctx, team: Team | None, parent_id: uuid.UUID | None) -> None:
    """The parent must be a team of this workspace, and not the team itself or one of its sub-teams."""
    seen, at = set(), parent_id
    while at is not None:
        parent = c.db.get(Team, at)
        if parent is None:
            raise ApiError(422, "validation_failed", "The request is not valid",
                           {"parent_team_id": "is not a team of this workspace"})
        if (team is not None and parent.id == team.id) or parent.id in seen:
            raise ApiError(422, "validation_failed", "The request is not valid",
                           {"parent_team_id": "a team cannot sit under itself or one of its sub-teams"})
        seen.add(parent.id)
        at = parent.parent_team_id


def name_taken(name: str) -> ApiError:
    return ApiError(409, "conflict", f"A team named {name!r} exists", {"name": "is already used"})


@router.get("/teams")
def list_teams(c: Ctx = Depends(requires("members.read"))):
    """Every team of the workspace with its member count. A workspace has few."""
    counts = dict(c.db.execute(select(TeamMember.team_id, func.count()).group_by(TeamMember.team_id)).all())
    teams = c.db.scalars(select(Team).order_by(func.lower(Team.name), Team.id))
    return {"data": [team_json(t, counts.get(t.id, 0)) for t in teams], "next_cursor": None}


@router.post("/teams", status_code=201)
def create_team(body: NewTeam, c: Ctx = Depends(requires("members.manage"))):
    check_parent(c, None, body.parent_team_id)
    team = Team(workspace_id=c.workspace.id, name=body.name, parent_team_id=body.parent_team_id)
    try:
        with c.db.begin_nested():
            c.db.add(team)
    except IntegrityError:
        raise name_taken(body.name) from None
    events.emit(c.db, "team.created", "team", team.id, team_data(team), actor=("user", c.user_id))
    c.db.commit()
    return team_json(team, 0)


@router.get("/teams/{team_id}")
def get_team(team_id: uuid.UUID, c: Ctx = Depends(requires("members.read"))):
    team = team_or_404(c, team_id)
    people = c.db.execute(select(User.id, User.name, User.email).join(TeamMember, TeamMember.user_id == User.id)
                          .where(TeamMember.team_id == team.id).order_by(User.name, User.email)).all()
    return {**team_json(team, len(people)), "members": [{"user_id": u, "name": n, "email": e} for u, n, e in people]}


@router.patch("/teams/{team_id}")
def update_team(team_id: uuid.UUID, body: PatchTeam, c: Ctx = Depends(requires("members.manage"))):
    team = team_or_404(c, team_id)
    sent = body.model_dump(exclude_unset=True)
    if sent.get("name", "") is None:
        raise ApiError(422, "validation_failed", "The request is not valid", {"name": "cannot be null"})
    before = team_data(team)
    if "parent_team_id" in sent:
        check_parent(c, team, sent["parent_team_id"])
    try:
        with c.db.begin_nested():  # the changes flush when the savepoint is released, so a clash rolls back to it
            for name, value in sent.items():
                setattr(team, name, value)
    except IntegrityError:
        raise name_taken(sent.get("name") or "") from None
    if changed := events.changes(before, team_data(team)):
        events.emit(c.db, "team.updated", "team", team.id, {**team_data(team), "changes": changed},
                    actor=("user", c.user_id))
    c.db.commit()
    members = c.db.scalar(select(func.count()).select_from(TeamMember).where(TeamMember.team_id == team.id))
    return team_json(team, members)


@router.delete("/teams/{team_id}", status_code=204)
def delete_team(team_id: uuid.UUID, c: Ctx = Depends(requires("members.manage"))):
    """The team's sub-teams move up to its parent; its memberships go with it."""
    team = team_or_404(c, team_id)
    c.db.execute(update(Team).where(Team.parent_team_id == team.id).values(parent_team_id=team.parent_team_id))
    events.emit(c.db, "team.deleted", "team", team.id, {"id": team.id, "name": team.name}, actor=("user", c.user_id))
    c.db.delete(team)
    c.db.commit()


@router.put("/teams/{team_id}/members/{user_id}")
def add_team_member(team_id: uuid.UUID, user_id: uuid.UUID, c: Ctx = Depends(requires("members.manage"))):
    """Idempotent: a person already in the team stays, and nothing is recorded."""
    team, person = team_or_404(c, team_id), person_or_404(c, user_id)
    added = c.db.scalar(pg_insert(TeamMember).values(team_id=team.id, user_id=person, workspace_id=c.workspace.id)
                        .on_conflict_do_nothing().returning(TeamMember.user_id))
    if added:
        events.emit(c.db, "team.member_added", "team", team.id, {"team_id": team.id, "user_id": person},
                    actor=("user", c.user_id))
    c.db.commit()
    return {"team_id": team.id, "user_id": person}


@router.delete("/teams/{team_id}/members/{user_id}", status_code=204)
def remove_team_member(team_id: uuid.UUID, user_id: uuid.UUID, c: Ctx = Depends(requires("members.manage"))):
    team = team_or_404(c, team_id)
    gone = c.db.scalar(delete(TeamMember).where(TeamMember.team_id == team.id, TeamMember.user_id == user_id)
                       .returning(TeamMember.user_id))
    if gone is None:
        raise HTTPException(404, "Member not found")
    events.emit(c.db, "team.member_removed", "team", team.id, {"team_id": team.id, "user_id": user_id},
                actor=("user", c.user_id))
    c.db.commit()


def role_ref(role: Role) -> dict:
    return {"id": role.id, "key": role.key, "name": role.name}


@router.get("/members")
def list_members(c: Ctx = Depends(requires("members.read"))):
    """The people who can act in this workspace: its members with their role, and the owners and admins of its
    organization, who are admins of every workspace. Nobody else is visible. A workspace has tens of people."""
    people = select(User.id, User.name, User.email, Role)
    explicit = people.join(WorkspaceMember, WorkspaceMember.user_id == User.id).join(
        Role, Role.id == WorkspaceMember.role_id).where(WorkspaceMember.workspace_id == c.workspace.id)
    implicit = people.join(OrgMember, OrgMember.user_id == User.id).join(Role, Role.id == OrgMember.role_id).where(
        OrgMember.org_id == c.workspace.org_id, Role.key.in_(ADMIN_ORG_ROLES))
    found = {u: (n, e, role, False) for u, n, e, role in c.db.execute(explicit)}
    found |= {u: (n, e, role, True) for u, n, e, role in c.db.execute(implicit)}
    teams: dict[uuid.UUID, list[dict]] = {u: [] for u in found}
    for user_id, team_id, name in c.db.execute(select(TeamMember.user_id, Team.id, Team.name).join(
            Team, Team.id == TeamMember.team_id).order_by(func.lower(Team.name))):
        teams.get(user_id, []).append({"id": team_id, "name": name})
    return {"data": [{"user_id": u, "name": n, "email": e, "role": role_ref(role), "implicit": implicit,
                      "teams": teams[u]}
                     for u, (n, e, role, implicit) in sorted(found.items(), key=lambda kv: (kv[1][0], kv[1][1]))],
            "next_cursor": None}


@router.put("/members/{user_id}")
def assign_role(user_id: uuid.UUID, body: Assign, c: Ctx = Depends(requires("members.manage"))):
    """Gives a member of the organization a role in this workspace (and adds them to it). Org owners and admins are
    admins everywhere and keep that. Unless you are one yourself, you cannot hand out a role that can do more than
    yours."""
    role = c.db.get(Role, body.role_id)  # row level security: this organization's roles only
    if role is None:
        raise HTTPException(404, "Role not found")
    if c.db.scalar(select(OrgMember.user_id).where(OrgMember.org_id == c.workspace.org_id,
                                                   OrgMember.user_id == user_id)) is None:
        raise HTTPException(404, "Member not found")
    found = effective_role(c.db, user_id, c.workspace)
    if found and found[1]:
        raise ApiError(409, "implicit_admin", "Organization owners and admins are admins of every workspace; "
                                              "change their role in the organization instead")
    if not c.org_admin and (beyond := set(role.capabilities) - permissions.grants(c).capabilities):
        raise ApiError(403, "forbidden",
                       f"You cannot give a role that can do more than yours: {', '.join(sorted(beyond))}")
    member = c.db.get(WorkspaceMember, (user_id, c.workspace.id))
    old = role_ref(found[0]) if found else None  # a role exactly when they are a member already
    if member is not None and member.role_id == role.id:
        return {"user_id": user_id, "role": role_ref(role)}
    if member is None:
        c.db.add(WorkspaceMember(user_id=user_id, workspace_id=c.workspace.id, role_id=role.id))
    else:
        member.role_id = role.id
    c.db.flush()
    events.emit(c.db, "member.role_changed", "user", user_id,
                {"user_id": user_id, "workspace_id": c.workspace.id, "old_role": old, "new_role": role_ref(role)},
                actor=("user", c.user_id))
    c.db.commit()
    return {"user_id": user_id, "role": role_ref(role)}
