"""Every field type: the values it accepts (and how it normalizes them), the values it refuses, and its settings."""
import uuid
from types import SimpleNamespace

import pytest

from app import config
from app.records import types

ID = str(uuid.uuid4())


@pytest.fixture(autouse=True)
def clean():
    yield  # these are pure functions: no database to clean between them
CHOICES = {"choices": [{"id": "lead", "label": "Lead"}, {"id": "won", "label": "Won"}]}


def field(type_: str, options: dict | None = None, rules: dict | None = None):
    return SimpleNamespace(key="f", label="F", type=type_, options=options or {}, rules=rules or {})


GOOD = [
    ("text", {}, {}, "  hi there ", "hi there"),
    ("text", {}, {"max_length": 3}, "abc", "abc"),
    ("long_text", {}, {}, "line one\nline two ", "line one\nline two"),
    ("number", {}, {}, 5, 5),
    ("number", {}, {}, 2.5, 2.5),
    ("number", {}, {}, 5.0, 5),
    ("number", {}, {"min": 1, "max": 10, "integer": True}, 10, 10),
    ("money", {}, {}, {"amount": 1999, "currency": "usd"}, {"amount": 1999, "currency": "USD"}),
    ("money", {}, {}, {"amount": -500}, {"amount": -500, "currency": "USD"}),
    ("money", {"currency": "EUR"}, {}, {"amount": 7}, {"amount": 7, "currency": "EUR"}),
    ("money", {}, {"min": 0}, {"amount": 0, "currency": "JPY"}, {"amount": 0, "currency": "JPY"}),
    ("date", {}, {}, "2026-10-17", "2026-10-17"),
    ("date", {}, {}, "2028-02-29", "2028-02-29"),
    ("datetime", {}, {}, "2026-10-17T09:30:00Z", "2026-10-17T09:30:00Z"),
    ("datetime", {}, {}, "2026-10-17T09:30:00+02:00", "2026-10-17T07:30:00Z"),
    ("boolean", {}, {}, True, True),
    ("boolean", {}, {}, False, False),
    ("select", CHOICES, {}, "lead", "lead"),
    ("stage", CHOICES, {}, "won", "won"),
    ("multi_select", CHOICES, {}, ["lead", "won", "lead"], ["lead", "won"]),
    ("email", {}, {}, "  Ada@Example.COM ", "ada@example.com"),
    ("phone", {}, {}, "(415) 555-2671", "+14155552671"),
    ("phone", {}, {}, "+44 20 7946 0958", "+442079460958"),
    ("phone", {"region": "gb"}, {}, "020 7946 0958", "+442079460958"),
    ("url", {}, {}, " https://example.com/a?b=1 ", "https://example.com/a?b=1"),
    ("user", {}, {}, ID.upper(), ID),
    ("record", {"object": "company"}, {}, ID, ID),
]

