"""The graph schema (no database): what a saved version must be, the errors that point into it, and the catalog the
builder is made from."""
import copy
import uuid

import pytest
from workflow_helpers import act, ask, graph, pause, tag

from app import events
from app.workflows import schema
from app.workflows.registry import ACTIONS

USER = str(uuid.uuid4())


def errors(g) -> dict[str, str]:
    with pytest.raises(schema.GraphError) as e:
        schema.validate(g)
    return e.value.fields


def simple(**more) -> dict:
    return graph({"a": tag("vip", "b"), "b": pause({"duration": {"days": 1}}, "c"),
                  "c": act("record.update", {"values": {"lifecycle": "lead"}})}, **more)


def test_a_valid_graph_comes_back_with_every_default_written_out_and_saving_it_again_changes_nothing():
    clean = schema.validate(simple())
    assert clean["trigger"] == {"event": "record.created", "object": "contact", "filter": {}, "data": {}}
    assert clean["start"] == "a" and list(clean["nodes"]) == ["a", "b", "c"]
    assert clean["nodes"]["a"] == {"type": "action", "action": "tag.add", "config": {"tag": "vip"}, "next": "b"}
    assert clean["nodes"]["b"]["config"] == {"duration": {"days": 1}, "until_field": None, "event": None}
    assert schema.validate(clean) == clean
    assert schema.validate({"trigger": {"event": "record.created"}, "start": None, "nodes": {}})["nodes"] == {}


def test_every_kind_of_node_validates_with_its_own_config_and_edges():
    clean = schema.validate(graph({
        "go": ask({"field": "lifecycle", "op": "is", "value": "lead"}, "split", "stop"),
        "split": {"type": "split", "config": {"paths": [{"name": "a", "percent": 30}, {"name": "b", "percent": 70}]},
                  "branches": {"a": "hold", "b": "stop"}},
        "hold": {"type": "wait", "config": {"event": {"event": "message.received", "timeout": {"hours": 4},
                                                      "match": {"channel_kind": "sms"}}},
                 "branches": {"event": "stop", "timeout": "pick"}},
        "pick": act("owner.assign", {"round_robin": [USER, str(uuid.uuid4())]}, "stop"),
        "won": {"type": "goal", "config": {"filter": {"tag": "customer"}}, "next": None},
        "stop": {"type": "end", "config": {}, "label": "Done", "ui": {"x": 1, "y": 2}}}, start="go"))
    assert clean["nodes"]["won"]["config"] == {"filter": {"tag": "customer"}, "otherwise": "continue"}
    assert clean["nodes"]["stop"] == {"type": "end", "config": {}, "label": "Done", "ui": {"x": 1, "y": 2}}
    assert clean["nodes"]["hold"]["branches"] == {"event": "stop", "timeout": "pick"}


def test_an_unknown_node_type_or_action_and_stray_keys_are_refused_at_their_place():
    g = simple()
    g["nodes"]["a"]["type"] = "teleport"
    assert errors(g)["nodes.a.type"].startswith("unknown node type 'teleport'")
    g = simple()
    g["nodes"]["a"]["action"] = "tag.explode"
    assert errors(g)["nodes.a.action"].startswith("unknown action 'tag.explode'; use one of ")
    g = simple()
    del g["nodes"]["a"]["action"]
    assert errors(g)["nodes.a.action"].startswith("is required; use one of ")
    g = simple()
    g["nodes"]["b"]["colour"] = "red"
    g["extra"] = 1
    assert errors(g) == {"nodes.b.colour": "is not a known key", "extra": "is not a known key"}
    assert errors("nonsense") == {"": "must be an object with a trigger, a start and nodes"}
    assert errors({**simple(), "nodes": []}) == {"nodes": "must be an object of nodes by id"}


