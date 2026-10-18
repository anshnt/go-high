"""Realtime (ADR 0005): `GET /api/v1/stream` is a Server-Sent Events stream for the signed-in user in one workspace.
An events consumer in the worker turns message, conversation and record events into compact `NOTIFY gohigh_events`
payloads, every API process listens on one connection and fans them out to the streams of the matching workspace.
A payload is `{id, type, workspace_id, ids}` and carries ids only: the client refetches through the normal API, so
permissions apply and nothing leaks over the stream.

A stream sends `: ping` every 25 seconds, ends after 30 minutes (EventSource reconnects, which checks the session
again) and resumes from `Last-Event-ID` when that event is still in the process's recent buffer; otherwise it sends
`stream.resync` and the client refetches what it shows. Browsers cannot set headers on EventSource, so the workspace
may also be given as `?workspace_id=`.
ponytail: everyone who may read conversations gets every id of the workspace, and an id carries nothing a client
could use without asking the API, which applies the scope (filtering here would cost a query per client per event);
the buffer lives in
the process's memory, and a slow client is cut loose with `stream.resync` instead of being buffered."""
import asyncio
import json
import logging
import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime, timedelta

import psycopg
from fastapi import APIRouter, Depends, Header, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from .. import config, events
from ..events import Event
from ..permissions import require
from ..security import Ctx, enter_workspace, user

log = logging.getLogger("stream")
router = APIRouter()
CHANNEL = "gohigh_events"
HEARTBEAT = 25.0  # seconds between pings
MAX_LIFETIME = 1800.0  # seconds a stream lives before the client reconnects
BUFFER = 1000  # recent notifications kept for Last-Event-ID resume
QUEUE = 200  # notifications a connected client may fall behind before it is cut loose
STALE = timedelta(minutes=5)  # an event older than this is not worth waking anyone for
RESYNC = {"id": None, "type": "stream.resync", "workspace_id": None, "ids": {}}


def ids_of(e: Event) -> dict | None:
    if e.type.startswith("message."):
        return {"message_id": e.subject_id, "conversation_id": e.data.get("conversation_id"),
                "contact_id": e.data.get("contact_id")}
    if e.type.startswith("conversation."):
        return {"conversation_id": e.subject_id, "contact_id": e.data.get("contact_id")}
    if e.type.startswith("record."):
        return {"record_id": e.subject_id, "object": e.data.get("object")}
    return None


@events.consumer("realtime")
def notify(db: Session, batch: list[Event]) -> None:
    """NOTIFYs each message, conversation and record event, in the transaction that advances the cursor (a NOTIFY
    is delivered at commit). A consumer meeting the log for the first time skips what is old."""
    fresh = datetime.now(UTC) - STALE
    for e in batch:
        ids = ids_of(e)
        if ids and e.occurred_at >= fresh:
            payload = {"id": e.id, "type": e.type, "workspace_id": e.workspace_id, "ids": ids}
            db.execute(select(func.pg_notify(CHANNEL, json.dumps(payload, default=str))))


class Hub:
    """The streams of one API process, by workspace."""

    def __init__(self) -> None:
        self.clients: dict[str, set[asyncio.Queue]] = defaultdict(set)
        self.recent: deque[dict] = deque(maxlen=BUFFER)
        self.seen_connection = False

    def put(self, queue: asyncio.Queue, payload: dict) -> None:
        try:
            queue.put_nowait(payload)
        except asyncio.QueueFull:  # too slow: drop what it missed and tell it to refetch
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait(RESYNC)

    def publish(self, payload: dict) -> None:
        self.recent.append(payload)
        for queue in list(self.clients.get(str(payload["workspace_id"]), ())):
            self.put(queue, payload)

    def publish_raw(self, raw: str) -> None:
        try:
            self.publish(json.loads(raw))
        except (ValueError, KeyError):
            log.warning("unreadable notification on %s", CHANNEL)

    def connected(self) -> None:
        """The listener is (re)connected: after a reconnect, events may have been missed, so everyone resyncs."""
        if self.seen_connection:
            for queues in list(self.clients.values()):
                for queue in list(queues):
                    self.put(queue, RESYNC)
        self.seen_connection = True

    def subscribe(self, workspace_id: str, last_event_id: str | None) -> tuple[asyncio.Queue, list[dict]]:
        queue: asyncio.Queue = asyncio.Queue(QUEUE)
        backlog: list[dict] = []
        if last_event_id:
            recent = list(self.recent)
            at = next((i for i, p in enumerate(recent) if str(p["id"]) == last_event_id), None)
            backlog = [RESYNC] if at is None else [p for p in recent[at + 1:] if str(p["workspace_id"]) == workspace_id]
        self.clients[workspace_id].add(queue)
        return queue, backlog

    def unsubscribe(self, workspace_id: str, queue: asyncio.Queue) -> None:
        self.clients[workspace_id].discard(queue)
        if not self.clients[workspace_id]:
            del self.clients[workspace_id]


