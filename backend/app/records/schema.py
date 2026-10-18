"""Looking up objects, fields and association types for one request. Objects and fields are rows, so a request that
touches records first needs its object's fields; the catalog loads each once."""
import uuid
from typing import Annotated

from fastapi import HTTPException
from pydantic import StringConstraints
from sqlalchemy import select

from ..security import Ctx
from .models import AssociationType, FieldDef, ObjectDef

Key = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,39}$")]
FieldKey = Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_]{0,62}$")]
Label = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
# Names a field may not take: they are record columns that filters and sorts address next to the fields.
RESERVED = {"id", "display_name", "owner_id", "created_by", "created_at", "updated_at", "deleted_at", "tag", "tags",
            "values", "relevance"}
MAX_FIELDS = 200  # ponytail: per object; the record page and the filter builder stop being usable well before this


def object_keys(c: Ctx) -> dict[uuid.UUID, str]:
    """Key of every object by id, archived ones too (their links and views remain)."""
    return dict(c.db.execute(select(ObjectDef.id, ObjectDef.key)).all())


class Catalog:
    def __init__(self, c: Ctx):
        self.c, self.db = c, c.db
        self._objects: dict[str, ObjectDef | None] = {}
        self._by_id: dict[uuid.UUID, ObjectDef | None] = {}
        self._fields: dict[uuid.UUID, dict[str, FieldDef]] = {}

    def object(self, key: str) -> ObjectDef | None:
        """The live (not archived) object with this key."""
        if key not in self._objects:
            self._objects[key] = self.db.scalar(select(ObjectDef).where(ObjectDef.key == key,
                                                                         ObjectDef.archived_at.is_(None)))
        return self._objects[key]

    def objects(self) -> list[ObjectDef]:
        """Every live object of the workspace."""
        return list(self.db.scalars(select(ObjectDef).where(ObjectDef.archived_at.is_(None))
                                    .order_by(ObjectDef.created_at, ObjectDef.key)))

    def by_id(self, object_id: uuid.UUID) -> ObjectDef | None:
        if object_id not in self._by_id:
            self._by_id[object_id] = self.db.scalar(select(ObjectDef).where(ObjectDef.id == object_id,
                                                                             ObjectDef.archived_at.is_(None)))
        return self._by_id[object_id]

    def fields(self, obj: ObjectDef) -> dict[str, FieldDef]:
        """The live fields of an object by key, in display order."""
        if obj.id not in self._fields:
            rows = self.db.scalars(select(FieldDef).where(FieldDef.object_id == obj.id, FieldDef.archived_at.is_(None))
                                   .order_by(FieldDef.position, FieldDef.created_at, FieldDef.key))
            self._fields[obj.id] = {f.key: f for f in rows}
        return self._fields[obj.id]

    def links(self, obj: ObjectDef, other: ObjectDef) -> list[tuple[AssociationType, bool]]:
        """Association types between two objects, each with whether `obj` is the type's from side."""
        rows = self.db.scalars(select(AssociationType).where(
            ((AssociationType.from_object_id == obj.id) & (AssociationType.to_object_id == other.id))
            | ((AssociationType.from_object_id == other.id) & (AssociationType.to_object_id == obj.id))))
        # a type between an object and itself reads in both directions
        return [(t, forward) for t in rows for forward in (True, False)
                if (t.from_object_id, t.to_object_id) == ((obj.id, other.id) if forward else (other.id, obj.id))]

    def need(self, key: str) -> ObjectDef:
        obj = self.object(key)
        if obj is None:
            raise HTTPException(404, "Object not found")
        return obj
