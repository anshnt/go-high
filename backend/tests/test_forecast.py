"""The forecast: pipeline, best case, commit, weighted and won per month or quarter of the close date, by currency and
by owner, on a dataset with the numbers worked out by hand."""
import pytest
from helpers import H, add_member, make_deal, move, stage_ids

P = "/api/v1/pipelines"
DEALS = "/api/v1/objects/deal/records"
EMPTY = {"pipeline": {}, "best_case": {}, "commit": {}, "weighted": {}, "won": {}}


def forecast(client, ws, pipeline, **params) -> dict:
    r = client.get(f"{P}/{pipeline}/forecast", params=params, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


def metrics(entry: dict) -> dict:
    return {k: entry[k] for k in EMPTY}


def owner(entry: dict, owner_id) -> dict:
    return metrics(next(o for o in entry["owners"] if o["owner_id"] == owner_id))


@pytest.fixture
def book(crm, db):
    """Sales stages: Lead 10 %, Qualified 25, Proposal 50, Negotiation 80, Won 100, Lost 0. Two owners (A and B) and
    deals nobody owns, in USD and EUR, closing in October and November 2026, December 2026 and January 2027; the rest
    are the ones that must not count."""
    client, ws, ids = crm
    a = client.get("/api/me").json()["user"]["id"]
    b_client = add_member(db, ids["org_id"], "b@example.com", workspace_id=ws)
    b = b_client.get("/api/me").json()["user"]["id"]
    [sales] = client.get(P, headers={H: ws}).json()["data"]
    s = stage_ids(client, ws)

    def deal(name, stage, amount, close, who=None, currency="USD", **extra):
        return make_deal(client, ws, name, s[stage], amount, close, owner_id=who, currency=currency, **extra)

    deals = {
        "d1": deal("d1", "proposal", 100000, "2026-10-10", a),
        "d2": deal("d2", "negotiation", 200000, "2026-10-20", a),
        "d3": deal("d3", "lead", 50000, "2026-10-25", b),
        "d4": deal("d4", "won", 300000, "2026-10-05", b),
        "d5": deal("d5", "negotiation", 40000, "2026-10-15", a, "EUR"),
        "d9": deal("d9", "negotiation", 10001, "2026-11-30"),
        "d12": deal("d12", "proposal", 1000, "2027-01-15"),
        "d13": deal("d13", "lead", 100, "2026-12-15"),
    }
    # what does not count: a lost deal, a deal with no close date, one with no amount, a trashed one, another pipeline
    deal("lost", "lost", 999999, "2026-10-15", a, lost_reason="price")
    deal("undated", "proposal", 70000, None, a)
    deal("no amount", "qualified", None, "2026-10-12", a)
    gone = deal("trashed", "proposal", 12345, "2026-10-12", a)
    assert client.delete(f"{DEALS}/{gone['id']}", headers={H: ws}).status_code == 204
    other = client.post(P, json={"name": "Renewals"}, headers={H: ws}).json()
    make_deal(client, ws, "renewal", other["stages"][0]["id"], 777777, "2026-10-12", owner_id=a)
    return client, ws, sales["id"], other["id"], a, b, deals, s


def test_the_forecast_adds_up_by_month_currency_and_owner(book):
    client, ws, pipeline, _, a, b, deals, s = book
    data = forecast(client, ws, pipeline)
    assert data["pipeline_id"] == pipeline and data["period"] == "month"
    assert [(p["label"], p["start"], p["end"]) for p in data["periods"]] == [
        ("2026-10", "2026-10-01", "2026-10-31"), ("2026-11", "2026-11-01", "2026-11-30"),
        ("2026-12", "2026-12-01", "2026-12-31"), ("2027-01", "2027-01-01", "2027-01-31")]
    october, november, december, january = data["periods"]
    # open deals: d1 100 000 at 50 %, d2 200 000 at 80 %, d3 50 000 at 10 % (all USD), d5 40 000 EUR at 80 %
    assert metrics(october) == {
        "pipeline": {"EUR": 40000, "USD": 350000},
        "best_case": {"EUR": 40000, "USD": 300000},  # 50 % or more: d1, d2, d5
        "commit": {"EUR": 40000, "USD": 200000},  # 80 % or more: d2, d5
        "weighted": {"EUR": 32000, "USD": 215000},  # 50 000 + 160 000 + 5 000
        "won": {"USD": 300000}}
    assert [o["owner_id"] for o in october["owners"]] == sorted([a, b])  # by id, unowned last
    assert owner(october, a) == {"pipeline": {"EUR": 40000, "USD": 300000}, "best_case": {"EUR": 40000, "USD": 300000},
                                 "commit": {"EUR": 40000, "USD": 200000}, "weighted": {"EUR": 32000, "USD": 210000},
                                 "won": {}}
    assert owner(october, b) == {"pipeline": {"USD": 50000}, "best_case": {}, "commit": {}, "weighted": {"USD": 5000},
                                 "won": {"USD": 300000}}
    assert metrics(november) == {"pipeline": {"USD": 10001}, "best_case": {"USD": 10001}, "commit": {"USD": 10001},
                                 "weighted": {"USD": 8001}, "won": {}}  # 8000.8 rounds to 8001
    assert [o["owner_id"] for o in november["owners"]] == [None] and owner(november, None) == metrics(november)
    assert metrics(december) == {"pipeline": {"USD": 100}, "best_case": {}, "commit": {}, "weighted": {"USD": 10},
                                 "won": {}}
    assert metrics(january) == {"pipeline": {"USD": 1000}, "best_case": {"USD": 1000}, "commit": {},
                                "weighted": {"USD": 500}, "won": {}}


def test_a_quarter_adds_its_months_and_rounds_once(book):
    client, ws, pipeline, _, a, b, deals, s = book
    data = forecast(client, ws, pipeline, period="quarter")
    assert data["period"] == "quarter"
    assert [(p["label"], p["start"], p["end"]) for p in data["periods"]] == [
        ("2026-Q4", "2026-10-01", "2026-12-31"), ("2027-Q1", "2027-01-01", "2027-03-31")]
    q4, q1 = data["periods"]
    assert metrics(q4) == {"pipeline": {"EUR": 40000, "USD": 360101}, "best_case": {"EUR": 40000, "USD": 310001},
                           "commit": {"EUR": 40000, "USD": 210001},
                           "weighted": {"EUR": 32000, "USD": 223011},  # one rounding of 22 301 080 / 100
                           "won": {"USD": 300000}}
    assert owner(q4, a)["pipeline"] == {"EUR": 40000, "USD": 300000} and owner(q4, b)["won"] == {"USD": 300000}
    assert owner(q4, None)["pipeline"] == {"USD": 10101} and owner(q4, None)["weighted"] == {"USD": 8011}
    assert metrics(q1)["weighted"] == {"USD": 500}


def test_the_forecast_can_be_limited_to_a_range_of_close_dates(book):
    client, ws, pipeline, _, a, b, deals, s = book
    later = forecast(client, ws, pipeline, **{"from": "2026-11-01", "to": "2026-12-31"})
    assert [p["label"] for p in later["periods"]] == ["2026-11", "2026-12"]
    middle = forecast(client, ws, pipeline, **{"from": "2026-10-12", "to": "2026-10-20"})
    [october] = middle["periods"]  # d2 on the 20th and d5 on the 15th; d1 is on the 10th, d3 on the 25th
    assert metrics(october) == {"pipeline": {"EUR": 40000, "USD": 200000}, "best_case": {"EUR": 40000, "USD": 200000},
                                "commit": {"EUR": 40000, "USD": 200000}, "weighted": {"EUR": 32000, "USD": 160000},
                                "won": {}}
    assert forecast(client, ws, pipeline, **{"from": "2030-01-01"})["periods"] == []
    for bad in ({"period": "week"}, {"from": "yesterday"}, {"to": "2026-13-01"}):
        assert client.get(f"{P}/{pipeline}/forecast", params=bad, headers={H: ws}).status_code == 422, bad


def test_each_pipeline_forecasts_its_own_deals_and_the_numbers_follow_a_move(book):
    client, ws, pipeline, renewals, a, b, deals, s = book
    [october] = forecast(client, ws, renewals)["periods"]
    assert metrics(october) == {"pipeline": {"USD": 777777}, "best_case": {}, "commit": {},
                                "weighted": {"USD": 77778}, "won": {}}  # 10 % of 777 777 is 77 777.7
    # d1 (100 000, Proposal) is won: the forecast follows at once
    assert move(client, ws, deals["d1"]["id"], s["won"]).status_code == 200
    october = forecast(client, ws, pipeline)["periods"][0]
    assert metrics(october) == {
        "pipeline": {"EUR": 40000, "USD": 250000}, "best_case": {"EUR": 40000, "USD": 200000},
        "commit": {"EUR": 40000, "USD": 200000}, "weighted": {"EUR": 32000, "USD": 165000},
        "won": {"USD": 400000}}
    # and a deal that goes to Lost leaves it
    assert move(client, ws, deals["d3"]["id"], s["lost"], lost_reason="timing").status_code == 200
    october = forecast(client, ws, pipeline)["periods"][0]
    assert october["pipeline"] == {"EUR": 40000, "USD": 200000} and october["weighted"] == {"EUR": 32000, "USD": 160000}
    assert [o["owner_id"] for o in october["owners"]] == sorted([a, b])  # B still has the won d4
    assert owner(october, b) == {**EMPTY, "won": {"USD": 300000}}
    assert client.get(f"{P}/00000000-0000-0000-0000-000000000000/forecast", headers={H: ws}).status_code == 404


def test_a_pipeline_with_no_deals_has_an_empty_forecast(crm):
    client, ws, _ = crm
    [sales] = client.get(P, headers={H: ws}).json()["data"]
    assert forecast(client, ws, sales["id"])["periods"] == []
