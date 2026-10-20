"""Running payments work that nobody signed in for (a webhook, a renewal, a visitor's checkout) inside one workspace,
as the workspace's Automation role, the way calendars and forms do (ADR 0004)."""
import uuid
from contextlib import contextmanager

from sqlalchemy.orm import Session

from ..calendars.contacts import system_ctx
from ..db import acting
from ..models import Workspace

__all__ = ["system_ctx", "workspace_job"]


@contextmanager
def workspace_job(db: Session, workspace_id: str | uuid.UUID):
    """For a job (the owner role's session): yields a context confined to the workspace by row level security, or None
    when the workspace is gone. Nothing is committed here; the job runner commits."""
    ws = db.get(Workspace, uuid.UUID(str(workspace_id)))
    if ws is None:
        yield None
        return
    with acting(db, workspace_id=ws.id, org_id=ws.org_id):
        yield system_ctx(db, ws)
