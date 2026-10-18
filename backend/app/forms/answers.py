"""Checking what a visitor sent: every visible question is validated by the record engine's own field types (one
validator for the API, imports, forms and workflows), required questions must be answered, and a quiz is scored."""
from types import SimpleNamespace

from ..records import types
from . import logic

CAPS = {"short_text": 1000, "long_text": 5000, "hidden": 500}
RECORD_TYPE = {"short_text": "text", "long_text": "long_text", "hidden": "text", "email": "email", "phone": "phone",
               "number": "number", "select": "select", "multi_select": "multi_select", "date": "date",
               "rating": "number", **dict.fromkeys(logic.FLAGS, "boolean")}


def shim(f: dict, contact_fields: dict | None = None):
    """The form field as a record field, so `records.types.validate` can check it."""
    t, v = f["type"], f.get("validation", {})
    rules = {k: v[k] for k in ("min_length", "max_length", "min", "max", "integer", "max_items") if k in v}
    if t in CAPS:
        rules["max_length"] = min(rules.get("max_length", CAPS[t]), CAPS[t])
    if t == "rating":
        rules |= {"min": 1, "max": 5, "integer": True}
    options: dict = {"choices": f.get("options", [])}
    mapped = (contact_fields or {}).get(f.get("maps_to"))
    if t == "phone":
        region = v.get("region") or (mapped.options.get("region") if mapped is not None else None)
        options = {"region": region} if region else {}
    return SimpleNamespace(type=RECORD_TYPE[t], options=options, rules=rules)


def check(f: dict, raw, contact_fields: dict | None = None):
    """The normalized answer to `f`, or None when it is empty. Raises ValueError (a sentence ending, like the record
    engine's) for an answer that is not valid."""
    if f["type"] in logic.FLAGS and raw is False:
        return False if f["type"] == "yes_no" else None
    value = types.validate(shim(f, contact_fields), raw)
    if f["type"] == "multi_select" and value is not None and len(value) < f.get("validation", {}).get("min_items", 0):
        raise ValueError(f"needs at least {f['validation']['min_items']} choices")
    return value


def validate(defn: dict, answers: dict, fl: logic.Flow, contact_fields: dict | None = None) -> tuple[dict, dict]:
    """(clean answers, errors by field key) for the visible questions of `fl`. Answers to anything else are dropped."""
    fields = {f["key"]: f for s in defn["steps"] for f in s["fields"]}
    clean: dict = {}
    errors: dict[str, str] = {}
    for key in fl.keys:
        f = fields[key]
        if f["type"] in logic.CONTENT:
            continue
        try:
            value = check(f, answers.get(key), contact_fields)
        except ValueError as e:
            errors[key] = f"{f['label']} {e}"
            continue
        if value is None:
            if f.get("required"):
                errors[key] = ("This box must be ticked" if f["type"] in ("consent", "checkbox")
                           else f"{f['label']} is required")
            continue
        clean[key] = value
    return clean, errors


def partial(defn: dict, answers) -> dict:
    """What an autosave keeps: answers to questions of the form, as long as they are plain values. Nothing is
    validated yet (a half typed email is fine); `complete` checks it all."""
    fields = {f["key"]: f for s in defn["steps"] for f in s["fields"] if f["type"] in logic.ANSWERABLE}
    out = {}
    for key, raw in (answers.items() if isinstance(answers, dict) else ()):
        f = fields.get(key)
        scalar = isinstance(raw, str | bool) or logic.is_number(raw)
        ok = scalar or (isinstance(raw, list) and len(raw) <= 50 and all(isinstance(x, str) for x in raw))
        ok = ok and "\x00" not in str(raw)  # Postgres text and jsonb cannot hold NUL
        if f is None or not ok or not logic.present(f, raw):
            continue
        out[key] = raw[: CAPS.get(f["type"], 1000)] if isinstance(raw, str) else raw
    return out


def last_answered(defn: dict, answers: dict) -> str | None:
    """The last question, in form order, that has an answer: where a visitor who left was."""
    keys = [f["key"] for s in defn["steps"] for f in s["fields"] if f["key"] in answers]
    return keys[-1] if keys else None


def correct(f: dict, a) -> bool:
    expected = f["quiz"]["correct"]
    if f["type"] == "multi_select":
        return isinstance(a, list) and logic.same(a, expected)
    if f["type"] == "short_text":
        accepted = expected if isinstance(expected, list) else [expected]
        return isinstance(a, str) and any(logic.same(a, e) for e in accepted)
    return logic.same(a, expected)


def score(defn: dict, fl: logic.Flow, answers: dict) -> dict | None:
    """The quiz result over the questions the visitor was shown: points, percentage (rounded down), whether the pass
    mark was met, the band, and which questions were right. None when the form has no scored question.
    Integer arithmetic only, so the browser gives the same numbers."""
    fields = {f["key"]: f for s in defn["steps"] for f in s["fields"]}
    scored = [fields[k] for k in fl.keys if "quiz" in fields[k]]
    if not scored:
        return None
    review = {f["key"]: correct(f, answers.get(f["key"])) for f in scored}
    got = sum(f["quiz"]["points"] for f in scored if review[f["key"]])
    top = sum(f["quiz"]["points"] for f in scored)
    settings = defn.get("quiz", {})
    mark = settings.get("pass_mark")
    band = next((b for b in reversed(settings.get("bands", [])) if got * 100 >= b["min"] * top), None)
    return {"score": got, "max_score": top, "percent": got * 100 // top, "review": review,
            "passed": None if mark is None else got * 100 >= mark * top,
            "band": {"title": band["title"], "message": band["message"]} if band else None}


def consent_evidence(defn: dict, fl: logic.Flow, clean: dict, when: str, form_id: str, ip_hash: str) -> dict:
    """Proof of opt-in for each consent box that was ticked: the exact words shown, when, on which form and version,
    and a keyed hash of the visitor's address."""
    fields = {f["key"]: f for s in defn["steps"] for f in s["fields"]}
    return {k: {"text": fields[k]["label"], "at": when, "form_id": form_id, "ip_hash": ip_hash}
            for k in fl.keys if fields[k]["type"] == "consent" and clean.get(k) is True}


def contact_values(defn: dict, clean: dict, contact_fields: dict) -> dict:
    """The contact values the answers write: only non-empty answers of questions mapped to a field that exists. A
    choice that fills a text field writes its label."""
    out = {}
    for s in defn["steps"]:
        for f in s["fields"]:
            target, value = f.get("maps_to"), clean.get(f["key"])
            if target is None or value is None or target not in contact_fields:
                continue
            if f["type"] == "select" and contact_fields[target].type == "text":
                value = next(o["label"] for o in f["options"] if o["id"] == value)
            out[target] = value
    return out

