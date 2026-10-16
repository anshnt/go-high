"""The filter language: every operator against real rows, AND/OR/NOT nesting, tags, association paths, and the 400 a
mistake gets (never SQL)."""
import json
from datetime import UTC, datetime, timedelta

import pytest
from helpers import H, link, make_record, names, type_id
from sqlalchemy import text

from app import permissions
from app.records import filters

OBJECTS = "/api/v1/objects"
R = f"{OBJECTS}/contact/records"
NOW = datetime.now(UTC)


def day(offset: int) -> str:
    return (NOW.date() + timedelta(days=offset)).isoformat()


def moment(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def usd(amount: int, currency: str = "USD") -> dict:
    return {"amount": amount, "currency": currency}


@pytest.fixture
def book(crm):
    """Eight contacts, one of each kind of value, two tags, two companies and two deals."""
    client, ws, ids = crm
    for key, type_, extra in [("score", "number", {}), ("joined", "date", {}), ("seen", "datetime", {}),
                              ("vip", "boolean", {}), ("site", "url", {}), ("budget", "money", {}),
                              ("rep", "user", {}),
                              ("interests", "multi_select", {"options": {"choices": [
                                  {"id": "math", "label": "Math"}, {"id": "code", "label": "Code"},
                                  {"id": "poetry", "label": "Poetry"}]}})]:
        r = client.post(f"{OBJECTS}/contact/fields", json={"key": key, "label": key.title(), "type": type_, **extra},
                        headers={H: ws})
        assert r.status_code == 201, r.text
    me = client.get("/api/me").json()["user"]["id"]
    acme = make_record(client, ws, "company", name="Acme", industry="Engines", size="11-50")
    bletchley = make_record(client, ws, "company", name="Bletchley", industry="Codebreaking")
    people = {
        "ada": make_record(client, ws, first_name="Ada", last_name="Lovelace", email="ada@example.com",
                           phone="+14155552671", lifecycle="lead", score=90, joined="2020-01-15", seen=moment(2),
                           vip=True, interests=["math", "poetry"], site="https://ada.example.com",
                           budget=usd(500000), rep=me, company=acme["id"]),
        "grace": make_record(client, ws, first_name="Grace", last_name="Hopper", email="grace@navy.example",
                             lifecycle="customer", score=75, joined="2021-06-01", seen=moment(40), vip=False,
                             interests=["code"], budget=usd(120000)),
        "alan": make_record(client, ws, first_name="Alan", last_name="Turing", email="alan@example.com",
                            lifecycle="lead", score=60, joined="2019-03-10", interests=["math", "code"],
                            company=bletchley["id"]),
        "edsger": make_record(client, ws, first_name="Edsger", last_name="Dijkstra", lifecycle="churned",
                              joined="2022-09-09", seen=moment(400), budget=usd(900000, "EUR")),
        "margaret": make_record(client, ws, first_name="Margaret", last_name="Hamilton", phone="+442079460958",
                                lifecycle="other", score=100, joined=day(-10), seen=moment(0.5), vip=True),
        "linus": make_record(client, ws, first_name="Linus", email="linus@example.org", score=0),
        "o'brien": make_record(client, ws, first_name="Pat", last_name="O'Brien_100%", score=12.5),
        "empty": make_record(client, ws, email="nobody@example.com"),
    }
    tags = {}
    for name in ("vip", "beta"):
        tags[name] = client.post("/api/v1/tags", json={"name": name}, headers={H: ws}).json()["id"]
    for record, tag in (("ada", "vip"), ("grace", "vip"), ("alan", "beta")):
        client.post(f"/api/v1/records/{people[record]['id']}/tags", json={"add": [tags[tag]]}, headers={H: ws})
    deals = {name: make_record(client, ws, "deal", name=name, amount=usd(amount), stage=stage)
             for name, amount, stage in (("Engine order", 700000, "won"), ("Code audit", 90000, "proposal"))}
    contact_deal = type_id(client, ws, "deal", "contact")
    link(client, ws, deals["Engine order"]["id"], people["ada"]["id"], contact_deal)
    link(client, ws, deals["Code audit"]["id"], people["alan"]["id"], contact_deal)
    link(client, ws, deals["Code audit"]["id"], people["grace"]["id"], contact_deal)
    works_at = type_id(client, ws, "contact", "company")
    link(client, ws, people["grace"]["id"], acme["id"], works_at)
    link(client, ws, people["alan"]["id"], bletchley["id"], works_at)
    return client, ws, {"people": people, "tags": tags, "me": me, "acme": acme, "bletchley": bletchley,
                        "deals": deals}


def find(client, ws, ast, key="contact", **params) -> list[str]:
    """Display names matching `ast`, sorted. Asks both ways (query string and POST body) and insists on the same."""
    r = client.get(f"{OBJECTS}/{key}/records", params={"filter": json.dumps(ast), "limit": 200, **params},
                   headers={H: ws})
    assert r.status_code == 200, (ast, r.text)
    body = {"filter": ast, "limit": 200, **{k: v for k, v in params.items() if k != "include"}}
    post = client.post(f"{OBJECTS}/{key}/records/query", json=body, headers={H: ws})
    assert post.status_code == 200 and names(post.json()) == names(r.json()), (ast, post.text)
    return sorted(names(r.json()))


def leaf(field, op, value=None):
    return {"field": field, "op": op, **({"value": value} if value is not None else {})}


def test_text_operators(book):
    client, ws, _ = book
    assert find(client, ws, leaf("first_name", "is", "Ada")) == ["Ada Lovelace"]
    assert find(client, ws, leaf("first_name", "is", "ada")) == []  # exact
    assert "Ada Lovelace" not in find(client, ws, leaf("first_name", "is_not", "Ada"))
    assert len(find(client, ws, leaf("first_name", "is_not", "Ada"))) == 7  # includes the one with no first name
    assert find(client, ws, leaf("first_name", "contains", "RA")) == ["Grace Hopper"]  # not case sensitive
    assert find(client, ws, leaf("first_name", "contains", "ar")) == ["Margaret Hamilton"]
    assert find(client, ws, leaf("first_name", "starts_with", "gr")) == ["Grace Hopper"]
    assert find(client, ws, leaf("first_name", "in", ["Ada", "Alan", "Nobody"])) == ["Ada Lovelace", "Alan Turing"]
    assert len(find(client, ws, leaf("first_name", "not_in", ["Ada", "Alan"]))) == 6
    assert find(client, ws, leaf("last_name", "is_empty")) == ["Linus", "nobody@example.com"]
    assert len(find(client, ws, leaf("last_name", "is_not_empty"))) == 6
    # wildcard characters in the search text are text
    assert find(client, ws, leaf("last_name", "contains", "_100%")) == ["Pat O'Brien_100%"]
    assert find(client, ws, leaf("last_name", "contains", "%")) == ["Pat O'Brien_100%"]
    assert find(client, ws, leaf("last_name", "contains", "_")) == ["Pat O'Brien_100%"]
    assert find(client, ws, leaf("last_name", "starts_with", "O'B")) == ["Pat O'Brien_100%"]


def test_email_phone_and_url_compare_their_normalized_form(book):
    client, ws, _ = book
    assert find(client, ws, leaf("email", "is", " ADA@Example.COM ")) == ["Ada Lovelace"]
    assert find(client, ws, leaf("email", "contains", "example.com")) == [
        "Ada Lovelace", "Alan Turing", "nobody@example.com"]
    assert find(client, ws, leaf("email", "starts_with", "gr")) == ["Grace Hopper"]
    assert find(client, ws, leaf("phone", "is", "(415) 555-2671")) == ["Ada Lovelace"]
    assert find(client, ws, leaf("phone", "is", "+1 415 555 2671")) == ["Ada Lovelace"]
    assert find(client, ws, leaf("phone", "starts_with", "+44")) == ["Margaret Hamilton"]
    assert find(client, ws, leaf("phone", "in", ["+14155552671", "+442079460958"])) == [
        "Ada Lovelace", "Margaret Hamilton"]
    assert find(client, ws, leaf("site", "contains", "ada.example")) == ["Ada Lovelace"]
    assert find(client, ws, leaf("site", "is", "https://ada.example.com")) == ["Ada Lovelace"]
    assert len(find(client, ws, leaf("email", "is_empty"))) == 3


def test_number_operators(book):
    client, ws, _ = book
    assert find(client, ws, leaf("score", "is", 90)) == ["Ada Lovelace"]
    assert find(client, ws, leaf("score", "is", 12.5)) == ["Pat O'Brien_100%"]
    assert find(client, ws, leaf("score", "gt", 75)) == ["Ada Lovelace", "Margaret Hamilton"]
    assert find(client, ws, leaf("score", "gte", 75)) == ["Ada Lovelace", "Grace Hopper", "Margaret Hamilton"]
    assert find(client, ws, leaf("score", "lt", 60)) == ["Linus", "Pat O'Brien_100%"]
    assert find(client, ws, leaf("score", "lte", 60)) == ["Alan Turing", "Linus", "Pat O'Brien_100%"]
    assert find(client, ws, leaf("score", "between", [60, 90])) == ["Ada Lovelace", "Alan Turing", "Grace Hopper"]
    assert find(client, ws, leaf("score", "in", [60, 100])) == ["Alan Turing", "Margaret Hamilton"]
    assert len(find(client, ws, leaf("score", "not_in", [60, 100]))) == 6
    assert len(find(client, ws, leaf("score", "is_not", 90))) == 7
    assert find(client, ws, leaf("score", "is_empty")) == ["Edsger Dijkstra", "nobody@example.com"]
    assert find(client, ws, leaf("score", "is", 0)) == ["Linus"]  # zero is a value, not empty


def test_money_compares_amounts_in_the_same_currency_only(book):
    client, ws, _ = book
    assert find(client, ws, leaf("budget", "is", usd(500000))) == ["Ada Lovelace"]
    assert find(client, ws, leaf("budget", "gt", usd(100000))) == ["Ada Lovelace", "Grace Hopper"]  # not the EUR one
    assert find(client, ws, leaf("budget", "gt", usd(100000, "EUR"))) == ["Edsger Dijkstra"]
    assert find(client, ws, leaf("budget", "lte", usd(120000))) == ["Grace Hopper"]
    assert find(client, ws, leaf("budget", "between", [usd(100000), usd(600000)])) == ["Ada Lovelace", "Grace Hopper"]
    assert find(client, ws, leaf("budget", "in", [usd(120000), usd(900000, "EUR")])) == [
        "Edsger Dijkstra", "Grace Hopper"]
    assert find(client, ws, leaf("budget", "gt", {"amount": 100000})) == ["Ada Lovelace", "Grace Hopper"]  # USD default
    assert len(find(client, ws, leaf("budget", "is_empty"))) == 5
    assert find(client, ws, leaf("amount", "gt", usd(100000)), key="deal") == ["Engine order"]


def test_date_operators(book):
    client, ws, _ = book
    assert find(client, ws, leaf("joined", "is", "2020-01-15")) == ["Ada Lovelace"]
    assert find(client, ws, leaf("joined", "gt", "2021-06-01")) == ["Edsger Dijkstra", "Margaret Hamilton"]
    assert find(client, ws, leaf("joined", "gte", "2021-06-01")) == [
        "Edsger Dijkstra", "Grace Hopper", "Margaret Hamilton"]
    assert find(client, ws, leaf("joined", "lt", "2020-01-15")) == ["Alan Turing"]
    assert find(client, ws, leaf("joined", "lte", "2020-01-15")) == ["Ada Lovelace", "Alan Turing"]
    assert find(client, ws, leaf("joined", "between", ["2020-01-01", "2021-12-31"])) == [
        "Ada Lovelace", "Grace Hopper"]
    assert find(client, ws, leaf("joined", "within_last", {"days": 30})) == ["Margaret Hamilton"]
    assert find(client, ws, leaf("joined", "within_last", {"weeks": 1})) == []
    assert find(client, ws, leaf("joined", "older_than", {"years": 3})) == [
        "Ada Lovelace", "Alan Turing", "Edsger Dijkstra", "Grace Hopper"]
    assert len(find(client, ws, leaf("joined", "is_empty"))) == 3
    assert find(client, ws, leaf("close_date", "is_empty"), key="deal") == ["Code audit", "Engine order"]


def test_datetime_operators_and_the_columns_of_the_record(book):
    client, ws, _ = book
    assert find(client, ws, leaf("seen", "within_last", {"days": 7})) == ["Ada Lovelace", "Margaret Hamilton"]
    assert find(client, ws, leaf("seen", "within_last", {"hours": 6})) == []
    assert find(client, ws, leaf("seen", "within_last", {"months": 2})) == [
        "Ada Lovelace", "Grace Hopper", "Margaret Hamilton"]
    assert find(client, ws, leaf("seen", "older_than", {"days": 30})) == ["Edsger Dijkstra", "Grace Hopper"]
    assert find(client, ws, leaf("seen", "gt", moment(10))) == ["Ada Lovelace", "Margaret Hamilton"]
    assert find(client, ws, leaf("seen", "lt", day(-100))) == ["Edsger Dijkstra"]  # a date means midnight UTC
    assert find(client, ws, leaf("seen", "between", [moment(50), moment(30)])) == ["Grace Hopper"]
    assert find(client, ws, leaf("seen", "is", moment(2))) == ["Ada Lovelace"]
    assert len(find(client, ws, leaf("seen", "is_empty"))) == 4
    # created_at and updated_at are columns of the record, filtered like fields
    assert len(find(client, ws, leaf("created_at", "within_last", {"minutes": 10}))) == 8
    assert find(client, ws, leaf("created_at", "older_than", {"days": 1})) == []
    assert len(find(client, ws, leaf("updated_at", "gte", day(0)))) == 8
    assert find(client, ws, leaf("created_at", "gt", day(1))) == []
    assert len(find(client, ws, leaf("created_at", "is_not_empty"))) == 8


def test_boolean_select_multi_select_user_and_record_operators(book):
    client, ws, d = book
    assert find(client, ws, leaf("vip", "is", True)) == ["Ada Lovelace", "Margaret Hamilton"]
    assert len(find(client, ws, leaf("vip", "is", False))) == 6  # Grace Hopper plus the five never ticked
    assert find(client, ws, leaf("vip", "is_not", False)) == ["Ada Lovelace", "Margaret Hamilton"]
    assert len(find(client, ws, leaf("vip", "is_not", True))) == 6
    assert len(find(client, ws, leaf("vip", "is_empty"))) == 5

    assert find(client, ws, leaf("lifecycle", "is", "lead")) == ["Ada Lovelace", "Alan Turing"]
    assert len(find(client, ws, leaf("lifecycle", "is_not", "lead"))) == 6
    assert find(client, ws, leaf("lifecycle", "in", ["customer", "churned", "gone"])) == [
        "Edsger Dijkstra", "Grace Hopper"]
    assert len(find(client, ws, leaf("lifecycle", "not_in", ["lead", "customer"]))) == 5
    assert find(client, ws, leaf("lifecycle", "is_empty")) == ["Linus", "Pat O'Brien_100%", "nobody@example.com"]
    assert find(client, ws, leaf("lifecycle", "is", "deleted_choice")) == []  # a stale choice matches nothing

    assert find(client, ws, leaf("interests", "contains", "math")) == ["Ada Lovelace", "Alan Turing"]
    assert find(client, ws, leaf("interests", "in", ["poetry", "code"])) == [
        "Ada Lovelace", "Alan Turing", "Grace Hopper"]
    assert len(find(client, ws, leaf("interests", "not_in", ["math"]))) == 6
    assert len(find(client, ws, leaf("interests", "is_empty"))) == 5

    assert find(client, ws, leaf("rep", "is", d["me"])) == ["Ada Lovelace"]
    assert len(find(client, ws, leaf("rep", "is_empty"))) == 7
    assert find(client, ws, leaf("company", "is", d["acme"]["id"])) == ["Ada Lovelace"]
    assert find(client, ws, leaf("company", "in", [d["acme"]["id"], d["bletchley"]["id"]])) == [
        "Ada Lovelace", "Alan Turing"]
    assert len(find(client, ws, leaf("company", "is_empty"))) == 6
    assert find(client, ws, leaf("stage", "is", "won"), key="deal") == ["Engine order"]
    assert find(client, ws, leaf("stage", "in", ["won", "proposal"]), key="deal") == ["Code audit", "Engine order"]
    assert find(client, ws, leaf("owner_id", "is_empty")) != []
    assert find(client, ws, leaf("owner_id", "is", d["me"])) == []
    assert find(client, ws, leaf("created_by", "is", d["me"])) != []
    assert find(client, ws, leaf("display_name", "starts_with", "ada")) == ["Ada Lovelace"]
    assert find(client, ws, leaf("display_name", "is", "Linus")) == ["Linus"]
    assert find(client, ws, leaf("display_name", "in", ["Linus", "Grace Hopper"])) == ["Grace Hopper", "Linus"]


def test_and_or_not_nest(book):
    client, ws, d = book
    lead, vip = leaf("lifecycle", "is", "lead"), {"tag": "vip"}
    assert find(client, ws, {"and": [lead, vip]}) == ["Ada Lovelace"]
    assert find(client, ws, {"or": [lead, vip]}) == ["Ada Lovelace", "Alan Turing", "Grace Hopper"]
    assert find(client, ws, {"and": [lead, {"not": vip}]}) == ["Alan Turing"]
    # the ADR's example: a lead, created recently, and (a vip or a big deal)
    ast = {"and": [lead, leaf("created_at", "within_last", {"days": 30}),
                   {"or": [{"tag": "beta"}, leaf("deal.amount", "gt", usd(500000))]}]}
    assert find(client, ws, ast) == ["Ada Lovelace", "Alan Turing"]
    deeper = {"and": [{"or": [{"and": [lead, {"or": [leaf("score", "gte", 90), leaf("score", "lt", 70)]}]},
                              {"not": {"or": [leaf("score", "gte", 0), leaf("score", "is_empty")]}}]}]}
    assert find(client, ws, deeper) == ["Ada Lovelace", "Alan Turing"]
    assert len(find(client, ws, {"not": {"not": lead}})) == 2
    assert len(find(client, ws, {"and": []})) == 8  # nothing to satisfy: everything
    assert find(client, ws, {"or": []}) == []
    assert len(find(client, ws, {})) == 8
    assert find(client, ws, {"not": leaf("score", "gt", 10)}) == ["Edsger Dijkstra", "Linus", "nobody@example.com"]


def test_tags_filter_by_name_or_id_and_ignore_trashed_tags_of_others(book):
    client, ws, d = book
    assert find(client, ws, {"tag": "vip"}) == ["Ada Lovelace", "Grace Hopper"]
    assert find(client, ws, {"tag": "VIP"}) == ["Ada Lovelace", "Grace Hopper"]  # names are case insensitive
    assert find(client, ws, {"tag": d["tags"]["vip"]}) == ["Ada Lovelace", "Grace Hopper"]
    assert find(client, ws, {"tag": "beta"}) == ["Alan Turing"]
    assert find(client, ws, {"tag": "nonexistent"}) == []
    assert len(find(client, ws, {"not": {"tag": "vip"}})) == 6
    assert find(client, ws, {"and": [{"tag": "vip"}, {"tag": "beta"}]}) == []
    assert find(client, ws, {"or": [{"tag": "vip"}, {"tag": "beta"}]}) == [
        "Ada Lovelace", "Alan Turing", "Grace Hopper"]


def test_association_paths_look_through_links_in_both_directions(book):
    client, ws, d = book
    # contact -> company ("works at" is stored from the contact) and deal -> contact (stored from the deal);
    # the `company` field of Ada and Alan is a plain value, not an association, so a path does not see it
    assert find(client, ws, leaf("company.name", "is", "Acme")) == ["Grace Hopper"]
    assert find(client, ws, leaf("company.industry", "contains", "code")) == ["Alan Turing"]
    assert find(client, ws, leaf("deal.amount", "gt", usd(500000))) == ["Ada Lovelace"]
    assert find(client, ws, leaf("deal.stage", "is", "proposal")) == ["Alan Turing", "Grace Hopper"]
    assert find(client, ws, leaf("deal.name", "starts_with", "code")) == ["Alan Turing", "Grace Hopper"]
    assert find(client, ws, {"and": [leaf("deal.stage", "is", "proposal"), leaf("lifecycle", "is", "lead")]}) == [
        "Alan Turing"]
    assert find(client, ws, {"or": [leaf("deal.stage", "is", "won"), {"tag": "beta"}]}) == [
        "Ada Lovelace", "Alan Turing"]
    assert len(find(client, ws, {"not": leaf("deal.stage", "is", "proposal")})) == 6
    # from the other side
    assert find(client, ws, leaf("contact.lifecycle", "is", "customer"), key="company") == ["Acme"]
    assert find(client, ws, leaf("contact.first_name", "is", "Alan"), key="company") == ["Bletchley"]
    assert find(client, ws, leaf("contact.first_name", "is", "Ada"), key="company") == []
    assert find(client, ws, leaf("contact.display_name", "contains", "a"), key="deal") == ["Code audit", "Engine order"]
    assert find(client, ws, leaf("contact.email", "is", "ada@example.com"), key="deal") == ["Engine order"]
    # an association to a trashed record no longer counts
    code_audit = d["deals"]["Code audit"]["id"]
    client.delete(f"{OBJECTS}/deal/records/{code_audit}", headers={H: ws})
    assert find(client, ws, leaf("deal.stage", "is", "proposal")) == []


def test_a_mistake_in_a_filter_is_a_400_that_points_at_it(book):
    client, ws, _ = book

    def bad(ast, pointer, message, key="contact"):
        r = client.get(f"{OBJECTS}/{key}/records", params={"filter": json.dumps(ast)}, headers={H: ws})
        error = r.json()["error"]
        assert r.status_code == 400 and error["code"] == "validation_failed", (ast, r.text)
        assert list(error["fields"]) == [pointer], (ast, error)
        assert message in error["fields"][pointer], (ast, error)
        post = client.post(f"{OBJECTS}/{key}/records/query", json={"filter": ast}, headers={H: ws})
        assert post.status_code == 400 and post.json()["error"]["fields"] == error["fields"]

    bad(leaf("nope", "is", 1), "filter.field", "unknown field 'nope' on contact")
    bad({"and": [leaf("first_name", "is", "A"), leaf("nope", "is", 1)]}, "filter.and.1.field", "unknown field")
    bad({"or": [{"and": [{"not": leaf("zzz", "is", 1)}]}]}, "filter.or.0.and.0.not.field", "unknown field 'zzz'")
    bad(leaf("amount", "gt", usd(1)), "filter.field", "unknown field 'amount' on contact")  # a field of deal
    bad(leaf("first_name", "is", "x"), "filter.field", "unknown field 'first_name' on deal", key="deal")
    bad(leaf("deal.nope", "is", 1), "filter.field", "unknown field 'nope' on deal")
    bad(leaf("deal.company.name", "is", "x"), "filter.field", "must be an object key and a field")
    bad(leaf("widget.name", "is", "x"), "filter.field", "must be an object key and a field")
    bad(leaf("company.name", "is", "x"), "filter.field", "no association", key="company")
    bad(leaf("first_name", "matches", "x"), "filter.op", "'matches' does not apply to the text field")
    bad(leaf("score", "contains", 5), "filter.op", "does not apply to the number field")
    bad(leaf("vip", "gt", True), "filter.op", "does not apply to the boolean field")
    bad(leaf("interests", "gt", "math"), "filter.op", "does not apply to the multi_select field")
    bad({"field": "first_name", "value": "x"}, "filter.op", "operator is required")
    bad(leaf("score", "is", "abc"), "filter.value", "score must be a number")
    bad(leaf("email", "is", "nope"), "filter.value", "not an email")
    bad(leaf("joined", "gt", "yesterday"), "filter.value", "like 2026-10-17")
    bad(leaf("score", "is"), "filter.value", "needs a value")
    bad(leaf("score", "in", 5), "filter.value", "must be a list")
    bad(leaf("score", "in", []), "filter.value", "must be a list")
    bad(leaf("score", "in", [1, "x"]), "filter.value.1", "must be a number")
    bad(leaf("score", "between", [1]), "filter.value", "list of 2")
    bad(leaf("score", "between", [1, 2, 3]), "filter.value", "list of 2")
    bad(leaf("budget", "between", [usd(1), usd(2, "EUR")]), "filter.value", "same currency")
    bad(leaf("budget", "gt", {"amount": 1.5}), "filter.value", "whole number")
    bad(leaf("joined", "within_last", 5), "filter.value", 'like {"days": 30}')
    bad(leaf("joined", "within_last", {"days": "x"}), "filter.value", 'like {"days": 30}')
    bad(leaf("joined", "within_last", {"days": 0}), "filter.value", 'like {"days": 30}')
    bad(leaf("joined", "within_last", {"fortnights": 2}), "filter.value", 'like {"days": 30}')
    bad(leaf("joined", "within_last", {"days": 1, "hours": 1}), "filter.value", 'like {"days": 30}')
    bad(leaf("first_name", "contains", ""), "filter.value", "some text")
    bad(leaf("first_name", "contains", 5), "filter.value", "some text")
    bad(leaf("first_name", "contains", "x" * 201), "filter.value", "some text")
    bad(leaf("lifecycle", "is", ["lead"]), "filter.value", "must be a choice id")
    bad({"tag": 5}, "filter.tag", "tag name or id")
    bad({"tag": ""}, "filter.tag", "tag name or id")
    bad({"tag": "x", "extra": 1}, "filter", "only a tag")
    bad({"field": "score", "op": "is", "value": 1, "extra": 1}, "filter", "unexpected key 'extra'")
    bad({"field": 5, "op": "is"}, "filter.field", "must be a field key")
    bad({"field": "score", "op": 5}, "filter.op", "operator is required")
    bad({"and": {}}, "filter", "takes a list")
    bad({"and": [], "or": []}, "filter", "takes a list and nothing else")
    bad({"and": [{}]}, "filter.and.0", "must be an object")
    bad({"and": ["x"]}, "filter.and.0", "must be an object")
    bad({"not": []}, "filter.not", "must be an object")
    bad({"not": leaf("score", "is", 1), "x": 1}, "filter", "not takes one condition")
    bad({"nonsense": 1}, "filter", "expected one of and, or, not, tag or field")
    bad({"and": [leaf("score", "gt", n) for n in range(101)]}, "filter.and.99", "too large")
    deep = leaf("score", "gt", 1)
    for _ in range(10):
        deep = {"not": deep}
    bad(deep, "filter.not.not.not.not.not.not.not.not.not", "too large")


def test_it_is_never_sql(book, db):
    client, ws, _ = book
    for key in ("first_name'; DROP TABLE records; --", "values) OR 1=1 --", 'first_name"', "1; select pg_sleep(5)"):
        r = client.get(R, params={"filter": json.dumps(leaf(key, "is", "x"))}, headers={H: ws})
        assert r.status_code == 400 and "unknown field" in str(r.json()["error"]["fields"]), key
    for value in ("'; DROP TABLE records; --", "' OR '1'='1", "%", "\\", "\x00x"):
        for op in ("is", "contains", "starts_with", "is_not"):
            r = client.get(R, params={"filter": json.dumps(leaf("first_name", op, value))}, headers={H: ws})
            assert r.status_code in (200, 400, 422), (op, value, r.text)
    assert find(client, ws, leaf("first_name", "is", "' OR '1'='1")) == []
    assert db.scalar(text("SELECT count(*) FROM records")) == 12  # eight contacts, two companies, two deals
    r = client.get(R, params={"filter": json.dumps(leaf("first_name", "is", "x")), "sort": "first_name; drop table x"},
                   headers={H: ws})
    assert r.status_code == 400 and "sort" in r.json()["error"]["fields"]


def test_computed_and_archived_fields_cannot_be_filtered(book):
    client, ws, _ = book
    client.post(f"{OBJECTS}/contact/fields", json={"key": "calc", "label": "Calc", "type": "formula"}, headers={H: ws})
    r = client.get(R, params={"filter": json.dumps(leaf("calc", "is_empty"))}, headers={H: ws})
    assert r.status_code == 400 and "computed and cannot be filtered" in r.json()["error"]["fields"]["filter.op"]
    client.delete(f"{OBJECTS}/contact/fields/score", headers={H: ws})
    r = client.get(R, params={"filter": json.dumps(leaf("score", "gt", 1))}, headers={H: ws})
    assert r.status_code == 400 and "unknown field 'score'" in r.json()["error"]["fields"]["filter.field"]


def test_the_filter_parameter_must_be_a_json_object(book):
    client, ws, _ = book
    for raw in ("not json", "[1]", "5", '"x"', "null"):
        r = client.get(R, params={"filter": raw}, headers={H: ws})
        assert r.status_code == 400 and r.json()["error"]["fields"] == {"filter": "must be a JSON object"}, raw
    assert client.get(R, params={"filter": "x" * 8001}, headers={H: ws}).status_code == 422
    assert client.post(f"{R}/query", json={"filter": [1]}, headers={H: ws}).status_code == 422
    big = {"and": [leaf("first_name", "is", "x" * 50)] * 90}  # too long for a URL, fine in a body
    assert len(json.dumps(big)) > 8000
    assert client.post(f"{R}/query", json={"filter": big}, headers={H: ws}).status_code == 200


def test_the_scope_hook_confines_every_read_and_the_redact_hook_every_output(book, monkeypatch):
    client, ws, d = book
    people = d["people"]
    only_leads = {"field": "lifecycle", "op": "is", "value": "lead"}
    monkeypatch.setattr(permissions, "scope_filter", lambda ctx, obj: only_leads if obj.key == "contact" else
                        permissions.EVERYTHING)
    assert find(client, ws, {}) == ["Ada Lovelace", "Alan Turing"]
    assert find(client, ws, {"tag": "vip"}) == ["Ada Lovelace"]
    assert find(client, ws, {"or": [{"tag": "vip"}, leaf("score", "gt", 0)]}) == ["Ada Lovelace", "Alan Turing"]
    page = client.get(R, params={"count": "true", "q": "a"}, headers={H: ws}).json()
    assert page["total"] == 2 and sorted(names(page)) == ["Ada Lovelace", "Alan Turing"]
    assert client.get(f"{R}/{people['grace']['id']}", headers={H: ws}).status_code == 404  # never a 403
    assert client.patch(f"{R}/{people['grace']['id']}", json={}, headers={H: ws}).status_code == 404
    assert client.delete(f"{R}/{people['grace']['id']}", headers={H: ws}).status_code == 404
    assert client.get(f"/api/v1/records/{people['grace']['id']}/timeline", headers={H: ws}).status_code == 404
    assert client.get(f"/api/v1/records/{people['grace']['id']}/associations", headers={H: ws}).status_code == 404
    assert client.post(f"/api/v1/records/{people['grace']['id']}/tags", json={}, headers={H: ws}).status_code == 404
    assert client.post("/api/v1/records/tags", json={"record_ids": [people["ada"]["id"], people["grace"]["id"]]},
                       headers={H: ws}).status_code == 404
    # records reached through other records
    assert find(client, ws, {}, key="deal") == ["Code audit", "Engine order"]
    code = client.get(f"{OBJECTS}/deal/records", params={"include": "contact"}, headers={H: ws}).json()["data"]
    seen = {r["display_name"]: [a["record"]["display_name"] for a in r["associations"]["contact"]] for r in code}
    assert seen == {"Code audit": ["Alan Turing"], "Engine order": ["Ada Lovelace"]}  # Grace is out of scope
    assert find(client, ws, leaf("contact.first_name", "is", "Grace"), key="deal") == []
    assert find(client, ws, leaf("contact.first_name", "is", "Alan"), key="deal") == ["Code audit"]
    # a view counts what the caller may see
    view = client.post("/api/v1/views", json={"object": "contact", "name": "All", "filter": {}}, headers={H: ws}).json()
    assert client.get(f"/api/v1/views/{view['id']}", headers={H: ws}).json()["count"] == 2
    monkeypatch.setattr(permissions, "scope_filter", lambda ctx, obj: permissions.EVERYTHING)
    assert len(find(client, ws, {})) == 8

    monkeypatch.setattr(permissions, "redact", lambda ctx, obj, values: {k: v for k, v in values.items()
                                                                        if k != "email"})
    ada = client.get(f"{R}/{people['ada']['id']}", headers={H: ws}).json()
    assert "email" not in ada["values"] and ada["values"]["first_name"] == "Ada"
    assert all("email" not in r["values"] for r in client.get(R, headers={H: ws}).json()["data"])


def test_search_words_become_quoted_prefix_literals():
    assert filters.search_terms("ada lov") == "'ada':* & 'lov':*"
    assert filters.search_terms("a'b; DROP") == "'a':* & 'b':* & 'drop':*"
    assert filters.search_terms("!!! ???") is None
    assert filters.search_terms("ada@example.com +1415") == "'ada@example.com':* & '+1415':*"
    assert len(filters.search_terms("w " * 30).split(" & ")) == 8
