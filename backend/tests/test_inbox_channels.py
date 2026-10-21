import json
import uuid

import pytest
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient
from helpers import H, add_member, drain
from inbox_helpers import (
    CHANNELS,
    META_VERIFY_TOKEN,
    TWILIO_TOKEN,
    add_channel,
    conversations_of,
    meta_hook,
    meta_in,
    path_of,
    sms_in,
)
from sqlalchemy import text

from app import config
from app.db import engine
from app.inbox import gateway, vault
from app.main import app

anonymous = TestClient(app)
SECRETS = [TWILIO_TOKEN, "test-api-key-not-real", "test-signing-key-not-real", "test-access-token-not-real",
           "test-app-secret-not-real", META_VERIFY_TOKEN, "test-smtp-password-not-real"]


def test_a_new_channel_shows_its_webhook_url_and_never_its_secrets(crm, db):
    client, ws, _ = crm
    r = client.post("/api/v1/channels", json=CHANNELS["twilio"], headers={H: ws})
    assert r.status_code == 201
    channel = r.json()
    assert (channel["kind"], channel["provider"], channel["status"], channel["secrets_set"]) == (
        "sms", "twilio", "pending", True)
    assert channel["webhook_url"] == f"{config.ALLOWED_ORIGINS[0]}/api/hooks/twilio/{channel['id']}"
    assert channel["config"] == {"account_sid": "AC" + "a" * 32} and "auth_token" not in r.text
    assert TWILIO_TOKEN not in r.text
    again = client.get(f"/api/v1/channels/{channel['id']}", headers={H: ws}).json()
    assert again == channel
    assert client.get("/api/v1/channels", headers={H: ws}).json() == {"data": [channel], "next_cursor": None}
    assert TWILIO_TOKEN not in client.get("/api/v1/channels", headers={H: ws}).text
    db.rollback()
    types = db.scalars(text("SELECT type FROM events WHERE type LIKE 'channel.%'")).all()
    assert types == ["channel.created"]


def test_secrets_are_encrypted_at_rest_and_appear_in_no_table_event_or_job(crm, db):
    client, ws, _ = crm
    for provider in ("twilio", "telnyx", "mailgun", "meta"):
        add_channel(client, ws, provider)
    smtp = {"kind": "email", "provider": "smtp", "name": "SMTP", "address": "x@example.com",
            "config": {"host": "smtp.example.com", "username": "user"},
            "secrets": {"password": "test-smtp-password-not-real"}}
    assert client.post("/api/v1/channels", json=smtp, headers={H: ws}).status_code == 201
    db.rollback()
    for table in ("channels", "events", "jobs", "idempotency_keys", "messages", "conversations"):
        dump = "".join(db.scalars(text(f"SELECT t::text FROM {table} t")).all())
        assert not any(secret in dump for secret in SECRETS), table
    blobs = db.execute(text("SELECT id, workspace_id, ciphertext FROM secrets")).all()
    assert len(blobs) == 5
    for ref, workspace_id, blob in blobs:
        assert not any(secret.encode() in bytes(blob) for secret in SECRETS)
        assert isinstance(vault.decrypt(bytes(blob), ref, workspace_id), dict)
    ref = db.scalar(text("SELECT secret_ref FROM channels WHERE provider = 'twilio'"))
    assert vault.reveal(ref) == {"auth_token": TWILIO_TOKEN}


