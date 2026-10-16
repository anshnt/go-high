import hashlib
import hmac
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from sqlalchemy import text

PASSWORD = "correct horse battery"
H = "X-Workspace-Id"


def make_record(client, ws, object_key="contact", owner_id=None, **values) -> dict:
    """Creates a record through the API (fields as keyword arguments) and returns it."""
    r = client.post(f"/api/v1/objects/{object_key}/records", json={"values": values, "owner_id": owner_id},
                    headers={H: ws})
    assert r.status_code == 201, r.text
    return r.json()


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


def add_member(db, org_id, email, org_role="member", workspace_id=None, workspace_role="member"):
    """Creates a user directly (as the owner role) and returns a signed-in client."""
    from fastapi.testclient import TestClient

    from app.main import app
    user_id = db.execute(text("INSERT INTO users (email, name) VALUES (:e, 'M') RETURNING id"), {"e": email}).scalar()
    db.execute(text("INSERT INTO org_members (user_id, org_id, role) VALUES (:u, :o, :r)"),
               {"u": user_id, "o": org_id, "r": org_role})
    if workspace_id:
        db.execute(text("INSERT INTO workspace_members (user_id, workspace_id, role) VALUES (:u, :w, :r)"),
                   {"u": user_id, "w": workspace_id, "r": workspace_role})
    db.commit()
    client = TestClient(app)
    link = client.post("/api/auth/magic-link", json={"email": email}).json()["link"]
    assert client.post("/api/auth/magic-link/consume", json={"token": link.split("token=")[1]}).status_code == 200
    return client


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
