"""The contact behind a response: found by the email or phone it gave (the record engine's `email_norm` and
`phone_e164` keys), or created. Written through the record store, so validation, the display name and the
`record.created` and `record.updated` events are the same as for any other write. An empty answer never blanks a
field that has a value: only answers that hold something are sent."""
import uuid

from sqlalchemy import func, select

from ..records import store
from ..records.models import ObjectDef, Record
from ..records.schema import Catalog


def find(cat: Catalog, obj: ObjectDef, values: dict) -> Record | None:
    """The oldest live contact with the email of `values`, else the oldest with its phone. Duplicates are allowed
    (the dedupe queue, module 09, merges them); the oldest one is the one that keeps receiving updates."""
    email, phone = store.identity(cat.fields(obj), values)
    for column, key in ((Record.email_norm, email), (Record.phone_e164, phone)):
        if key is not None:
            found = cat.db.scalar(select(Record).where(*store.live(cat, obj), column == key)
                                  .order_by(Record.created_at, Record.id).limit(1))
            if found is not None:
                return found
    return None


def form_source(fields: dict) -> str | None:
    """The choice of the contact's `source` field that says a form brought the contact in, if the workspace has one."""
    f = fields.get("source")
    if f is None or f.type != "select":
        return None
    return next((c["id"] for c in f.options.get("choices", []) if c["id"] == "form" or c["label"].lower() == "form"),
                None)


# ponytail: forms write to the contact object only; deals and custom objects follow when a form needs them.
def upsert(cat: Catalog, values: dict, existing: str) -> tuple[uuid.UUID, bool]:
    """(contact id, whether it was created). A new contact gets `source = form`; a known one never has its source
    touched. `existing`: `fill_empty` only fills fields the contact has no value for, which keeps a stranger's answer
    from rewriting what the business already knows; `update` writes every answer."""
    obj = cat.need("contact")
    email, phone = store.identity(cat.fields(obj), values)
    key = email or phone
    if key:  # two answers with the same new address at once must not make two contacts
        cat.db.execute(select(func.pg_advisory_xact_lock(func.hashtextextended(f"{cat.c.workspace.id}:{key}", 0))))
    rec = find(cat, obj, values)
    if rec is None:
        source = form_source(cat.fields(obj))
        return store.create(cat, obj, {**({"source": source} if source and "source" not in values else {}), **values},
                            None).id, True
    rec = store.get(cat, obj, rec.id, lock=True)
    patch = values if existing == "update" else {k: v for k, v in values.items() if k not in rec.values}
    if patch:
        store.update(cat, obj, rec, patch)
    return rec.id, False
