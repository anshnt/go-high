"""Listing records (ADR 0002, module 08): filter, full text search with prefix matching, sort, keyset pagination with a
signed cursor, expansion of tags and associations, and counts. One function serves lists, saved views and counts."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import NamedTuple

from sqlalchemy import ARRAY, Double, Text, and_, cast, false, func, literal, or_, select
from sqlalchemy.dialects.postgresql import REGCONFIG, TSQUERY, array

from .. import permissions
from ..api import ApiError, seal, unseal
from . import associations, filters, tags, types
from .models import ObjectDef, Record
from .schema import Catalog
from .store import live, record_json

MAX_SORTS = 3
COLUMNS = {"display_name": (Record.display_name, "str"), "created_at": (Record.created_at, "ts"),
           "updated_at": (Record.updated_at, "ts")}
KINDS = {"number": "num", "money": "int", "date": "date", "datetime": "ts", "boolean": "bool"}
LOAD = {"ts": datetime.fromisoformat, "date": date.fromisoformat, "num": Decimal, "int": int, "bool": bool,
        "float": float, "str": str}


class Key(NamedTuple):
    name: str
    expr: object
    kind: str
    desc: bool


def invalid(field: str, message: str, status: int = 400) -> ApiError:
    return ApiError(status, "validation_failed", f"The {field} is not valid", {field: message})


def where_of(cat: Catalog, obj: ObjectDef, ast, root: str = "filter"):
    """The filter as SQL; a mistake in it is a 400 that points at the node, never an error from the database."""
    try:
        return filters.compile(cat, obj, ast, root=root)
    except filters.FilterError as e:
        raise ApiError(400, "validation_failed", "The filter is not valid", {e.path: e.message}) from None


def sort_keys(cat: Catalog, obj: ObjectDef, spec, rank) -> list[Key]:
    """`-updated_at,display_name`: a leading minus is descending, nulls come last either way. `relevance` ranks a
    text search. The default is the newest change first (what the list index serves), best match first for a search.
    ponytail: select fields sort by choice id, not by the order of their choices."""
    items = [s.strip() for s in (spec.split(",") if isinstance(spec, str) else spec or []) if s.strip()]
    items = items or ["-relevance" if rank is not None else "-updated_at"]
    if len(items) > MAX_SORTS:
        raise invalid("sort", f"sort by at most {MAX_SORTS} fields")
    fields, keys, hidden = cat.fields(obj), [], permissions.hidden(cat.c, obj)
    for item in items:
        desc, name = item.startswith("-"), item.removeprefix("-")
        if name == "relevance" and rank is not None:
            expr, kind = rank, "float"
        elif name in COLUMNS and name not in hidden:
            expr, kind = COLUMNS[name]
        elif name in fields and name not in hidden and fields[name].type in types.SORTABLE:
            expr, kind = filters.scalar(Record, fields[name]), KINDS.get(fields[name].type, "str")
        else:
            raise invalid("sort", f"cannot sort {obj.key} by {name!r}")
        if any(k.name == name for k in keys):
            raise invalid("sort", f"{name!r} is listed twice")
        keys.append(Key(name, expr, kind, desc))
    return keys


def after(keys: list[Key], values: list, last_id, id_desc: bool):
    """Rows strictly after the cursor row in the sort order, with nulls last: per key, "beyond the value, or null",
    given that all earlier keys tie. The id closes every tie, so no row repeats or goes missing between pages."""
    clauses, tied = [], []
    for key, value in zip(keys, values, strict=True):
        if value is not None:
            bound = literal(value)  # also for True and False, which a bare comparison treats as keywords
            beyond = key.expr < bound if key.desc else key.expr > bound
            clauses.append(and_(*tied, or_(beyond, key.expr.is_(None))))
        tied.append(key.expr.is_(None) if value is None else key.expr == literal(value))
    clauses.append(and_(*tied, Record.id < last_id if id_desc else Record.id > last_id))
    return or_(*clauses)


def signature(keys: list[Key]) -> list[str]:
    return [f"{'-' if k.desc else ''}{k.name}" for k in keys]


def dump(value):
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return value.isoformat() if isinstance(value, datetime | date) else str(value)


def read_cursor(cursor: str, keys: list[Key]):
    try:
        sig, values, last_id = unseal(cursor)
        if sig != signature(keys) or len(values) != len(keys):
            raise ValueError("another sort")
        return [None if v is None else LOAD[k.kind](v) for k, v in zip(keys, values, strict=True)], uuid.UUID(last_id)
    except (ValueError, TypeError, KeyError):
        raise ApiError(400, "invalid_cursor", "The cursor is not valid for this sort") from None


def search_vector(cat: Catalog, obj: ObjectDef):
    """What `q` searches: the indexed column, or, for a role that hides fields of this object, the same text built
    without them, so a hidden value cannot be found by searching for it.
    ponytail: that text is built per row, without the index; fine for a role's slice of a workspace, and a partial
    index per role is the way out if a restricted role searches millions of records."""
    hidden = permissions.hidden(cat.c, obj)
    if not hidden:
        return Record.search
    values = Record.values.op("-")(cast(array(sorted(hidden - {"display_name"}), type_=Text), ARRAY(Text)))
    name = literal("") if "display_name" in hidden else func.coalesce(Record.display_name, "")
    simple = cast(literal("simple"), REGCONFIG)
    return func.setweight(func.to_tsvector(simple, name), "A").op("||")(
        func.setweight(func.to_tsvector(simple, values), "B"))


def include_names(cat: Catalog, obj: ObjectDef, names: list[str]) -> list[tuple[str, ObjectDef | None]]:
    out = []
    for name in dict.fromkeys(names):
        if name == "tags":
            out.append((name, None))
            continue
        other = cat.object(name)
        if other is None or not cat.links(obj, other):
            raise invalid("include", f"{name!r} is not tags or an object associated with {obj.key}")
        out.append((name, other))
    return out


def decorate(cat: Catalog, obj: ObjectDef, records: list[Record], expand) -> list[dict]:
    """Record JSON, with the tags and associated records asked for by `include`, one query per kind."""
    data, ids = [record_json(cat, obj, r) for r in records], [r.id for r in records]
    for name, other in expand:
        found = tags.of(cat.db, ids) if other is None else associations.expand(cat, obj, other, ids)
        for d in data:
            if other is None:
                d["tags"] = found.get(d["id"], [])
            else:
                d.setdefault("associations", {})[name] = found.get(d["id"], [])
    return data


def run(cat: Catalog, obj: ObjectDef, *, ast=None, sort=None, q: str | None = None, limit: int = 50,
        cursor: str | None = None, include: list[str] | None = None, count: bool = False) -> dict:
    expand = include_names(cat, obj, include or [])
    terms = filters.search_terms(q) if q else None
    tsquery = cast(terms, TSQUERY) if terms else None
    where = [*live(cat, obj), where_of(cat, obj, ast)]
    vector = search_vector(cat, obj)
    if q:  # a query without words ("!!!") finds nothing
        where.append(vector.bool_op("@@")(tsquery) if terms else false())
    keys = sort_keys(cat, obj, sort, cast(func.ts_rank(vector, tsquery), Double) if terms else None)
    id_desc = keys[0].desc
    stmt = select(Record, *[k.expr for k in keys]).where(*where)
    if cursor:
        values, last_id = read_cursor(cursor, keys)
        stmt = stmt.where(after(keys, values, last_id, id_desc))
    order = [(k.expr.desc() if k.desc else k.expr.asc()).nulls_last() for k in keys]
    rows = cat.db.execute(stmt.order_by(*order, Record.id.desc() if id_desc else Record.id.asc())
                          .limit(limit + 1)).all()
    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        next_cursor = seal([signature(keys), [dump(v) for v in page[-1][1:]], str(page[-1][0].id)])
    out = {"data": decorate(cat, obj, [row[0] for row in page], expand), "next_cursor": next_cursor}
    if count:
        out["total"] = cat.db.scalar(select(func.count()).select_from(Record).where(*where))
    return out


def total(cat: Catalog, obj: ObjectDef, ast) -> int:
    """How many live records of `obj` the caller may see match `ast` (a saved view's live count)."""
    return cat.db.scalar(select(func.count()).select_from(Record).where(*live(cat, obj), where_of(cat, obj, ast)))
