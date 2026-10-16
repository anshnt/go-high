"""The system objects every workspace starts with (ADR 0002): contact, company and deal, their fields and how they
link. Called when a workspace is created (sign up, POST /api/workspaces) and by migration 0004 for existing ones.
The tables are declared here with only the columns this writes (the rest have defaults), so an old migration keeps
working when the models grow."""
import uuid

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Session

from ..db import rescope

OBJECTS = sa.table("objects", *(sa.column(c) for c in ("id", "workspace_id", "key", "singular", "plural", "icon",
                                                       "is_system")), sa.column("primary_fields", ARRAY(sa.String)))
FIELDS = sa.table("fields", *(sa.column(c) for c in ("id", "workspace_id", "object_id", "key", "label", "type",
                                                     "is_system", "position")),
                  sa.column("options", JSONB), sa.column("rules", JSONB))
ASSOCIATION_TYPES = sa.table("association_types", *(sa.column(c) for c in (
    "id", "workspace_id", "from_object_id", "to_object_id", "label", "inverse_label", "cardinality", "is_system")))


def choices(*items: tuple[str, str, str]) -> dict:
    return {"choices": [{"id": id_, "label": label, "color": color} for id_, label, color in items]}


# object key: (singular, plural, icon, primary fields, [(field key, label, type, options, rules)])
SYSTEM_OBJECTS = {
    "contact": ("Contact", "Contacts", "user", ["first_name", "last_name"], [
        ("first_name", "First name", "text", {}, {}),
        ("last_name", "Last name", "text", {}, {}),
        ("email", "Email", "email", {}, {}),
        ("phone", "Phone", "phone", {"region": "US"}, {}),
        ("lifecycle", "Lifecycle stage", "select", choices(
            ("lead", "Lead", "blue"), ("qualified", "Qualified", "amber"), ("customer", "Customer", "green"),
            ("churned", "Churned", "red"), ("other", "Other", "gray")), {}),
        ("company", "Company", "record", {"object": "company"}, {}),
    ]),
    "company": ("Company", "Companies", "building", ["name"], [
        ("name", "Name", "text", {}, {"required": True}),
        ("domain", "Domain", "text", {}, {}),
        ("industry", "Industry", "text", {}, {}),
        ("size", "Size", "select", choices(
            ("1-10", "1-10", "gray"), ("11-50", "11-50", "gray"), ("51-200", "51-200", "gray"),
            ("201-1000", "201-1000", "gray"), ("1000_plus", "1000+", "gray")), {}),
    ]),
    "deal": ("Deal", "Deals", "handshake", ["name"], [
        ("name", "Name", "text", {}, {"required": True}),
        ("amount", "Amount", "money", {"currency": "USD"}, {}),
        ("stage", "Stage", "stage", choices(  # ponytail: placeholder choices until pipelines (module 10)
            ("new", "New", "gray"), ("qualified", "Qualified", "blue"), ("proposal", "Proposal", "amber"),
            ("negotiation", "Negotiation", "amber"), ("won", "Won", "green"), ("lost", "Lost", "red")), {}),
        ("close_date", "Close date", "date", {}, {}),
    ]),
}
# (from object, to object, label seen from the first, label seen from the second)
SYSTEM_LINKS = [("contact", "company", "works at", "employs"), ("deal", "contact", "contact", "deal"),
                ("deal", "company", "company", "deal")]


def add(db, workspace_id: uuid.UUID) -> None:
    """Inserts the system objects of a new workspace through `db` (a session or connection), with no checks:
    the workspace must have none yet."""
    ids = {key: uuid.uuid4() for key in SYSTEM_OBJECTS}
    db.execute(sa.insert(OBJECTS), [
        {"id": ids[key], "workspace_id": workspace_id, "key": key, "singular": singular, "plural": plural,
         "icon": icon, "is_system": True, "primary_fields": primary}
        for key, (singular, plural, icon, primary, _) in SYSTEM_OBJECTS.items()])
    db.execute(sa.insert(FIELDS), [
        {"id": uuid.uuid4(), "workspace_id": workspace_id, "object_id": ids[key], "key": k, "label": label,
         "type": type_, "options": options, "rules": rules, "is_system": True, "position": position}
        for key, spec in SYSTEM_OBJECTS.items() for position, (k, label, type_, options, rules) in enumerate(spec[4])])
    db.execute(sa.insert(ASSOCIATION_TYPES), [
        {"id": uuid.uuid4(), "workspace_id": workspace_id, "from_object_id": ids[a], "to_object_id": ids[b],
         "label": label, "inverse_label": inverse, "cardinality": "many_to_many", "is_system": True}
        for a, b, label, inverse in SYSTEM_LINKS])


def seed_workspace(db: Session, workspace_id: uuid.UUID) -> None:
    """`add` for a request session: the tables are workspace scoped, so the scope moves to the new workspace for
    the inserts (sign up runs in the pre-auth scope) and goes back."""
    scope = dict(db.info.get("scope", {}))
    rescope(db, **{**scope, "workspace_id": workspace_id})
    add(db, workspace_id)
    rescope(db, **scope)
