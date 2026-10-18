"""Form definitions, logic, answer checking and quiz scoring: pure functions, no database. The logic and quiz cases are
the shared fixtures (tests/fixtures/form_logic.json) that the browser runtime's tests run too."""
import copy
import json
from pathlib import Path

import pytest
from forms_helpers import form, pick, q, step

from app.forms import answers, logic
from app.forms.definition import (
    DefinitionError,
    Settings,
    check_mapping,
    fields_of,
    public,
    starter,
    validate_definition,
)

FIXTURES = json.loads((Path(__file__).parent / "fixtures" / "form_logic.json").read_text("utf-8"))


@pytest.fixture(autouse=True)
def clean():
    """Overrides the suite's database cleanup: nothing here touches the database."""
    yield


def names(cases):
    return [c["name"] for c in cases]


@pytest.mark.parametrize("case", FIXTURES["conditions"], ids=names(FIXTURES["conditions"]))
def test_conditions(case):
    assert logic.holds(case["when"], case["answers"]) is case["expect"]


@pytest.mark.parametrize("case", FIXTURES["flows"], ids=names(FIXTURES["flows"]))
def test_flows(case):
    fl = logic.flow(case["definition"], case["answers"])
    assert {"path": fl.steps, "ended": fl.ended, "answers": fl.answers} == case["expect"]


@pytest.mark.parametrize("case", FIXTURES["quizzes"], ids=names(FIXTURES["quizzes"]))
def test_quizzes(case):
    defn = case["definition"]
    fl = logic.flow(defn, case["answers"])
    result = answers.score(defn, fl, fl.answers)
    if case["expect"] is None:
        assert result is None
        return
    band = result.pop("band")
    expect = dict(case["expect"])
    assert (band or {}).get("title") == expect.pop("band")
    assert result == expect


# --- definitions ---------------------------------------------------------------------------------------------

def rejected(defn, kind="form") -> dict:
    with pytest.raises(DefinitionError) as e:
        validate_definition(defn, kind)
    return e.value.fields


def two_steps(*rules):
    size = q("size", "select", options=[{"id": "big", "label": "Big"}, {"id": "small", "label": "Small"}])
    return form(step("s1", size, q("note")), step("s2", q("detail")), step("s3", q("email", "email")),
                logic_=list(rules))


def test_the_starters_are_valid_for_every_kind():
    for kind in ("form", "survey", "quiz"):
        assert validate_definition(starter(kind), kind)["steps"][0]["fields"]


def test_a_valid_definition_is_normalized():
    out = validate_definition(two_steps(
        {"when": {"field": "size", "op": "is", "value": "big"}, "do": "jump", "from": "s1", "target": "s3"},
        {"when": {"field": "size", "op": "is", "value": "big"}, "do": "hide", "target": "detail"}), "form")
    assert [r["id"] for r in out["logic"]] == ["r1", "r2"]  # rules are numbered
    assert out["steps"][0]["fields"][0]["options"] == [{"id": "big", "label": "Big"}, {"id": "small", "label": "Small"}]
    generated = validate_definition(form(step("s1", q("c", "select", options=[{"label": "Red"}, {"label": "Red"}]))),
                                    "form")
    assert [o["id"] for o in generated["steps"][0]["fields"][0]["options"]] == ["red", "red_2"]  # ids from labels
    assert fields_of(out)["email"]["type"] == "email"


