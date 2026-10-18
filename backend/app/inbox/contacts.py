"""Finding the contact behind an inbound message, or making one (ADR 0005): by `phone_e164` or `email_norm`, through the
record store so validation, display name and events are the same as for a contact made in the app."""
import uuid

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from ..api import ApiError
from ..records import store, types
from ..records.models import ObjectDef, Record
from ..records.schema import Catalog


class Unusable(Exception):
    """A sender that cannot become a contact (a short code, an alphanumeric sender id)."""


def lock(db: Session, workspace_id: uuid.UUID, identity: str) -> None:
    """Held to the end of the transaction, so two messages from one unknown sender make one contact, not two."""
    db.execute(text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"), {"key": f"{workspace_id}:{identity}"})


def find(cat: Catalog, obj: ObjectDef, *, email: str | None = None, phone: str | None = None) -> Record | None:
    """The oldest live contact with this email or phone (duplicates are for the dedupe queue, module 09)."""
    keys = [Record.email_norm == email.lower()] if email else []
    keys += [Record.phone_e164 == phone] if phone else []
    if not keys:
        return None
    return cat.db.scalar(select(Record).where(Record.workspace_id == cat.c.workspace.id, Record.object_id == obj.id,
                                              Record.deleted_at.is_(None), or_(*keys)).order_by(Record.created_at)
                         .limit(1))


def create(cat: Catalog, obj: ObjectDef, values: dict, source: str) -> Record:
    """A contact from what the channel knows. `source` (the channel kind) fills the contact's `source` field."""
    field = cat.fields(obj).get("source")
    if field is not None and field.type == "select" and source in types.choice_ids(field):
        values = {**values, "source": source}
    try:
        return store.create(cat, obj, values, None)
    except ApiError as e:
        if e.status_code != 422:  # a role that may not create contacts is a setup problem: say so, do not drop mail
            raise
        raise Unusable(str(e.fields or e.detail)) from None
