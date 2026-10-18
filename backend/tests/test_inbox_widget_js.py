"""The widget script run by node against a live server, with a tiny fake DOM (widget_harness.js): a visitor opens it,
sees the greeting, writes, gets an agent's reply by polling and leaves their details, with and without storage."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest
from helpers import H
from inbox_helpers import add_channel, only_conversation

NODE = shutil.which("node")
HARNESS = Path(__file__).parent / "widget_harness.js"
pytestmark = pytest.mark.skipif(NODE is None, reason="node is not installed")


def run(port: int, key: str, *flags: str) -> subprocess.Popen:
    return subprocess.Popen([NODE, str(HARNESS), f"http://127.0.0.1:{port}", key, *flags], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)


def step(proc: subprocess.Popen, name: str) -> dict:
    line = proc.stdout.readline()
    assert line, proc.stderr.read()
    data = json.loads(line)
    assert data["step"] == name, data
    return data


@pytest.mark.parametrize("storage", ["usable", "blocked"])
def test_a_visitor_chats_through_the_real_script(live, crm, storage):
    client, ws, _ = crm
    channel = add_channel(client, ws, "internal", config={"title": "Ask Acme", "greeting": "Hi, how can we help?"})
    proc = run(live, channel["widget_key"], *(["blocked"] if storage == "blocked" else []))
    try:
        assert step(proc, "loaded")["bubble"] == 1  # a bubble at once, nothing else drawn yet
        greeting = step(proc, "greeting")
        assert (greeting["text"], greeting["title"]) == ("Hi, how can we help?", "Ask Acme")
        sent = step(proc, "sent")
        assert sent["asked"] is True
        assert sent["stored"] == (0 if storage == "blocked" else 1)  # the token is kept, or not
        conv = only_conversation(client, ws)
        assert conv["visitor"] is True and conv["preview"] == "hello from the widget"
        r = client.post(f"/api/v1/conversations/{conv['id']}/messages", json={"body": "an agent replies"},
                        headers={H: ws})
        assert r.status_code == 201
        proc.stdin.write("go\n")
        proc.stdin.flush()
        replied = step(proc, "replied")
        assert replied["messages"][-2:] == [["gh-m gh-visitor", "hello from the widget"],
                                            ["gh-m gh-agent", "an agent replies"]]
        assert step(proc, "identified")["note"].startswith("Thanks")
        assert proc.wait(timeout=20) == 0
    finally:
        proc.kill()
    contact = client.get(f"/api/v1/objects/contact/records/{only_conversation(client, ws)['contact']['id']}",
                         headers={H: ws}).json()
    assert contact["values"]["email"] == "pat@example.com" and contact["display_name"] == "Pat Smith"