@pytest.mark.parametrize("rule, path, fragment", [
    # a condition may only look at questions that come earlier than what the rule controls
    ({"when": {"field": "email", "op": "is", "value": "x"}, "do": "hide", "target": "detail"},
     "logic.0.when.field", "earlier"),
    ({"when": {"field": "detail", "op": "is", "value": "x"}, "do": "hide", "target": "detail"},
     "logic.0.when.field", "earlier"),  # itself
    ({"when": {"field": "note", "op": "is", "value": "x"}, "do": "hide", "target": "size"},
     "logic.0.when.field", "earlier"),  # later in the same step
    ({"when": {"field": "detail", "op": "is", "value": "x"}, "do": "hide", "target": "s2"},
     "logic.0.when.field", "earlier"),  # a step cannot depend on its own answers
    ({"when": {"field": "email", "op": "is_empty"}, "do": "end", "from": "s1"}, "logic.0.when.field", "earlier"),
    ({"when": {"field": "nope", "op": "is", "value": "x"}, "do": "hide", "target": "detail"},
     "logic.0.when.field", "not a question"),
    ({"when": {"field": "size", "op": "is", "value": "x"}, "do": "hide", "target": "nope"},
     "logic.0.target", "not a field or step"),
    ({"when": {"field": "size", "op": "is", "value": "big"}, "do": "jump", "from": "s3", "target": "s2"},
     "logic.0.target", "later step"),  # backwards: a loop
    ({"when": {"field": "size", "op": "is", "value": "big"}, "do": "jump", "from": "s2", "target": "s2"},
     "logic.0.target", "later step"),
    ({"when": {"field": "size", "op": "is", "value": "big"}, "do": "jump", "from": "s1", "target": "email"},
     "logic.0.target", "later step"),  # a field is not a step
    ({"when": {"field": "size", "op": "is", "value": "big"}, "do": "jump", "from": "nope", "target": "s3"},
     "logic.0.from", "step of this form"),
    ({"when": {"field": "size", "op": "is", "value": "big"}, "do": "end", "from": "s1", "target": "s2"},
     "logic.0.target", "no target"),
    ({"when": {"field": "size", "op": "is", "value": "big"}, "do": "hide", "target": "detail", "from": "s1"},
     "logic.0.from", "only for jump"),
    ({"when": {"field": "size", "op": "is", "value": "big"}, "do": "teleport", "target": "detail"},
     "logic.0.do", "show, hide, jump or end"),
    ({"when": {"field": "size", "op": "is", "value": "huge"}, "do": "hide", "target": "detail"},
     "logic.0.when.value", "not a valid value"),  # not one of the options
    ({"when": {"field": "size", "op": "in", "value": ["big", "huge"]}, "do": "hide", "target": "detail"},
     "logic.0.when.value", "not a valid value"),
    ({"when": {"field": "size", "op": "gt", "value": 3}, "do": "hide", "target": "detail"},
     "logic.0.when.op", "cannot be tested"),
    ({"when": {"field": "size", "op": "in", "value": "big"}, "do": "hide", "target": "detail"},
     "logic.0.when.value", "list"),
    ({"when": {"field": "size", "op": "is"}, "do": "hide", "target": "detail"}, "logic.0.when.value", "required"),
    ({"when": {"field": "size", "op": "is_empty", "value": "x"}, "do": "hide", "target": "detail"},
     "logic.0.when.value", "not used"),
    ({"when": {"and": []}, "do": "hide", "target": "detail"}, "logic.0.when", "non-empty"),
    ({"when": {"field": "size", "op": "is", "value": "big", "extra": 1}, "do": "hide", "target": "detail"},
     "logic.0.when", "needs field"),
    ({"when": "size is big", "do": "hide", "target": "detail"}, "logic.0.when", "object"),
    ({"do": "hide", "target": "detail"}, "logic.0.when", "object"),
    ({"when": {"field": "size", "op": "is", "value": "big"}, "do": "hide", "target": "detail", "mood": "x"},
     "logic.0.mood", "not a known"),
])
def test_bad_logic_is_refused_when_the_definition_is_saved(rule, path, fragment):
    errors = rejected(two_steps(rule))
    assert fragment in errors[path], errors


def test_logic_that_is_fine():
    big, filled = {"field": "size", "op": "is", "value": "big"}, {"not": {"field": "note", "op": "is_empty"}}
    ok = [{"when": {"and": [big, filled]}, "do": "jump", "from": "s1", "target": "s3"},
          {"when": {"field": "note", "op": "contains", "value": "x"}, "do": "show", "target": "detail"},
          {"when": {"field": "size", "op": "in", "value": ["big", "small"]}, "do": "end", "from": "s2"}]
    assert len(validate_definition(two_steps(*ok), "form")["logic"]) == 3


def test_rules_are_limited_in_size_and_depth():
    deep = {"field": "size", "op": "is", "value": "big"}
    for _ in range(7):
        deep = {"not": deep}
    errors = rejected(two_steps({"when": deep, "do": "hide", "target": "detail"}))
    assert any("too big" in m for m in errors.values())
    wide = {"or": [{"field": "size", "op": "is", "value": "big"}] * 60}
    assert any("too big" in m for m in rejected(two_steps({"when": wide, "do": "hide", "target": "detail"})).values())
    rule = {"when": {"field": "size", "op": "is", "value": "big"}, "do": "hide", "target": "detail"}
    assert "at most" in rejected(two_steps(*[rule] * 101))["logic"]


