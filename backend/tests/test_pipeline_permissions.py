"""Permissions on pipelines, the deal board and the forecast: who may read and change them, what a role with a narrow
scope or hidden fields gets of them, and that their changes are in the audit log."""
import json

from helpers import H, add_member, audit, make_record, make_role, rule, user_id_of

PIPELINES = "/api/v1/pipelines"
DEALS = "/api/v1/objects/deal/records"
USD = {"currency": "USD"}


def pipeline_of(client, ws) -> dict:
    return client.get(PIPELINES, headers={H: ws}).json()["data"][0]


def deal(client, ws, name, amount, owner_id=None, close="2026-12-15"):
    return make_record(client, ws, "deal", owner_id=owner_id, name=name, amount={"amount": amount, **USD},
                       close_date=close)


def move(client, ws, deal_id, stage_id):
    return client.post(f"/api/v1/deals/{deal_id}/move", json={"stage_id": stage_id}, headers={H: ws})


def card_total(board) -> int:
    return sum(s["count"] for s in board["stages"])


def test_pipeline_routes_need_the_capability_that_fits_them(crm, db):
    admin, ws, ids = crm
    pipe = pipeline_of(admin, ws)
    stage, other = pipe["stages"][0]["id"], pipe["stages"][1]["id"]
    won = deal(admin, ws, "Won deal", 100)
    viewer = add_member(db, ids["org_id"], "v@example.com", workspace_id=ws, workspace_role="viewer")
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    manager = add_member(db, ids["org_id"], "g@example.com", workspace_id=ws, workspace_role="manager")
    base = f"{PIPELINES}/{pipe['id']}"
    for who in (viewer, member, manager, admin):  # everyone reads pipelines, boards, forecasts and their own layout
        for path in (PIPELINES, base, f"{base}/board", f"{base}/forecast", f"{base}/layout"):
            assert who.get(path, headers={H: ws}).status_code == 200, path
        assert who.put(f"{base}/layout", json={"collapsed": [stage]}, headers={H: ws}).status_code == 200
    manage = [("POST", PIPELINES, {"name": "New"}), ("PATCH", base, {"name": "Renamed"}),
              ("POST", f"{base}/stages", {"name": "Extra"}),
              ("PATCH", f"{base}/stages/{stage}", {"name": "Renamed"}), ("DELETE", f"{base}/stages/{stage}", None),
              ("POST", f"{base}/stages/reorder", {"stage_ids": [other, stage]}), ("DELETE", base, None)]
    for who in (viewer, member):
        for method, path, body in manage:
            r = who.request(method, path, json=body, headers={H: ws})
            assert r.status_code == 403 and "pipelines.manage" in r.json()["error"]["message"], (method, path)
    r = viewer.post(f"/api/v1/deals/{won['id']}/move", json={"stage_id": other}, headers={H: ws})
    assert r.status_code == 403 and "deals.write" in r.json()["error"]["message"]
    assert member.post(f"/api/v1/deals/{won['id']}/move", json={"stage_id": other}, headers={H: ws}).status_code == 200
    assert manager.post(PIPELINES, json={"name": "Renewals"}, headers={H: ws}).status_code == 201  # a manager does
    assert pipeline_of(admin, ws)["name"] == "Sales"  # and nothing the others tried changed


def test_the_board_and_the_forecast_hold_only_the_deals_a_role_may_see(crm, db):
    admin, ws, ids = crm
    make_role(admin, ws, "Own deals", rules=[rule(), rule("deal", "own")])
    ivy = add_member(db, ids["org_id"], "ivy@example.com", workspace_id=ws, workspace_role="own_deals")
    bob = add_member(db, ids["org_id"], "bob@example.com", workspace_id=ws, workspace_role="own_deals")
    pipe = pipeline_of(admin, ws)
    mine = deal(ivy, ws, "Ivy deal", 1000, owner_id=user_id_of(ivy))
    deal(admin, ws, "Bob deal", 5000, owner_id=user_id_of(bob))
    deal(admin, ws, "Nobody deal", 70000)
    base = f"{PIPELINES}/{pipe['id']}"
    everyone, ivys = (c.get(f"{base}/board", headers={H: ws}).json() for c in (admin, ivy))
    assert card_total(everyone) == 3 and card_total(ivys) == 1
    first = ivys["stages"][0]
    assert first["count"] == 1 and first["amount"] == {"USD": 1000} and [d["display_name"] for d in first["deals"]] == [
        "Ivy deal"]
    assert everyone["stages"][0]["amount"] == {"USD": 76000}
    totals = lambda who: {p["label"]: p["pipeline"] for p in who.get(  # noqa: E731
        f"{base}/forecast", headers={H: ws}).json()["periods"]}
    assert totals(admin) == {"2026-12": {"USD": 76000}} and totals(ivy) == {"2026-12": {"USD": 1000}}
    assert [o["owner_id"] for p in ivy.get(f"{base}/forecast", headers={H: ws}).json()["periods"]
            for o in p["owners"]] == [user_id_of(ivy)]
    # a stage's own pages, and moving: theirs only
    page = ivy.get(f"{base}/board", params={"stage": first["id"], "limit": 1}, headers={H: ws}).json()
    column = page["stages"][0]
    assert [d["display_name"] for d in column["deals"]] == ["Ivy deal"] and not column["next_cursor"]
    other = pipe["stages"][1]["id"]
    assert move(ivy, ws, mine["id"], other).status_code == 200
    assert ivy.get(f"{base}/board", headers={H: ws}).json()["stages"][1]["count"] == 1
    theirs = next(d["id"] for d in admin.get(f"{base}/board", headers={H: ws}).json()["stages"][0]["deals"]
                  if d["display_name"] == "Bob deal")
    assert move(ivy, ws, theirs, other).status_code == 404  # not hers: not there
    assert move(bob, ws, theirs, other).status_code == 200