def test_an_edge_to_a_node_that_does_not_exist_is_refused():
    g = simple()
    g["nodes"]["a"]["next"] = "nowhere"
    assert errors(g) == {"nodes.a.next": "leads to 'nowhere', which is not a node"}
    g = graph({"q": ask({"tag": "x"}, "q", "gone")})
    assert errors(g) == {"nodes.q.branches.no": "leads to 'gone', which is not a node"}


def test_a_node_nothing_leads_to_is_refused_but_a_goal_needs_no_edge_into_it():
    g = simple()
    g["nodes"]["lonely"] = tag("x")
    assert errors(g) == {"nodes.lonely": "is not reachable: nothing leads to it (remove it or connect it)"}
    g = simple()
    g["nodes"]["win"] = {"type": "goal", "config": {"filter": {"tag": "customer"}}, "next": "after"}
    g["nodes"]["after"] = tag("won")
    assert schema.validate(g)["nodes"]["win"]["next"] == "after"  # a run jumps here, so the goal and what follows count


def test_a_loop_is_refused_unless_a_wait_is_in_it():
    g = graph({"a": tag("x", "b"), "b": tag("y", "a")})
    found = errors(g)
    assert list(found) in (["nodes.a"], ["nodes.b"]) and "loop with no wait" in next(iter(found.values()))
    assert "nodes.a" in errors(graph({"a": ask({"tag": "x"}, "a", None)}))  # a node that loops on itself
    ok = graph({"a": tag("x", "w"), "w": pause({"duration": {"hours": 1}}, "a")})
    assert schema.validate(ok)["nodes"]["w"]["next"] == "a"  # the wait slows it: the loop is allowed
    event_loop = graph({"w": {"type": "wait", "config": {"event": {"event": "tag.added", "timeout": {"days": 1}}},
                              "branches": {"event": "a", "timeout": None}}, "a": tag("x", "w")})
    assert schema.validate(event_loop)


def test_action_configs_are_validated_by_their_schema_with_a_pointer_to_each_problem():
    g = graph({"t": act("task.create", {"notes": 5, "due": {"days": 0}, "priority": "urgent", "boss": 1}, "m"),
               "m": act("message.send", {"body": "", "channel_id": "not-a-uuid", "if_refused": "shrug"}, "o"),
               "o": act("owner.assign", {"user_id": USER, "round_robin": [USER]}, "s"),
               "s": act("deal.move_stage", {}, "r"), "r": act("record.update", {"values": {}}, "w"),
               "w": act("webhook.send", {"url": "", "payload": {"k": {"nested": 1}}}, "n"),
               "n": act("notify.user", {"user_id": "somebody", "title": "x"}, "g"), "g": tag("")})
    found = errors(g)
    assert found["nodes.t.config.title"] == "is required"
    assert found["nodes.t.config.notes"] and found["nodes.t.config.due.days"] == "Input should be greater than or equal to 1"
    assert found["nodes.t.config.priority"].startswith("Input should be")
    assert found["nodes.t.config.boss"] == "is not a known setting"
    assert found["nodes.m.config.body"].startswith("String should have at least 1 character")
    assert found["nodes.m.config.channel_id"].startswith("Input should be a valid UUID")
    assert found["nodes.m.config.if_refused"].startswith("Input should be")
    assert found["nodes.o.config"] == "give a user_id or a round_robin list, not both and not neither"
    assert found["nodes.s.config.stage_id"] == "is required"
    assert found["nodes.r.config.values"].startswith("Dictionary should have at least 1 item")
    assert found["nodes.w.config.url"].startswith("String should have at least 1 character")
    assert "nodes.w.config.payload.k" in found
    assert found["nodes.n.config.user_id"] == 'must be the id of a user, or "owner"'
    assert found["nodes.g.config.tag"].startswith("String should have at least 1 character")


