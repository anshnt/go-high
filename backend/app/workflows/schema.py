"""What a workflow is (the JSON stored in `workflow_versions.graph`) and the checks that keep a saved one sound. A saved
version is always valid: an unknown node type, an edge to nothing, a node nothing leads to, a loop with no wait in it
or a bad action config is refused when the version is saved, never discovered by a run. Errors point into the graph
(`nodes.send.config.body`). This module needs no database; `check` adds what only the workspace knows.

    {"trigger": {"event": "form.submitted", "object": "contact", "filter": {"tag": "vip"},
                 "data": {"form_id": "..."}},
     "start": "hello",
     "nodes": {"hello": {"type": "action", "action": "message.send", "config": {...}, "next": "pause"},
               "pause": {"type": "wait", "config": {"duration": {"days": 2}}, "next": "check"},
               "check": {"type": "condition", "config": {"filter": {...}}, "branches": {"yes": null, "no": "tag"}},
               "tag": {"type": "action", "action": "tag.add", "config": {"tag": "cold"}, "next": null},
               "won": {"type": "goal", "config": {"filter": {"tag": "customer"}}, "next": null}}}

A node with `next: null` (or a branch to null) ends the run. A goal is entered by a jump when its condition becomes
true, so nothing needs to lead to it. Node ids are `^[a-z][a-z0-9_]{0,39}$`."""
import re
import uuid
from typing import Annotated, Any, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints, ValidationError, model_validator

from .. import events
from ..records.schema import FieldKey, Key
from . import actions  # noqa: F401  (registers the actions)
from .registry import ACTIONS, Offset, SignedOffset

NODE_ID = re.compile(r"[a-z][a-z0-9_]{0,39}")
MAX_NODES = 200
MAX_STEPS = 500  # per run: the loop guard of the engine
Scalar = str | int | float | bool | None
UNION_TAGS = re.compile(r"(str|int|float|bool|none|uuid|literal\[.*|list.*|dict.*)")


def record_key(event_type: str) -> str | None:
    """How an event names the record it is about: `subject` (the record is its subject), or the key of its data
    that holds the id (`contact_id`, `record_id`). None for an event about nothing a workflow can run on, and for the
    workflow events themselves, which must never start workflows."""
    props = events.TYPES[event_type]["properties"]
    if event_type.startswith("workflow."):
        return None
    if {"object", "display_name"} <= props.keys():
        return "subject"
    return next((k for k in ("contact_id", "record_id") if k in props), None)


TRIGGERS = {t: key for t in sorted(events.TYPES) if (key := record_key(t))}


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


def known_event(name: str) -> str:
    if name not in TRIGGERS:
        raise ValueError("is not an event about a record: see the catalog for the ones a workflow can start on")
    return name


def known_keys(event: str, data: dict) -> dict:
    if unknown := sorted(data.keys() - events.TYPES[event]["properties"].keys()):
        raise ValueError(f"{unknown[0]!r} is not in the data of {event}")
    return data


Event = Annotated[str, AfterValidator(known_event)]


class Settings(Model):
    reentry: bool = False  # may a record enter again after its run ended


class Trigger(Model):
    event: Event
    object: Key = "contact"  # the objects whose records enter; the filter and the conditions read its fields
    filter: dict = {}  # a filter AST (ADR 0002) over the record, as it is when the event is read
    data: dict[Annotated[str, StringConstraints(max_length=63)], Scalar] = {}  # the event's data must hold these

    @model_validator(mode="after")
    def data_is_known(self):
        known_keys(self.event, self.data)
        return self


class UntilField(Model):
    field: FieldKey  # a date or datetime field of the record
    offset: SignedOffset | None = None  # {"days": -1}: a day before
    at: Annotated[str, StringConstraints(pattern=r"^([01]\d|2[0-3]):[0-5]\d$")] = "09:00"  # a date: contact's zone


class UntilEvent(Model):
    event: Event
    match: dict[Annotated[str, StringConstraints(max_length=63)], Scalar] = {}
    timeout: Offset

    @model_validator(mode="after")
    def match_is_known(self):
        known_keys(self.event, self.match)
        return self


class Wait(Model):
    duration: Offset | None = None
    until_field: UntilField | None = None
    event: UntilEvent | None = None  # the run goes on at the `event` branch when it happens, else at `timeout`

    @model_validator(mode="after")
    def one_way(self):
        if sum(x is not None for x in (self.duration, self.until_field, self.event)) != 1:
            raise ValueError("give exactly one of duration, until_field and event")
        return self


