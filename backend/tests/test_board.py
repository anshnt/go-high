"""The deal board: counts, sums and weighted sums per stage and currency, cards, rotting, paging, ordering by drag and
drop and the saved layouts."""
from decimal import Decimal

import pytest
from helpers import H, add_member, link, make_deal, make_record, move, stage_ids, type_id
from sqlalchemy import text

from app import permissions

P = "/api/v1/pipelines"
DEALS = "/api/v1/objects/deal/records"


def board(client, ws, pipeline, **params) -> dict:
    r = client.get(f"{P}/{pipeline}/board", params=params, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


def column(data: dict, name: str) -> dict:
    return next(s for s in data["stages"] if s["name"] == name)


def order(client, ws, pipeline, name: str) -> list[str]:
    """The cards of a stage from top to bottom, all of them (a page is at most 100)."""
    first = column(board(client, ws, pipeline, limit=100), name)
    found, cursor = [d["display_name"] for d in first["deals"]], first["next_cursor"]
    while cursor:
        page = column(board(client, ws, pipeline, limit=100, stage=first["id"], cursor=cursor), name)
        found += [d["display_name"] for d in page["deals"]]
        cursor = page["next_cursor"]
    return found


def positions(db, ids: list[str]) -> list[Decimal]:
    db.expire_all()
    return [db.scalar(text("SELECT board_position FROM records WHERE id = :i"), {"i": i}) for i in ids]


@pytest.fixture
def sales(crm):
    client, ws, ids = crm
    pipeline = client.get(P, headers={H: ws}).json()["data"][0]["id"]
    return client, ws, pipeline, stage_ids(client, ws)


@pytest.fixture
def pipeline_with_deals(sales):
    client, ws, pipeline, s = sales
    me = client.get("/api/me").json()["user"]["id"]
    deals = {
        "L1": make_deal(client, ws, "L1", s["lead"], 10000, "2026-11-01", owner_id=me),
        "L2": make_deal(client, ws, "L2", s["lead"], 5000, currency="EUR"),
        "L3": make_deal(client, ws, "L3", s["lead"]),
        "Q1": make_deal(client, ws, "Q1", s["qualified"], 20000),
        "P1": make_deal(client, ws, "P1", s["proposal"], 100000),
        "P2": make_deal(client, ws, "P2", s["proposal"], 50001),
        "N1": make_deal(client, ws, "N1", s["negotiation"], 80000),
        "W1": make_deal(client, ws, "W1", s["won"], 300000),
        "X1": make_deal(client, ws, "X1", s["lost"], 7, lost_reason="price"),
    }
    gone = make_deal(client, ws, "Trashed", s["lead"], 999)
    assert client.delete(f"{DEALS}/{gone['id']}", headers={H: ws}).status_code == 204
    return client, ws, pipeline, s, deals, me


def test_the_board_counts_and_sums_each_stage_by_currency(pipeline_with_deals):
    client, ws, pipeline, s, deals, me = pipeline_with_deals
    data = board(client, ws, pipeline)
    assert data["id"] == pipeline and data["name"] == "Sales" and data["object"] == "deal"
    assert [st["name"] for st in data["stages"]] == ["Lead", "Qualified", "Proposal", "Negotiation", "Won", "Lost"]
    summary = {st["name"]: (st["count"], st["amount"], st["weighted"]) for st in data["stages"]}
    assert summary == {
        "Lead": (3, {"EUR": 5000, "USD": 10000}, {"EUR": 500, "USD": 1000}),  # the trashed deal is not counted
        "Qualified": (1, {"USD": 20000}, {"USD": 5000}),
        "Proposal": (2, {"USD": 150001}, {"USD": 75001}),  # 150001 * 50 % rounds half up
        "Negotiation": (1, {"USD": 80000}, {"USD": 64000}),
        "Won": (1, {"USD": 300000}, {"USD": 300000}),
        "Lost": (1, {"USD": 7}, {"USD": 0})}
    lead = column(data, "Lead")
    assert (lead["id"], lead["kind"], lead["probability"], lead["rotting_days"]) == (s["lead"], "open", 10, 14)
    assert lead["next_cursor"] is None
    empty = client.post(P, json={"name": "Empty"}, headers={H: ws}).json()
    assert all(st["count"] == 0 and st["amount"] == {} and st["deals"] == [] for st in board(
        client, ws, empty["id"])["stages"])


def test_a_card_has_what_the_column_shows(pipeline_with_deals):
    client, ws, pipeline, s, deals, me = pipeline_with_deals
    cards = {d["display_name"]: d for d in column(board(client, ws, pipeline), "Lead")["deals"]}
    assert set(cards) == {"L1", "L2", "L3"}
    one = cards["L1"]
    assert one["id"] == deals["L1"]["id"] and one["amount"] == {"amount": 10000, "currency": "USD"}
    assert one["close_date"] == "2026-11-01" and one["owner_id"] == me and one["stage_id"] == s["lead"]
    assert one["days_in_stage"] == 0 and one["rotting"] is False and one["last_activity_at"] is not None
    assert one["stage_entered_at"] is not None and one["values"]["name"] == "L1"
    assert isinstance(one["board_position"], str) and Decimal(one["board_position"]) == 0  # the first one in
    assert Decimal(cards["L3"]["board_position"]) == -2  # and each later one lands above it
    assert cards["L3"]["amount"] is None and cards["L3"]["close_date"] is None and cards["L3"]["owner_id"] is None
    assert [d["display_name"] for d in column(board(client, ws, pipeline), "Lead")["deals"]] == ["L3", "L2", "L1"]


def test_a_deal_is_rotting_when_it_has_been_in_its_stage_for_more_days_than_the_stage_allows(pipeline_with_deals, db):
    client, ws, pipeline, s, deals, me = pipeline_with_deals
    # Lead rots after 14 days, counted from creation for a deal that never moved; whole days, as the card shows
    for name, age in (("L1", "20 days 3 hours"), ("L2", "14 days 1 hour"), ("L3", "15 days 2 hours"),
                      ("W1", "30 days")):
        db.execute(text(f"UPDATE records SET created_at = now() - interval '{age}' WHERE id = :i"),
                   {"i": deals[name]["id"]})
    db.commit()
    # Proposal rots after 21 days, counted from the last move into it
    for name, days in (("P1", 30), ("P2", 21)):
        assert move(client, ws, deals[name]["id"], s["negotiation"]).status_code == 200
        assert move(client, ws, deals[name]["id"], s["proposal"]).status_code == 200
        db.execute(text("UPDATE events SET occurred_at = now() - make_interval(days => :d) WHERE subject_id = :i "
                        "AND type = 'deal.stage_changed'"), {"d": days, "i": deals[name]["id"]})
    db.commit()
    assert move(client, ws, deals["Q1"]["id"], s["qualified"]).status_code == 200  # not a move: it is there already
    data = board(client, ws, pipeline)
    flags = {d["display_name"]: (d["days_in_stage"], d["rotting"]) for st in data["stages"] for d in st["deals"]}
    assert flags["L1"] == (20, True) and flags["L2"] == (14, False) and flags["L3"] == (15, True)
    assert flags["P1"] == (30, True) and flags["P2"] == (21, False)
    assert flags["Q1"] == (0, False)
    assert flags["W1"] == (30, False) and flags["X1"][1] is False  # stages with no limit never rot
    assert column(data, "Lead")["deals"][0]["stage_entered_at"] is not None
    # the stage decides: loosen Lead and nothing in it rots, tighten it and L2 does too
    for days, rotting in ((25, []), (10, ["L1", "L2", "L3"]), (None, [])):
        client.patch(f"{P}/{pipeline}/stages/{s['lead']}", json={"rotting_days": days}, headers={H: ws})
        found = [d["display_name"] for d in column(board(client, ws, pipeline), "Lead")["deals"] if d["rotting"]]
        assert sorted(found) == rotting, days


def test_a_card_shows_when_something_last_happened_to_the_deal(sales, db):
    client, ws, pipeline, s = sales
    deal = make_deal(client, ws, "Busy", s["lead"])
    ada = make_record(client, ws, first_name="Ada")

    def seen():
        return column(board(client, ws, pipeline), "Lead")["deals"][0]["last_activity_at"]

    created = seen()
    link(client, ws, deal["id"], ada["id"], type_id(client, ws, "deal", "contact"))  # on the deal's timeline
    linked = seen()
    assert linked > created
    assert move(client, ws, deal["id"], s["qualified"]).status_code == 200
    assert column(board(client, ws, pipeline), "Qualified")["deals"][0]["last_activity_at"] > linked


def test_each_stage_pages_on_its_own_and_its_cursor_belongs_to_it(sales):
    client, ws, pipeline, s = sales
    for n in range(5):
        make_deal(client, ws, f"Lead {n}", s["lead"], 100)
    make_deal(client, ws, "Q", s["qualified"], 200)
    first = board(client, ws, pipeline, limit=2)
    lead = column(first, "Lead")
    assert lead["count"] == 5 and lead["amount"] == {"USD": 500}  # the totals are for the whole stage
    assert [d["display_name"] for d in lead["deals"]] == ["Lead 4", "Lead 3"] and lead["next_cursor"]
    assert column(first, "Qualified")["next_cursor"] is None
    seen, cursor = [d["display_name"] for d in lead["deals"]], lead["next_cursor"]
    while cursor:
        page = board(client, ws, pipeline, limit=2, stage=s["lead"], cursor=cursor)
        assert [st["name"] for st in page["stages"]] == ["Lead"]  # that column only
        assert page["stages"][0]["count"] == 5
        seen += [d["display_name"] for d in page["stages"][0]["deals"]]
        cursor = page["stages"][0]["next_cursor"]
    assert seen == ["Lead 4", "Lead 3", "Lead 2", "Lead 1", "Lead 0"]
    # the other stage's cursor, a cursor with no stage, a made up one and unknown stages are all refused
    r = client.get(f"{P}/{pipeline}/board", params={"stage": s["qualified"], "cursor": lead["next_cursor"]},
                   headers={H: ws})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_cursor"
    r = client.get(f"{P}/{pipeline}/board", params={"cursor": lead["next_cursor"]}, headers={H: ws})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_cursor"
    r = client.get(f"{P}/{pipeline}/board", params={"stage": s["lead"], "cursor": "nope"}, headers={H: ws})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_cursor"
    other = client.post(P, json={"name": "Other"}, headers={H: ws}).json()
    for stage in ("00000000-0000-0000-0000-000000000000", other["stages"][0]["id"]):
        assert client.get(f"{P}/{pipeline}/board", params={"stage": stage}, headers={H: ws}).status_code == 404
    for limit in (0, 101):
        assert client.get(f"{P}/{pipeline}/board", params={"limit": limit}, headers={H: ws}).status_code == 422
    assert client.get(f"{P}/00000000-0000-0000-0000-000000000000/board", headers={H: ws}).status_code == 404


def test_the_board_reads_through_the_permission_hooks(pipeline_with_deals, monkeypatch):
    client, ws, pipeline, s, deals, me = pipeline_with_deals
    monkeypatch.setattr(permissions, "scope_filter", lambda ctx, obj: {"field": "name", "op": "starts_with",
                                                                       "value": "P"})
    data = board(client, ws, pipeline)
    assert {st["name"]: st["count"] for st in data["stages"]} == {
        "Lead": 0, "Qualified": 0, "Proposal": 2, "Negotiation": 0, "Won": 0, "Lost": 0}
    assert column(data, "Proposal")["amount"] == {"USD": 150001} and column(data, "Lead")["amount"] == {}
    monkeypatch.setattr(permissions, "scope_filter", lambda ctx, obj: permissions.EVERYTHING)
    monkeypatch.setattr(permissions, "redact", lambda ctx, obj, values: {k: v for k, v in values.items()
                                                                        if k != "amount"})
    card = column(board(client, ws, pipeline), "Proposal")["deals"][0]
    assert card["amount"] is None and "amount" not in card["values"]
    # the sums of the whole stage still read amount: documented as a gap for the permission module
    assert column(board(client, ws, pipeline), "Proposal")["amount"] == {"USD": 150001}


def test_a_new_deal_and_a_deal_entering_a_stage_land_on_top(sales):
    client, ws, pipeline, s = sales
    a, b, c = (make_deal(client, ws, n, s["lead"]) for n in "ABC")
    assert order(client, ws, pipeline, "Lead") == ["C", "B", "A"]
    assert move(client, ws, a["id"], s["qualified"]).status_code == 200
    assert move(client, ws, b["id"], s["qualified"]).status_code == 200
    assert order(client, ws, pipeline, "Qualified") == ["B", "A"] and order(client, ws, pipeline, "Lead") == ["C"]
    # a move inside the stage with nothing said about where changes nothing
    assert move(client, ws, a["id"], s["qualified"]).status_code == 200
    assert order(client, ws, pipeline, "Qualified") == ["B", "A"]


def test_a_drop_between_two_cards_is_one_write_to_the_dropped_deal(sales, db):
    client, ws, pipeline, s = sales
    cards = {n: make_deal(client, ws, n, s["lead"]) for n in "ABCDE"}
    ids = [c["id"] for c in cards.values()]
    assert order(client, ws, pipeline, "Lead") == ["E", "D", "C", "B", "A"]
    before = positions(db, ids)
    updated = db.scalar(text("SELECT updated_at FROM records WHERE id = :i"), {"i": cards["A"]["id"]})
    events_before = db.scalar(text("SELECT count(*) FROM events"))
    # A, the bottom card, dropped between E and D
    r = move(client, ws, cards["A"]["id"], s["lead"], after_id=cards["E"]["id"], before_id=cards["D"]["id"])
    assert r.status_code == 200 and r.json()["display_name"] == "A" and r.json()["stage_id"] == s["lead"]
    assert order(client, ws, pipeline, "Lead") == ["E", "A", "D", "C", "B"]
    after = positions(db, ids)
    changed = [n for n, x, y in zip("ABCDE", before, after, strict=True) if x != y]
    assert changed == ["A"] and Decimal(r.json()["board_position"]) == after[0]
    assert before[4] < after[0] < before[3]  # the midpoint of the two it landed between
    assert db.scalar(text("SELECT updated_at FROM records WHERE id = :i"), {"i": cards["A"]["id"]}) == updated
    assert db.scalar(text("SELECT count(*) FROM events")) == events_before  # a reorder is not an event
    # only a card above: it goes to the bottom; only one below: to the top
    assert move(client, ws, cards["E"]["id"], s["lead"], after_id=cards["B"]["id"]).status_code == 200
    assert order(client, ws, pipeline, "Lead") == ["A", "D", "C", "B", "E"]
    assert move(client, ws, cards["C"]["id"], s["lead"], before_id=cards["A"]["id"]).status_code == 200
    assert order(client, ws, pipeline, "Lead") == ["C", "A", "D", "B", "E"]
    # a position of your own, as text or as a number
    assert move(client, ws, cards["B"]["id"], s["lead"], position="-1000.5").status_code == 200
    assert order(client, ws, pipeline, "Lead") == ["B", "C", "A", "D", "E"]
    assert move(client, ws, cards["B"]["id"], s["lead"], position=10 ** 6).status_code == 200
    assert order(client, ws, pipeline, "Lead") == ["C", "A", "D", "E", "B"]


def test_a_drop_into_another_stage_lands_between_the_cards_there(sales, db):
    client, ws, pipeline, s = sales
    q = [make_deal(client, ws, n, s["qualified"]) for n in ("Q1", "Q2", "Q3")]  # Q3 on top
    mover = make_deal(client, ws, "Mover", s["lead"])
    assert order(client, ws, pipeline, "Qualified") == ["Q3", "Q2", "Q1"]
    r = move(client, ws, mover["id"], s["qualified"], after_id=q[1]["id"], before_id=q[0]["id"])
    assert r.status_code == 200 and r.json()["stage_id"] == s["qualified"]
    assert order(client, ws, pipeline, "Qualified") == ["Q3", "Q2", "Mover", "Q1"]
    assert order(client, ws, pipeline, "Lead") == []
    assert [e[0] for e in db.execute(text("SELECT data ->> 'to_stage' FROM events WHERE subject_id = :i "
                                          "AND type = 'deal.stage_changed'"), {"i": mover["id"]})] == ["Qualified"]
    top = make_deal(client, ws, "Top", s["lead"])  # dropped above the first card of another stage
    assert move(client, ws, top["id"], s["qualified"], before_id=q[2]["id"]).status_code == 200
    assert order(client, ws, pipeline, "Qualified")[0] == "Top"


def test_a_bad_drop_is_refused_and_changes_nothing(sales, db):
    client, ws, pipeline, s = sales
    a, b = make_deal(client, ws, "A", s["lead"]), make_deal(client, ws, "B", s["lead"])
    elsewhere = make_deal(client, ws, "Elsewhere", s["qualified"])
    trashed = make_deal(client, ws, "Trashed", s["lead"])
    client.delete(f"{DEALS}/{trashed['id']}", headers={H: ws})
    snapshot = positions(db, [a["id"], b["id"], elsewhere["id"]])
    nobody = "00000000-0000-0000-0000-000000000000"
    for body, field in (({"after_id": elsewhere["id"]}, "after_id"), ({"before_id": elsewhere["id"]}, "before_id"),
                        ({"after_id": a["id"]}, "after_id"), ({"before_id": a["id"]}, "before_id"),
                        ({"after_id": nobody}, "after_id"), ({"before_id": trashed["id"]}, "before_id")):
        r = move(client, ws, a["id"], s["lead"], **body)
        assert r.status_code == 422 and list(r.json()["error"]["fields"]) == [field], (body, r.text)
    r = move(client, ws, a["id"], s["lead"], position=1, after_id=b["id"])
    assert r.status_code == 422 and list(r.json()["error"]["fields"]) == ["position"]
    # the neighbours must be in the order the board shows: B is above A, not the other way round
    r = move(client, ws, make_deal(client, ws, "C", s["lead"])["id"], s["lead"], after_id=a["id"], before_id=b["id"])
    assert r.status_code == 409 and "reload the board" in r.json()["error"]["message"]
    for bad in ("nope", "NaN", "Infinity", True):
        assert move(client, ws, a["id"], s["lead"], position=bad).status_code == 422, bad
    assert positions(db, [a["id"], b["id"], elsewhere["id"]]) == snapshot


def test_many_drops_between_the_same_two_cards_stay_in_order(sales, db):
    """Halving a gap sixty times would run a double out of digits; a position is an exact number."""
    client, ws, pipeline, s = sales
    bottom, top = make_deal(client, ws, "Bottom", s["lead"]), make_deal(client, ws, "Top", s["lead"])
    assert order(client, ws, pipeline, "Lead") == ["Top", "Bottom"]
    drops = []
    below = bottom["id"]
    for n in range(60):  # each lands between Top and the card dropped before it
        drop = make_deal(client, ws, f"Down {n}", s["lead"])
        assert move(client, ws, drop["id"], s["lead"], after_id=top["id"], before_id=below).status_code == 200
        drops.append(drop["id"])
        below = drop["id"]
    expected = ["Top", *[f"Down {n}" for n in reversed(range(60))], "Bottom"]
    assert order(client, ws, pipeline, "Lead") == expected
    above, rising = drops[0], []
    for n in range(60):  # and the other way: each lands between the card dropped before it and Bottom
        drop = make_deal(client, ws, f"Up {n}", s["lead"])
        assert move(client, ws, drop["id"], s["lead"], after_id=above, before_id=bottom["id"]).status_code == 200
        rising.append(drop["id"])
        above = drop["id"]
    expected = ["Top", *[f"Down {n}" for n in reversed(range(60))], *[f"Up {n}" for n in range(60)], "Bottom"]
    assert order(client, ws, pipeline, "Lead") == expected
    chain = [top["id"], *reversed(drops), *rising, bottom["id"]]
    spots = positions(db, chain)
    assert all(a < b for a, b in zip(spots, spots[1:], strict=False))  # strictly increasing, no ties
    assert max(len(str(p)) for p in spots) > 60  # more digits than a double has


def test_a_deal_dragged_through_stages_with_rules_enforced_updates_the_totals(sales):
    client, ws, pipeline, s = sales
    client.patch(f"{P}/{pipeline}/stages/{s['proposal']}", json={"exit_rules": {"and": [
        {"field": "amount", "op": "is_not_empty"}, {"field": "close_date", "op": "is_not_empty"}]}}, headers={H: ws})
    deal = make_deal(client, ws, "Journey", s["lead"], 60000)
    for name in ("qualified", "proposal"):
        assert move(client, ws, deal["id"], s[name]).status_code == 200
    r = move(client, ws, deal["id"], s["won"])
    assert r.status_code == 422 and list(r.json()["error"]["fields"]) == ["values.close_date"]
    assert column(board(client, ws, pipeline), "Proposal")["weighted"] == {"USD": 30000}
    client.patch(f"{DEALS}/{deal['id']}", json={"values": {"close_date": "2026-12-24"}}, headers={H: ws})
    assert move(client, ws, deal["id"], s["won"]).status_code == 200
    data = board(client, ws, pipeline)
    assert column(data, "Proposal")["count"] == 0 and column(data, "Won")["weighted"] == {"USD": 60000}


def test_the_default_layout_and_a_saved_one_belong_to_the_user(crm, db):
    client, ws, ids = crm
    [sales] = client.get(P, headers={H: ws}).json()["data"]
    s = stage_ids(client, ws)
    url = f"{P}/{sales['id']}/layout"
    default = {"pipeline_id": sales["id"], "collapsed": [], "card_fields": ["amount", "close_date", "owner_id"],
               "updated_at": None}
    assert client.get(url, headers={H: ws}).json() == default
    r = client.put(url, json={"collapsed": [s["won"], s["lost"], s["won"]], "card_fields": ["name", "amount", "name"]},
                   headers={H: ws})
    assert r.status_code == 200
    saved = r.json()
    assert saved["collapsed"] == [s["won"], s["lost"]] and saved["card_fields"] == ["name", "amount"]
    assert saved["updated_at"] is not None and client.get(url, headers={H: ws}).json() == saved
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    assert member.get(url, headers={H: ws}).json() == default  # nobody else's layout is seen
    mine = member.put(url, json={"collapsed": [s["lead"]], "card_fields": ["owner_id", "created_at"]}, headers={H: ws})
    assert mine.status_code == 200 and mine.json()["collapsed"] == [s["lead"]]
    assert client.get(url, headers={H: ws}).json() == saved
    assert db.scalar(text("SELECT count(*) FROM board_layouts")) == 2
    again = client.put(url, json={"collapsed": [], "card_fields": ["amount"]}, headers={H: ws}).json()
    assert again["collapsed"] == [] and again["updated_at"] >= saved["updated_at"]
    assert db.scalar(text("SELECT count(*) FROM board_layouts")) == 2  # an update, not a second row
    # a stage that is gone drops out of the saved layout
    client.put(url, json={"collapsed": [s["lost"], s["won"]]}, headers={H: ws})
    assert client.delete(f"{P}/{sales['id']}/stages/{s['lost']}", headers={H: ws}).status_code == 204
    assert client.get(url, headers={H: ws}).json()["collapsed"] == [s["won"]]


def test_a_layout_must_name_stages_of_the_pipeline_and_fields_of_a_deal(crm):
    client, ws, _ = crm
    [sales] = client.get(P, headers={H: ws}).json()["data"]
    spare = client.post(P, json={"name": "Spare"}, headers={H: ws}).json()
    url = f"{P}/{sales['id']}/layout"
    stage = sales["stages"][0]["id"]
    r = client.put(url, json={"collapsed": [stage, spare["stages"][0]["id"], "00000000-0000-0000-0000-000000000000"],
                              "card_fields": ["amount", "nope"]}, headers={H: ws})
    assert r.status_code == 422
    assert r.json()["error"]["fields"] == {"collapsed.1": "is not a stage of this pipeline",
                                           "collapsed.2": "is not a stage of this pipeline",
                                           "card_fields.1": "unknown field 'nope'"}
    for body in ({"collapsed": "x"}, {"collapsed": ["nope"]}, {"card_fields": [f"f{i}" for i in range(21)]},
                 {"card_fields": ["Not A Key"]}):
        assert client.put(url, json=body, headers={H: ws}).status_code == 422, body
    assert client.get(url, headers={H: ws}).json()["updated_at"] is None  # none of it was saved
    assert client.put(url, json={"card_fields": ["lost_reason", "stage"]}, headers={H: ws}).status_code == 200
    assert client.get(f"{P}/00000000-0000-0000-0000-000000000000/layout", headers={H: ws}).status_code == 404
    assert client.put(f"{P}/00000000-0000-0000-0000-000000000000/layout", json={}, headers={H: ws}).status_code == 404