def test_a_role_that_cannot_read_the_amount_gets_counts_and_no_sums(crm, db):
    admin, ws, ids = crm
    make_role(admin, ws, "No amounts", rules=[rule(), rule("deal", "all", hidden=["amount"])])
    make_role(admin, ws, "No names", rules=[rule(), rule("deal", "all", hidden=["name"])])
    blind = add_member(db, ids["org_id"], "b@example.com", workspace_id=ws, workspace_role="no_amounts")
    nameless = add_member(db, ids["org_id"], "n@example.com", workspace_id=ws, workspace_role="no_names")
    pipe = pipeline_of(admin, ws)
    deal(admin, ws, "Big deal", 9_900_000)
    base = f"{PIPELINES}/{pipe['id']}"
    full = admin.get(f"{base}/board", headers={H: ws}).json()["stages"][0]
    assert full["amount"] == {"USD": 9_900_000}
    assert full["deals"][0]["amount"] == {"amount": 9_900_000, "currency": "USD"}
    seen = blind.get(f"{base}/board", headers={H: ws}).json()
    first = seen["stages"][0]
    assert first["count"] == 1 and first["amount"] == {} and first["weighted"] == {}  # the count, not the sum
    assert first["deals"][0]["amount"] is None and "amount" not in first["deals"][0]["values"]
    assert "9900000" not in json.dumps(seen) and "9_900_000" not in json.dumps(seen)
    r = blind.get(f"{base}/forecast", headers={H: ws})
    assert r.status_code == 403 and "amount" in r.json()["error"]["message"]
    # the name is part of the card too
    assert nameless.get(f"{base}/board", headers={H: ws}).json()["stages"][0]["deals"][0]["display_name"] == "(hidden)"
    assert nameless.get(f"{base}/board", headers={H: ws}).json()["stages"][0]["amount"] == {"USD": 9_900_000}
    # and a hidden field is not one to show on a card
    r = blind.put(f"{base}/layout", json={"card_fields": ["amount"]}, headers={H: ws})
    assert r.status_code == 422 and "card_fields.0" in r.json()["error"]["fields"]
    assert blind.put(f"{base}/layout", json={"card_fields": ["close_date"]}, headers={H: ws}).status_code == 200


def test_a_role_that_cannot_read_the_stage_has_no_board_and_no_stage_events(crm, db):
    admin, ws, ids = crm
    make_role(admin, ws, "No stage", rules=[rule(), rule("deal", "all", hidden=["stage"])])
    make_role(admin, ws, "Stage auditor", copy_from="viewer", capabilities=["audit.read", "deals.read"],
              rules=[rule("*", "all", hidden=["stage"])])
    blind = add_member(db, ids["org_id"], "b@example.com", workspace_id=ws, workspace_role="no_stage")
    auditor = add_member(db, ids["org_id"], "aud@example.com", workspace_id=ws, workspace_role="stage_auditor")
    pipe = pipeline_of(admin, ws)
    mine = deal(admin, ws, "A deal", 100)
    assert move(admin, ws, mine["id"], pipe["stages"][1]["id"]).status_code == 200
    base = f"{PIPELINES}/{pipe['id']}"
    for path in (f"{base}/board", f"{base}/forecast"):
        r = blind.get(path, headers={H: ws})
        assert r.status_code == 403 and "stage" in r.json()["error"]["message"], path
    assert move(blind, ws, mine["id"], pipe["stages"][0]["id"]).status_code == 422  # not a field of deal, for them
    r = blind.get(DEALS, params={"filter": json.dumps({"field": "stage.kind", "op": "is", "value": "open"})},
                  headers={H: ws})
    assert r.status_code == 400  # the stage is not there to ask about
    assert admin.get(DEALS, params={"filter": json.dumps({"field": "stage.kind", "op": "is", "value": "open"})},
                     headers={H: ws}).json()["data"]
    record = blind.get(f"{DEALS}/{mine['id']}", headers={H: ws}).json()
    assert "stage" not in record["values"] and record["values"]["name"] == "A deal"
    timeline = blind.get(f"/api/v1/records/{mine['id']}/timeline", headers={H: ws}).json()["data"]
    assert {e["type"] for e in timeline} >= {"record.created", "record.updated"}
    assert "deal.stage_changed" not in {e["type"] for e in timeline} and pipe["stages"][1]["id"] not in json.dumps(
        timeline)
    assert "deal.stage_changed" in {e["type"] for e in audit(admin, ws)}
    rows = audit(auditor, ws)
    assert "deal.stage_changed" not in {e["type"] for e in rows} and pipe["stages"][1]["id"] not in json.dumps(rows)
    export = auditor.get("/api/v1/audit/export", headers={H: ws}).text
    assert "deal.stage_changed" not in export and pipe["stages"][1]["id"] not in export


