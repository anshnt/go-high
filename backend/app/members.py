"""The people of the workspace, for pickers (assign a task, a record owner). `users` can only be read by its owner,
so the list comes from `workspace_people()` (migration 0009), which answers only to someone in the workspace."""
from fastapi import APIRouter, Depends
from sqlalchemy import text

from .security import Ctx, in_workspace

router = APIRouter(prefix="/api/v1")


@router.get("/members")
def list_members(c: Ctx = Depends(in_workspace)):
    """Members of this workspace and the admins of its organization: id, name, email and role (admin or member)."""
    rows = c.db.execute(text("SELECT user_id, name, email, role FROM workspace_people() ORDER BY lower(name), email"))
    return {"data": [{"id": r.user_id, "name": r.name, "email": r.email, "role": r.role} for r in rows]}
