"""What a form is (the JSON stored in `form_versions.definition`), what its settings are, and the checks that keep both
sound. A saved definition is always valid: bad logic references, unknown option ids or a mapping to a field that does
not exist are refused when the version is saved, never discovered by a visitor.

    {"title": "Get a quote", "steps": [{"key": "about", "title": "About you", "fields": [
        {"key": "email", "type": "email", "label": "Email", "required": true, "maps_to": "email"}]}],
     "logic": [{"when": {"field": "size", "op": "is", "value": "big"}, "do": "jump", "from": "about",
                "target": "team"}],
     "quiz": {"pass_mark": 60, "bands": [{"min": 0, "title": "Keep going", "message": "..."}]}}

Keys of steps and fields share one namespace (`^[a-z][a-z0-9_]{0,39}$`). A rule's conditions may only look at fields
that come earlier than what the rule controls, which also rules out loops."""
import re
import secrets
from typing import Annotated, Literal
from urllib.parse import urlsplit

import phonenumbers
from pydantic import AfterValidator, AwareDatetime, BaseModel, Field, StringConstraints

from ..auth import Email
from ..records import types
from . import logic

KEY = re.compile(r"[a-z][a-z0-9_]{0,39}")
FIELD_TYPES = (*logic.ANSWERABLE, *logic.CONTENT)
QUIZ_TYPES = ("select", "multi_select", "yes_no", "rating", "number", "short_text")
LABEL_CAP = {"heading": 200, "paragraph": 2000, "consent": 1000}
MAX_STEPS, MAX_FIELDS, MAX_OPTIONS, MAX_RULES, MAX_NODES, MAX_DEPTH = 30, 200, 50, 100, 50, 6
KEYS = {"top": {"title", "description", "submit_label", "steps", "logic", "quiz"},
        "step": {"key", "title", "description", "fields"},
        "field": {"key", "type", "label", "help", "placeholder", "required", "options", "validation", "maps_to",
                  "param", "quiz"},
        "rule": {"id", "when", "do", "target", "from"}}
VALIDATION = {"short_text": {"min_length", "max_length"}, "long_text": {"min_length", "max_length"},
              "phone": {"region"}, "number": {"min", "max", "integer"}, "multi_select": {"min_items", "max_items"}}
# contact field types a form field type can write to
COMPATIBLE = {"short_text": ("text", "url"), "long_text": ("text", "long_text"), "hidden": ("text", "url"),
              "email": ("email",), "phone": ("phone",), "number": ("number",), "rating": ("number",),
              "date": ("date",), "select": ("select", "text"), "multi_select": ("multi_select",),
              **dict.fromkeys(logic.FLAGS, ("boolean",))}


class DefinitionError(Exception):
    def __init__(self, fields: dict[str, str]):
        super().__init__("invalid definition")
        self.fields = fields


class Checker:
    def __init__(self, kind: str):
        self.kind, self.errors = kind, {}
        self.fields: dict[str, dict] = {}  # key -> field
        self.where: dict[str, tuple[int, int]] = {}  # key -> (step index, field index); steps are (index, -1)

    def bad(self, path: str, message: str) -> None:
        self.errors.setdefault(path, message)

    def unknown(self, obj: dict, allowed: set[str], path: str) -> None:
        for k in sorted(obj.keys() - allowed):
            self.bad(f"{path}.{k}" if path else k, "is not a known setting")

    def text(self, obj: dict, name: str, path: str, cap: int, required: bool = False) -> str | None:
        value, at = obj.get(name), f"{path}.{name}" if path else name
        if value is None and not required:
            return None
        if value is not None and (not isinstance(value, str) or "\x00" in value):
            self.bad(at, "must be text")
            return None
        if value is None or (required and not value.strip()):
            self.bad(at, "is required")
            return None
        if len(value.strip()) > cap:
            self.bad(at, f"must be at most {cap} characters")
        return value.strip()


def key_of(ck: Checker, obj: dict, path: str, seen: set[str]) -> str | None:
    key = obj.get("key")
    if not isinstance(key, str) or not KEY.fullmatch(key):
        ck.bad(f"{path}.key", "must be lower case letters, digits and _, starting with a letter (40 at most)")
        return None
    if key in seen:
        ck.bad(f"{path}.key", f"{key!r} is used twice")
    seen.add(key)
    return key


