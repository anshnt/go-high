"""The contact behind a booking. Whoever books is found by email, else by phone, among the live contacts; a new person
becomes a contact owned by the host. A contact that exists is only ever filled in: a name, email or phone the person
leaves out, or the contact already has, is never blanked or overwritten. Everything goes through the record store, so
the field rules, the record events and the permissions of the Automation role apply as they do to any other writer."""
import uuid
from typing import NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..api import ApiError
from ..models import Role, Workspace
from ..records import store, types
from ..records.models import Record
from ..records.schema import Catalog
from ..security import Ctx


class Invitee(NamedTuple):
    name: str
    email: str | None
    phone: str | None


def system_ctx(db: Session, ws: Workspace) -> Ctx:
    """A request context for work nobody signed in for (a visitor booking): no user, and the workspace's Automation
    role, which is what workflows run as too (ADR 0004). The session must already be scoped to the workspace."""
    role = db.scalar(select(Role).where(Role.org_id == ws.org_id, Role.key == "automation"))
    return Ctx(db, None, None, "", ws, "automation", role)  # type: ignore[arg-type]  # no user, no session


def split(name: str) -> dict:
    first, _, last = name.strip().partition(" ")
    return {k: v.strip() for k, v in (("first_name", first), ("last_name", last)) if v.strip()}


def clean(cat: Catalog, invitee: Invitee) -> Invitee:
    """The email and phone as the contact fields normalize them (lower case, E.164), or a 422 naming the field."""
    fields, errors, out = cat.fields(cat.need("contact")), {}, {}
    for key, raw in (("email", invitee.email), ("phone", invitee.phone)):
        if not raw:
            continue
        try:
            out[key] = types.validate(fields[key], raw)
        except ValueError as e:
            errors[key] = f"{fields[key].label} {e}"
    if errors:
        raise ApiError(422, "validation_failed", "The details are not valid", errors)
    return Invitee(invitee.name.strip(), out.get("email"), out.get("phone"))


def find(cat: Catalog, who: Invitee) -> Record | None:
    obj = cat.need("contact")
    for column, value in ((Record.email_norm, who.email), (Record.phone_e164, who.phone)):
        if value:
            found = cat.db.scalar(select(Record).where(*store.live(cat, obj), column == value)
                                  .order_by(Record.created_at, Record.id).limit(1))
            if found:
                return found
    return None


def attach(cat: Catalog, who: Invitee, host_id: uuid.UUID | None) -> Record:
    """The contact for this person: created (owned by the host) or, if it exists, filled in where it is blank."""
    obj = cat.need("contact")
    wanted = {**split(who.name), **{k: v for k, v in (("email", who.email), ("phone", who.phone)) if v}}
    found = find(cat, who)
    if found is None:
        return store.create(cat, obj, wanted, owner_id=host_id)
    rec = store.get(cat, obj, found.id, lock=True)
    patch = {k: v for k, v in wanted.items() if not rec.values.get(k)}
    if patch:
        store.update(cat, obj, rec, patch)
    return rec


def visible(c: Ctx, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    """Display names of those contacts the caller may see; the rest are left out, as everywhere else."""
    if not ids:
        return {}
    cat = Catalog(c)
    obj = cat.object("contact")
    if obj is None:
        return {}
    rows = c.db.scalars(select(Record).where(*store.live(cat, obj), Record.id.in_(ids)))
    return {r.id: store.shown_name(cat, obj, r) for r in rows}
