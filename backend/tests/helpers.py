import hashlib
import hmac
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from fastapi.routing import iter_route_contexts
from sqlalchemy import text

PASSWORD = "correct horse battery"
H = "X-Workspace-Id"


def make_record(client, ws, object_key="contact", owner_id=None, **values) -> dict:
    """Creates a record through the API (fields as keyword arguments) and returns it."""
    r = client.post(f"/api/v1/objects/{object_key}/records", json={"values": values, "owner_id": owner_id},
                    headers={H: ws})
    assert r.status_code == 201, r.text
    return r.json()


def stage_ids(client, ws) -> dict[str, str]:
    """Stage ids of the workspace's first pipeline (Sales), by lower case name: lead, qualified, proposal,
    negotiation, won, lost."""
    first = client.get("/api/v1/pipelines", headers={H: ws}).json()["data"][0]
    return {s["name"].lower(): s["id"] for s in first["stages"]}


def make_deal(client, ws, name, stage=None, amount=None, close_date=None, owner_id=None, currency="USD", **values):
    """Creates a deal through the API. `stage` is a stage id (left out: the first stage of the default pipeline),
    `amount` is in minor units."""
    body = {"name": name, **values}
    if stage:
        body["stage"] = stage
    if amount is not None:
        body["amount"] = {"amount": amount, "currency": currency}
    if close_date:
        body["close_date"] = close_date
    return make_record(client, ws, "deal", owner_id=owner_id, **body)


def move(client, ws, deal_id, stage_id, **body):
    return client.post(f"/api/v1/deals/{deal_id}/move", json={"stage_id": stage_id, **body}, headers={H: ws})


