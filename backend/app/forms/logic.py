"""Form logic, pure and without a database, so the browser runtime can mirror it line by line (the shared fixtures in
tests/fixtures/form_logic.json are run by pytest and by node and must give the same answers).

A condition is the filter language of ADR 0002 evaluated in memory over the answers given so far:
`{"and": [...]}`, `{"or": [...]}`, `{"not": {...}}` and `{"field": key, "op": op, "value": value}`.

`flow(definition, answers)` walks the steps in order: a step or field hidden by a `hide` rule (or not revealed by a
`show` rule) is skipped, a `jump` rule sends the visitor to a later step, an `end` rule finishes the form. Conditions
see only the answers of fields that are visible, so a stale answer to a hidden field never counts."""
from dataclasses import dataclass, field

TEXT = ("short_text", "long_text", "email", "phone", "hidden")
FLAGS = ("checkbox", "consent", "yes_no")
CONTENT = ("heading", "paragraph")
ANSWERABLE = (*TEXT, "number", "select", "multi_select", "checkbox", "date", "rating", "yes_no", "consent")
OPS_BY_TYPE = {
    **dict.fromkeys(TEXT, ("is", "is_not", "contains", "in", "not_in", "is_empty", "is_not_empty")),
    **dict.fromkeys(("number", "rating"), ("is", "is_not", "gt", "gte", "lt", "lte", "in", "not_in", "is_empty",
                                           "is_not_empty")),
    "date": ("is", "is_not", "gt", "gte", "lt", "lte", "is_empty", "is_not_empty"),
    "select": ("is", "is_not", "in", "not_in", "is_empty", "is_not_empty"),
    "multi_select": ("is", "is_not", "contains", "in", "not_in", "is_empty", "is_not_empty"),
    **dict.fromkeys(("checkbox", "consent", "yes_no"), ("is", "is_not", "is_empty", "is_not_empty")),
}
NO_VALUE = ("is_empty", "is_not_empty")
LIST_VALUE = ("in", "not_in")


def is_number(x) -> bool:
    return isinstance(x, int | float) and not isinstance(x, bool)


def norm(x):
    return x.strip().lower() if isinstance(x, str) else x


def empty(x) -> bool:
    return x is None or x == [] or (isinstance(x, str) and not x.strip())


def present(f: dict, raw) -> bool:
    """Whether `raw` counts as an answer to field `f`: an unticked checkbox is no answer, a "no" is one."""
    return not empty(raw) and not (f["type"] in ("checkbox", "consent") and raw is False)


def same(a, v) -> bool:
    if isinstance(a, list):
        return isinstance(v, list) and sorted(map(str, map(norm, a))) == sorted(map(str, map(norm, v)))
    if isinstance(a, bool) or isinstance(v, bool):
        return a is v
    if is_number(a) and is_number(v):
        return a == v
    return norm(a) == norm(v)


def contains(a, v) -> bool:
    if isinstance(a, list):
        return any(same(item, v) for item in a)
    return isinstance(a, str) and isinstance(v, str) and norm(v) in norm(a)


def among(a, values) -> bool:
    return any(same(item, v) for item in (a if isinstance(a, list) else [a]) for v in values)


def compare(a, v) -> int | None:
    if is_number(a) and is_number(v) or isinstance(a, str) and isinstance(v, str):
        return (a > v) - (a < v)
    return None


def holds(cond: dict, answers: dict) -> bool:
    if "and" in cond:
        return all(holds(c, answers) for c in cond["and"])
    if "or" in cond:
        return any(holds(c, answers) for c in cond["or"])
    if "not" in cond:
        return not holds(cond["not"], answers)
    a, op, v = answers.get(cond["field"]), cond["op"], cond.get("value")
    if op == "is_empty":
        return empty(a)
    if op == "is_not_empty":
        return not empty(a)
    if empty(a):
        return op in ("is_not", "not_in")
    order = compare(a, v) if op in ("gt", "gte", "lt", "lte") else None
    return {"is": lambda: same(a, v), "is_not": lambda: not same(a, v), "contains": lambda: contains(a, v),
            "in": lambda: among(a, v), "not_in": lambda: not among(a, v),
            "gt": lambda: order is not None and order > 0, "gte": lambda: order is not None and order >= 0,
            "lt": lambda: order is not None and order < 0, "lte": lambda: order is not None and order <= 0}[op]()


@dataclass
class Flow:
    steps: list[dict] = field(default_factory=list)  # visited steps: {"key": step key, "fields": visible field keys}
    ended: bool = False
    answers: dict = field(default_factory=dict)  # the answers of visible fields

    @property
    def keys(self) -> list[str]:
        return [k for s in self.steps for k in s["fields"]]


def flow(defn: dict, answers: dict) -> Flow:
    steps, rules = defn["steps"], defn.get("logic", [])
    index = {s["key"]: i for i, s in enumerate(steps)}
    reveal: dict[str, list[dict]] = {}
    leave: dict[str, list[dict]] = {}
    for r in rules:
        where, key = (leave, r["from"]) if r["do"] in ("jump", "end") else (reveal, r["target"])
        where.setdefault(key, []).append(r)

    out, seen = Flow(), {}

    def hidden(key: str) -> bool:
        mine = reveal.get(key, [])
        shows = [r for r in mine if r["do"] == "show"]
        return (bool(shows) and not any(holds(r["when"], seen) for r in shows)) or any(
            holds(r["when"], seen) for r in mine if r["do"] == "hide")

    i = 0
    while i < len(steps) and not out.ended:
        step, i = steps[i], i + 1
        if hidden(step["key"]):
            continue
        keys = []
        for f in step["fields"]:
            if hidden(f["key"]):
                continue
            keys.append(f["key"])
            if f["type"] in ANSWERABLE and present(f, answers.get(f["key"])):
                seen[f["key"]] = answers[f["key"]]
        out.steps.append({"key": step["key"], "fields": keys})
        for r in leave.get(step["key"], []):
            if holds(r["when"], seen):
                out.ended = r["do"] == "end"
                i = index[r["target"]] if r["do"] == "jump" else i
                break
    out.answers = seen
    return out