def not_empty(ast: dict) -> dict:
    if not ast:
        raise ValueError("needs a condition")
    return ast


class Condition(Model):
    filter: Annotated[dict, AfterValidator(not_empty)]


class Path(Model):
    name: Key
    percent: Annotated[int, Field(ge=1, le=100)]


class Split(Model):
    paths: Annotated[list[Path], Field(min_length=2, max_length=10)]

    @model_validator(mode="after")
    def whole(self):
        if len({p.name for p in self.paths}) != len(self.paths):
            raise ValueError("path names must differ")
        if sum(p.percent for p in self.paths) != 100:
            raise ValueError("the percentages must add up to 100")
        return self


class Goal(Model):
    filter: Annotated[dict, AfterValidator(not_empty)]
    otherwise: Literal["continue", "end"] = "continue"  # a run that walks to the goal before it is met


class Subflow(Model):  # ponytail: saved but not run; publishing refuses it until subflows are built
    workflow_id: uuid.UUID
    inputs: dict = {}


class End(Model):
    pass


# type: (config model or None for an action's own, what it does)
NODE_TYPES: dict[str, tuple[type[BaseModel] | None, str]] = {
    "action": (None, "Does one thing, named by `action`; its config is that action's schema."),
    "wait": (Wait, "Holds the run for a duration, until a date field, or until an event with a timeout."),
    "condition": (Condition, "If/else over a filter on the record: branches `yes` and `no`."),
    "split": (Split, "Sends runs down paths by percentage, decided by the run's id, so a run always takes the same."),
    "goal": (Goal, "Runs jump here when the filter becomes true, wherever they are."),
    "subflow": (Subflow, "Runs another workflow (not built yet: it can be saved, not published)."),
    "end": (End, "Ends the run."),
}
NODE_KEYS = {"type", "config", "next", "branches", "label", "ui"}
LIMITS = {"max_nodes": MAX_NODES, "max_steps_per_run": MAX_STEPS}


class GraphError(ValueError):
    def __init__(self, fields: dict[str, str]):
        super().__init__("invalid graph")
        self.fields = fields


def join(path: str, *parts) -> str:
    return ".".join(p for p in (path, *map(str, parts)) if p)


def explain(error: dict) -> str:
    return {"missing": "is required", "extra_forbidden": "is not a known setting"}.get(
        error["type"], error["msg"].removeprefix("Value error, "))


def parse(model: type[BaseModel], raw: Any, path: str, errors: dict[str, str]) -> BaseModel | None:
    """The validated config, or None with each problem in `errors` at its path."""
    try:
        return model.model_validate(raw if raw is not None else {})
    except ValidationError as e:
        for err in e.errors():
            parts = [p for p in err["loc"] if p != "[key]" and not UNION_TAGS.fullmatch(str(p))]
            errors.setdefault(join(path, *parts), explain(err))
    return None


def edges(type_: str, cfg: BaseModel) -> tuple[str, tuple[str, ...]]:
    """How a node leaves: `next` (one way), `branches` (these names) or `none`."""
    if type_ == "end":
        return "none", ()
    if type_ == "condition":
        return "branches", ("yes", "no")
    if type_ == "split":
        return "branches", tuple(p.name for p in cfg.paths)
    if type_ == "wait" and cfg.event is not None:
        return "branches", ("event", "timeout")
    return "next", ()


def targets(node: dict) -> list[str]:
    return [t for t in ([node.get("next")] + list((node.get("branches") or {}).values())) if t]


def cycle_without_wait(nodes: dict[str, dict]) -> str | None:
    """A node on a loop that never waits (it would run its 500 steps at once), or None."""
    free = {n: [t for t in targets(node) if nodes[t]["type"] != "wait"] for n, node in nodes.items()
            if node["type"] != "wait"}
    state: dict[str, int] = {}  # 1: on the path being walked, 2: done

    def visit(n: str) -> str | None:
        state[n] = 1
        for t in free[n]:
            if state.get(t) == 1 or (t not in state and visit(t)):
                return t
        state[n] = 2
        return None

    return next((hit for n in free if n not in state and (hit := visit(n))), None)


def reachable(start: str | None, nodes: dict[str, dict]) -> set[str]:
    """What a run can get to: from the start, and from each goal (a run jumps to those)."""
    seen: set[str] = set()
    todo = [*([start] if start else []), *(n for n, node in nodes.items() if node["type"] == "goal")]
    while todo:
        n = todo.pop()
        if n not in seen:
            seen.add(n)
            todo += targets(nodes[n])
    return seen


