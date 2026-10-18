"""The system objects every workspace starts with (ADR 0002): contact, company and deal, their fields and how they
link, and the Sales pipeline. Called when a workspace is created (sign up, POST /api/workspaces) and by migrations
0004 and 0007 for existing ones. The tables are declared here with only the columns this writes (the rest have
defaults), so an old migration keeps working when the models grow."""
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
PIPELINES = sa.table("pipelines", *(sa.column(c) for c in ("id", "workspace_id", "name", "position")))
STAGES = sa.table("stages", *(sa.column(c) for c in ("id", "workspace_id", "pipeline_id", "name", "position", "kind",
                                                     "probability", "rotting_days", "color")))


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
        ("stage", "Stage", "stage", {}, {}),  # a stage id; the stages are the pipeline's (module 10)
        ("close_date", "Close date", "date", {}, {}),
        ("lost_reason", "Lost reason", "select", choices(
            ("price", "Price", "gray"), ("timing", "Timing", "gray"), ("competitor", "Competitor", "gray"),
            ("no_decision", "No decision", "gray"), ("other", "Other", "gray")), {}),
        ("lost_note", "Lost note", "long_text", {}, {}),
    ]),
}
# (name, kind, probability, rotting days, color) of the Sales pipeline every workspace starts with
DEFAULT_STAGES = [("Lead", "open", 10, 14, "gray"), ("Qualified", "open", 25, 14, "blue"),
                  ("Proposal", "open", 50, 21, "amber"), ("Negotiation", "open", 80, 21, "orange"),
                  ("Won", "won", 100, None, "green"), ("Lost", "lost", 0, None, "red")]
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


def add_pipeline(db, workspace_id: uuid.UUID) -> uuid.UUID:
    """Inserts the Sales pipeline and its stages through `db`, with no checks, and returns the pipeline's id."""
    pipeline_id = uuid.uuid4()
    db.execute(sa.insert(PIPELINES), [{"id": pipeline_id, "workspace_id": workspace_id, "name": "Sales",
                                       "position": 0}])
    db.execute(sa.insert(STAGES), [
        {"id": uuid.uuid4(), "workspace_id": workspace_id, "pipeline_id": pipeline_id, "name": name,
         "position": position, "kind": kind, "probability": probability, "rotting_days": rotting, "color": color}
        for position, (name, kind, probability, rotting, color) in enumerate(DEFAULT_STAGES)])
    return pipeline_id


def seed_workspace(db: Session, workspace_id: uuid.UUID) -> None:
    """`add` and `add_pipeline` for a request session: the tables are workspace scoped, so the scope moves to the new
    workspace for the inserts (sign up runs in the pre-auth scope) and goes back."""
    scope = dict(db.info.get("scope", {}))
    rescope(db, **{**scope, "workspace_id": workspace_id})
    add(db, workspace_id)
    add_pipeline(db, workspace_id)
    rescope(db, **scope)
