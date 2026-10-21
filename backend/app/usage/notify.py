"""Who hears about money: the people whose role in the workspace holds `billing.manage` (the organization's owners, and
anyone given a role with it). The notifications consumer turns the wallet's alert events into one in-app notification
each for them (kind `billing`)."""
import uuid

from sqlalchemy import select

from .. import permissions
from ..events import Event
from ..models import OrgMember, Role, Workspace, WorkspaceMember
from ..tenancy import ADMIN_ORG_ROLES, effective_role
from . import money

TYPES = ("wallet.low_balance", "usage.cap_warning", "wallet.topup_failed")
LINK = "/settings/billing"


def billing_people(db, workspace_id: uuid.UUID) -> list[uuid.UUID]:
    ws = db.get(Workspace, workspace_id)
    if ws is None:
        return []
    admins = select(OrgMember.user_id).join(Role, Role.id == OrgMember.role_id).where(
        OrgMember.org_id == ws.org_id, Role.key.in_(ADMIN_ORG_ROLES))
    members = select(WorkspaceMember.user_id).where(WorkspaceMember.workspace_id == ws.id)
    people = []
    for user_id in sorted(set(db.scalars(admins)) | set(db.scalars(members))):
        found = effective_role(db, user_id, ws)
        if found and "billing.manage" in permissions.load(db, found[0]).capabilities:
            people.append(user_id)
    return people


def text(e: Event) -> tuple[str, str]:
    """(title, body) of the notification for one of TYPES."""
    d, c = e.data, e.data["currency"]
    if e.type == "wallet.low_balance":
        return (f"Wallet balance is low: {money.show(d['balance'], c)}",
                f"It fell below the alert at {money.show(d['threshold'], c)}. Top up so sends do not stop.")
    if e.type == "usage.cap_warning":
        return (f"Usage reached {d['alert_pct']} % of this month's cap",
                f"{money.show(d['spent'], c)} of {money.show(d['cap'], c)} used. Sends stop at the cap.")
    who = "An automatic top-up" if d["trigger"] == "auto" else "A top-up"
    return f"{who} of {money.show(d['amount'], c)} failed", d["error"]