def validate(graph: Any) -> dict:
    """The normalized graph (every default written out, so saving what is already saved changes nothing), or a
    GraphError whose `fields` point into it."""
    errors: dict[str, str] = {}
    if not isinstance(graph, dict):
        raise GraphError({"": "must be an object with a trigger, a start and nodes"})
    for key in sorted(graph.keys() - {"trigger", "start", "nodes"}):
        errors[key] = "is not a known key"
    trigger = parse(Trigger, graph.get("trigger"), "trigger", errors)
    raw_nodes, start = graph.get("nodes", {}), graph.get("start")
    if not isinstance(raw_nodes, dict):
        raise GraphError({**errors, "nodes": "must be an object of nodes by id"})
    if len(raw_nodes) > MAX_NODES:
        errors["nodes"] = f"a workflow has at most {MAX_NODES} nodes"
    nodes: dict[str, dict] = {}
    configs: dict[str, BaseModel] = {}
    for nid, node in raw_nodes.items():
        path = f"nodes.{nid}"
        if not NODE_ID.fullmatch(str(nid)):
            errors[path] = "node ids are lower case letters, digits and _, starting with a letter (40 at most)"
        elif not isinstance(node, dict):
            errors[path] = "must be an object"
        else:
            keep(nid, node, path, errors, nodes, configs)
    if not errors:
        link(start, nodes, configs, errors)
    if errors:
        raise GraphError(errors)
    return {"trigger": trigger.model_dump(mode="json"), "start": start, "nodes": nodes}


def keep(nid: str, node: dict, path: str, errors: dict[str, str], nodes: dict, configs: dict) -> None:
    """Checks one node and, if it is sound, adds its normalized form."""
    type_ = node.get("type")
    if type_ not in NODE_TYPES:
        errors[f"{path}.type"] = f"unknown node type {type_!r}; use one of {', '.join(NODE_TYPES)}"
        return
    for key in sorted(node.keys() - NODE_KEYS - ({"action"} if type_ == "action" else set())):
        errors[f"{path}.{key}"] = "is not a known key"
    model, name = NODE_TYPES[type_][0], node.get("action")
    if type_ == "action":
        if name not in ACTIONS:
            errors[f"{path}.action"] = ("is required" if name is None else f"unknown action {name!r}") + (
                f"; use one of {', '.join(sorted(ACTIONS))}")
            return
        model = ACTIONS[name].config
    cfg = parse(model, node.get("config"), f"{path}.config", errors)
    if cfg is None:
        return
    kind, names = edges(type_, cfg)
    out: dict = {"type": type_, **({"action": name} if type_ == "action" else {}),
                 "config": cfg.model_dump(mode="json")}
    if kind == "next":
        out["next"] = node.get("next")
        if node.get("branches") is not None:
            errors[f"{path}.branches"] = f"a {type_} node goes on with `next`"
    elif kind == "branches":
        out["branches"] = branches = node.get("branches")
        if node.get("next") is not None:
            errors[f"{path}.next"] = f"a {type_} node goes on with `branches`"
        if not isinstance(branches, dict) or set(branches) != set(names):
            errors[f"{path}.branches"] = f"must have exactly the branches {', '.join(names)}"
    elif node.get("next") is not None or node.get("branches") is not None:
        errors[path] = "an end node goes nowhere"
    out |= {k: node[k] for k in ("label", "ui") if node.get(k) is not None}
    for k, maximum, what in (("label", 100, str), ("ui", 2000, dict)):
        if k in out and (not isinstance(out[k], what) or len(str(out[k])) > maximum):
            errors[f"{path}.{k}"] = f"must be {'text' if what is str else 'an object'} of at most {maximum} characters"
    nodes[nid], configs[nid] = out, cfg