def test_the_ciphertext_is_tied_to_its_row_and_to_the_server_key(crm, db, monkeypatch):
    client, ws, _ = crm
    add_channel(client, ws, "twilio")
    add_channel(client, ws, "telnyx")
    db.rollback()
    (a, a_ws, a_blob), (b, _, b_blob) = db.execute(text("SELECT id, workspace_id, ciphertext FROM secrets "
                                                        "ORDER BY created_at")).all()
    assert vault.decrypt(bytes(a_blob), a, a_ws) == {"auth_token": TWILIO_TOKEN}
    with pytest.raises(InvalidTag):  # copied to another row
        vault.decrypt(bytes(b_blob), a, a_ws)
    with pytest.raises(InvalidTag):  # the same row, claimed by another workspace
        vault.decrypt(bytes(a_blob), a, uuid.uuid4())
    assert vault.encrypt({"k": "v"}, a, a_ws) != vault.encrypt({"k": "v"}, a, a_ws)  # a fresh nonce every time
    monkeypatch.setattr(config, "SECRET_KEY", "another-server-key-not-real")
    with pytest.raises(InvalidTag):
        vault.decrypt(bytes(a_blob), a, a_ws)
    with pytest.raises(ValueError, match="format"):
        vault.decrypt(b"\x09" + bytes(a_blob)[1:], a, a_ws)


def test_request_handlers_cannot_read_ciphertext_but_the_owner_can(crm):
    client, ws, _ = crm
    add_channel(client, ws, "twilio")
    with engine.connect() as conn:
        def can(column: str, privilege: str) -> bool:
            return conn.scalar(text("SELECT has_column_privilege('gohigh_app', 'secrets', :c, :p)"),
                               {"c": column, "p": privilege})

        assert [can("ciphertext", "SELECT"), can("id", "SELECT"), can("ciphertext", "UPDATE")] == [False, True, True]
    assert len(vault.reveal(uuid.uuid4())) == 0  # an unknown ref has no secrets


def test_settings_are_checked_per_provider_and_secrets_belong_in_secrets(crm):
    client, ws, _ = crm

    def create(**over):
        return client.post("/api/v1/channels", json={**CHANNELS["twilio"], **over}, headers={H: ws})

    def fields(r) -> dict:
        assert r.status_code == 422 and r.json()["error"]["code"] == "validation_failed", r.text
        return r.json()["error"]["fields"]

    leak = "test-leak-not-real"
    assert fields(create(config={"account_sid": "AC1", "auth_token": leak})) == {
        "config.auth_token": "is not a setting of this provider"}
    assert leak not in create(config={"account_sid": "AC1", "auth_token": leak}).text
    assert fields(create(config={})) == {"config.account_sid": "is required"}
    assert fields(create(secrets={})) == {"secrets.auth_token": "is required"}
    assert fields(create(secrets={"auth_token": "t", "other": leak})) == {
        "secrets.other": "is not a secret of this provider"}
    assert "address" in fields(create(address="not a number"))
    assert "address" in fields(create(address=""))
    assert fields(create(kind="email")) == {"kind": "twilio is for sms channels", "address": (
        "must be the sending email address")}
    assert fields(create(config={"account_sid": "AC1", "segment_cost": -1})) == {"config.segment_cost": (
        "must not be negative")}
    assert "config.quiet_start" in fields(create(config={"account_sid": "AC1", "quiet_start": "late"}))
    assert "config.frequency_cap" in fields(create(config={"account_sid": "AC1", "frequency_cap": {"max": 1}}))
    assert "config.auto_replies" in fields(create(config={"account_sid": "AC1", "auto_replies": {"go": "x"}}))
    ok = create(address="", config={"account_sid": "AC1", "messaging_service_sid": "MG1"})
    assert ok.status_code == 201 and ok.json()["address"] == ""  # a messaging service needs no number
    smtp = {"kind": "email", "provider": "smtp", "name": "SMTP", "address": "me@example.com",
            "config": {"host": "smtp.example.com", "username": "me"}}
    assert fields(client.post("/api/v1/channels", json=smtp, headers={H: ws})) == {"secrets.password": "is required"}
    assert client.post("/api/v1/channels", json={**smtp, "secrets": {"password": "test-smtp-password-not-real"}},
                       headers={H: ws}).status_code == 201
    assert client.post("/api/v1/channels", json={**smtp, "kind": "email", "provider": "nope"},
                       headers={H: ws}).status_code == 422
    assert client.post("/api/v1/channels", json={**smtp, "kind": "voice"}, headers={H: ws}).status_code == 422


