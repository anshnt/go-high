"""Pipelines and stages: seeding, the API, the stage field, exit rules, lost reasons, stage events and filters."""
import json

from helpers import H, add_member, link, listing, make_deal, make_record, move, names, stage_ids, type_id
from sqlalchemy import text

P = "/api/v1/pipelines"
DEALS = "/api/v1/objects/deal/records"
SALES = [("Lead", "open", 10, 14), ("Qualified", "open", 25, 14), ("Proposal", "open", 50, 21),
         ("Negotiation", "open", 80, 21), ("Won", "won", 100, None), ("Lost", "lost", 0, None)]


def pipelines(client, ws, **params) -> list[dict]:
    r = client.get(P, params=params, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def stage_events(db, deal_id) -> list[dict]:
    db.expire_all()
    return [row[0] for row in db.execute(text("SELECT data FROM events WHERE subject_id = :i AND "
                                              "type = 'deal.stage_changed' ORDER BY id"), {"i": deal_id})]


def deal_stage(client, ws, deal_id) -> str | None:
    return client.get(f"{DEALS}/{deal_id}", headers={H: ws}).json()["values"].get("stage")


def error_fields(r) -> dict:
    return r.json()["error"]["fields"]


def new_stage(client, ws, pipeline, **body):
    r = client.post(f"{P}/{pipeline}/stages", json=body, headers={H: ws})
    assert r.status_code == 201, r.text
    return r.json()


def rules(client, ws, pipeline, stage, exit_rules):
    r = client.patch(f"{P}/{pipeline}/stages/{stage}", json={"exit_rules": exit_rules}, headers={H: ws})
    assert r.status_code == 200, r.text


def filled(amount=1000):
    return {"amount": {"amount": amount, "currency": "USD"}, "close_date": "2026-12-01"}


NEEDS_MONEY = {"and": [{"field": "amount", "op": "is_not_empty"}, {"field": "close_date", "op": "is_not_empty"}]}


def test_every_workspace_starts_with_a_sales_pipeline(crm):
    client, ws, ids = crm
    second = client.post("/api/workspaces", json={"name": "Second", "brand_id": ids["brand_id"]}).json()["id"]
    seen = set()
    for workspace in (ws, second):
        [sales] = pipelines(client, workspace)
        assert (sales["name"], sales["object"], sales["position"], sales["archived_at"]) == ("Sales", "deal", 0, None)
        assert [(s["name"], s["kind"], s["probability"], s["rotting_days"]) for s in sales["stages"]] == SALES
        assert [s["position"] for s in sales["stages"]] == [0, 1, 2, 3, 4, 5]
        assert all(s["exit_rules"] == {} and s["pipeline_id"] == sales["id"] for s in sales["stages"])
        seen |= {sales["id"], *(s["id"] for s in sales["stages"])}
        got = client.get(f"{P}/{sales['id']}", headers={H: workspace}).json()
        assert got["stages"] == sales["stages"]
    assert len(seen) == 14  # nothing is shared between workspaces


def test_a_deal_has_lost_reason_fields_and_a_stage_field_without_choices(crm):
    client, ws, _ = crm
    fields = {f["key"]: f for f in client.get("/api/v1/objects/deal", headers={H: ws}).json()["fields"]}
    assert fields["stage"]["type"] == "stage" and fields["stage"]["options"] == {}
    assert fields["lost_reason"]["type"] == "select" and fields["lost_reason"]["is_system"]
    assert [c["id"] for c in fields["lost_reason"]["options"]["choices"]] == [
        "price", "timing", "competitor", "no_decision", "other"]
    assert fields["lost_note"]["type"] == "long_text"
    r = client.post("/api/v1/objects/deal/fields", json={"key": "phase", "label": "Phase", "type": "stage",
                                                         "options": {"choices": []}}, headers={H: ws})
    assert r.status_code == 422 and "no option" in error_fields(r)["options"]


def test_a_new_deal_starts_in_the_first_open_stage_and_needs_no_contact(crm, db):
    client, ws, _ = crm
    stages = stage_ids(client, ws)
    deal = make_deal(client, ws, "Lonely deal")
    assert deal["values"]["stage"] == stages["lead"]
    assert db.scalar(text("SELECT board_position FROM records WHERE id = :i"), {"i": deal["id"]}) == 0
    assert client.get(f"/api/v1/records/{deal['id']}/associations", headers={H: ws}).json()["data"] == []
    newer = make_deal(client, ws, "Newer deal")  # a deal lands on top of the column
    assert db.scalar(text("SELECT board_position FROM records WHERE id = :i"), {"i": newer["id"]}) == -1
    named = make_deal(client, ws, "Picked", stage=stages["proposal"])
    assert named["values"]["stage"] == stages["proposal"]
    bare = client.post(DEALS, json={"values": {"name": "No stage", "stage": None}}, headers={H: ws}).json()
    assert "stage" not in bare["values"]  # asking for none is honored
    # the lead column of an empty workspace is the same default for the next one
    moved = move(client, ws, deal["id"], stages["won"])
    assert moved.status_code == 200 and deal_stage(client, ws, deal["id"]) == stages["won"]


def test_a_stage_value_must_be_a_stage_of_a_live_pipeline_of_this_workspace(crm, make_user):
    client, ws, ids = crm
    other, other_ids = make_user("b@example.com")
    foreign = stage_ids(other, other_ids["workspace_id"])["lead"]
    [sales] = pipelines(client, ws)
    spare = client.post(P, json={"name": "Spare"}, headers={H: ws}).json()
    for stage in (foreign, "00000000-0000-0000-0000-000000000000", "nope", 5):
        r = client.post(DEALS, json={"values": {"name": "X", "stage": stage}}, headers={H: ws})
        assert r.status_code == 422, stage
        assert list(error_fields(r)) == ["values.stage"], (stage, r.text)
    assert "is not a stage of an active pipeline" in error_fields(
        client.post(DEALS, json={"values": {"name": "X", "stage": foreign}}, headers={H: ws}))["values.stage"]
    assert listing(client, ws, "deal")["data"] == []
    assert client.patch(f"{P}/{spare['id']}", json={"archived": True}, headers={H: ws}).status_code == 200
    r = client.post(DEALS, json={"values": {"name": "X", "stage": spare["stages"][0]["id"]}}, headers={H: ws})
    assert r.status_code == 422 and list(error_fields(r)) == ["values.stage"]  # an archived pipeline takes no deals
    assert sales["stages"][0]["id"] == stage_ids(client, ws)["lead"]


def test_pipelines_are_created_listed_renamed_archived_and_deleted(crm, db):
    client, ws, ids = crm
    [sales] = pipelines(client, ws)
    r = client.post(P, json={"name": "Renewals", "stages": [
        {"name": "Open", "kind": "open", "probability": 40, "rotting_days": 30, "color": "blue"},
        {"name": "Renewed", "kind": "won"}, {"name": "Churned", "kind": "lost", "probability": 0}]}, headers={H: ws})
    assert r.status_code == 201, r.text
    renewals = r.json()
    assert (renewals["name"], renewals["position"]) == ("Renewals", 1)
    assert [(s["name"], s["position"], s["probability"], s["rotting_days"], s["color"]) for s in
            renewals["stages"]] == [("Open", 0, 40, 30, "blue"), ("Renewed", 1, 100, None, None),
                                    ("Churned", 2, 0, None, None)]
    assert [p["name"] for p in pipelines(client, ws)] == ["Sales", "Renewals"]
    plain = client.post(P, json={"name": "Another"}, headers={H: ws}).json()  # no stages: the Sales stages
    assert [(s["name"], s["probability"]) for s in plain["stages"]] == [(n, p) for n, _, p, _ in SALES]
    assert client.post(P, json={"name": "Empty", "stages": []}, headers={H: ws}).json()["stages"] == []

    r = client.post(P, json={"name": "Bad", "stages": [{"name": "A"}, {"name": "W", "kind": "won", "probability": 70}]},
                    headers={H: ws})
    assert r.status_code == 422 and error_fields(r) == {"stages.1.probability": "is 100 for a won stage"}
    r = client.post(P, json={"name": "Bad", "stages": [{"name": "A", "exit_rules": {"field": "nope", "op": "is"}}]},
                    headers={H: ws})
    assert r.status_code == 400 and list(error_fields(r)) == ["stages.0.exit_rules.field"]
    assert client.post(P, json={"name": " "}, headers={H: ws}).status_code == 422
    assert client.post(P, json={"name": "Many", "stages": [{"name": str(i)} for i in range(31)]},
                       headers={H: ws}).status_code == 422
    assert len(pipelines(client, ws)) == 4

    r = client.patch(f"{P}/{renewals['id']}", json={"name": "Renewal cycle", "position": 7}, headers={H: ws})
    assert r.status_code == 200 and (r.json()["name"], r.json()["position"]) == ("Renewal cycle", 7)
    assert client.patch(f"{P}/{renewals['id']}", json={"name": None}, headers={H: ws}).status_code == 422
    assert [p["name"] for p in pipelines(client, ws)][:2] == ["Sales", "Another"]  # by position

    r = client.patch(f"{P}/{renewals['id']}", json={"archived": True}, headers={H: ws})
    assert r.json()["archived_at"] is not None
    assert renewals["id"] not in [p["id"] for p in pipelines(client, ws)]
    assert [p["id"] for p in pipelines(client, ws, archived="true")] == [renewals["id"]]
    assert client.get(f"{P}/{renewals['id']}", headers={H: ws}).status_code == 200  # still readable
    back = client.patch(f"{P}/{renewals['id']}", json={"archived": False}, headers={H: ws})
    assert back.json()["archived_at"] is None

    # a pipeline with no deals is deleted, with its stages
    gone = client.delete(f"{P}/{plain['id']}", headers={H: ws})
    assert gone.status_code == 204 and gone.content == b""
    assert client.get(f"{P}/{plain['id']}", headers={H: ws}).status_code == 404
    assert db.scalar(text("SELECT count(*) FROM stages WHERE pipeline_id = :p"), {"p": plain["id"]}) == 0
    # one with deals is archived instead, and its deals stay where they are
    deal = make_deal(client, ws, "Kept", stage=renewals["stages"][0]["id"])
    r = client.delete(f"{P}/{renewals['id']}", headers={H: ws})
    assert r.status_code == 200 and r.json()["archived_at"] is not None and len(r.json()["stages"]) == 3
    assert deal_stage(client, ws, deal["id"]) == renewals["stages"][0]["id"]
    assert client.delete(f"{P}/{renewals['id']}", headers={H: ws}).status_code == 200  # still has its deal
    assert client.get(f"{P}/{renewals['id']}", headers={H: ws}).status_code == 200
    # a stage of an archived pipeline takes no deal, and a deal may not be moved into it
    assert move(client, ws, deal["id"], renewals["stages"][1]["id"]).status_code == 422
    assert sales["id"] in [p["id"] for p in pipelines(client, ws)]


def test_the_last_pipeline_cannot_be_archived_or_deleted(crm):
    client, ws, _ = crm
    [sales] = pipelines(client, ws)
    for r in (client.patch(f"{P}/{sales['id']}", json={"archived": True}, headers={H: ws}),
              client.delete(f"{P}/{sales['id']}", headers={H: ws})):
        assert r.status_code == 409 and r.json()["error"]["code"] == "conflict"
    spare = client.post(P, json={"name": "Spare"}, headers={H: ws}).json()
    assert client.delete(f"{P}/{sales['id']}", headers={H: ws}).status_code == 204  # now another one remains
    assert [p["id"] for p in pipelines(client, ws)] == [spare["id"]]
    # the deals of a new deal now start in the remaining pipeline
    assert make_deal(client, ws, "D")["values"]["stage"] == spare["stages"][0]["id"]


def test_only_admins_change_pipelines_but_every_member_reads_them(crm, db):
    client, ws, ids = crm
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    [sales] = pipelines(member, ws)
    stage = sales["stages"][0]["id"]
    attempts = [("POST", P, {"name": "x"}), ("PATCH", f"{P}/{sales['id']}", {"name": "x"}),
                ("DELETE", f"{P}/{sales['id']}", None), ("POST", f"{P}/{sales['id']}/stages", {"name": "x"}),
                ("PATCH", f"{P}/{sales['id']}/stages/{stage}", {"name": "x"}),
                ("DELETE", f"{P}/{sales['id']}/stages/{stage}", None),
                ("POST", f"{P}/{sales['id']}/stages/reorder", {"stage_ids": []})]
    for method, path, body in attempts:
        assert member.request(method, path, json=body, headers={H: ws}).status_code == 403, (method, path)
    assert member.get(f"{P}/{sales['id']}", headers={H: ws}).status_code == 200
    assert member.get(f"{P}/{sales['id']}/board", headers={H: ws}).status_code == 200
    assert member.get(f"{P}/{sales['id']}/forecast", headers={H: ws}).status_code == 200
    assert pipelines(client, ws)[0]["name"] == "Sales"


def test_stages_are_created_changed_deleted_and_reordered(crm):
    client, ws, _ = crm
    [sales] = pipelines(client, ws)
    pid, stages = sales["id"], sales["stages"]
    extra = new_stage(client, ws, pid, name="Demo", probability=40, rotting_days=5, color="green",
                      exit_rules=NEEDS_MONEY)
    assert (extra["position"], extra["kind"], extra["probability"], extra["exit_rules"]) == (6, "open", 40, NEEDS_MONEY)
    assert new_stage(client, ws, pid, name="Plain")["probability"] == 10  # the default for an open stage
    assert new_stage(client, ws, pid, name="Closed", kind="won")["probability"] == 100
    assert new_stage(client, ws, pid, name="Dead", kind="lost")["probability"] == 0
    r = client.post(f"{P}/{pid}/stages", json={"name": "Odd", "kind": "lost", "probability": 5}, headers={H: ws})
    assert r.status_code == 422 and error_fields(r) == {"probability": "is 0 for a lost stage"}
    r = client.post(f"{P}/{pid}/stages", json={"name": "Bad", "exit_rules": {"field": "nope", "op": "is_empty"}},
                    headers={H: ws})
    assert r.status_code == 400 and list(error_fields(r)) == ["exit_rules.field"]
    assert client.post(f"{P}/{pid}/stages", json={"name": "Bad", "probability": 101}, headers={H: ws}
                       ).status_code == 422
    assert client.post(f"{P}/{pid}/stages", json={"name": "Bad", "rotting_days": 0}, headers={H: ws}
                       ).status_code == 422

    lead = stages[0]["id"]
    one = f"{P}/{pid}/stages/{lead}"
    r = client.patch(one, json={"name": "Inbound", "probability": 15, "rotting_days": None, "color": None},
                     headers={H: ws})
    assert r.status_code == 200 and (r.json()["name"], r.json()["probability"], r.json()["rotting_days"],
                                     r.json()["color"]) == ("Inbound", 15, None, None)
    r = client.patch(one, json={"kind": "won"}, headers={H: ws})  # a kind alone sets its probability
    assert r.json()["kind"] == "won" and r.json()["probability"] == 100
    r = client.patch(one, json={"probability": 30}, headers={H: ws})
    assert r.status_code == 422 and error_fields(r) == {"probability": "is 100 for a won stage"}
    r = client.patch(one, json={"kind": "open"}, headers={H: ws})
    assert r.json()["kind"] == "open" and r.json()["probability"] == 10
    assert client.patch(one, json={"kind": "open", "probability": 20}, headers={H: ws}).json()["probability"] == 20
    for bad in ({"name": None}, {"kind": None}, {"probability": None}, {"exit_rules": None}, {"kind": "paused"}):
        assert client.patch(one, json=bad, headers={H: ws}).status_code == 422, bad
    assert client.patch(f"{P}/{pid}/stages/{extra['id']}", json={"exit_rules": {}}, headers={H: ws}
                        ).json()["exit_rules"] == {}
    assert client.patch(f"{P}/{pid}/stages/{extra['id']}", json={"exit_rules": {"tag": "x"}}, headers={H: ws}
                        ).status_code == 200
    assert client.patch(f"{P}/{pid}/stages/{extra['id']}", json={"exit_rules": {"field": "x", "op": "is"}},
                        headers={H: ws}).status_code == 400
    assert client.get(f"{P}/{pid}", headers={H: ws}).json()["stages"][0]["name"] == "Inbound"

    # a stage with deals stays; an empty one goes
    make_deal(client, ws, "Sitting", stage=lead)
    r = client.delete(one, headers={H: ws})
    assert r.status_code == 409 and "Move the 1 deal in Inbound" in r.json()["error"]["message"]
    assert client.delete(f"{P}/{pid}/stages/{extra['id']}", headers={H: ws}).status_code == 204
    assert client.delete(f"{P}/{pid}/stages/{extra['id']}", headers={H: ws}).status_code == 404

    # one call with the whole order
    ids = [s["id"] for s in client.get(f"{P}/{pid}", headers={H: ws}).json()["stages"]]
    order = [ids[3], ids[2], ids[1], ids[0], *ids[4:]]
    r = client.post(f"{P}/{pid}/stages/reorder", json={"stage_ids": order}, headers={H: ws})
    assert r.status_code == 200 and [s["id"] for s in r.json()["stages"]] == order
    assert [s["position"] for s in r.json()["stages"]] == list(range(len(order)))
    assert [s["id"] for s in client.get(f"{P}/{pid}", headers={H: ws}).json()["stages"]] == order
    for bad in (order[:-1], [*order, order[0]], [*order[:-1], "00000000-0000-0000-0000-000000000000"], [order[0]] * 2):
        r = client.post(f"{P}/{pid}/stages/reorder", json={"stage_ids": bad}, headers={H: ws})
        assert r.status_code == 422 and "stage_ids" in error_fields(r), bad
    assert [s["id"] for s in client.get(f"{P}/{pid}", headers={H: ws}).json()["stages"]] == order  # nothing moved


def test_a_pipeline_has_at_most_thirty_stages(crm):
    client, ws, _ = crm
    [sales] = pipelines(client, ws)
    for i in range(30 - len(sales["stages"])):
        new_stage(client, ws, sales["id"], name=f"S{i}")
    r = client.post(f"{P}/{sales['id']}/stages", json={"name": "One too many"}, headers={H: ws})
    assert r.status_code == 409


def test_exit_rules_stop_a_deal_and_say_what_is_missing(crm, db):
    client, ws, _ = crm
    [sales] = pipelines(client, ws)
    s = stage_ids(client, ws)
    rules(client, ws, sales["id"], s["proposal"], NEEDS_MONEY)
    deal = make_deal(client, ws, "Big one", stage=s["proposal"])
    updated = db.scalar(text("SELECT updated_at FROM records WHERE id = :i"), {"i": deal["id"]})

    r = move(client, ws, deal["id"], s["negotiation"])
    assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed"
    assert r.json()["error"]["message"] == "The deal cannot leave Proposal yet"
    assert error_fields(r) == {"values.amount": "Amount is required to leave Proposal",
                               "values.close_date": "Close date is required to leave Proposal"}
    assert deal_stage(client, ws, deal["id"]) == s["proposal"] and stage_events(db, deal["id"]) == []
    # part of it is not enough, and only what is still missing is named
    client.patch(f"{DEALS}/{deal['id']}", json={"values": {"close_date": "2026-12-01"}}, headers={H: ws})
    assert error_fields(move(client, ws, deal["id"], s["lost"], lost_reason="price")) == {
        "values.amount": "Amount is required to leave Proposal"}  # leaving is leaving, whichever way
    client.patch(f"{DEALS}/{deal['id']}", json={"values": {"amount": {"amount": 5000}}}, headers={H: ws})
    r = move(client, ws, deal["id"], s["negotiation"])
    assert r.status_code == 200 and r.json()["stage_id"] == s["negotiation"]
    assert deal_stage(client, ws, deal["id"]) == s["negotiation"]
    assert [e["to_stage"] for e in stage_events(db, deal["id"])] == ["Negotiation"]
    assert db.scalar(text("SELECT updated_at FROM records WHERE id = :i"), {"i": deal["id"]}) > updated
    # the rules guard the stage being left: Negotiation has none
    assert move(client, ws, deal["id"], s["qualified"]).status_code == 200
    # back in Proposal the rules apply again, now that the deal has what they ask
    assert move(client, ws, deal["id"], s["proposal"]).status_code == 200
    client.patch(f"{DEALS}/{deal['id']}", json={"values": {"amount": None}}, headers={H: ws})
    assert move(client, ws, deal["id"], s["won"]).status_code == 422


def test_the_record_api_enforces_the_same_rules_and_can_fix_and_move_in_one_call(crm, db):
    client, ws, _ = crm
    [sales] = pipelines(client, ws)
    s = stage_ids(client, ws)
    rules(client, ws, sales["id"], s["lead"], NEEDS_MONEY)
    deal = make_deal(client, ws, "Patched")
    path = f"{DEALS}/{deal['id']}"
    r = client.patch(path, json={"values": {"stage": s["qualified"]}}, headers={H: ws})
    assert r.status_code == 422 and sorted(error_fields(r)) == ["values.amount", "values.close_date"]
    assert deal_stage(client, ws, deal["id"]) == s["lead"]
    # the change itself can supply what is missing
    r = client.patch(path, json={"values": {"stage": s["qualified"], **filled()}}, headers={H: ws})
    assert r.status_code == 200 and r.json()["values"]["stage"] == s["qualified"]
    assert [(e["from_stage"], e["to_stage"]) for e in stage_events(db, deal["id"])] == [("Lead", "Qualified")]
    # a patch that does not touch the stage is not stopped, and no stage event comes of it
    rules(client, ws, sales["id"], s["qualified"], NEEDS_MONEY)
    client.patch(path, json={"values": {"amount": None}}, headers={H: ws})
    assert client.patch(path, json={"values": {"name": "Renamed"}}, headers={H: ws}).status_code == 200
    assert len(stage_events(db, deal["id"])) == 1
    assert client.patch(path, json={"values": {"stage": s["proposal"]}}, headers={H: ws}).status_code == 422


def test_exit_rules_can_look_at_associated_records_and_nest(crm):
    client, ws, _ = crm
    [sales] = pipelines(client, ws)
    s = stage_ids(client, ws)
    rules(client, ws, sales["id"], s["lead"], {"and": [{"field": "contact.email", "op": "is_not_empty"},
                                                       {"or": [{"field": "name", "op": "starts_with", "value": "A"},
                                                               {"field": "close_date", "op": "is_not_empty"}]}]})
    deal = make_deal(client, ws, "Zed")
    r = move(client, ws, deal["id"], s["qualified"])
    assert r.status_code == 422
    fields = error_fields(r)
    assert set(fields) == {"contact.email", "exit_rules"}
    assert fields["contact.email"] == "contact.email is required to leave Lead"
    assert fields["exit_rules"].startswith("Lead needs this to hold before a deal leaves: ")
    ada = make_record(client, ws, first_name="Ada", email="ada@example.com")
    link(client, ws, deal["id"], ada["id"], type_id(client, ws, "deal", "contact"))
    assert set(error_fields(move(client, ws, deal["id"], s["qualified"]))) == {"exit_rules"}
    client.patch(f"{DEALS}/{deal['id']}", json={"values": {"close_date": "2026-12-01"}}, headers={H: ws})
    assert move(client, ws, deal["id"], s["qualified"]).status_code == 200  # the contact the rule looks for exists


def test_exit_rules_judge_the_deal_as_it_will_be_including_its_new_owner(crm):
    client, ws, _ = crm
    [sales] = pipelines(client, ws)
    s = stage_ids(client, ws)
    me = client.get("/api/me").json()["user"]["id"]
    rules(client, ws, sales["id"], s["qualified"], {"and": [{"field": "owner_id", "op": "is_not_empty"},
                                                            {"field": "name", "op": "contains", "value": "deal"}]})
    deal = make_deal(client, ws, "My deal", s["qualified"])
    r = move(client, ws, deal["id"], s["proposal"])
    assert r.status_code == 422 and error_fields(r) == {"owner_id": "owner_id is required to leave Qualified"}
    r = client.patch(f"{DEALS}/{deal['id']}", json={"values": {"stage": s["proposal"], "name": "Plain"},
                                                    "owner_id": me}, headers={H: ws})
    assert r.status_code == 422 and error_fields(r) == {"values.name": 'Name must satisfy contains "deal" to leave '
                                                                     "Qualified"}  # the new name is what counts
    r = client.patch(f"{DEALS}/{deal['id']}", json={"values": {"stage": s["proposal"]}, "owner_id": me},
                     headers={H: ws})
    assert r.status_code == 200 and r.json()["owner_id"] == me and r.json()["values"]["stage"] == s["proposal"]


def test_a_rule_that_is_a_single_condition_names_how_it_failed(crm):
    client, ws, _ = crm
    [sales] = pipelines(client, ws)
    s = stage_ids(client, ws)
    big = {"field": "amount", "op": "gt", "value": {"amount": 100000, "currency": "USD"}}
    rules(client, ws, sales["id"], s["lead"], big)
    deal = make_deal(client, ws, "Small", amount=500)
    r = move(client, ws, deal["id"], s["qualified"])
    assert error_fields(r) == {"values.amount": 'Amount must satisfy gt {"amount": 100000, "currency": "USD"} '
                                                "to leave Lead"}
    client.patch(f"{DEALS}/{deal['id']}", json={"values": {"amount": {"amount": 100001}}}, headers={H: ws})
    assert move(client, ws, deal["id"], s["qualified"]).status_code == 200


def test_exit_rules_that_no_longer_compile_stop_the_deal_with_a_409(crm):
    client, ws, _ = crm
    [sales] = pipelines(client, ws)
    s = stage_ids(client, ws)
    client.post("/api/v1/objects/deal/fields", json={"key": "budget_ok", "label": "Budget ok", "type": "boolean"},
                headers={H: ws})
    rules(client, ws, sales["id"], s["lead"], {"field": "budget_ok", "op": "is", "value": True})
    deal = make_deal(client, ws, "Stuck")
    assert move(client, ws, deal["id"], s["qualified"]).status_code == 422
    client.delete("/api/v1/objects/deal/fields/budget_ok", headers={H: ws})
    r = move(client, ws, deal["id"], s["qualified"])
    assert r.status_code == 409 and "exit rules of Lead are not valid" in r.json()["error"]["message"]
    rules(client, ws, sales["id"], s["lead"], {})  # an admin fixes them
    assert move(client, ws, deal["id"], s["qualified"]).status_code == 200


def test_a_lost_deal_needs_a_structured_reason(crm, db):
    client, ws, _ = crm
    s = stage_ids(client, ws)
    deal = make_deal(client, ws, "Doomed", stage=s["negotiation"])
    r = move(client, ws, deal["id"], s["lost"])
    assert r.status_code == 422 and error_fields(r) == {
        "values.lost_reason": "Lost reason is required to move a deal to Lost"}
    assert deal_stage(client, ws, deal["id"]) == s["negotiation"]
    r = move(client, ws, deal["id"], s["lost"], lost_reason="because")
    assert r.status_code == 422 and error_fields(r) == {
        "values.lost_reason": "Lost reason is not one of the field's choices"}
    r = move(client, ws, deal["id"], s["lost"], lost_reason="competitor", lost_note="  Went with Acme  ")
    assert r.status_code == 200
    got = client.get(f"{DEALS}/{deal['id']}", headers={H: ws}).json()["values"]
    assert (got["stage"], got["lost_reason"], got["lost_note"]) == (s["lost"], "competitor", "Went with Acme")
    assert [(e["to_kind"], e["from_kind"]) for e in stage_events(db, deal["id"])] == [("lost", "open")]
    # the record API holds the same line, at creation and on a patch
    r = client.post(DEALS, json={"values": {"name": "Born lost", "stage": s["lost"]}}, headers={H: ws})
    assert r.status_code == 422 and list(error_fields(r)) == ["values.lost_reason"]
    born = client.post(DEALS, json={"values": {"name": "Born lost", "stage": s["lost"], "lost_reason": "price"}},
                       headers={H: ws})
    assert born.status_code == 201
    r = client.patch(f"{DEALS}/{born.json()['id']}", json={"values": {"lost_reason": None}}, headers={H: ws})
    assert r.status_code == 422 and list(error_fields(r)) == ["values.lost_reason"]
    other = make_deal(client, ws, "Other", stage=s["qualified"])
    r = client.patch(f"{DEALS}/{other['id']}", json={"values": {"stage": s["lost"], "lost_reason": "timing"}},
                     headers={H: ws})
    assert r.status_code == 200
    # a second lost stage keeps the reason; reopening a deal clears it, so the next loss asks again
    spare = new_stage(client, ws, pipelines(client, ws)[0]["id"], name="Lost for good", kind="lost")
    assert move(client, ws, other["id"], spare["id"]).status_code == 200
    assert client.get(f"{DEALS}/{other['id']}", headers={H: ws}).json()["values"]["lost_reason"] == "timing"
    assert move(client, ws, other["id"], s["qualified"]).status_code == 200
    reopened = client.get(f"{DEALS}/{other['id']}", headers={H: ws}).json()["values"]
    assert "lost_reason" not in reopened and "lost_note" not in reopened
    assert move(client, ws, other["id"], s["lost"]).status_code == 422


def test_a_stage_change_is_an_event_with_the_time_spent_in_the_stage_it_left(crm, db):
    client, ws, _ = crm
    s = stage_ids(client, ws)
    pipeline = pipelines(client, ws)[0]["id"]
    deal = make_deal(client, ws, "Timed")
    db.execute(text("UPDATE records SET created_at = now() - interval '3 days' WHERE id = :i"), {"i": deal["id"]})
    db.commit()
    assert move(client, ws, deal["id"], s["qualified"]).status_code == 200
    [first] = stage_events(db, deal["id"])
    assert first == {"id": deal["id"], "object": "deal", "display_name": "Timed", "pipeline_id": pipeline,
                     "from_stage_id": s["lead"], "from_stage": "Lead", "from_kind": "open",
                     "to_stage_id": s["qualified"], "to_stage": "Qualified", "to_kind": "open",
                     "seconds_in_stage": first["seconds_in_stage"]}
    assert 3 * 86400 <= first["seconds_in_stage"] < 3 * 86400 + 120  # counted from the deal's creation
    db.execute(text("UPDATE events SET occurred_at = now() - interval '2 hours' WHERE type = 'deal.stage_changed'"))
    db.commit()
    assert move(client, ws, deal["id"], s["proposal"]).status_code == 200  # and from the last change after that
    assert 7200 <= stage_events(db, deal["id"])[1]["seconds_in_stage"] < 7320
    assert [(e["from_stage"], e["to_stage"]) for e in stage_events(db, deal["id"])] == [
        ("Lead", "Qualified"), ("Qualified", "Proposal")]
    # it comes with the record.updated of the same change, and shows on the deal's timeline
    timeline = client.get(f"/api/v1/records/{deal['id']}/timeline", headers={H: ws}).json()["data"]
    kinds = [e["type"] for e in timeline]  # the first change was backdated above, so it sits further down
    assert kinds[:2] == ["deal.stage_changed", "record.updated"] and sorted(kinds) == [
        "deal.stage_changed", "deal.stage_changed", "record.created", "record.updated", "record.updated"]
    assert timeline[0]["data"]["to_stage"] == "Proposal"
    assert timeline[1]["data"]["changes"]["stage"]["new"] == s["proposal"]
    assert timeline[0]["actor"]["type"] == "user"


def test_a_deal_that_had_no_stage_gets_one_and_a_non_change_emits_nothing(crm, db):
    client, ws, _ = crm
    s = stage_ids(client, ws)
    deal = client.post(DEALS, json={"values": {"name": "Floating", "stage": None}}, headers={H: ws}).json()
    assert move(client, ws, deal["id"], s["proposal"]).status_code == 200
    [event] = stage_events(db, deal["id"])
    assert (event["from_stage_id"], event["from_stage"], event["from_kind"], event["seconds_in_stage"]) == (
        None, None, None, None)
    assert event["to_stage"] == "Proposal"
    before = db.scalar(text("SELECT count(*) FROM events WHERE subject_id = :i"), {"i": deal["id"]})
    assert move(client, ws, deal["id"], s["proposal"]).status_code == 200  # already there
    db.expire_all()
    assert db.scalar(text("SELECT count(*) FROM events WHERE subject_id = :i"), {"i": deal["id"]}) == before
    # removing the stage is a plain update: no stage event, no exit rules
    r = client.patch(f"{DEALS}/{deal['id']}", json={"values": {"stage": None}}, headers={H: ws})
    assert r.status_code == 200 and "stage" not in r.json()["values"] and len(stage_events(db, deal["id"])) == 1


def test_moving_a_deal_that_is_not_there_or_a_stage_that_is_not_there_is_a_404(crm):
    client, ws, _ = crm
    s = stage_ids(client, ws)
    nobody = "00000000-0000-0000-0000-000000000000"
    deal = make_deal(client, ws, "Here")
    assert move(client, ws, nobody, s["won"]).status_code == 404
    assert move(client, ws, deal["id"], nobody).status_code == 404
    client.delete(f"{DEALS}/{deal['id']}", headers={H: ws})
    assert move(client, ws, deal["id"], s["won"]).status_code == 404  # in the trash
    contact = make_record(client, ws, first_name="Ada")
    assert move(client, ws, contact["id"], s["won"]).status_code == 404  # not a deal


def test_deals_filter_by_stage_and_by_what_kind_of_stage_it_is(crm):
    client, ws, _ = crm
    [sales] = pipelines(client, ws)
    s = stage_ids(client, ws)
    spare = client.post(P, json={"name": "Spare"}, headers={H: ws}).json()
    other = spare["stages"][0]["id"]
    for name, stage, extra in (("lead", s["lead"], {}), ("prop", s["proposal"], {}), ("won", s["won"], {}),
                               ("lost", s["lost"], {"lost_reason": "price"}), ("spare", other, {})):
        make_deal(client, ws, name, stage=stage, **extra)
    client.post(DEALS, json={"values": {"name": "none", "stage": None}}, headers={H: ws})

    def find(**leaf):
        r = client.get(DEALS, params={"filter": json.dumps(leaf), "limit": 200}, headers={H: ws})
        assert r.status_code == 200, (leaf, r.text)
        return sorted(names(r.json()))

    assert find(field="stage", op="is", value=s["lead"]) == ["lead"]
    assert find(field="stage", op="in", value=[s["lead"], s["won"]]) == ["lead", "won"]
    assert find(field="stage", op="is_not", value=s["lead"]) == ["lost", "none", "prop", "spare", "won"]
    assert find(field="stage", op="is_empty") == ["none"]
    assert find(field="stage.kind", op="is", value="open") == ["lead", "prop", "spare"]
    assert find(field="stage.kind", op="is", value="won") == ["won"]
    assert find(field="stage.kind", op="is", value="lost") == ["lost"]
    assert find(field="stage.kind", op="in", value=["won", "lost"]) == ["lost", "won"]
    assert find(field="stage.kind", op="not_in", value=["won", "lost"]) == ["lead", "none", "prop", "spare"]
    assert find(field="stage.kind", op="is_not", value="open") == ["lost", "none", "won"]
    assert find(field="stage.pipeline", op="is", value=sales["id"]) == ["lead", "lost", "prop", "won"]
    assert find(field="stage.pipeline", op="is", value=spare["id"]) == ["spare"]
    assert find(field="stage.pipeline", op="in", value=[sales["id"], spare["id"]]) == [
        "lead", "lost", "prop", "spare", "won"]
    both = {"and": [{"field": "stage.kind", "op": "is", "value": "open"},
                    {"field": "stage.pipeline", "op": "is", "value": sales["id"]}]}
    r = client.get(DEALS, params={"filter": json.dumps(both)}, headers={H: ws})
    assert sorted(names(r.json())) == ["lead", "prop"]
    r = client.get(DEALS, params={"filter": json.dumps({"not": {"field": "stage.kind", "op": "is", "value": "open"}})},
                   headers={H: ws})
    assert sorted(names(r.json())) == ["lost", "none", "won"]

    def bad(leaf, pointer, message):
        r = client.get(DEALS, params={"filter": json.dumps(leaf)}, headers={H: ws})
        assert r.status_code == 400 and r.json()["error"]["code"] == "validation_failed", (leaf, r.text)
        assert list(error_fields(r)) == [pointer] and message in error_fields(r)[pointer], (leaf, r.text)

    bad({"field": "stage.nope", "op": "is", "value": "x"}, "filter.field", "not a stage property")
    bad({"field": "stage.kind", "op": "gt", "value": "open"}, "filter.op", "use is, is_not, in or not_in")
    bad({"field": "stage.kind", "op": "is", "value": "paused"}, "filter.value", "open, won or lost")
    bad({"field": "stage.kind", "op": "is", "value": 5}, "filter.value", "open, won or lost")
    bad({"field": "stage.kind", "op": "in", "value": "open"}, "filter.value", "must be a list")
    bad({"field": "stage.pipeline", "op": "is", "value": "nope"}, "filter.value", "a pipeline id")
    bad({"field": "stage.kind.x", "op": "is", "value": "open"}, "filter.field", "not a stage property")
    # a contact has no stage field, so the association path rules apply as before
    r = client.get("/api/v1/objects/contact/records", params={"filter": json.dumps(
        {"field": "stage.kind", "op": "is", "value": "open"})}, headers={H: ws})
    assert r.status_code == 400 and "must be an object key and a field" in error_fields(r)["filter.field"]
    assert client.get(DEALS, params={"sort": "stage"}, headers={H: ws}).status_code == 400  # not sortable


def test_a_stage_filter_is_allowed_in_a_saved_view_and_survives_a_stage_rename(crm):
    client, ws, _ = crm
    s = stage_ids(client, ws)
    make_deal(client, ws, "Open one")
    make_deal(client, ws, "Closed one", stage=s["won"])
    view = client.post("/api/v1/views", json={"object": "deal", "name": "Open deals", "filter": {
        "field": "stage.kind", "op": "is", "value": "open"}}, headers={H: ws})
    assert view.status_code == 201
    got = client.get(f"/api/v1/views/{view.json()['id']}", headers={H: ws}).json()
    assert got["count"] == 1
    assert names(listing(client, ws, "deal", view=view.json()["id"])) == ["Open one"]
    [sales] = pipelines(client, ws)
    client.patch(f"{P}/{sales['id']}/stages/{s['won']}", json={"kind": "open", "probability": 90}, headers={H: ws})
    assert client.get(f"/api/v1/views/{view.json()['id']}", headers={H: ws}).json()["count"] == 2