def whole(x) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def check_validation(ck: Checker, f: dict, path: str) -> dict:
    v = f.get("validation", {})
    if not isinstance(v, dict):
        ck.bad(f"{path}.validation", "must be an object")
        return {}
    allowed = VALIDATION.get(f["type"], set())
    ck.unknown(v, allowed, f"{path}.validation")
    for name in v.keys() & allowed:
        if name == "integer":
            ok = isinstance(v[name], bool)
        elif name == "region":
            ok = isinstance(v[name], str) and v[name].upper() in phonenumbers.SUPPORTED_REGIONS
        elif name in ("min", "max"):
            ok = logic.is_number(v[name]) and abs(v[name]) <= types.MAX_MONEY
        else:
            ok = whole(v[name]) and 0 <= v[name] <= types.LONG_TEXT_CAP
        if not ok:
            ck.bad(f"{path}.validation.{name}", "is not valid")
    if "min" in v and "max" in v and logic.is_number(v["min"]) and logic.is_number(v["max"]) and v["min"] > v["max"]:
        ck.bad(f"{path}.validation.min", "is above the maximum")
    for low, high in (("min_length", "max_length"), ("min_items", "max_items")):
        if whole(v.get(low)) and whole(v.get(high)) and v[low] > v[high]:
            ck.bad(f"{path}.validation.{low}", "is above the maximum")
    return v


def check_quiz_answer(ck: Checker, f: dict, path: str) -> dict | None:
    q = f.get("quiz")
    if q is None:
        return None
    if ck.kind != "quiz" or f["type"] not in QUIZ_TYPES:
        ck.bad(f"{path}.quiz", "only questions of a quiz can be scored" if ck.kind != "quiz"
               else f"a {f['type']} field cannot be scored")
        return None
    if not isinstance(q, dict) or q.keys() != {"correct", "points"}:
        ck.bad(f"{path}.quiz", "needs correct and points")
        return None
    ids, correct, t = {o["id"] for o in f.get("options", [])}, q["correct"], f["type"]
    ok = {"select": isinstance(correct, str) and correct in ids,
          "multi_select": isinstance(correct, list) and bool(correct) and all(c in ids for c in correct),
          "yes_no": isinstance(correct, bool), "rating": whole(correct) and 1 <= correct <= 5,
          "number": logic.is_number(correct),
          "short_text": isinstance(correct, str) and bool(correct.strip()) or (
              isinstance(correct, list) and 0 < len(correct) <= 10 and all(isinstance(c, str) and c.strip()
                                                                           for c in correct))}[t]
    if not ok:
        ck.bad(f"{path}.quiz.correct", "is not a valid answer for this question")
    if not whole(q["points"]) or not 1 <= q["points"] <= 100:
        ck.bad(f"{path}.quiz.points", "must be a whole number from 1 to 100")
    return q