def test_a_read_only_stage_cannot_be_changed_by_a_move_or_a_patch(crm, db):
    admin, ws, ids = crm
    make_role(admin, ws, "Fixed stage", rules=[rule(), rule("deal", "all", readonly=["stage"])])
    user = add_member(db, ids["org_id"], "f@example.com", workspace_id=ws, workspace_role="fixed_stage")
    pipe = pipeline_of(admin, ws)
    mine = deal(admin, ws, "A deal", 100)
    target = pipe["stages"][1]["id"]
    r = move(user, ws, mine["id"], target)
    assert r.status_code == 403 and r.json()["error"]["fields"] == {"values.stage": "is read-only for your role"}
    r = user.patch(f"{DEALS}/{mine['id']}", json={"values": {"stage": target}}, headers={H: ws})
    assert r.status_code == 403
    assert user.patch(f"{DEALS}/{mine['id']}", json={"values": {"name": "Renamed"}}, headers={H: ws}).status_code == 200
    got = admin.get(f"{DEALS}/{mine['id']}", headers={H: ws}).json()["values"]
    assert got["stage"] == pipe["stages"][0]["id"] and got["name"] == "Renamed"  # it did not move


def test_pipeline_and_stage_changes_are_in_the_audit_log(crm):
    client, ws, _ = crm
    me = user_id_of(client)
    h = {H: ws}

    def call(method, path, status, **kw):
        r = client.request(method, path, headers=h, **kw)
        assert r.status_code == status, (method, path, r.text)
        return r.json() if r.content else None

    sales = pipeline_of(client, ws)
    new = call("POST", PIPELINES, 201, json={"name": "Renewals", "stages": [{"name": "Due"}, {"name": "Done",
                                                                                              "kind": "won"}]})
    base = f"{PIPELINES}/{new['id']}"
    call("PATCH", base, 200, json={"name": "Renewals 2026"})
    call("PATCH", base, 200, json={"name": "Renewals 2026"})  # nothing changed: nothing recorded
    extra = call("POST", f"{base}/stages", 201, json={"name": "Extra", "rotting_days": 7})
    call("PATCH", f"{base}/stages/{extra['id']}", 200, json={"name": "Extras", "probability": 40})
    order = [new["stages"][1]["id"], new["stages"][0]["id"], extra["id"]]
    call("POST", f"{base}/stages/reorder", 200, json={"stage_ids": order})
    call("POST", f"{base}/stages/reorder", 200, json={"stage_ids": order})  # the same order again: nothing recorded
    call("DELETE", f"{base}/stages/{extra['id']}", 204)
    call("PATCH", base, 200, json={"archived": True})
    call("PATCH", base, 200, json={"archived": False})
    call("DELETE", base, 204)
    rows = audit(client, ws)
    kinds = [r["type"] for r in rows]
    for expected in ("pipeline.created", "pipeline.updated", "pipeline.archived", "pipeline.restored",
                     "pipeline.deleted", "stage.created", "stage.updated", "stage.deleted", "stages.reordered"):
        assert expected in kinds, expected
    assert kinds.count("pipeline.updated") == 1 and kinds.count("stages.reordered") == 1
    by = {r["type"]: r for r in rows if r["type"].startswith(("pipeline.", "stage"))}
    assert by["pipeline.created"]["subject"] == {"type": "pipeline", "id": new["id"]} and by[
        "pipeline.created"]["data"]["name"] == "Renewals"
    assert by["pipeline.updated"]["data"]["changes"] == {"name": {"old": "Renewals", "new": "Renewals 2026"}}
    assert by["stage.created"]["data"]["name"] == "Extra" and by["stage.created"]["data"]["rotting_days"] == 7
    assert by["stage.updated"]["data"]["changes"] == {"name": {"old": "Extra", "new": "Extras"},
                                                       "probability": {"old": 10, "new": 40}}
    assert by["stages.reordered"]["data"]["stage_ids"] == order
    assert by["stage.deleted"]["data"]["name"] == "Extras" and by["pipeline.deleted"]["data"]["name"] == "Renewals 2026"
    assert all(r["actor"] == {"type": "user", "id": me} for r in by.values()) and sales["id"] not in json.dumps(rows)
