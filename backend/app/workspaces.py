"""/api/workspaces: list mine, read one, create one, and the active workspace chosen by X-Workspace-Id."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, StringConstraints

from . import events
from .db import rescope
from .models import Brand, Workspace
from .security import Ctx, in_workspace, user
from .tenancy import ADMIN_ORG_ROLES, my_workspaces, org_role, workspace_data, workspace_json, workspace_role

router = APIRouter(prefix="/api/workspaces")


class NewWorkspace(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
    brand_id: uuid.UUID


@router.get("")
def list_workspaces(c: Ctx = Depends(user)):
    return my_workspaces(c.db, c.user_id)


@router.get("/current")
def current_workspace(c: Ctx = Depends(in_workspace)):
    return workspace_json(c.workspace, c.workspace_role)


@router.post("", status_code=201)
def create_workspace(body: NewWorkspace, c: Ctx = Depends(user)):
    brand = c.db.get(Brand, body.brand_id)  # visible only to members of the brand's org
    if brand is None:
        raise HTTPException(404, "Brand not found")
    if org_role(c.db, c.user_id, brand.org_id) not in ADMIN_ORG_ROLES:
        raise HTTPException(403, "Only organization owners and admins can create workspaces")
    ws = Workspace(org_id=brand.org_id, brand_id=brand.id, name=body.name)
    c.db.add(ws)
    c.db.flush()
    rescope(c.db, user_id=c.user_id, org_id=ws.org_id, workspace_id=ws.id)  # the event belongs to the new workspace
    events.emit(c.db, "workspace.created", "workspace", ws.id, workspace_data(ws), actor=("user", c.user_id))
    c.db.commit()
    return workspace_json(ws, "admin")


@router.get("/{workspace_id}")
def get_workspace(workspace_id: uuid.UUID, c: Ctx = Depends(user)):
    ws = c.db.get(Workspace, workspace_id)
    if ws is None:
        raise HTTPException(404, "Workspace not found")
    return workspace_json(ws, workspace_role(c.db, c.user_id, ws))
