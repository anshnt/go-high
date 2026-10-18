"""The filter language (ADR 0002) compiled to SQLAlchemy. One JSON AST serves lists, saved views, the API and, later,
segments, workflow conditions and permissions:

    {"and": [{"field": "lifecycle", "op": "is", "value": "lead"},
             {"or": [{"tag": "vip"}, {"field": "deal.amount", "op": "gt", "value": {"amount": 500000}}]}]}

Nodes are `and`, `or`, `not`, `tag` and `field` leaves. A leaf names a field of the object (or of an associated object
as `company.name`, compiled to EXISTS) and an operator its type supports. Every field, operator and value is checked
against the field's type and a mistake is a FilterError with a pointer to the node, so a filter never becomes SQL it
did not earn: values are bound parameters and names only ever come from the catalog."""
import re
import uuid
from datetime import date, datetime
from types import SimpleNamespace

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Interval,
    Numeric,
    String,
    and_,
    case,
    cast,
    exists,
    false,
    func,
    or_,
    true,
)
from sqlalchemy.orm import aliased

from .. import permissions
from . import types
from .models import STAGE_KINDS, Association, Record, RecordTag, Stage, Tag
from .schema import Catalog

MAX_NODES, MAX_DEPTH, MAX_VALUES = 100, 8, 100
UNITS = ("minutes", "hours", "days", "weeks", "months", "years")
# Columns of the record itself that filters and sorts address like fields.
BUILTIN = {name: SimpleNamespace(key=name, type=type_, options={}, rules={}, object_id=None) for name, type_ in (
    ("display_name", "text"), ("owner_id", "user"), ("created_by", "user"), ("created_at", "datetime"),
    ("updated_at", "datetime"))}


class FilterError(ValueError):
    def __init__(self, path: str, message: str):
        super().__init__(message)
        self.path, self.message = path, message


def scalar(entity, field):
    """The field's value as a typed SQL expression. The cast is guarded by the object, because two objects may use
    one key for different types and Postgres may otherwise try the cast on the other object's rows."""
    if BUILTIN.get(field.key) is field:
        return getattr(entity, field.key)
    raw = entity.values[field.key]
    if field.type == "money":
        typed = cast(raw["amount"].astext, BigInteger)
    elif field.type in ("number", "date", "datetime", "boolean"):
        kinds = {"number": Numeric, "date": Date, "datetime": DateTime(timezone=True), "boolean": Boolean}
        typed = cast(raw.astext, kinds[field.type])
    else:
        return raw.astext
    return case((entity.object_id == field.object_id, typed))


def native(field, value):
    """The Python value to compare a normalized value with in SQL."""
    if field.type == "money":
        return value["amount"]
    if field.type == "date":
        return date.fromisoformat(value)
    if field.type == "datetime":
        return datetime.fromisoformat(value)
    if field.type == "user":
        return uuid.UUID(value)
    return value


def like(value: str, front: bool) -> str:
    return ("%" if front else "") + re.sub(r"([\\%_])", r"\\\1", value) + "%"


