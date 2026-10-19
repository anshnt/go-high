"""Helpers for the workflow tests: graphs written compactly, workflows through the API, and a pump that runs the
worker's jobs the way it would (enrollment, steps, wake-ups)."""
from helpers import H, drain, make_record, wait_for_quiet
from sqlalchemy import text

ROOT = "/api/v1/workflows"


def graph(nodes: dict, start: str | None = None, event: str = "record.created", **trigger) -> dict:
    """A graph that starts at `start` (default: the first node) when `event` happens to a contact (`object`,
    `filter` and `data` go in the trigger)."""
    return {"trigger": {"event": event, **trigger}, "start": start or next(iter(nodes)), "nodes": nodes}


def act(action: str, config: dict, next: str | None = None) -> dict:
    return {"type": "action", "action": action, "config": config, "next": next}


def pause(config: dict, next: str | None = None) -> dict:
    return {"type": "wait", "config": config, "next": next}


def ask(filter: dict, yes: str | None = None, no: str | None = None) -> dict:
    return {"type": "condition", "config": {"filter": filter}, "branches": {"yes": yes, "no": no}}


def tag(name: str, next: str | None = None) -> dict:
    return act("tag.add", {"tag": name}, next)


def create(client, ws, graph_: dict | None = None, name: str = "Flow", **extra) -> dict:
    body = {"name": name, **extra, **({"graph": graph_} if graph_ is not None else {})}
    r = client.post(ROOT, json=body, headers={H: ws})
    assert r.status_code == 201, r.text
    return r.json()


def publish(client, ws, workflow_id: str, **body) -> dict:
    r = client.post(f"{ROOT}/{workflow_id}/publish", json=body, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


def live(client, ws, graph_: dict, name: str = "Flow", **extra) -> dict:
    """A workflow with this graph, published."""
    wf = create(client, ws, graph_, name, **extra)
    publish(client, ws, wf["id"])
    return wf


def pump(db, rounds: int = 10) -> None:
    """Runs the due jobs, and the jobs they queued: the event dispatcher is made due each round, so the consumers see
    what the steps just emitted, however many transactions are open elsewhere on the server."""
    for _ in range(rounds):
        wait_for_quiet()
        db.execute(text("UPDATE jobs SET run_at = now() WHERE status = 'queued' AND kind = 'events.dispatch'"))
        db.commit()
        if not drain(quiet=False):
            return


def wake(db) -> None:
    """Time passes: every queued job is due (the wake-up of each wait included), and runs."""
    db.execute(text("UPDATE jobs SET run_at = now() WHERE status = 'queued'"))
    db.commit()
    pump(db)


def runs(client, ws, **params) -> list[dict]:
    r = client.get(f"{ROOT}/runs", params={"limit": 200, **params}, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def detail(client, ws, run_id: str) -> dict:
    r = client.get(f"{ROOT}/runs/{run_id}", headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


def only_run(client, ws, **params) -> dict:
    found = runs(client, ws, **params)
    assert len(found) == 1, found
    return detail(client, ws, found[0]["id"])


def walked(run: dict) -> list[tuple[str, str]]:
    """The trace as (node, status) pairs."""
    return [(s["node_id"], s["status"]) for s in run["steps"]]


def contact(client, ws, **values) -> dict:
    return make_record(client, ws, **{"first_name": "Ada", "email": "ada@example.com", **values})


def tags_of(client, ws, record_id: str) -> list[str]:
    r = client.get(f"/api/v1/objects/contact/records/{record_id}", params={"include": "tags"}, headers={H: ws})
    assert r.status_code == 200, r.text
    return sorted(t["name"] for t in r.json().get("tags", []))


def value_of(client, ws, record_id: str, key: str, object_key: str = "contact"):
    return get_record(client, ws, record_id, object_key)["values"].get(key)


def make_tag(client, ws, name: str) -> dict:
    r = client.post("/api/v1/tags", json={"name": name}, headers={H: ws})
    assert r.status_code == 201, r.text
    return r.json()


def get_record(client, ws, record_id: str, object_key: str = "contact") -> dict:
    r = client.get(f"/api/v1/objects/{object_key}/records/{record_id}", headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


def sql(db, query: str, **params):
    db.rollback()  # see what the application committed
    return db.execute(text(query), params).all()
