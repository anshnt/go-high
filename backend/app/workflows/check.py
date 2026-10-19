"""What only the workspace knows about a graph (the structure is `schema`'s): the trigger's object and filters compile
against its fields, an update names fields that exist and values their types accept, tags, stages, channels and people
exist, an email has a subject, a webhook's address may be called. Run when a version is saved and again when it is
published, because the fields, tags and channels it names may have changed since. Errors point into the graph."""
from ..records import filters
from ..records.schema import Catalog
from .registry import ACTIONS


def check(cat: Catalog, graph: dict) -> dict[str, str]:
    """{path into the graph: what is wrong}; empty when the graph can run in this workspace."""
    key = graph["trigger"]["object"]
    obj = cat.object(key)
    if obj is None:
        return {"trigger.object": f"there is no object {key!r}"}
    errors: dict[str, str] = {}

    def condition(ast: dict, path: str) -> None:
        try:
            filters.compile(cat, obj, ast, root=path)
        except filters.FilterError as e:
            errors.setdefault(e.path, e.message)

    condition(graph["trigger"]["filter"], "trigger.filter")
    fields = cat.fields(obj)
    for nid, node in graph["nodes"].items():
        cfg, where = node["config"], f"nodes.{nid}.config"
        if node["type"] in ("condition", "goal"):
            condition(cfg["filter"], f"{where}.filter")
        elif node["type"] == "wait" and cfg.get("until_field"):
            field = fields.get(cfg["until_field"]["field"])
            if field is None or field.type not in ("date", "datetime"):
                errors[f"{where}.until_field.field"] = f"must be a date or datetime field of {obj.key}"
        elif node["type"] == "action" and (act := ACTIONS[node["action"]]).check:
            for sub, message in act.check(cat, obj, act.config.model_validate(cfg)).items():
                errors.setdefault(f"{where}.{sub}" if sub else where, message)
    return errors