def test_the_trigger_names_an_event_about_a_record_and_data_the_event_has():
    bad = errors(graph({"a": tag("x")}, event="webhook.test"))
    assert bad["trigger.event"].startswith("is not an event about a record")
    assert "trigger.event" in errors(graph({"a": tag("x")}, event="workflow.run_started"))  # never starts workflows
    assert "trigger.event" in errors(graph({"a": tag("x")}, event="no.such.event"))
    found = errors(graph({"a": tag("x")}, event="form.submitted", data={"nope": 1}))
    assert found == {"trigger": "'nope' is not in the data of form.submitted"}
    assert errors({"trigger": {}, "start": None, "nodes": {}}) == {"trigger.event": "is required"}
    assert errors(graph({"a": tag("x")}, object="Bad Key")) == {"trigger.object": (
        "String should match pattern '^[a-z][a-z0-9_]{0,39}$'")}
    ok = schema.validate(graph({"a": tag("x")}, event="form.submitted", data={"form_id": USER}, object="contact"))
    assert ok["trigger"]["data"] == {"form_id": USER}


def test_wait_split_condition_and_end_configs_are_checked():
    def node_errors(node):
        return errors(graph({"n": node}))

    assert node_errors(pause({}))["nodes.n.config"] == "give exactly one of duration, until_field and event"
    assert node_errors(pause({"duration": {"days": 1}, "until_field": {"field": "x"}}))["nodes.n.config"]
    assert node_errors(pause({"duration": {"days": 1, "hours": 2}}))["nodes.n.config.duration"].startswith(
        "Dictionary should have at most 1 item")
    assert "more than a year" in node_errors(pause({"duration": {"days": 400}}))["nodes.n.config.duration"]
    assert node_errors(pause({"until_field": {"field": "x", "at": "25:61"}}))["nodes.n.config.until_field.at"]
    assert node_errors({"type": "wait", "config": {"event": {"event": "tag.added", "timeout": {"days": 1}}},
                        "next": None})["nodes.n.branches"] == "must have exactly the branches event, timeout"
    split = lambda paths: {"type": "split", "config": {"paths": paths}, "branches": {p["name"]: None for p in paths}}  # noqa: E731
    assert node_errors(split([{"name": "a", "percent": 60}, {"name": "b", "percent": 60}]))[
        "nodes.n.config"] == "the percentages must add up to 100"
    assert node_errors(split([{"name": "a", "percent": 50}, {"name": "a", "percent": 50}]))[
        "nodes.n.config"] == "path names must differ"
    assert node_errors(split([{"name": "a", "percent": 100}]))["nodes.n.config.paths"].startswith(
        "List should have at least 2 items")
    assert node_errors({"type": "condition", "config": {"filter": {}}, "branches": {"yes": None, "no": None}})[
        "nodes.n.config.filter"] == "needs a condition"
    assert node_errors({"type": "condition", "config": {"filter": {"tag": "x"}}, "branches": {"yes": None}})[
        "nodes.n.branches"] == "must have exactly the branches yes, no"
    assert node_errors({"type": "end", "config": {}, "next": "n"}) == {"nodes.n": "an end node goes nowhere"}
    assert node_errors({"type": "action", "action": "tag.add", "config": {"tag": "x"}, "branches": {}})[
        "nodes.n.branches"] == "a action node goes on with `next`"


def test_node_ids_and_the_size_of_a_workflow_are_limited():
    assert "nodes.Bad-Id" in errors({"trigger": {"event": "record.created"}, "start": "Bad-Id",
                                     "nodes": {"Bad-Id": tag("x")}})
    many = {f"n{i}": tag("x", f"n{i + 1}" if i < schema.MAX_NODES else None) for i in range(schema.MAX_NODES + 1)}
    assert errors(graph(many))["nodes"] == f"a workflow has at most {schema.MAX_NODES} nodes"
    assert errors(graph({"a": tag("x")}, start="zz")) == {"start": "must be the id of the first node"}
    assert errors({"trigger": {"event": "record.created"}, "start": "a", "nodes": {}}) == {"start": "there are no nodes"}
    assert errors({"trigger": {"event": "record.created"}, "nodes": {"a": tag("x")}}) == {
        "start": "is required: the id of the first node"}


