import json
import time

import pytest
from fastapi.testclient import TestClient
from helpers import H, drain, listing
from inbox_helpers import (
    META_VERIFY_TOKEN,
    TELNYX_KEY,
    add_channel,
    bodies,
    conversation,
    conversations_of,
    mailgun_event,
    mailgun_in,
    meta_hook,
    meta_in,
    only_conversation,
    path_of,
    sms_in,
    sms_status,
    sql,
    telnyx_hook,
    telnyx_in,
    twilio_hook,
)
from sqlalchemy import text

from app.main import app

anonymous = TestClient(app)
ALICE = "+14155550123"


def test_a_signed_sms_creates_the_contact_and_a_conversation(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws)
    r = sms_in(anonymous, channel, ALICE, "Hello there")
    assert r.status_code == 200 and r.json() == {"received": 1}
    conv = only_conversation(client, ws)
    assert conv["contact"]["phone"] == ALICE and conv["contact"]["display_name"] == ALICE
    assert (conv["status"], conv["unread"], conv["preview"], conv["channel_kind"]) == ("open", True, "Hello there", "sms")
    contacts = listing(client, ws)["data"]
    assert [c["values"] for c in contacts] == [{"phone": ALICE}] and contacts[0]["id"] == conv["contact"]["id"]
    messages = conversation(client, ws, conv["id"])["messages"]["data"]
    assert [(m["direction"], m["kind"], m["status"], m["body"], m["seq"]) for m in messages] == [
        ("in", "message", "received", "Hello there", 1)]
    types = [r[0] for r in sql(db, "SELECT type FROM events ORDER BY id")]
    assert types[-3:] == ["record.created", "conversation.created", "message.received"]
