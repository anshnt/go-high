"""Finding the contact behind an inbound message, or making one (ADR 0005): by `phone_e164` or `email_norm`, through the
record store so validation, display name and events are the same as for a contact made in the app."""
import uuid

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session

from ..api import ApiError
from ..records import store
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
    """A contact from what the channel knows. `source` fills the contact's `source` field when the workspace has
    one (the system objects do not define it yet)."""
    field = cat.fields(obj).get("source")
    if field is not None and field.type == "text":
        values = {**values, "source": source}
    try:
        return store.create(cat, obj, values, None)
    except ApiError as e:
        raise Unusable(str(e.fields or e.detail)) from None


def find_or_create(cat: Catalog, *, email: str | None = None, phone: str | None = None,
                   source: str) -> tuple[Record, bool]:
    """(contact, whether it was just created). The caller holds `lock` for the identity."""
    obj = cat.need("contact")
    found = find(cat, obj, email=email, phone=phone)
    if found:
        return found, False
    return create(cat, obj, {k: v for k, v in (("email", email), ("phone", phone)) if v}, source), True