def listing(client, ws, object_key="contact", **params) -> dict:
    r = client.get(f"/api/v1/objects/{object_key}/records", params=params, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


def names(page: dict) -> list[str]:
    return [r["display_name"] for r in page["data"]]


def type_id(client, ws, from_object: str, to_object: str, label: str | None = None) -> str:
    """The id of the association type between two objects (the built in ones, or a custom one by `label`)."""
    types = client.get("/api/v1/association-types", headers={H: ws}).json()["data"]
    found = [t["id"] for t in types if (t["from_object"], t["to_object"]) == (from_object, to_object)
             and label in (None, t["label"])]
    assert len(found) == 1, (from_object, to_object, label, types)
    return found[0]


def link(client, ws, record_id: str, other_id: str, association_type: str) -> dict:
    r = client.post(f"/api/v1/records/{record_id}/associations", json={"type_id": association_type,
                                                                        "other_id": other_id}, headers={H: ws})
    assert r.status_code == 201, r.text
    return r.json()


def role_id(db, org_id, key: str):
    """The id of a role of the organization by its key (owner, admin, manager, member, viewer, automation, or a custom
    role's)."""
    found = db.scalar(text("SELECT id FROM roles WHERE org_id = :o AND key = :k"), {"o": org_id, "k": key})
    assert found, key
    return str(found)


def add_member(db, org_id, email, org_role="member", workspace_id=None, workspace_role="member"):
    """Creates a user directly (as the owner role) and returns a signed-in client. The roles are given by key."""
    from fastapi.testclient import TestClient

    from app.main import app
    user_id = db.execute(text("INSERT INTO users (email, name) VALUES (:e, 'M') RETURNING id"), {"e": email}).scalar()
    db.execute(text("INSERT INTO org_members (user_id, org_id, role_id) VALUES (:u, :o, :r)"),
               {"u": user_id, "o": org_id, "r": role_id(db, org_id, org_role)})
    if workspace_id:
        db.execute(text("INSERT INTO workspace_members (user_id, workspace_id, role_id) VALUES (:u, :w, :r)"),
                   {"u": user_id, "w": workspace_id, "r": role_id(db, org_id, workspace_role)})
    db.commit()
    client = TestClient(app)
    link = client.post("/api/auth/magic-link", json={"email": email}).json()["link"]
    assert client.post("/api/auth/magic-link/consume", json={"token": link.split("token=")[1]}).status_code == 200
    return client


def context(conn, **ctx) -> None:
    """Runs the rest of the connection's transaction as the app role, with the request context given (user_id, org_id,
    workspace_id, system), the way a request handler would."""
    conn.execute(text("SET LOCAL ROLE gohigh_app"))
    for key in ("user_id", "org_id", "workspace_id", "system"):
        conn.execute(text("SELECT set_config(:k, :v, true)"), {"k": f"app.{key}", "v": str(ctx.get(key, ""))})


def v1_routes() -> list[tuple[str, str, object]]:
    """(method, path, route) of every /api/v1 route of the app."""
    from app.main import app
    return [(m, r.path, r) for r in iter_route_contexts(app.routes) if (r.path or "").startswith("/api/v1")
            for m in sorted(r.methods - {"HEAD", "OPTIONS"})]


def declared(dependant) -> list[str]:
    """The capabilities a route's dependencies declare (see permissions.requires)."""
    found = []
    for dep in dependant.dependencies:
        if capability := getattr(dep.call, "capability", None):
            found.append(capability)
        found += declared(dep)
    return found


def user_id_of(client) -> str:
    return client.get("/api/me").json()["user"]["id"]


def rule(object_key: str = "*", scope: str = "all", hidden=(), readonly=()) -> dict:
    """An object rule of a role, as the API takes it."""
    return {"object_key": object_key, "scope": scope, "hidden_fields": list(hidden), "readonly_fields": list(readonly)}


def make_role(client, ws, name: str, copy_from: str = "member", capabilities=None, rules=None) -> dict:
    """A custom role through the API: a copy of `copy_from`, then `capabilities` and `rules` if given."""
    r = client.post("/api/v1/roles", json={"name": name, "copy_from": copy_from}, headers={H: ws})
    assert r.status_code == 201, r.text
    role = r.json()
    patch = {k: v for k, v in (("capabilities", capabilities), ("object_rules", rules)) if v is not None}
    if patch:
        r = client.patch(f"/api/v1/roles/{role['id']}", json=patch, headers={H: ws})
        assert r.status_code == 200, r.text
        role = r.json()
    return role


def audit(client, ws, **params) -> list[dict]:
    """The events of the audit log, newest first (all of them, whatever their number)."""
    out, cursor = [], None
    while True:
        r = client.get("/api/v1/audit", params={**params, "limit": 200, **({"cursor": cursor} if cursor else {})},
                       headers={H: ws})
        assert r.status_code == 200, r.text
        out += r.json()["data"]
        cursor = r.json()["next_cursor"]
        if not cursor:
            return out


def wait_for_quiet(timeout: float = 60) -> None:
    """Event consumers only see transactions older than every open transaction in the whole Postgres cluster
    (ADR 0003). If something else uses the same server, wait until nothing older than now is open, so a test that
    expects an event to be handed out does not depend on that. Never call it while the test holds a transaction."""
    from app.db import SessionLocal
    deadline = time.monotonic() + timeout
    with SessionLocal() as db:
        target = db.scalar(text("SELECT pg_snapshot_xmax(pg_current_snapshot())"))
        while not db.scalar(text("SELECT pg_snapshot_xmin(pg_current_snapshot()) >= :t"), {"t": target}):
            assert time.monotonic() < deadline, "a transaction elsewhere in the cluster stays open"
            db.rollback()
            time.sleep(0.2)


def drain(limit: int = 200, quiet: bool = True) -> int:
    """Runs due jobs the way the worker would, until none is due. Retries wait for their backoff: see due_now.
    `quiet=False` for tests that hold a transaction open on purpose."""
    from app.db import SessionLocal
    from app.jobs import run_one
    if quiet:
        wait_for_quiet()
    ran = 0
    while run_one(SessionLocal):
        ran += 1
        assert ran < limit, "jobs keep producing jobs"
    return ran


def due_now(db) -> None:
    """Skips the wait for queued jobs (retry backoff, delayed continuations)."""
    db.execute(text("UPDATE jobs SET run_at = now() WHERE status = 'queued'"))
    db.commit()


def verify_signature(secret: str, header: str, body: bytes, tolerance: int = 300) -> bool:
    """What a receiver does; the same as the snippet in the README."""
    parts = dict(p.split("=", 1) for p in header.split(","))
    expected = hmac.new(secret.encode(), parts["t"].encode() + b"." + body, hashlib.sha256).hexdigest()
    return abs(time.time() - int(parts["t"])) <= tolerance and hmac.compare_digest(parts["v1"], expected)


class Receiver:
    """A local HTTP server that records requests. `replies` holds (status, body, headers), one per request;
    then `default` repeats. `delay` holds each answer back, `trickle` answers with an endless header stream."""

    def __init__(self):
        self.requests: list[dict] = []
        self.replies: list[tuple[int, bytes, dict]] = []
        self.default: tuple[int, bytes, dict] = (200, b"ok", {})
        self.delay = 0.0
        self.trickle = False
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
                outer.requests.append({"path": self.path, "body": body,
                                       "headers": {k.lower(): v for k, v in self.headers.items()}})
                try:
                    if outer.trickle:
                        self.wfile.write(b"HTTP/1.1 200 OK\r\n")
                        for _ in range(100):
                            self.wfile.write(b"X-Pad: 1\r\n")
                            self.wfile.flush()
                            time.sleep(0.2)
                        return
                    time.sleep(outer.delay)
                    status, payload, headers = outer.replies.pop(0) if outer.replies else outer.default
                    self.send_response(status)
                    for name, value in headers.items():
                        self.send_header(name, value)
                    self.send_header("Content-Length", str(len(payload)))
                    self.end_headers()
                    self.wfile.write(payload)
                except OSError:
                    pass  # the client gave up

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        threading.Thread(target=self.server.serve_forever, args=(0.05,), daemon=True).start()

    @property
    def port(self) -> int:
        return self.server.server_address[1]

    def url(self, path: str = "/hook", host: str = "127.0.0.1") -> str:
        return f"http://{host}:{self.port}{path}"

    def close(self) -> None:
        self.server.shutdown()
        self.server.server_close()