@pytest.mark.parametrize("defn, path, fragment", [
    ({"steps": []}, "steps", "1 to"),
    ({"steps": [{"key": "s1", "fields": []}]}, "steps.0.fields", "at least one"),
    ({"steps": [step("s1", q("a"), q("a"))]}, "steps.0.fields.1.key", "used twice"),
    ({"steps": [step("s1", q("a")), step("a", q("b"))]}, "steps.1.key", "used twice"),  # one namespace
    ({"steps": [step("s1", q("Bad Key"))]}, "steps.0.fields.0.key", "lower case"),
    ({"steps": [step("s1", q("a", "color"))]}, "steps.0.fields.0.type", "must be one of"),
    ({"steps": [step("s1", {"key": "a", "type": "short_text"})]}, "steps.0.fields.0.label", "required"),
    ({"steps": [step("s1", q("a", options=[{"label": "x"}]))]}, "steps.0.fields.0.options", "no options"),
    ({"steps": [step("s1", q("a", "select", options=[]))]}, "steps.0.fields.0.options", "1 to"),
    ({"steps": [step("s1", q("a", "select"))]}, "steps.0.fields.0.options", "1 to"),
    ({"steps": [step("s1", q("a", required="yes"))]}, "steps.0.fields.0.required", "true or false"),
    ({"steps": [step("s1", q("a", "hidden", required=True))]}, "steps.0.fields.0.required", "never required"),
    ({"steps": [step("s1", q("a", "heading", required=True))]}, "steps.0.fields.0.required", "never required"),
    ({"steps": [step("s1", q("a", glitter=True))]}, "steps.0.fields.0.glitter", "not a known"),
    ({"steps": [step("s1", q("a", validation={"min_length": 9, "max_length": 3}))]},
     "steps.0.fields.0.validation.min_length", "above"),
    ({"steps": [step("s1", q("a", "number", validation={"min": 5, "max": 1}))]},
     "steps.0.fields.0.validation.min", "above"),
    ({"steps": [step("s1", q("a", "email", validation={"max_length": 3}))]},
     "steps.0.fields.0.validation.max_length", "not a known"),
    ({"steps": [step("s1", q("a", "phone", validation={"region": "ZZ"}))]},
     "steps.0.fields.0.validation.region", "not valid"),
    ({"steps": [step("s1", q("a", param="utm_source"))]}, "steps.0.fields.0.param", "hidden field"),
    ({"steps": [step("s1", q("a", "heading", maps_to="email"))]}, "steps.0.fields.0.maps_to", "not for a text block"),
    ({"steps": [step("s1", q("a", maps_to="Not A Key"))]}, "steps.0.fields.0.maps_to", "key of a contact"),
    ({"steps": [step("s1", q("a"))], "surprise": 1}, "surprise", "not a known"),
    ({"steps": [step("s1", q("a"))], "title": 5}, "title", "text"),
    ({"steps": [step("s1", q("a"))], "quiz": {"pass_mark": 50}}, "quiz", "only a quiz"),
    ({"steps": [step("s1", q("a", "select", options=[{"id": "x", "label": "X"}], quiz={"correct": "x", "points": 1}))]},
     "steps.0.fields.0.quiz", "only questions of a quiz"),
    ("not an object", "definition", "object"),
    ({"steps": ["a step"]}, "steps.0", "object"),
    ({"steps": [step("s1", "a field")]}, "steps.0.fields.0", "object"),
    ({"steps": [step("s1", q("a", label="x" * 301))]}, "steps.0.fields.0.label", "at most 300"),
    ({"steps": [step("s1", q("a", "heading", label="x" * 201))]}, "steps.0.fields.0.label", "at most 200"),
    ({"steps": [step("s1", q("a", help="x\x00y"))]}, "steps.0.fields.0.help", "text"),
    ({"steps": [step("s1", q("a"))], "submit_label": "x" * 41}, "submit_label", "at most 40"),
    ({"steps": [step("s1", q("a", validation=["max_length", 3]))]}, "steps.0.fields.0.validation", "object"),
    ({"steps": [step("s1", *[q(f"f{n}") for n in range(120)]), step("s2", *[q(f"g{n}") for n in range(81)])]},
     "steps.1.fields", "more than 200"),
])
def test_bad_definitions_are_refused_with_a_path(defn, path, fragment):
    assert fragment in rejected(defn)[path]