BAD = [
    ("text", {}, {}, 5, "must be text"),
    ("text", {}, {}, "x" * 1001, "at most 1000"),
    ("text", {}, {"max_length": 3}, "abcd", "at most 3"),
    ("text", {}, {"min_length": 3}, "ab", "at least 3"),
    ("long_text", {}, {}, "x" * 20001, "at most 20000"),
    ("number", {}, {}, "5", "must be a number"),
    ("number", {}, {}, True, "must be a number"),
    ("number", {}, {}, float("nan"), "must be a number"),
    ("number", {}, {}, float("inf"), "must be a number"),
    ("number", {}, {}, 10**16, "out of range"),
    ("number", {}, {"min": 1}, 0, "at least 1"),
    ("number", {}, {"max": 10}, 11, "at most 10"),
    ("number", {}, {"integer": True}, 1.5, "whole number"),
    ("money", {}, {}, "5", "must look like"),
    ("money", {}, {}, 5, "must look like"),
    ("money", {}, {}, {"amount": 19.99, "currency": "USD"}, "whole number of minor units"),
    ("money", {}, {}, {"amount": "5"}, "whole number of minor units"),
    ("money", {}, {}, {"amount": True}, "whole number of minor units"),
    ("money", {}, {}, {"currency": "USD"}, "whole number of minor units"),
    ("money", {}, {}, {"amount": 1, "currency": "XXX"}, "ISO 4217"),
    ("money", {}, {}, {"amount": 1, "currency": "US"}, "ISO 4217"),
    ("money", {}, {}, {"amount": 1, "extra": 2}, "must look like"),
    ("money", {}, {}, {"amount": 10**16}, "out of range"),
    ("money", {}, {"min": 0}, {"amount": -1}, "at least 0"),
    ("money", {}, {"max": 100}, {"amount": 101}, "at most 100"),
    ("date", {}, {}, "17/10/2026", "like 2026-10-17"),
    ("date", {}, {}, "2026-10-17T10:00:00Z", "like 2026-10-17"),
    ("date", {}, {}, 20261017, "like 2026-10-17"),
    ("date", {}, {}, "2026-02-30", "not a real date"),
    ("date", {}, {}, "2027-02-29", "not a real date"),
    ("datetime", {}, {}, "2026-10-17T09:30:00", "with a zone"),
    ("datetime", {}, {}, "2026-10-17", "with a zone"),
    ("datetime", {}, {}, "yesterday", "with a zone"),
    ("datetime", {}, {}, 5, "with a zone"),
    ("boolean", {}, {}, "true", "true or false"),
    ("boolean", {}, {}, 1, "true or false"),
    ("select", CHOICES, {}, "nope", "choices"),
    ("select", CHOICES, {}, 5, "choices"),
    ("select", CHOICES, {}, ["lead"], "choices"),
    ("stage", CHOICES, {}, "nope", "choices"),
    ("multi_select", CHOICES, {}, "lead", "list"),
    ("multi_select", CHOICES, {}, ["lead", "nope"], "choices"),
    ("multi_select", CHOICES, {"max_items": 1}, ["lead", "won"], "more than 1"),
    ("email", {}, {}, "ada", "not an email"),
    ("email", {}, {}, "ada@example", "not an email"),
    ("email", {}, {}, "a b@example.com", "not an email"),
    ("email", {}, {}, 5, "must be text"),
    ("email", {}, {}, "a@" + "b" * 250 + ".com", "at most 254"),
    ("phone", {}, {}, "123", "not a valid phone"),
    ("phone", {}, {}, "abc", "not a phone number"),
    ("phone", {}, {}, "+999 1234", "phone number"),
    ("phone", {}, {}, 4155552671, "must be text"),
    ("url", {}, {}, "example.com", "http or https"),
    ("url", {}, {}, "ftp://example.com", "http or https"),
    ("url", {}, {}, "javascript:alert(1)", "http or https"),
    ("url", {}, {}, "https://exa mple.com", "http or https"),
    ("url", {}, {}, "https://" + "a" * 2000 + ".com", "at most 2000"),
    ("user", {}, {}, "nobody", "must be an id"),
    ("user", {}, {}, 5, "must be an id"),
    ("record", {"object": "company"}, {}, "12345", "must be an id"),
    ("formula", {}, {}, "1+1", "read-only"),
    ("rollup", {}, {}, 5, "read-only"),
    ("formula", {}, {}, None, "read-only"),
]


@pytest.mark.parametrize(("type_", "options", "rules", "value", "stored"), GOOD)
def test_valid_values_are_normalized(type_, options, rules, value, stored):
    assert types.validate(field(type_, options, rules), value) == stored


@pytest.mark.parametrize(("type_", "options", "rules", "value", "message"), BAD)
def test_invalid_values_are_refused_with_a_reason(type_, options, rules, value, message):
    with pytest.raises(ValueError, match=message):
        types.validate(field(type_, options, rules), value)


@pytest.mark.parametrize("type_", [t for t in types.TYPES if t not in ("formula", "rollup")])
@pytest.mark.parametrize("empty", [None, "", "   ", [], {}])
def test_an_empty_value_means_no_value(type_, empty):
    assert types.validate(field(type_, CHOICES), empty) is None