def test_setting_values_must_be_short_plain_values(crm):
    client, ws, _ = crm
    smtp = {"kind": "email", "provider": "smtp", "name": "SMTP", "address": "me@example.com",
            "config": {"host": "smtp.example.com"}}

    def problem(**config):
        r = client.post("/api/v1/channels", json={**smtp, "config": {**smtp["config"], **config}}, headers={H: ws})
        assert r.status_code == 422, r.text
        [(key, message)] = r.json()["error"]["fields"].items()
        return key, message

    assert problem(port=0) == ("config.port", "must be a port number")
    assert problem(port=65536) == ("config.port", "must be a port number")
    assert problem(port="smtp") == ("config.port", "is not a valid value")
    assert problem(host={"name": "smtp.example.com"}) == ("config.host", "must be text or a number")
    assert problem(reply_to=["a@example.com", "b@example.com"]) == ("config.reply_to", "must be text or a number")
    assert problem(host="h" * 501) == ("config.host", "is too long")
    assert problem(frequency_cap={"max": 1, "hours": 721}) == ("config.frequency_cap",
                                                               'must be {"max": messages, "hours": 1 to 720}')
    assert problem(auto_replies={"stop": "x" * 321})[0] == "config.auto_replies"
    ok = client.post("/api/v1/channels", json={**smtp, "config": {**smtp["config"], "port": "587", "host": "h" * 500}},
                     headers={H: ws})
    assert ok.status_code == 201, ok.text


def test_channels_are_listed_by_status(crm):
    client, ws, _ = crm
    chat = add_channel(client, ws, "internal")  # a chat channel is active at once
    sms = add_channel(client, ws, "twilio")  # a provider channel waits for its first check
    client.patch(f"/api/v1/channels/{sms['id']}", json={"status": "disabled"}, headers={H: ws})

    def listed(**params) -> list[str]:
        r = client.get("/api/v1/channels", params=params, headers={H: ws})
        assert r.status_code == 200, r.text
        return [c["id"] for c in r.json()["data"]]

    assert listed(status="active") == [chat["id"]]
    assert listed(status="disabled") == [sms["id"]]
    assert listed(status="failing") == []
    assert sorted(listed()) == sorted([chat["id"], sms["id"]])
    assert client.get("/api/v1/channels", params={"status": "broken"}, headers={H: ws}).status_code == 422


def test_update_merges_settings_rotates_secrets_and_disables(crm, db):
    client, ws, _ = crm
    channel = add_channel(client, ws, "twilio")
    url = f"/api/v1/channels/{channel['id']}"
    r = client.patch(url, json={"name": "Renamed", "config": {"segment_cost": "0.0079"}}, headers={H: ws})
    assert r.status_code == 200 and r.json()["name"] == "Renamed"
    assert r.json()["config"] == {"account_sid": "AC" + "a" * 32, "segment_cost": "0.0079"}
    r = client.patch(url, json={"config": {"segment_cost": None}}, headers={H: ws})
    assert r.json()["config"] == {"account_sid": "AC" + "a" * 32}
    rotated = "test-rotated-token-not-real"
    r = client.patch(url, json={"secrets": {"auth_token": rotated}}, headers={H: ws})
    assert r.status_code == 200 and rotated not in r.text and r.json()["secrets_set"] is True
    db.rollback()
    assert vault.reveal(db.scalar(text("SELECT secret_ref FROM channels"))) == {"auth_token": rotated}
    r = client.patch(url, json={"secrets": {"auth_token": None}}, headers={H: ws})  # removing a required secret
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"secrets.auth_token": "is required"}
    r = client.patch(url, json={"status": "disabled"}, headers={H: ws}).json()
    assert (r["status"], r["status_detail"]) == ("disabled", "Disabled by an admin")
    assert client.patch(url, json={"status": "active"}, headers={H: ws}).json()["status"] == "pending"
    assert client.patch(url, json={"address": "+15550009999"}, headers={H: ws}).json()["address"] == "+15550009999"
    assert client.patch(url, json={"address": "nope"}, headers={H: ws}).status_code == 422
    assert client.patch(url, json={}, headers={H: ws}).status_code == 200  # nothing to change
    db.rollback()
    changes = [e for e in db.execute(text("SELECT data FROM events WHERE type = 'channel.updated' ORDER BY id")
                                     ).scalars()]
    assert [c["changed"] for c in changes] == [["name", "config"], ["config"], ["secrets"], ["status"], ["status"],
                                               ["address"]]
    assert all("auth_token" not in json.dumps(c) and "config" not in c.keys() for c in changes)
    assert client.patch(f"/api/v1/channels/{uuid.uuid4()}", json={}, headers={H: ws}).status_code == 404


