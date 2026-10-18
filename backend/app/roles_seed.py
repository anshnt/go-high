"""The system roles every organization starts with (ADR 0004): Owner, Admin, Manager, Member, Viewer and the Automation
role that workflows and AI agents run as. Seeded when an organization is created (sign up) and by migration 0005 for
existing ones. Owner and Admin are the implicit admins of every workspace and cannot be changed; the others can be
edited but not deleted, and a custom role starts as a copy of one of them. The tables are declared here with only the
columns this writes, so an old migration keeps working when the models grow.

A module that adds a capability puts it in `permissions.CATALOG`, lists it here for new organizations and grants it to
existing ones in its own migration (`UPDATE roles SET capabilities = capabilities || ...`)."""
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY

from .permissions import CAPABILITIES, CATALOG, CUSTOM, FAMILIES

ROLES = sa.table("roles", *(sa.column(c) for c in ("id", "org_id", "key", "name", "description", "is_system")),
                 sa.column("capabilities", ARRAY(sa.Text)))
RULES = sa.table("role_object_rules", *(sa.column(c) for c in ("id", "org_id", "role_id", "object_key", "scope")))
LOCKED = ("owner", "admin")  # these two define what an organization owner or admin is; nobody edits them

KINDS = (*FAMILIES.values(), CUSTOM)


def records(*actions: str) -> set[str]:
    return {f"{kind}.{action}" for kind in KINDS for action in actions}


MEMBER = {*records("read", "write", "delete"), "schema.read", "tags.write", "views.write", "messages.send",
           "members.read", "tasks.read", "tasks.write", "tasks.delete", "conversations.read", "conversations.write",
           "consents.manage", "forms.read", "forms.write", "responses.read", "calendars.read", "calendars.write"}
# key: (name, description, capabilities). Every role starts with the rule "all records of every object".
SYSTEM_ROLES = {
    "owner": ("Owner", "Everything, billing included. Cannot be changed.", set(CAPABILITIES)),
    "admin": ("Admin", "Everything except billing. Cannot be changed.", CAPABILITIES - {"billing.manage"}),
    "manager": ("Manager", "Works with every record, exports, looks after tags, views, pipelines, workflows, forms, "
                "calendars.",
                MEMBER | records("export") | {"tags.manage", "views.manage", "pipelines.manage", "workflows.publish",
                                              "forms.publish", "forms.delete", "responses.export", "calendars.manage"}),
    "member": ("Member", "Works with records, tags, views, and forms and their responses (cannot publish).", MEMBER),
    "viewer": ("Viewer", "Reads records, and cannot change anything.",
               {*records("read"), "schema.read", "members.read", "tasks.read", "conversations.read", "forms.read",
                "responses.read", "calendars.read"}),
    "automation": ("Automation", "What workflows and AI agents run as: reads and writes records, tags, sends messages.",
                   {*records("read", "write"), "schema.read", "tags.write", "messages.send", "tasks.read",
                    "tasks.write", "conversations.read", "conversations.write", "calendars.read", "calendars.write"}),
}


def in_catalog_order(capabilities: set[str]) -> list[str]:
    return [cap for _, cap, _ in CATALOG if cap in capabilities]


def add(db, org_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """Inserts the system roles of a new organization through `db` (a session or connection), with no checks: the
    organization must have none yet. Returns their ids by key."""
    ids = {key: uuid.uuid4() for key in SYSTEM_ROLES}
    db.execute(sa.insert(ROLES), [
        {"id": ids[key], "org_id": org_id, "key": key, "name": name, "description": description, "is_system": True,
         "capabilities": in_catalog_order(capabilities)}
        for key, (name, description, capabilities) in SYSTEM_ROLES.items()])
    db.execute(sa.insert(RULES), [{"id": uuid.uuid4(), "org_id": org_id, "role_id": ids[key], "object_key": "*",
                                   "scope": "all"} for key in SYSTEM_ROLES])
    return ids