def test_zero_and_false_are_values_not_empties():
    assert types.validate(field("number"), 0) == 0
    assert types.validate(field("boolean"), False) is False
    assert types.validate(field("money"), {"amount": 0}) == {"amount": 0, "currency": "USD"}


def test_a_phone_without_a_plus_uses_the_fields_region_then_the_default(monkeypatch):
    assert types.validate(field("phone"), "(415) 555-2671") == "+14155552671"
    with pytest.raises(ValueError, match="not a valid phone"):
        types.validate(field("phone"), "020 7946 0958")  # a UK number is not a US one
    monkeypatch.setattr(config, "DEFAULT_PHONE_REGION", "GB")
    assert types.validate(field("phone"), "020 7946 0958") == "+442079460958"
    assert types.validate(field("phone", {"region": "US"}), "(415) 555-2671") == "+14155552671"  # the field wins
    assert types.validate(field("phone"), "+1 415 555 2671") == "+14155552671"  # a + number needs no region


def test_every_type_declares_operators_and_the_registry_matches_the_database_check():
    assert set(types.TYPES) == {"text", "long_text", "number", "money", "date", "datetime", "boolean", "select",
                                "multi_select", "email", "phone", "url", "user", "record", "stage", "formula",
                                "rollup"}
    assert types.TYPES["formula"].ops == types.TYPES["rollup"].ops == frozenset()
    assert all("is_empty" in k.ops for t, k in types.TYPES.items() if t not in ("formula", "rollup"))


def test_choices_get_ids_from_their_labels_and_stay_unique():
    options = types.check_options("select", {"choices": [{"label": "Hot lead"}, {"label": "Hot lead!"},
                                                           {"label": "Won", "id": "won", "color": "green"}]})
    assert options["choices"] == [{"id": "hot_lead", "label": "Hot lead"}, {"id": "hot_lead_2", "label": "Hot lead!"},
                                  {"id": "won", "label": "Won", "color": "green"}]
    assert types.check_options("select", {}) == {"choices": []}
    for bad, message in [({"choices": "lead"}, "list"), ({"choices": [{"id": "a"}]}, "needs a label"),
                         ({"choices": [{"label": "A", "id": "a"}, {"label": "B", "id": "a"}]}, "used twice"),
                         ({"choices": [{"label": "A", "id": "Not Valid"}]}, "lower case"),
                         ({"choices": [{"label": "A", "extra": 1}]}, "needs a label"),
                         ({"choices": [{"label": str(i)} for i in range(201)]}, "at most 200"),
                         ({"nope": 1}, "no option")]:
        with pytest.raises(ValueError, match=message):
            types.check_options("select", bad)


def test_options_belong_to_their_type():
    assert types.check_options("money", {}) == {"currency": "USD"}
    assert types.check_options("money", {"currency": "eur"}) == {"currency": "EUR"}
    assert types.check_options("phone", {"region": "gb"}) == {"region": "GB"}
    assert types.check_options("record", {"object": "company"}) == {"object": "company"}
    assert types.check_options("text", {}) == {}
    for type_, bad, message in [("money", {"currency": "ZZZ"}, "ISO 4217"), ("phone", {"region": "ZZ"}, "country"),
                                ("record", {}, "key of the object"), ("text", {"choices": []}, "no option"),
                                ("number", {"currency": "USD"}, "no option"), ("text", [], "object")]:
        with pytest.raises(ValueError, match=message):
            types.check_options(type_, bad)


def test_rules_belong_to_their_type():
    assert types.check_rules("text", {"required": True, "max_length": 10}) == {"required": True, "max_length": 10}
    assert types.check_rules("number", {"min": 0, "integer": True}) == {"min": 0, "integer": True}
    assert types.check_rules("boolean", {}) == {}
    for type_, bad, message in [("text", {"min": 1}, "no rule"), ("date", {"max_length": 1}, "no rule"),
                                ("text", {"required": "yes"}, "true or false"),
                                ("text", {"max_length": "5"}, "must be a number"),
                                ("number", {"integer": 1}, "true or false"), ("text", [], "object")]:
        with pytest.raises(ValueError, match=message):
            types.check_rules(type_, bad)
