"""Whether a filter holds for a record now, and when it does not, which clause failed in words. Triggers, conditions and
goals all ask this: a top level `and` is judged clause by clause (the way stage exit rules are), so "why did this
record not enter" can name `Lifecycle stage is "lead"` and what the record has instead. The filter compiler checks every
field and operator, so a filter that stopped being valid (a field was archived) raises `FilterError` here."""
import json

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from ..records import filters
from ..records.models import Record


def clauses(ast: dict) -> list[dict]:
    return ast["and"] if set(ast) == {"and"} and isinstance(ast["and"], list) else [ast]


def describe(cat, obj, rec: Record, clause: dict) -> str:
    """The clause in words, with what the record has: `Lifecycle stage is "lead" did not hold (it is "customer")`."""
    if isinstance(clause.get("field"), str):
        key, op = clause["field"], str(clause.get("op", "")).replace("_", " ")
        field = cat.fields(obj).get(key)
        label = field.label if field else key
        value = f" {json.dumps(jsonable_encoder(clause['value']))}" if "value" in clause else ""
        have = rec.values.get(key) if field else getattr(rec, key, None)
        shown = "empty" if have in (None, "", []) else json.dumps(jsonable_encoder(have))
        return f"{label} {op}{value} did not hold (it is {shown})"
    if isinstance(clause.get("tag"), str):
        return f"the record does not have the tag {clause['tag']!r}"
    return f"{json.dumps(jsonable_encoder(clause))} did not hold"


def judge(cat, obj, rec: Record, ast: dict, root: str) -> tuple[bool, str | None]:
    """(holds, the first failing clause in words). An empty filter holds. `root` names the filter in errors."""
    parts = clauses(ast) if ast else []
    if not parts:
        return True, None
    tests = [filters.compile(cat, obj, part, root=f"{root}.and.{i}" if len(parts) > 1 else root)
             for i, part in enumerate(parts)]
    held = cat.db.execute(select(*tests).where(Record.id == rec.id)).one()
    failed = next((i for i, ok in enumerate(held) if not ok), None)
    return failed is None, None if failed is None else describe(cat, obj, rec, parts[failed])