def link(start: str | None, nodes: dict[str, dict], configs: dict, errors: dict[str, str]) -> None:
    """The checks that need every node: edges that lead somewhere, nothing orphaned, no loop without a wait."""
    if nodes and start not in nodes:
        errors["start"] = "must be the id of the first node" if start else "is required: the id of the first node"
    if start is not None and not nodes:
        errors["start"] = "there are no nodes"
    for nid, node in nodes.items():
        for where, target in (("next", node.get("next")), *((f"branches.{b}", t) for b, t in
                                                            (node.get("branches") or {}).items())):
            if target is not None and (not isinstance(target, str) or target not in nodes):
                errors[f"nodes.{nid}.{where}"] = f"leads to {target!r}, which is not a node"
    if errors:
        return
    seen = reachable(start, nodes)
    for nid in nodes:
        if nid not in seen:
            errors[f"nodes.{nid}"] = "is not reachable: nothing leads to it (remove it or connect it)"
    if not errors and (loop := cycle_without_wait(nodes)):
        errors[f"nodes.{loop}"] = (f"is on a loop with no wait in it, which would run its {MAX_STEPS} steps at once: "
                                   "put a wait in the loop")


def publishable(graph: dict) -> dict[str, str]:
    """What a version may not be published with: nothing to run, or a node that cannot run yet."""
    if not graph["nodes"]:
        return {"nodes": "add a step first: there is nothing to run"}
    return {f"nodes.{nid}.type": "subflows are not built yet: they can be saved but not published"
            for nid, node in graph["nodes"].items() if node["type"] == "subflow"}


# --- what a version uses ----------------------------------------------------------------------------------------

DATA_REFS = {"form_id": "form", "calendar_id": "calendar", "channel_id": "channel", "to_stage_id": "stage",
             "from_stage_id": "stage", "tag_id": "tag", "host_user_id": "user"}


def filter_refs(ast: Any, obj: str):
    """(kind, value) of the fields, tags and stages a filter names."""
    if not isinstance(ast, dict):
        return
    for joiner in ("and", "or"):
        for item in ast.get(joiner) if isinstance(ast.get(joiner), list) else []:
            yield from filter_refs(item, obj)
    yield from filter_refs(ast.get("not"), obj)
    if "tag" in ast:
        yield "tag", str(ast["tag"])
    if isinstance(ast.get("field"), str):
        yield "field", f"{obj}.{ast['field']}"
        if ast["field"] == "stage":
            for value in ast["value"] if isinstance(ast.get("value"), list) else [ast.get("value")]:
                if value is not None:
                    yield "stage", str(value)


def data_refs(data: dict):
    return ((DATA_REFS[k], str(v)) for k, v in data.items() if k in DATA_REFS and v is not None)


def refs(graph: dict) -> list[tuple[str | None, str, str]]:
    """(node id or None for the trigger, kind, id or key) of everything the graph uses, without repeats."""
    obj, found = graph["trigger"]["object"], []
    found += [(None, k, v) for k, v in (*filter_refs(graph["trigger"]["filter"], obj),
                                        *data_refs(graph["trigger"]["data"]))]
    for nid, node in graph["nodes"].items():
        cfg, type_ = node["config"], node["type"]
        if type_ == "action":
            act = ACTIONS[node["action"]]
            used = act.refs(act.config.model_validate(cfg))
            found += [(nid, k, f"{obj}.{v}" if k == "field" else v) for k, v in used]
        elif type_ in ("condition", "goal"):
            found += [(nid, k, v) for k, v in filter_refs(cfg["filter"], obj)]
        elif type_ == "wait" and cfg.get("until_field"):
            found.append((nid, "field", f"{obj}.{cfg['until_field']['field']}"))
        elif type_ == "wait" and cfg.get("event"):
            found += [(nid, k, v) for k, v in data_refs(cfg["event"]["match"])]
    return list(dict.fromkeys(found))


# --- what the builder needs -------------------------------------------------------------------------------------

def catalog() -> dict:
    """The triggers (events about a record, with their data schemas), the node types and the actions with the JSON
    schema of each config: what the builder, the validator and the AI generator are all made from."""
    return {
        "triggers": [{"event": t, "description": events.TYPES[t]["description"], "record": key,
                      "data_schema": events.TYPES[t]} for t, key in TRIGGERS.items()],
        "trigger_schema": Trigger.model_json_schema(),
        "nodes": [{"type": t, "description": about, "config_schema": model.model_json_schema() if model else None,
                   "published": t != "subflow"} for t, (model, about) in NODE_TYPES.items()],
        "actions": [{"key": a.key, "label": a.label, "description": a.description, "outbound": a.outbound,
                     "config_schema": a.config.model_json_schema()} for a in ACTIONS.values()],
        "settings_schema": Settings.model_json_schema(), "limits": LIMITS,
        "merge_fields": "Text in message, task, notification and webhook configs may hold {{field_key}}.",
    }
