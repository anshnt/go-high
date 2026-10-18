"""Who can see what: roles and the organization/workspace listing behind /api/me and /api/workspaces.
Every query here runs in a scoped session, so row level security already limits it to the user's tenants."""
import uuid
from collections import defaultdict

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from .models import Brand, Organization, OrgMember, Role, Workspace, WorkspaceMember

ADMIN_ORG_ROLES = ("owner", "admin")  # keys of the system roles that are admins of every workspace of their org


def org_role(db: Session, user_id: uuid.UUID, org_id: uuid.UUID) -> str | None:
    """The key of the user's role in the organization (`owner`, `admin`, `member` or a custom role's key)."""
    return db.scalar(select(Role.key).join(OrgMember, OrgMember.role_id == Role.id)
                     .where(OrgMember.user_id == user_id, OrgMember.org_id == org_id))


def effective_role(db: Session, user_id: uuid.UUID, ws: Workspace) -> tuple[Role, bool] | None:
    """The role that applies to the user in the workspace, and whether it is implicit: org owners and admins are
    admins of every workspace in the org, with their organization role; others need a workspace membership."""
    org = db.scalar(select(Role).join(OrgMember, OrgMember.role_id == Role.id)
                    .where(OrgMember.user_id == user_id, OrgMember.org_id == ws.org_id))
    if org is not None and org.key in ADMIN_ORG_ROLES:
        return org, True
    role = db.scalar(select(Role).join(WorkspaceMember, WorkspaceMember.role_id == Role.id)
                     .where(WorkspaceMember.user_id == user_id, WorkspaceMember.workspace_id == ws.id))
    return None if role is None else (role, False)


def workspace_role(db: Session, user_id: uuid.UUID, ws: Workspace) -> str | None:
    """`admin` for org owners and admins, else the key of the workspace role; None without access."""
    found = effective_role(db, user_id, ws)
    return None if found is None else "admin" if found[1] else found[0].key


def workspace_ids(db: Session, user_id: uuid.UUID) -> list[uuid.UUID]:
    """The workspaces the user can act in. Explicit joins instead of row level security, so it also answers in the
    pre-auth scope."""
    admin_orgs = (select(OrgMember.org_id).join(Role, Role.id == OrgMember.role_id)
                  .where(OrgMember.user_id == user_id, Role.key.in_(ADMIN_ORG_ROLES)))
    member = select(WorkspaceMember.workspace_id).where(WorkspaceMember.user_id == user_id)
    return list(db.scalars(select(Workspace.id).where(or_(Workspace.org_id.in_(admin_orgs),
                                                          Workspace.id.in_(member)))))


def workspace_data(ws: Workspace) -> dict:
    return {"id": ws.id, "name": ws.name, "org_id": ws.org_id, "brand_id": ws.brand_id}


def workspace_json(ws: Workspace, role: str | None) -> dict:
    return {**workspace_data(ws), "role": role}


def my_workspaces(db: Session, user_id: uuid.UUID) -> list[dict]:
    org_roles = dict(db.execute(select(OrgMember.org_id, Role.key).join(Role, Role.id == OrgMember.role_id)
                                .where(OrgMember.user_id == user_id)).all())
    ws_roles = dict(db.execute(select(WorkspaceMember.workspace_id, Role.key)
                               .join(Role, Role.id == WorkspaceMember.role_id)
                               .where(WorkspaceMember.user_id == user_id)).all())
    return [workspace_json(ws, "admin" if org_roles.get(ws.org_id) in ADMIN_ORG_ROLES else ws_roles.get(ws.id))
            for ws in db.scalars(select(Workspace).order_by(Workspace.created_at))]


def my_orgs(db: Session, user_id: uuid.UUID) -> list[dict]:
    rows = db.execute(select(Organization, Role.key).join(OrgMember, OrgMember.org_id == Organization.id)
                      .join(Role, Role.id == OrgMember.role_id)
                      .where(OrgMember.user_id == user_id).order_by(Organization.created_at)).all()
    brands = defaultdict(list)
    for b in db.scalars(select(Brand).where(Brand.org_id.in_([org.id for org, _ in rows])).order_by(Brand.created_at)):
        brands[b.org_id].append({"id": b.id, "name": b.name})
    return [{"id": org.id, "name": org.name, "role": role, "brands": brands[org.id]} for org, role in rows]