def test_only_admins_change_channels_and_members_see_no_settings(crm, db, make_user):
    client, ws, ids = crm
    channel = add_channel(client, ws, "twilio")
    member = add_member(db, ids["org_id"], "m@example.com", workspace_id=ws)
    url = f"/api/v1/channels/{channel['id']}"
    for method, path, body in [("POST", "/api/v1/channels", CHANNELS["twilio"]), ("PATCH", url, {"name": "x"}),
                               ("POST", f"{url}/test", None)]:
        r = member.request(method, path, json=body, headers={H: ws})
        assert r.status_code == 403, (method, path)
    seen = member.get(url, headers={H: ws}).json()
    assert seen["name"] == "Main line" and seen["address"] == "+15550001111"
    assert not {"config", "secrets_set", "webhook_url", "embed"} & seen.keys()
    assert member.get("/api/v1/channels", headers={H: ws}).json()["data"][0]["id"] == channel["id"]
    assert member.post(f"{url}/estimate", json={"body": "hi"}, headers={H: ws}).status_code == 200
    stranger, _ = make_user("b@example.com")
    for method, path, body in [("GET", url, None), ("PATCH", url, {"name": "x"}), ("POST", f"{url}/test", None),
                               ("POST", f"{url}/estimate", {"body": "x"}), ("GET", "/api/v1/channels", None)]:
        assert stranger.request(method, path, json=body, headers={H: ws}).status_code == 404, (method, path)
        assert anonymous.request(method, path, json=body, headers={H: ws}).status_code == 401
    other = stranger.get("/api/me").json()["workspaces"][0]["id"]
    assert stranger.get(url, headers={H: other}).status_code == 404  # B's own workspace does not hold it
    assert stranger.get("/api/v1/channels", headers={H: other}).json()["data"] == []


def test_a_channel_is_tested_against_its_provider(crm, receiver, monkeypatch):
    client, ws, _ = crm
    channel = add_channel(client, ws, "twilio")
    url = f"/api/v1/channels/{channel['id']}/test"
    monkeypatch.setitem(gateway.BASE_URLS, "twilio", receiver.url(""))
    receiver.default = (200, b'{"sid": "AC1"}', {})
    r = client.post(url, headers={H: ws})
    assert r.json() == {"ok": True, "detail": "Twilio accepted the account SID and auth token"}
    call = receiver.requests[0]
    assert call["method"] == "GET" and call["path"] == f"/2010-04-01/Accounts/AC{'a' * 32}.json"
    assert call["headers"]["authorization"].startswith("Basic ")
    assert client.get(f"/api/v1/channels/{channel['id']}", headers={H: ws}).json()["status"] == "active"
    receiver.default = (401, b'{"code": 20003, "message": "Authenticate"}', {})
    r = client.post(url, headers={H: ws}).json()
    assert r["ok"] is False and "Authenticate" in r["detail"] and TWILIO_TOKEN not in json.dumps(r)
    failing = client.get(f"/api/v1/channels/{channel['id']}", headers={H: ws}).json()
    assert failing["status"] == "failing" and "Authenticate" in failing["status_detail"]
    client.patch(f"/api/v1/channels/{channel['id']}", json={"status": "disabled"}, headers={H: ws})
    receiver.default = (200, b"{}", {})
    assert client.post(url, headers={H: ws}).json()["ok"] is True
    assert client.get(f"/api/v1/channels/{channel['id']}", headers={H: ws}).json()["status"] == "disabled"