class Compiler:
    def __init__(self, cat: Catalog):
        self.cat, self.nodes = cat, 0

    def node(self, obj, entity, n, path: str, depth: int):
        self.nodes += 1
        if self.nodes > MAX_NODES or depth > MAX_DEPTH:
            raise FilterError(path, f"the filter is too large (at most {MAX_NODES} conditions, {MAX_DEPTH} levels)")
        if not isinstance(n, dict) or not n:
            raise FilterError(path, 'must be an object like {"field": "email", "op": "is_not_empty"}')
        for joiner in ("and", "or"):
            if joiner in n:
                items = n[joiner]
                if set(n) != {joiner} or not isinstance(items, list):
                    raise FilterError(path, f"{joiner} takes a list and nothing else")
                parts = [self.node(obj, entity, item, f"{path}.{joiner}.{i}", depth + 1)
                         for i, item in enumerate(items)]
                return and_(true(), *parts) if joiner == "and" else or_(false(), *parts)
        if "not" in n:
            if set(n) != {"not"}:
                raise FilterError(path, "not takes one condition and nothing else")
            return ~self.node(obj, entity, n["not"], f"{path}.not", depth + 1)
        if "tag" in n:
            if set(n) != {"tag"}:
                raise FilterError(path, "a tag condition has only a tag")
            return self.tag(entity, n["tag"], f"{path}.tag")
        if "field" in n:
            return self.leaf(obj, entity, n, path)
        raise FilterError(path, "expected one of and, or, not, tag or field")

    def tag(self, entity, value, path: str):
        """The record has this tag, given as its id or its name. A tag that no longer exists matches nothing."""
        if not isinstance(value, str) or not value.strip() or len(value) > 100:
            raise FilterError(path, "must be a tag name or id")
        try:
            match = Tag.id == uuid.UUID(value)
        except ValueError:
            match = func.lower(Tag.name) == value.strip().lower()
        return exists().where(RecordTag.record_id == entity.id, RecordTag.tag_id == Tag.id, match)

    def field(self, obj, key, path: str):
        field = BUILTIN.get(key) or self.cat.fields(obj).get(key)
        if field is None:
            raise FilterError(path, f"unknown field {key!r} on {obj.key}")
        return field

    def leaf(self, obj, entity, n, path: str):
        if extra := set(n) - {"field", "op", "value"}:
            raise FilterError(path, f"unexpected key {sorted(extra)[0]!r}")
        key, op = n["field"], n.get("op")
        if not isinstance(key, str):
            raise FilterError(f"{path}.field", "must be a field key")
        if not isinstance(op, str):
            raise FilterError(f"{path}.op", "an operator is required")
        if "." not in key:
            return self.condition(entity, self.field(obj, key, f"{path}.field"), op, n.get("value"), path)
        head, _, rest = key.partition(".")
        if (staged := self.cat.fields(obj).get(head)) is not None and staged.type == "stage":
            return self.stage_path(entity, staged, rest, op, n.get("value"), path)
        other = self.cat.object(head)
        if other is None or "." in rest:
            raise FilterError(f"{path}.field", f"{key!r} must be an object key and a field, like company.name")
        links = self.cat.links(obj, other)
        if not links:
            raise FilterError(f"{path}.field", f"{obj.key} has no association with {head}")
        linked = aliased(Record)
        test = and_(linked.deleted_at.is_(None), linked.object_id == other.id, self.scope(other, linked),
                    self.condition(linked, self.field(other, rest, f"{path}.field"), op, n.get("value"), path))
        sides = ((Association.from_record_id, Association.to_record_id, [t.id for t, fwd in links if fwd]),
                 (Association.to_record_id, Association.from_record_id, [t.id for t, fwd in links if not fwd]))
        return or_(false(), *[exists().where(mine == entity.id, Association.type_id.in_(ids), theirs == linked.id, test)
                              for mine, theirs, ids in sides if ids])

    def stage_path(self, entity, field, rest: str, op: str, raw, path: str):
        """`stage.kind` (open, won or lost) and `stage.pipeline` (a pipeline id) for a stage field: what the record's
        stage is, without naming its id. A record with no stage has neither."""
        column = {"kind": Stage.kind, "pipeline": Stage.pipeline_id}.get(rest)
        key = f"{field.key}.{rest}"
        if column is None:
            raise FilterError(f"{path}.field", f"{key!r} is not a stage property; use {field.key}.kind or "
                                               f"{field.key}.pipeline")
        if op not in ("is", "is_not", "in", "not_in"):
            raise FilterError(f"{path}.op", f"{op!r} does not apply to {key!r}; use is, is_not, in or not_in")
        many = op in ("in", "not_in")
        if many and not (isinstance(raw, list) and 0 < len(raw) <= MAX_VALUES):
            raise FilterError(f"{path}.value", f"must be a list of 1 to {MAX_VALUES} values")

        def one(value):
            try:
                if rest == "pipeline" and isinstance(value, str):
                    return uuid.UUID(value)
                if rest == "kind" and value in STAGE_KINDS:
                    return value
            except ValueError:
                pass
            what = "a pipeline id" if rest == "pipeline" else "open, won or lost"
            raise FilterError(f"{path}.value", f"must be {what}")

        wanted = [one(v) for v in (raw if many else [raw])]
        hit = exists().where(cast(Stage.id, String) == entity.values[field.key].astext, column.in_(wanted))
        return ~hit if op in ("is_not", "not_in") else hit

    def scope(self, obj, entity):
        return Compiler(self.cat).node(obj, entity, permissions.scope_filter(self.cat.c, obj), "scope", 0)

    def coerce(self, field, raw, path: str):
        if field.type in types.CHOICES:  # a view may name a choice that was deleted since; that matches nothing
            if not isinstance(raw, str) or not raw:
                raise FilterError(path, "must be a choice id")
            return raw
        if field.type == "datetime" and isinstance(raw, str) and types.DATE.fullmatch(raw.strip()):
            raw = raw.strip() + "T00:00:00Z"
        try:
            value = types.validate(field, raw)
        except ValueError as e:
            raise FilterError(path, f"{field.key} {e}") from None
        if value is None:
            raise FilterError(path, "needs a value")
        return value

    def values(self, field, raw, path: str, count: int | None = None):
        if not isinstance(raw, list) or not raw or len(raw) > MAX_VALUES or (count and len(raw) != count):
            raise FilterError(path, f"must be a list of {count or f'1 to {MAX_VALUES}'} values")
        return [self.coerce(field, v, f"{path}.{i}") for i, v in enumerate(raw)]

    def interval(self, raw, path: str):
        if (not isinstance(raw, dict) or len(raw) != 1 or next(iter(raw)) not in UNITS
                or isinstance(n := next(iter(raw.values())), bool) or not isinstance(n, int) or not 0 < n <= 100000):
            raise FilterError(path, f'must look like {{"days": 30}}, with one of {", ".join(UNITS)}')
        return cast(f"{n} {next(iter(raw))}", Interval)

    def condition(self, entity, field, op: str, raw, path: str):
        kind = types.TYPES[field.type]
        if op not in kind.ops:
            hint = f"use one of: {', '.join(sorted(kind.ops))}" if kind.ops else "it is computed and cannot be filtered"
            raise FilterError(f"{path}.op", f"{op!r} does not apply to the {field.type} field {field.key!r}; {hint}")
        vpath = f"{path}.value"
        builtin = BUILTIN.get(field.key) is field
        multi = field.type == "multi_select"
        has = scalar(entity, field).is_not(None) if builtin else entity.values.has_key(field.key)
        if op in ("is_empty", "is_not_empty"):
            return ~has if op == "is_empty" else has

        def one(value):  # the record's value equals `value`; for a multi select, it includes it
            if builtin:
                return func.coalesce(scalar(entity, field) == native(field, value), false())
            return entity.values.contains({field.key: [value] if multi else value})

        if op in ("is", "is_not") or (op == "contains" and multi):
            value = self.coerce(field, raw, vpath)
            hit = one(value)
            if field.type == "boolean" and value is False:
                hit = or_(hit, ~has)  # an unticked checkbox was never set: "is false" means "not true"
            return ~hit if op == "is_not" else hit
        if op in ("in", "not_in"):
            hit = or_(false(), *[one(v) for v in self.values(field, raw, vpath)])
            return ~hit if op == "not_in" else hit
        x = scalar(entity, field)
        if op in ("contains", "starts_with"):
            if not isinstance(raw, str) or not raw.strip() or len(raw) > 200 or "\x00" in raw:
                raise FilterError(vpath, "must be some text")
            return func.coalesce(x.ilike(like(raw.strip(), op == "contains"), escape="\\"), false())
        if op in ("within_last", "older_than"):
            span = self.interval(raw, vpath)
            now = func.current_date() if field.type == "date" else func.now()
            edge = cast(now - span, Date) if field.type == "date" else now - span
            test = and_(x >= edge, x <= now) if op == "within_last" else x < edge
            return func.coalesce(test, false())
        bounds = self.values(field, raw, vpath, 2) if op == "between" else [self.coerce(field, raw, vpath)]
        if field.type == "money" and len({b["currency"] for b in bounds}) != 1:
            raise FilterError(vpath, "both amounts need the same currency")
        a = [native(field, b) for b in bounds]
        test = (x.between(a[0], a[1]) if op == "between"
                else {"gt": x > a[0], "gte": x >= a[0], "lt": x < a[0], "lte": x <= a[0]}[op])
        if field.type == "money":  # an amount only compares with the same currency
            test = and_(test, entity.values[field.key]["currency"].astext == bounds[0]["currency"])
        return func.coalesce(test, false())


def compile(cat: Catalog, obj, ast, *, entity=Record, root: str = "filter"):
    """The SQL condition for `ast` over `entity` (Record or an alias of it) of object `obj`; {} is everything."""
    if not ast:
        return true()
    return Compiler(cat).node(obj, entity, ast, root, 0)


def search_terms(q: str) -> str | None:
    """A tsquery that matches every word of `q` as a prefix (so "ada lov" finds Ada Lovelace), or None for no words.
    Words keep only letters, digits and @ . + - _ (the characters an email or phone token has) and go into the query
    as quoted literals, so none of them can be tsquery syntax."""
    words = [w[:64] for w in re.findall(r"[\w@.+\-]+", q.lower())[:8]]
    return " & ".join(f"'{w}':*" for w in words) or None