def test_a_definition_of_the_largest_size_is_accepted():
    fields = [q(f"f{n}") for n in range(200)]
    out = validate_definition(form(step("s1", *fields[:100]), step("s2", *fields[100:])), "form")
    assert sum(len(s["fields"]) for s in out["steps"]) == 200


@pytest.mark.parametrize("rule, path, fragment", [
    ("hide detail", "logic.0", "object"),
    ({"when": {"not": {"field": "size", "op": "is", "value": "big"}, "field": "size"}, "do": "hide",
      "target": "detail"}, "logic.0.when", "not takes one condition"),
])
def test_malformed_rules_are_refused(rule, path, fragment):
    assert fragment in rejected(two_steps(rule))[path]


def test_rule_ids_are_kept_when_given_and_made_unique():
    big = {"field": "size", "op": "is", "value": "big"}
    out = validate_definition(two_steps(
        {"id": "keep", "when": big, "do": "hide", "target": "detail"},
        {"id": "keep", "when": big, "do": "show", "target": "detail"},
        {"id": "x" * 41, "when": big, "do": "hide", "target": "s3"},
        {"id": "r3", "when": big, "do": "hide", "target": "s2"}), "form")
    ids = [r["id"] for r in out["logic"]]
    assert ids == ["keep", "keep_", "r3", "r3_"]  # a duplicate gets a suffix, an id too long is numbered
    assert len(set(ids)) == len(ids)


@pytest.mark.parametrize("settings, path, fragment", [
    ("pass at 50", "quiz", "pass_mark and bands"),
    ({"pass_mark": 50, "colour": "red"}, "quiz", "pass_mark and bands"),
    ({"bands": "A to F"}, "quiz.bands", "at most 10"),
    ({"bands": [{"min": n * 5, "title": str(n)} for n in range(11)]}, "quiz.bands", "at most 10"),
    ({"bands": ["A"]}, "quiz.bands.0", "needs min"),
    ({"bands": [{"min": 10, "title": "A", "emoji": "x"}]}, "quiz.bands.0", "needs min"),
    ({"bands": [{"min": True, "title": "A"}]}, "quiz.bands.0", "needs min"),
])
def test_quiz_settings_of_the_wrong_shape_are_refused(settings, path, fragment):
    scored = q("a", "select", options=[{"id": "x", "label": "X"}], quiz={"correct": "x", "points": 1})
    assert fragment in rejected(form(step("s1", scored), quiz=settings), "quiz")[path]


def test_quiz_questions_and_settings_are_checked():
    def quiz(field, **top):
        return form(step("s1", field), quiz=top or None) if top else form(step("s1", field))

    pick = {"options": [{"id": "x", "label": "X"}, {"id": "y", "label": "Y"}]}
    bad = [(q("a", "select", **pick, quiz={"correct": "z", "points": 1}), "steps.0.fields.0.quiz.correct"),
           (q("a", "select", **pick, quiz={"correct": "x", "points": 0}), "steps.0.fields.0.quiz.points"),
           (q("a", "select", **pick, quiz={"correct": "x"}), "steps.0.fields.0.quiz"),
           (q("a", "multi_select", **pick, quiz={"correct": [], "points": 1}), "steps.0.fields.0.quiz.correct"),
           (q("a", "multi_select", **pick, quiz={"correct": ["x", "z"], "points": 1}), "steps.0.fields.0.quiz.correct"),
           (q("a", "rating", quiz={"correct": 6, "points": 1}), "steps.0.fields.0.quiz.correct"),
           (q("a", "yes_no", quiz={"correct": "yes", "points": 1}), "steps.0.fields.0.quiz.correct"),
           (q("a", "short_text", quiz={"correct": ["ok", ""], "points": 1}), "steps.0.fields.0.quiz.correct"),
           (q("a", "long_text", quiz={"correct": "x", "points": 1}), "steps.0.fields.0.quiz")]
    for field, path in bad:
        assert path in rejected(quiz(field), "quiz"), field
    fine = [q("a", "select", **pick, quiz={"correct": "x", "points": 2}), q("b", "number", quiz={"correct": 4.5,
                                                                                                   "points": 1}),
            q("c", "short_text", quiz={"correct": ["a", "b"], "points": 1}), q("d", "yes_no",
                                                                                 quiz={"correct": False, "points": 1})]
    out = validate_definition(form(step("s1", *fine), quiz={"pass_mark": 60, "bands": [
        {"min": 50, "title": "B", "message": "m"}, {"min": 0, "title": "A", "message": ""}]}), "quiz")
    assert [b["min"] for b in out["quiz"]["bands"]] == [0, 50]  # sorted
    for settings, path in [({"pass_mark": 101}, "quiz.pass_mark"), ({"pass_mark": "high"}, "quiz.pass_mark"),
                           ({"bands": [{"min": 0, "title": "A"}, {"min": 0, "title": "B"}]}, "quiz.bands"),
                           ({"bands": [{"min": 150, "title": "A"}]}, "quiz.bands.0.min"),
                           ({"bands": [{"min": 10}]}, "quiz.bands.0.title")]:
        assert path in rejected(form(step("s1", fine[0]), quiz=settings), "quiz"), settings