@pytest.mark.parametrize("provider,reply,path", [
    ("telnyx", b'{"data": []}', "/v2/messaging_profiles?page%5Bsize%5D=1"),
    ("mailgun", b'{"domain": {}}', "/v3/domains/mg.example.com"),
    ("meta", b'{"id": "106540352242922"}', "/106540352242922?fields=id")])
def test_every_http_provider_has_a_connection_check(crm, receiver, monkeypatch, provider, reply, path):
    client, ws, _ = crm
    channel = add_channel(client, ws, provider)
    monkeypatch.setitem(gateway.BASE_URLS, provider, receiver.url(""))
    receiver.default = (200, reply, {})
    assert client.post(f"/api/v1/channels/{channel['id']}/test", headers={H: ws}).json()["ok"] is True
    assert (receiver.requests[0]["method"], receiver.requests[0]["path"]) == ("GET", path)
    assert "authorization" in receiver.requests[0]["headers"]


def test_an_smtp_channel_is_tested_by_logging_in_and_a_webchat_channel_has_nothing_to_test(
        crm, receiver, tls, smtp_server, dns):
    client, ws, _ = crm
    dns["smtp.test"] = ["127.0.0.1"]
    server = smtp_server(context=tls("smtp.test"), login=("user", "test-smtp-password-not-real"))
    smtp = {"kind": "email", "provider": "smtp", "name": "SMTP", "address": "me@example.com",
            "config": {"host": "smtp.test", "port": server.port, "username": "user"},
            "secrets": {"password": "test-smtp-password-not-real"}}
    channel = client.post("/api/v1/channels", json=smtp, headers={H: ws}).json()
    r = client.post(f"/api/v1/channels/{channel['id']}/test", headers={H: ws}).json()
    assert r["ok"] is True and server.commands.index("STARTTLS") < server.commands.index("AUTH")
    assert "MAIL" not in server.commands  # nothing is sent by a test
    client.patch(f"/api/v1/channels/{channel['id']}", json={"secrets": {"password": "test-wrong-password-not-real"}},
                 headers={H: ws})
    r = client.post(f"/api/v1/channels/{channel['id']}/test", headers={H: ws}).json()
    assert r["ok"] is False and "535" in r["detail"] and "wrong-password" not in r["detail"]
    chat = add_channel(client, ws, "internal")
    assert client.post(f"/api/v1/channels/{chat['id']}/test", headers={H: ws}).json() == {
        "ok": True, "detail": "This channel has nothing to connect to"}


def test_a_webchat_channel_gets_a_widget_key_and_an_embed_snippet(crm):
    client, ws, _ = crm
    chat = add_channel(client, ws, "internal", config={"title": "Ask us", "greeting": "Hi!"})
    assert chat["status"] == "active" and chat["widget_key"] == chat["address"] and chat["address"].startswith("wk_")
    assert chat["webhook_url"] is None and chat["secrets_set"] is False
    assert chat["embed"] == (f'<script src="{config.ALLOWED_ORIGINS[0]}/widget.js" data-key="{chat["address"]}" '
                             "async></script>")
    second = add_channel(client, ws, "internal")
    assert second["address"] != chat["address"]
    r = client.patch(f"/api/v1/channels/{chat['id']}", json={"address": "wk_chosen"}, headers={H: ws})
    assert r.json()["address"] == chat["address"]  # the key does not change


