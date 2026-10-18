"""The realtime stream needs a real server: the test client buffers a response until it ends, and a stream never does.
The app runs under uvicorn on a free port in this process, with its lifespan (so its LISTEN connection), and these
tests read the stream with a plain socket client."""
import http.client
import json
import queue
import threading
import time

import psycopg
import pytest
from fastapi.testclient import TestClient
from helpers import H, drain, make_record
from inbox_helpers import add_channel, conversations_of, sms_in, sql
from sqlalchemy import text

from app.inbox import stream
from app.main import app

anonymous = TestClient(app)
ALICE = "+14155550123"
TYPES = ["record.created", "conversation.created", "message.received"]


class Stream:
    """One open stream: lines are read on a thread; `next` returns the next block of the event stream."""

    def __init__(self, port: int, client, workspace: str | None, *, last_event_id: str | None = None,
                 query: str = "", header: bool = True):
        self.conn = http.client.HTTPConnection("127.0.0.1", port, timeout=20)
        headers = {"Accept": "text/event-stream"}
        if client is not None:
            headers["Cookie"] = f"gohigh_session={client.cookies.get('gohigh_session')}"
        if workspace and header:
            headers[H] = workspace
        if last_event_id:
            headers["Last-Event-ID"] = last_event_id
        self.conn.request("GET", f"/api/v1/stream{query}", headers=headers)
        self.response = self.conn.getresponse()
        self.blocks: queue.Queue = queue.Queue()
        self.raw: list[str] = []
        threading.Thread(target=self.read, daemon=True).start()

    def read(self) -> None:
        block: list[str] = []
        try:
            for line in iter(self.response.readline, b""):
                text_ = line.decode().rstrip("\r\n")
                self.raw.append(text_)
                if text_:
                    block.append(text_)
                elif block:
                    self.blocks.put(block)
                    block = []
        except (OSError, AttributeError, http.client.HTTPException):  # the connection was closed under us
            pass
        self.blocks.put(None)  # the stream ended

    def next(self, timeout: float = 15):
        return self.blocks.get(timeout=timeout)

    def payloads(self, n: int, timeout: float = 20) -> list[dict]:
        """The next `n` events with data, skipping pings and the retry hint."""
        out, deadline = [], time.monotonic() + timeout
        while len(out) < n:
            block = self.next(max(deadline - time.monotonic(), 0.01))
            assert block is not None, "the stream ended"
            data = [line[6:] for line in block if line.startswith("data: ")]
            if data:
                out.append({**json.loads(data[0]), "_id_line": next((b for b in block if b.startswith("id: ")), None)})
        return out

    def silent_for(self, seconds: float) -> bool:
        """True when no event with data arrives for `seconds` (pings do not count)."""
        deadline = time.monotonic() + seconds
        while (left := deadline - time.monotonic()) > 0:
            try:
                block = self.blocks.get(timeout=left)
            except queue.Empty:
                return True
            if block is None or any(line.startswith("data: ") for line in block):
                return False
        return True

    def close(self) -> None:
        self.conn.close()


@pytest.fixture
def streams():
    opened = []

    def open_(*args, **kwargs):
        opened.append(Stream(*args, **kwargs))
        return opened[-1]

    yield open_
    for s in opened:
        s.close()


def test_a_connected_client_hears_message_events_as_ids_only_and_another_workspace_hears_nothing(
        live, crm, make_user, streams, db):
    client, ws, _ = crm
    other, other_ids = make_user("b@example.com")
    mine, theirs = streams(live, client, ws), streams(live, other, other_ids["workspace_id"])
    assert mine.response.status == 200 and mine.response.getheader("Content-Type").startswith("text/event-stream")
    assert mine.response.getheader("Cache-Control") == "no-cache"
    channel = add_channel(client, ws)
    sms_in(anonymous, channel, ALICE, "Where is my secret invoice 1043?")
    drain()
    got = mine.payloads(3)
    assert [p["type"] for p in got] == TYPES
    conv = conversations_of(client, ws)["data"][0]
    assert all(set(p) == {"id", "type", "workspace_id", "ids", "_id_line"} for p in got)
    assert all(p["workspace_id"] == ws and p["_id_line"] == f"id: {p['id']}" for p in got)
    assert got[1]["ids"] == {"conversation_id": conv["id"], "contact_id": conv["contact"]["id"]}
    assert set(got[2]["ids"]) == {"message_id", "conversation_id", "contact_id"}
    assert got[2]["ids"]["conversation_id"] == conv["id"] and got[0]["ids"] == {
        "record_id": conv["contact"]["id"], "object": "contact"}
    assert "secret" not in "".join(mine.raw) and "invoice" not in "".join(mine.raw)  # ids only, no content
    assert theirs.silent_for(1.5)
    make_record(other, other_ids["workspace_id"], first_name="Bea")
    drain()
    assert [p["type"] for p in theirs.payloads(1)] == ["record.created"]
    assert mine.silent_for(1.5)  # and their event did not reach me