def test_what_a_visitor_gets_has_no_mapping_and_no_answers():
    scored = q("q1", "select", options=[{"id": "x", "label": "X"}], quiz={"correct": "x", "points": 3})
    settings = {"pass_mark": 50, "bands": [{"min": 0, "title": "A", "message": "m"}]}
    defn = validate_definition(form(step("s1", q("email", "email", maps_to="email"), scored), quiz=settings), "quiz")
    seen = public(defn)
    text = json.dumps(seen)
    assert "maps_to" not in text and "correct" not in text and "points" not in text and "pass_mark" not in text
    assert seen["steps"][0]["fields"][0] == {"key": "email", "type": "email", "label": "Email"}
    assert defn["steps"][0]["fields"][0]["maps_to"] == "email"  # the stored version is untouched


class Field:
    def __init__(self, type_, options=None):
        self.type, self.options = type_, options or {}


def test_a_mapping_must_fit_a_contact_field():
    contact = {"email": Field("email"), "phone": Field("phone"), "first_name": Field("text"),
               "lifecycle": Field("select", {"choices": [{"id": "lead"}, {"id": "customer"}]}),
               "tags": Field("multi_select", {"choices": [{"id": "a"}]}), "age": Field("number"),
               "calc": Field("formula")}

    def defn(*fields):
        return validate_definition(form(step("s1", *fields)), "form")

    assert check_mapping(defn(q("a", "email", maps_to="email"), q("b", maps_to="first_name")), contact) == {}
    assert check_mapping(defn(q("a", "select", **pick("lead", "customer"), maps_to="lifecycle")), contact) == {}
    assert check_mapping(defn(q("a", "select", **pick("a"), maps_to="first_name")), contact) == {}  # label goes in
    wrong = defn(q("a", "email", maps_to="nope"), q("b", "email", maps_to="phone"), q("c", maps_to="calc"),
                 q("d", "select", **pick("lead", "gone"), maps_to="lifecycle"), q("e", "email", maps_to="email"),
                 q("f", "email", maps_to="email"), q("g", "number", maps_to="first_name"))
    errors = check_mapping(wrong, contact)
    assert sorted(errors) == [f"steps.0.fields.{i}.maps_to" for i in (0, 1, 2, 3, 5, 6)]
    assert "no contact field" in errors["steps.0.fields.0.maps_to"]
    assert "cannot fill" in errors["steps.0.fields.1.maps_to"] and "cannot fill" in errors["steps.0.fields.2.maps_to"]
    assert "not all choices" in errors["steps.0.fields.3.maps_to"]
    assert "already filled" in errors["steps.0.fields.5.maps_to"]


def test_settings_have_safe_defaults_and_refuse_bad_values():
    s = Settings()
    assert s.spam_protection and s.rate_limit_per_minute == 30 and s.max_body_kb == 64 and s.contact.create
    assert s.double_submission == "allow" and s.contact.existing == "fill_empty" and s.redirect_url is None
    for bad in ({"redirect_url": "javascript:alert(1)"}, {"redirect_url": "ftp://x.test/a"},
                {"redirect_url": "https://x.test/a b"}, {"redirect_url": "//x.test"},
                {"close_at": "2026-12-01T10:00:00"}, {"max_responses": 0}, {"rate_limit_per_minute": 0},
                {"rate_limit_per_minute": 601}, {"max_body_kb": 2000}, {"double_submission": "twice"},
                {"notify_emails": ["not an email"]}, {"notify_emails": ["a@example.com"] * 11}, {"unknown": 1},
                {"contact": {"existing": "replace"}}):
        with pytest.raises(ValueError):
            Settings.model_validate(bad)
    ok = Settings.model_validate({"redirect_url": "https://example.com/thanks", "close_at": "2030-01-01T00:00:00Z",
                                  "max_responses": 10, "notify_emails": ["a@example.com"]})
    assert ok.model_dump(mode="json")["close_at"].startswith("2030-01-01T00:00:00")


