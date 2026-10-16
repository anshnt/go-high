"""Who can see what: roles and the organization/workspace listing behind /api/me and /api/workspaces.
Every query here runs in a scoped session, so row level security already limits it to the user's tenants."""
import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Organization, OrgMember, Workspace, WorkspaceMember

ADMIN_ORG_ROLES = ("owner", "admin")


def org_role(db: Session, user_id: uuid.UUID, org_id: uuid.UUID) -> str | None:
    return db.scalar(select(OrgMember.role).where(OrgMember.user_id == user_id, OrgMember.org_id == org_id))


def workspace_role(db: Session, user_id: uuid.UUID, ws: Workspace) -> str | None:
    """Org owners and admins are admins of every workspace in the org; others need a workspace membership."""
    if org_role(db, user_id, ws.org_id) in ADMIN_ORG_ROLES:
        return "admin"
    return db.scalar(select(WorkspaceMember.role).where(
        WorkspaceMember.user_id == user_id, WorkspaceMember.workspace_id == ws.id))


def workspace_json(ws: Workspace, role: str | None) -> dict:
    return {"id": ws.id, "name": ws.name, "org_id": ws.org_id, "brand_id": ws.brand_id, "role": role}


def my_workspaces(db: Session, user_id: uuid.UUID) -> list[dict]:
    org_roles = dict(db.execute(select(OrgMember.org_id, OrgMember.role).where(OrgMember.user_id == user_id)).all())
    ws_roles = dict(db.execute(
        select(WorkspaceMember.workspace_id, WorkspaceMember.role).where(WorkspaceMember.user_id == user_id)).all())
    return [workspace_json(ws, "admin" if org_roles.get(ws.org_id) in ADMIN_ORG_ROLES else ws_roles.get(ws.id))
            for ws in db.scalars(select(Workspace).order_by(Workspace.created_at))]


def my_orgs(db: Session, user_id: uuid.UUID) -> list[dict]:
    rows = db.execute(select(Organization, OrgMember.role).join(OrgMember, OrgMember.org_id == Organization.id)
                      .where(OrgMember.user_id == user_id).order_by(Organization.created_at)).all()
    return [{"id": org.id, "name": org.name, "role": role} for org, role in rows]