def test_publishing_needs_something_to_run_and_no_subflow_yet():
    empty = schema.validate({"trigger": {"event": "record.created"}, "start": None, "nodes": {}})
    assert schema.publishable(empty) == {"nodes": "add a step first: there is nothing to run"}
    sub = schema.validate(graph({"s": {"type": "subflow", "config": {"workflow_id": USER}, "next": None}}))
    assert schema.publishable(sub) == {"nodes.s.type": "subflows are not built yet: they can be saved but not published"}
    assert schema.publishable(schema.validate(simple())) == {}


def test_a_version_lists_what_it_uses_for_the_dependency_index():
    stage, other = str(uuid.uuid4()), str(uuid.uuid4())
    clean = schema.validate(graph({
        "go": ask({"and": [{"field": "lifecycle", "op": "is", "value": "lead"}, {"not": {"tag": "cold"}},
                           {"field": "stage", "op": "in", "value": [stage]}]}, "set", None),
        "set": act("record.update", {"values": {"lifecycle": "customer", "company": None}}, "own"),
        "own": act("owner.assign", {"round_robin": [USER, other]}, "tg"),
        "tg": tag(other, "wait"), "wait": pause({"until_field": {"field": "renewal"}}, "mv"),
        "mv": act("deal.move_stage", {"stage_id": stage}, None)},
        start="go", event="form.submitted", data={"form_id": other}, filter={"tag": "vip"}))
    found = schema.refs(clean)
    assert (None, "form", other) in found and (None, "tag", "vip") in found
    assert ("go", "field", "contact.lifecycle") in found and ("go", "tag", "cold") in found
    assert ("go", "stage", stage) in found and ("set", "field", "contact.company") in found
    assert ("own", "user", USER) in found and ("own", "user", other) in found and ("tg", "tag", other) in found
    assert ("wait", "field", "contact.renewal") in found and ("mv", "stage", stage) in found
    assert len(found) == len(set(found))


def test_the_catalog_lists_the_triggers_the_node_types_and_every_action_with_its_json_schema():
    catalog = schema.catalog()
    triggers = {t["event"]: t for t in catalog["triggers"]}
    assert {"record.created", "record.updated", "deal.stage_changed", "tag.added", "form.submitted", "booking.created",
            "message.received", "task.completed", "consent.changed"} <= triggers.keys()
    assert not [t for t in triggers if t.startswith("workflow.") or t.startswith("webhook")]
    assert triggers["record.created"]["record"] == "subject" and triggers["form.submitted"]["record"] == "contact_id"
    assert triggers["tag.added"]["record"] == "record_id"
    assert triggers["form.submitted"]["data_schema"] == events.TYPES["form.submitted"]
    assert {a["key"] for a in catalog["actions"]} == set(ACTIONS) == {
        "record.update", "tag.add", "tag.remove", "owner.assign", "deal.move_stage", "task.create", "message.send",
        "notify.user", "webhook.send"}
    for a in catalog["actions"]:
        assert a["config_schema"]["type"] == "object" and a["config_schema"]["additionalProperties"] is False
        assert a["label"] and a["description"] is not None
    assert {a["key"] for a in catalog["actions"] if a["outbound"]} == {"message.send", "webhook.send"}
    assert [n["type"] for n in catalog["nodes"]] == ["action", "wait", "condition", "split", "goal", "subflow", "end"]
    assert catalog["nodes"][2]["config_schema"]["required"] == ["filter"]
    assert catalog["limits"] == {"max_nodes": 200, "max_steps_per_run": 500}
    assert catalog["trigger_schema"]["required"] == ["event"] and catalog["settings_schema"]["properties"]["reentry"]


def test_validation_does_not_change_what_it_is_given():
    g = simple()
    before = copy.deepcopy(g)
    schema.validate(g)
    assert g == before