# --- answers -------------------------------------------------------------------------------------------------

def run(defn, given, kind="form", contact=None):
    defn = validate_definition(defn, kind)
    fl = logic.flow(defn, given)
    clean, errors = answers.validate(defn, given, fl, contact)
    return defn, fl, clean, errors


ALL_TYPES = form(step(
    "s1", q("name", "short_text", required=True, validation={"max_length": 10}), q("bio", "long_text"),
    q("email", "email"), q("phone", "phone"), q("age", "number", validation={"min": 18, "max": 99, "integer": True}),
    q("plan", "select", options=[{"id": "solo", "label": "Solo"}, {"id": "team", "label": "Team"}]),
    q("tags", "multi_select", options=[{"id": "a", "label": "A"}, {"id": "b", "label": "B"}, {"id": "c", "label": "C"}],
      validation={"min_items": 2, "max_items": 3}),
    q("news", "checkbox"), q("when", "date"), q("stars", "rating"), q("ok", "yes_no"),
    q("ref", "hidden", param="ref"), q("terms", "consent", required=True), q("intro", "heading")))
GOOD = {"name": "Ada", "bio": " Long text ", "email": " ADA@Example.com ", "phone": "+1 415 555 0100", "age": 36,
        "plan": "team", "tags": ["a", "b", "a"], "news": True, "when": "2026-10-18", "stars": 4, "ok": False,
        "ref": "ad-7", "terms": True}


def test_every_answer_type_is_normalized_by_the_record_engines_validators():
    _, _, clean, errors = run(ALL_TYPES, GOOD)
    assert errors == {}
    assert clean == {"name": "Ada", "bio": "Long text", "email": "ada@example.com", "phone": "+14155550100", "age": 36,
                     "plan": "team", "tags": ["a", "b"], "news": True, "when": "2026-10-18", "stars": 4, "ok": False,
                     "ref": "ad-7", "terms": True}  # a "no" is an answer; trimmed, lower-cased, E.164, no duplicates


@pytest.mark.parametrize("key, value, fragment", [
    ("name", "x" * 11, "at most 10"), ("email", "not-an-email", "email address"), ("phone", "123", "phone number"),
    ("age", 17, "at least 18"), ("age", 100, "at most 99"), ("age", 20.5, "whole number"), ("age", "20", "a number"),
    ("age", True, "a number"), ("plan", "gold", "choices"), ("plan", ["solo"], "choices"), ("tags", "a", "list"),
    ("tags", ["a"], "at least 2"), ("tags", ["a", "b", "c", "d"], "more than"), ("tags", ["a", "zzz"], "choices"),
    ("news", "yes", "true or false"), ("when", "18/10/2026", "date"), ("when", "2026-02-30", "real date"),
    ("stars", 0, "at least 1"), ("stars", 6, "at most 5"), ("stars", 2.5, "whole number"),
    ("ok", "no", "true or false"), ("bio", 5, "text"), ("name", "a\x00b", "text")])
def test_an_invalid_answer_is_refused_with_its_label(key, value, fragment):
    _, _, _, errors = run(ALL_TYPES, {**GOOD, key: value})
    assert fragment in errors[key] and errors[key].startswith(fields_of(ALL_TYPES)[key]["label"]), errors


def test_required_questions_must_be_answered_and_consent_must_be_ticked():
    _, _, clean, errors = run(ALL_TYPES, {"name": "  ", "terms": False, "email": "", "tags": []})
    assert errors == {"name": "Name is required", "terms": "This box must be ticked"}
    assert clean == {}
    _, _, _, errors = run(ALL_TYPES, {"name": "Ada"})
    assert errors == {"terms": "This box must be ticked"}