hub = Hub()


def dsn() -> str:
    return make_url(config.DATABASE_URL).set(drivername="postgresql").render_as_string(hide_password=False)


def pump(loop: asyncio.AbstractEventLoop, hub: Hub, stop: threading.Event) -> None:
    """Reads notifications until the connection fails or `stop` is set. The blocking psycopg API on a thread works
    on every event loop (the async API needs a selector loop, which Windows does not use by default)."""
    with psycopg.connect(dsn(), autocommit=True, keepalives=1, keepalives_idle=30, keepalives_interval=10) as conn:
        conn.execute(f"LISTEN {CHANNEL}")
        loop.call_soon_threadsafe(hub.connected)
        while not stop.is_set():
            for n in conn.notifies(timeout=1.0):
                loop.call_soon_threadsafe(hub.publish_raw, n.payload)


async def listen(hub: Hub = hub) -> None:
    """The process's one LISTEN connection, started in the app's lifespan: reconnects with a growing pause."""
    stop, loop, delay = threading.Event(), asyncio.get_running_loop(), 1
    try:
        while True:
            started = time.monotonic()
            try:
                await asyncio.to_thread(pump, loop, hub, stop)
            except Exception:
                log.warning("the realtime listener lost its database connection", exc_info=True)
            delay = 1 if time.monotonic() - started > 30 else min(delay * 2, 30)
            await asyncio.sleep(delay)
    finally:
        stop.set()


def stream_workspace(c: Ctx = Depends(user), x_workspace_id: str | None = Header(default=None),
                     workspace_id: str | None = Query(default=None)) -> Ctx:
    c = enter_workspace(c, x_workspace_id or workspace_id)
    require(c, "conversations.read")
    return c


stream_workspace.capability = "conversations.read"  # what tests/test_permissions.py reads, as for `requires`


def frame(payload: dict) -> str:
    ident = f"id: {payload['id']}\n" if payload.get("id") is not None else ""
    return f"{ident}data: {json.dumps(payload, default=str)}\n\n"


async def frames(queue: asyncio.Queue, backlog: list[dict], workspace_id: str):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + MAX_LIFETIME
    try:
        yield "retry: 3000\n\n"
        for payload in backlog:
            yield frame(payload)
        while (left := deadline - loop.time()) > 0:
            try:
                payload = await asyncio.wait_for(queue.get(), min(HEARTBEAT, left))
            except TimeoutError:
                if loop.time() < deadline:
                    yield ": ping\n\n"
                continue
            yield frame(payload)
    finally:
        hub.unsubscribe(workspace_id, queue)


@router.get("/api/v1/stream")
async def stream(c: Ctx = Depends(stream_workspace), last_event_id: str | None = Header(default=None),
                 last: str | None = Query(default=None, alias="last_event_id")):
    """Server-Sent Events for this user and workspace: one `data:` line of JSON per event
    (`{id, type, workspace_id, ids}`, ids only). Refetch what a payload names through the API."""
    workspace_id = str(c.workspace.id)
    c.db.close()  # a stream must not keep a transaction open: event consumers wait for every open one
    queue, backlog = hub.subscribe(workspace_id, last_event_id or last)
    return StreamingResponse(frames(queue, backlog, workspace_id), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