def check_field(ck: Checker, f, path: str, seen: set[str], at: tuple[int, int]) -> dict | None:
    if not isinstance(f, dict):
        ck.bad(path, "must be an object")
        return None
    ck.unknown(f, KEYS["field"], path)
    key = key_of(ck, f, path, seen)
    t = f.get("type")
    if t not in FIELD_TYPES:
        ck.bad(f"{path}.type", f"must be one of {', '.join(FIELD_TYPES)}")
        return None
    out = {"key": key, "type": t, "label": ck.text(f, "label", path, LABEL_CAP.get(t, 300), required=True)}
    for name, cap in (("help", 500), ("placeholder", 200)):
        if (value := ck.text(f, name, path, cap)) is not None:
            out[name] = value
    if "required" in f:
        if not isinstance(f["required"], bool) or (f["required"] and t in (*logic.CONTENT, "hidden")):
            ck.bad(f"{path}.required", "must be true or false (and a hidden field or text block is never required)")
        elif f["required"]:
            out["required"] = True
    choices = t in ("select", "multi_select")
    if choices:
        try:
            options = types.clean_choices(f.get("options", []))
            if not options or len(options) > MAX_OPTIONS:
                raise ValueError(f"needs 1 to {MAX_OPTIONS} options")
            out["options"] = [{"id": o["id"], "label": o["label"]} for o in options]
        except ValueError as e:
            ck.bad(f"{path}.options", str(e))
    elif "options" in f:
        ck.bad(f"{path}.options", f"a {t} field has no options")
    if v := check_validation(ck, f, path):
        out["validation"] = v
    if "maps_to" in f:
        maps_to = f["maps_to"]
        if t in logic.CONTENT or not isinstance(maps_to, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,62}", maps_to):
            ck.bad(f"{path}.maps_to", "must be the key of a contact field (not for a text block)")
        else:
            out["maps_to"] = maps_to
    if "param" in f:
        if t != "hidden" or not isinstance(f["param"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,60}", f["param"]):
            ck.bad(f"{path}.param", "only a hidden field has a URL parameter (letters, digits, . _ -)")
        else:
            out["param"] = f["param"]
    if (q := check_quiz_answer(ck, {**f, "type": t, "options": out.get("options", [])}, path)) is not None:
        out["quiz"] = q
    if key:
        ck.fields[key] = out
        ck.where[key] = at
    return out


def check_condition(ck: Checker, c, path: str, limit: tuple[int, int], budget: list[int], depth: int = 0) -> None:
    """`limit`: conditions may only look at fields strictly before this (step, field) position."""
    budget[0] += 1
    if budget[0] > MAX_NODES or depth > MAX_DEPTH:
        return ck.bad(path, f"is too big (at most {MAX_NODES} tests, {MAX_DEPTH} levels)")
    if not isinstance(c, dict):
        return ck.bad(path, "must be an object")
    for combinator in ("and", "or"):
        if combinator in c:
            if c.keys() != {combinator} or not isinstance(c[combinator], list) or not c[combinator]:
                return ck.bad(path, f"{combinator} must be a non-empty list")
            for i, child in enumerate(c[combinator]):
                check_condition(ck, child, f"{path}.{combinator}.{i}", limit, budget, depth + 1)
            return None
    if "not" in c:
        if c.keys() != {"not"}:
            return ck.bad(path, "not takes one condition")
        return check_condition(ck, c["not"], f"{path}.not", limit, budget, depth + 1)
    if not c.keys() <= {"field", "op", "value"} or not {"field", "op"} <= c.keys():
        return ck.bad(path, "needs field, op and (for most tests) value")
    f = ck.fields.get(c["field"]) if isinstance(c["field"], str) else None
    if f is None or f["type"] not in logic.ANSWERABLE:
        return ck.bad(f"{path}.field", "is not a question of this form")
    if not ck.where[f["key"]] < limit:
        return ck.bad(f"{path}.field", "must come earlier in the form than what this rule controls")
    op = c["op"]
    if op not in logic.OPS_BY_TYPE[f["type"]]:
        return ck.bad(f"{path}.op", f"a {f['type']} question cannot be tested with {op!r}")
    if op in logic.NO_VALUE:
        return ck.bad(f"{path}.value", "is not used by this test") if "value" in c else None
    values = c.get("value") if op in logic.LIST_VALUE or (f["type"] == "multi_select" and op == "is") else [
        c.get("value")]
    if not isinstance(values, list) or not values or "value" not in c:
        return ck.bad(f"{path}.value", "needs a list" if op in logic.LIST_VALUE else "is required")
    ids = {o["id"] for o in f.get("options", [])}
    for v in values:
        ok = {"select": v in ids if isinstance(v, str) else False,
              "multi_select": v in ids if isinstance(v, str) else False,
              "number": logic.is_number(v), "rating": logic.is_number(v),
              "date": isinstance(v, str) and bool(types.DATE.fullmatch(v)),
              **dict.fromkeys(logic.FLAGS, isinstance(v, bool)),
              **dict.fromkeys(logic.TEXT, isinstance(v, str))}[f["type"]]
        if not ok:
            return ck.bad(f"{path}.value", f"is not a valid value for this {f['type']} question")
    return None


def check_rules(ck: Checker, rules, steps: list[dict]) -> list[dict]:
    if not isinstance(rules, list) or len(rules) > MAX_RULES:
        ck.bad("logic", f"must be a list of at most {MAX_RULES} rules")
        return []
    index = {s["key"]: i for i, s in enumerate(steps) if s["key"]}
    out, ids = [], set()
    for n, r in enumerate(rules):
        path = f"logic.{n}"
        if not isinstance(r, dict):
            ck.bad(path, "must be an object")
            continue
        ck.unknown(r, KEYS["rule"], path)
        do, target, origin = r.get("do"), r.get("target"), r.get("from")
        rid = r["id"] if isinstance(r.get("id"), str) and 0 < len(r["id"]) <= 40 else f"r{n + 1}"
        while rid in ids:
            rid += "_"
        ids.add(rid)
        rule = {"id": rid, "when": r.get("when"), "do": do}
        if do in ("show", "hide"):
            if not isinstance(target, str) or target not in ck.where:
                ck.bad(f"{path}.target", "is not a field or step of this form")
                continue
            if origin is not None:
                ck.bad(f"{path}.from", "is only for jump and end rules")
            rule["target"], limit = target, ck.where[target]
        elif do in ("jump", "end"):
            if not isinstance(origin, str) or origin not in index:
                ck.bad(f"{path}.from", "must be a step of this form")
                continue
            limit = (index[origin] + 1, -1)  # a step's own answers are known when it is left
            rule["from"] = origin
            if do == "jump":
                if not isinstance(target, str) or target not in index or index[target] <= index[origin]:
                    ck.bad(f"{path}.target", "must be a later step")
                    continue
                rule["target"] = target
            elif target is not None:
                ck.bad(f"{path}.target", "an end rule has no target")
        else:
            ck.bad(f"{path}.do", "must be show, hide, jump or end")
            continue
        check_condition(ck, r.get("when"), f"{path}.when", limit, [0])
        out.append(rule)
    return out


def check_quiz(ck: Checker, quiz) -> dict | None:
    if quiz is None:
        return None
    if ck.kind != "quiz":
        ck.bad("quiz", "only a quiz has scoring settings")
        return None
    if not isinstance(quiz, dict) or quiz.keys() - {"pass_mark", "bands"}:
        ck.bad("quiz", "must be an object with pass_mark and bands")
        return None
    out: dict = {}
    if "pass_mark" in quiz:
        if not whole(quiz["pass_mark"]) or not 0 <= quiz["pass_mark"] <= 100:
            ck.bad("quiz.pass_mark", "must be a percentage from 0 to 100")
        out["pass_mark"] = quiz["pass_mark"]
    bands = quiz.get("bands", [])
    if not isinstance(bands, list) or len(bands) > 10:
        ck.bad("quiz.bands", "must be a list of at most 10 bands")
        return out
    clean = []
    for n, b in enumerate(bands):
        path = f"quiz.bands.{n}"
        if not isinstance(b, dict) or b.keys() - {"min", "title", "message"} or not whole(b.get("min")):
            ck.bad(path, "needs min (a percentage), title and message")
            continue
        if not 0 <= b["min"] <= 100:
            ck.bad(f"{path}.min", "must be a percentage from 0 to 100")
        clean.append({"min": b["min"], "title": ck.text(b, "title", path, 100, required=True),
                      "message": ck.text(b, "message", path, 1000) or ""})
    if len({b["min"] for b in clean}) != len(clean):
        ck.bad("quiz.bands", "two bands start at the same percentage")
    out["bands"] = sorted(clean, key=lambda b: b["min"])
    return out


def validate_definition(defn, kind: str) -> dict:
    """The normalized definition (option ids filled in, rule ids numbered), or a DefinitionError whose `fields` are
    dotted paths such as `steps.0.fields.1.key`."""
    ck = Checker(kind)
    if not isinstance(defn, dict):
        raise DefinitionError({"definition": "must be an object"})
    ck.unknown(defn, KEYS["top"], "")
    out: dict = {}
    for name, cap in (("title", 200), ("description", 1000), ("submit_label", 40)):
        if (value := ck.text(defn, name, "", cap)) is not None:
            out[name] = value
    raw_steps = defn.get("steps")
    if not isinstance(raw_steps, list) or not 1 <= len(raw_steps) <= MAX_STEPS:
        ck.bad("steps", f"needs 1 to {MAX_STEPS} steps")
        raw_steps = []
    seen: set[str] = set()
    steps, count = [], 0
    for i, s in enumerate(raw_steps):
        path = f"steps.{i}"
        if not isinstance(s, dict):
            ck.bad(path, "must be an object")
            continue
        ck.unknown(s, KEYS["step"], path)
        key = key_of(ck, s, path, seen)
        if key:
            ck.where[key] = (i, -1)
        step = {"key": key, "title": ck.text(s, "title", path, 200) or "",
                **({"description": d} if (d := ck.text(s, "description", path, 1000)) else {})}
        raw_fields = s.get("fields")
        if not isinstance(raw_fields, list) or not raw_fields:
            ck.bad(f"{path}.fields", "needs at least one field")
            raw_fields = []
        count += len(raw_fields)
        if count > MAX_FIELDS:
            ck.bad(f"{path}.fields", f"the form has more than {MAX_FIELDS} fields")
            break
        step["fields"] = [f for j, raw in enumerate(raw_fields)
                          if (f := check_field(ck, raw, f"{path}.fields.{j}", seen, (i, j))) is not None]
        steps.append(step)
    out["steps"] = steps
    if "logic" in defn:
        out["logic"] = check_rules(ck, defn["logic"], steps)
    if (quiz := check_quiz(ck, defn.get("quiz"))) is not None:
        out["quiz"] = quiz
    if ck.errors:
        raise DefinitionError(ck.errors)
    return out


def check_mapping(defn: dict, contact_fields: dict) -> dict[str, str]:
    """Errors for fields that write to a contact field that is missing, computed, of another type or mapped twice.
    `contact_fields` maps key to a field row (anything with .type and .options)."""
    errors: dict[str, str] = {}
    taken: dict[str, str] = {}
    for i, s in enumerate(defn["steps"]):
        for j, f in enumerate(s["fields"]):
            target, path = f.get("maps_to"), f"steps.{i}.fields.{j}.maps_to"
            if target is None:
                continue
            cf = contact_fields.get(target)
            if cf is None:
                errors[path] = f"there is no contact field {target!r}"
            elif cf.type not in COMPATIBLE[f["type"]]:
                errors[path] = f"a {f['type']} field cannot fill the {cf.type} field {target!r}"
            elif target in taken:
                errors[path] = f"{target!r} is already filled by {taken[target]!r}"
            elif f["type"] in ("select", "multi_select") and cf.type == f["type"] and not (
                    {o["id"] for o in f["options"]} <= types.choice_ids(cf)):
                errors[path] = f"the options of this field are not all choices of the contact field {target!r}"
            taken[target] = f["key"]
    return errors


def fields_of(defn: dict) -> dict[str, dict]:
    return {f["key"]: f for s in defn["steps"] for f in s["fields"]}


def public(defn: dict) -> dict:
    """The definition a visitor gets: no contact mapping and no quiz answers or scoring."""
    steps = [{**s, "fields": [{k: v for k, v in f.items() if k not in ("maps_to", "quiz")} for f in s["fields"]]}
             for s in defn["steps"]]
    return {**{k: v for k, v in defn.items() if k not in ("quiz", "steps")}, "steps": steps}


def starter(kind: str) -> dict:
    """A working first version: a name and an email for a form; a question for a quiz or survey."""
    if kind == "form":
        fields = [{"key": "first_name", "type": "short_text", "label": "Name", "required": True,
                   "maps_to": "first_name"},
                  {"key": "email", "type": "email", "label": "Email", "required": True, "maps_to": "email"}]
    else:
        question = {"key": "question_1", "type": "select", "label": "Pick one", "required": True, "options": [
            {"id": "yes", "label": "Option A"}, {"id": "no", "label": "Option B"}]}
        fields = [{**question, "quiz": {"correct": "yes", "points": 1}} if kind == "quiz" else question]
    return {"steps": [{"key": "step_1", "title": "", "fields": fields}],
            **({"quiz": {"pass_mark": 50, "bands": []}} if kind == "quiz" else {})}


def public_key() -> str:
    return secrets.token_urlsafe(12)


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "form"


def http_url(value: str) -> str:
    parts = urlsplit(value)
    if parts.scheme not in ("http", "https") or not parts.netloc or re.search(r"\s", value) or len(value) > 2000:
        raise ValueError("must be an http or https URL")
    return value


Text = Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)]


class ContactSettings(BaseModel, extra="forbid"):
    create: bool = True  # a form without a contact (an anonymous survey) leaves this off
    existing: Literal["update", "fill_empty"] = "update"  # what a known contact gets from a new answer


class Settings(BaseModel, extra="forbid"):
    success_message: Text = "Thanks, we got your response."
    redirect_url: Annotated[str, AfterValidator(http_url)] | None = None
    closed_message: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    notify_emails: list[Email] = Field(default=[], max_length=10)
    contact: ContactSettings = ContactSettings()
    double_submission: Literal["allow", "block"] = "allow"  # block: a contact answers once
    close_at: AwareDatetime | None = None
    max_responses: int | None = Field(default=None, ge=1, le=10_000_000)
    spam_protection: bool = True  # honeypot and minimum fill time; the rate limit and body size always apply
    rate_limit_per_minute: int = Field(default=30, ge=1, le=600)  # requests per visitor and form
    max_body_kb: int = Field(default=64, ge=4, le=1024)