def test_hidden_questions_are_not_required_and_their_answers_are_dropped():
    choices = [{"id": "solo", "label": "Solo"}, {"id": "team", "label": "Team"}]
    solo = {"field": "plan", "op": "is", "value": "solo"}
    defn = form(step("s1", q("plan", "select", options=choices, required=True), q("company", required=True),
                     q("seats", "number", required=True)),
                step("s2", q("note", required=True)),
                logic_=[{"when": solo, "do": "hide", "target": "company"},
                        {"when": solo, "do": "hide", "target": "s2"}])
    _, fl, clean, errors = run(defn, {"plan": "solo", "company": "Acme", "seats": 1, "note": "typed before"})
    assert errors == {} and clean == {"plan": "solo", "seats": 1}
    assert fl.keys == ["plan", "seats"]
    _, _, _, errors = run(defn, {"plan": "team", "seats": 1})
    assert errors == {"company": "Company is required", "note": "Note is required"}


def test_a_required_question_after_an_end_rule_is_not_required():
    defn = form(step("s1", q("done", "yes_no")), step("s2", q("more", required=True)),
                logic_=[{"when": {"field": "done", "op": "is", "value": True}, "do": "end", "from": "s1"}])
    assert run(defn, {"done": True})[3] == {}
    assert run(defn, {"done": False})[3] == {"more": "More is required"}


def test_unknown_keys_and_content_blocks_are_ignored():
    _, _, clean, errors = run(ALL_TYPES, {**GOOD, "intro": "x", "surprise": "y", "__proto__": {"a": 1}})
    assert errors == {} and "intro" not in clean and "surprise" not in clean


def test_a_mapped_phone_uses_the_contact_fields_region():
    defn = form(step("s1", q("phone", "phone", maps_to="phone")))
    contact = {"phone": Field("phone", {"region": "GB"})}
    assert run(defn, {"phone": "020 7946 0958"}, contact=contact)[2] == {"phone": "+442079460958"}
    assert "phone number" in run(defn, {"phone": "020 7946 0958"}, contact={})[3]["phone"]  # US by default


def test_partial_answers_are_kept_unvalidated_but_only_plain_values_of_real_questions():
    defn = validate_definition(ALL_TYPES, "form")
    kept = answers.partial(defn, {"name": "Ad", "email": "ada@", "age": "twenty", "tags": ["a", 5], "plan": {"x": 1},
                                  "news": False, "ok": False, "terms": True, "intro": "x", "nope": "y",
                                  "bio": "z" * 9000, "when": "a\x00b"})
    assert kept["name"] == "Ad" and kept["email"] == "ada@" and kept["age"] == "twenty"  # not validated yet
    assert "tags" not in kept and "plan" not in kept and "news" not in kept  # not plain, not an answer
    assert kept["ok"] is False and kept["terms"] is True  # a "no" is an answer
    assert "intro" not in kept and "nope" not in kept and "when" not in kept and len(kept["bio"]) == 5000
    assert answers.partial(defn, "not a dict") == {} and answers.partial(defn, None) == {}
    assert answers.last_answered(defn, kept) == "terms"
    assert answers.last_answered(defn, {}) is None


def test_contact_values_are_the_non_empty_answers_of_mapped_questions():
    defn = validate_definition(form(step(
        "s1", q("first", maps_to="first_name"), q("email", "email", maps_to="email"), q("note", maps_to="gone"),
        q("plan", "select", options=[{"id": "t", "label": "Team plan"}], maps_to="company_size"),
        q("loose"))), "form")
    contact = {"first_name": Field("text"), "email": Field("email"), "company_size": Field("text")}
    got = answers.contact_values(defn, {"first": "Ada", "note": "x", "plan": "t", "loose": "y"}, contact)
    assert got == {"first_name": "Ada", "company_size": "Team plan"}  # no email answer, no field "gone", label for text


def test_consent_evidence_records_the_words_the_time_the_form_and_the_hashed_address():
    defn = validate_definition(form(step("s1", q("terms", "consent", label="I agree to be emailed"),
                                         q("other", "consent", label="Partners may write"))), "form")
    fl = logic.flow(defn, {"terms": True, "other": False})
    evidence = answers.consent_evidence(defn, fl, {"terms": True}, "2026-10-18T10:00:00+00:00", "form-id", "hash")
    assert evidence == {"terms": {"text": "I agree to be emailed", "at": "2026-10-18T10:00:00+00:00",
                                  "form_id": "form-id", "ip_hash": "hash"}}


def test_quiz_scoring_does_not_change_the_answers_it_reads():
    case = copy.deepcopy(FIXTURES["quizzes"][1])
    before = json.dumps(case, sort_keys=True)
    fl = logic.flow(case["definition"], case["answers"])
    answers.score(case["definition"], fl, fl.answers)
    assert json.dumps(case, sort_keys=True) == before