def test_conversation_changes_are_streamed_with_the_conversation_and_contact_ids(live, crm, streams, db):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    sms_in(anonymous, channel, ALICE, "hello")
    drain()
    conv = conversations_of(client, ws)["data"][0]
    watcher = streams(live, client, ws)
    client.post(f"/api/v1/conversations/{conv['id']}/close", headers={H: ws})
    client.post(f"/api/v1/conversations/{conv['id']}/messages", json={"body": "a note", "kind": "note"},
                headers={H: ws})
    drain()
    updated, note = watcher.payloads(2)
    assert (updated["type"], note["type"]) == ("conversation.updated", "message.note_added")
    assert updated["ids"] == {"conversation_id": conv["id"], "contact_id": conv["contact"]["id"]}
    assert note["ids"]["conversation_id"] == conv["id"]


def test_a_reconnecting_client_resumes_after_its_last_event_id(live, crm, streams, db):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    first = streams(live, client, ws)
    sms_in(anonymous, channel, ALICE, "one")
    drain()
    seen = first.payloads(3)
    first.close()
    sms_in(anonymous, channel, ALICE, "two")
    sms_in(anonymous, channel, ALICE, "three")
    drain()
    time.sleep(0.5)
    resumed = streams(live, client, ws, last_event_id=str(seen[-1]["id"]))
    missed = resumed.payloads(2)
    assert [p["type"] for p in missed] == ["message.received"] * 2
    assert missed[0]["id"] > seen[-1]["id"] and missed[0]["ids"]["message_id"] != missed[1]["ids"]["message_id"]
    assert resumed.silent_for(1.0)
    sms_in(anonymous, channel, ALICE, "four")
    drain()
    assert [p["type"] for p in resumed.payloads(1)] == ["message.received"]
    via_query = streams(live, client, ws, query=f"?workspace_id={ws}&last_event_id={seen[0]['id']}", header=False)
    assert [p["type"] for p in via_query.payloads(2)] == TYPES[1:]  # everything after the first event, for browsers
    unknown = streams(live, client, ws, last_event_id="999999999999")
    [lost] = unknown.payloads(1)
    assert lost["type"] == "stream.resync" and lost["_id_line"] is None  # the client refetches what it shows


def test_a_stream_pings_so_proxies_keep_it_open(live, crm, streams, monkeypatch):
    client, ws, _ = crm
    monkeypatch.setattr(stream, "HEARTBEAT", 0.3)
    s = streams(live, client, ws)
    assert s.next() == ["retry: 3000"]
    assert [s.next(), s.next()] == [[": ping"], [": ping"]]


def test_a_stream_ends_after_its_lifetime_so_the_session_is_checked_again(live, crm, streams, monkeypatch):
    client, ws, _ = crm
    monkeypatch.setattr(stream, "MAX_LIFETIME", 0.5)
    s = streams(live, client, ws)
    assert s.next() == ["retry: 3000"]
    assert s.next(timeout=10) is None


def test_a_stream_needs_a_session_and_a_workspace_the_user_can_see(live, crm, make_user, streams):
    client, ws, _ = crm
    other, other_ids = make_user("b@example.com")
    assert streams(live, None, ws).response.status == 401
    assert streams(live, other, ws).response.status == 404
    assert streams(live, client, None).response.status == 400
    assert streams(live, client, "not-a-uuid").response.status == 400
    foreign = f"?workspace_id={other_ids['workspace_id']}"
    assert streams(live, client, ws, header=False, query=foreign).response.status == 404
    assert streams(live, client, ws, header=False, query=f"?workspace_id={ws}").response.status == 200


def test_a_stream_holds_no_transaction_open_while_it_waits(live, crm, streams, db):
    client, ws, _ = crm
    streams(live, client, ws)
    time.sleep(0.5)
    idle = sql(db, "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                   "AND state = 'idle in transaction' AND pid <> pg_backend_pid()")
    assert idle[0][0] == 0  # the event consumers wait for every open transaction, so a stream must not hold one


def test_the_consumer_notifies_on_the_channel_and_skips_stale_events(live, crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    with psycopg.connect(stream.dsn(), autocommit=True) as listener:
        listener.execute("LISTEN gohigh_events")
        sms_in(anonymous, channel, ALICE, "old news")
        db.rollback()
        db.execute(text("UPDATE events SET occurred_at = now() - interval '10 minutes' "
                        "WHERE type = 'message.received'"))
        db.commit()
        sms_in(anonymous, channel, ALICE, "fresh news", sid="SMfresh")
        drain()
        got = [json.loads(n.payload) for n in listener.notifies(timeout=2.0)]
    assert [(g["type"]) for g in got].count("message.received") == 1  # the stale one made no noise
    assert all(set(g) == {"id", "type", "workspace_id", "ids"} for g in got)


def test_a_client_that_falls_behind_is_told_to_refetch_instead_of_buffering_forever(monkeypatch):
    monkeypatch.setattr(stream, "QUEUE", 3)
    hub = stream.Hub()
    slow, _ = hub.subscribe("w", None)
    elsewhere, _ = hub.subscribe("other", None)
    for i in range(5):
        hub.publish({"id": i, "type": "message.received", "workspace_id": "w", "ids": {}})
    assert [slow.get_nowait() for _ in range(slow.qsize())] == [
        stream.RESYNC, {"id": 4, "type": "message.received", "workspace_id": "w", "ids": {}}]
    assert elsewhere.empty()
    hub.connected()  # the first connection
    hub.connected()  # a reconnect: events may have been missed, so everyone resyncs
    assert slow.get_nowait() == stream.RESYNC and elsewhere.get_nowait() == stream.RESYNC
    hub.unsubscribe("w", slow)
    assert "w" not in hub.clients