def test_the_estimate_counts_segments_and_prices_them_per_channel(crm):
    client, ws, _ = crm
    free = add_channel(client, ws, "twilio")
    paid = add_channel(client, ws, "telnyx", config={"public_key": CHANNELS["telnyx"]["config"]["public_key"],
                                                     "segment_cost": "0.0079"})
    one = client.post(f"/api/v1/channels/{free['id']}/estimate", json={"body": "x" * 160}, headers={H: ws}).json()
    assert one.pop("charge")["price"] == 0  # what the wallet would charge (test_usage_sends goes further)
    assert one == {"encoding": "gsm7", "segments": 1, "chars": 160, "estimated_cost": "0.000000"}
    two = client.post(f"/api/v1/channels/{paid['id']}/estimate", json={"body": "x" * 161}, headers={H: ws}).json()
    assert (two.pop("charge")["price"], two.pop("charge", None)) == (15_800, None)
    assert two == {"encoding": "gsm7", "segments": 2, "chars": 161, "estimated_cost": "0.015800"}
    smile = {"body": "hi \U0001f600"}
    emoji = client.post(f"/api/v1/channels/{paid['id']}/estimate", json=smile, headers={H: ws}).json()
    assert (emoji["encoding"], emoji["segments"], emoji["estimated_cost"]) == ("ucs2", 1, "0.007900")
    assert client.post(f"/api/v1/channels/{paid['id']}/estimate", json={"body": "x" * 10001},
                       headers={H: ws}).status_code == 422


def test_a_disabled_channel_no_longer_takes_webhooks_and_a_wrong_provider_path_is_unknown(crm):
    client, ws, _ = crm
    channel = add_channel(client, ws, "twilio")
    assert sms_in(anonymous, channel, "+14155550123", "hello").status_code == 200
    client.patch(f"/api/v1/channels/{channel['id']}", json={"status": "disabled"}, headers={H: ws})
    assert sms_in(anonymous, channel, "+14155550123", "again").status_code == 404
    wrong = {**channel, "provider": "telnyx"}
    assert anonymous.post(path_of(wrong), content=b"{}").status_code == 404
    assert anonymous.post(f"/api/hooks/nope/{channel['id']}", content=b"{}").status_code == 404
    assert anonymous.post(f"/api/hooks/twilio/{uuid.uuid4()}", content=b"{}").status_code == 404
    assert anonymous.get(path_of(channel)).status_code == 404  # only Meta has a GET handshake


def test_no_secret_comes_back_from_any_response_of_a_full_lifecycle(crm, db, receiver, monkeypatch):
    """Creates, tests, receives, replies and lists, and looks for every secret in every response body."""
    client, ws, _ = crm
    twilio = add_channel(client, ws, "twilio")
    meta = add_channel(client, ws, "meta")
    monkeypatch.setitem(gateway.BASE_URLS, "twilio", receiver.url(""))
    receiver.default = (200, b'{"sid": "SMOUT"}', {})
    bodies = [client.post(f"/api/v1/channels/{twilio['id']}/test", headers={H: ws}).text,
              client.patch(f"/api/v1/channels/{twilio['id']}", json={"name": "x"}, headers={H: ws}).text,
              client.get("/api/v1/channels", headers={H: ws}).text,
              sms_in(anonymous, twilio, "+14155550123", "hello").text]
    page = conversations_of(client, ws)
    conv = page["data"][0]["id"]
    bodies += [json.dumps(page), client.get(f"/api/v1/conversations/{conv}", headers={H: ws}).text,
               client.post(f"/api/v1/conversations/{conv}/messages", json={"body": "hi"}, headers={H: ws}).text,
               meta_hook(anonymous, meta, meta_in("15551230000", "hola")).text]
    drain()
    bodies.append(client.get(f"/api/v1/conversations/{conv}", headers={H: ws}).text)
    assert not [b for b in bodies if any(secret in b for secret in SECRETS)]
    db.rollback()
    assert not [t for t in ("messages", "events", "jobs") if any(
        s in "".join(db.scalars(text(f"SELECT t::text FROM {t} t")).all()) for s in SECRETS)]
