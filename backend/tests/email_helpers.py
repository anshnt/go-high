"""Helpers for the email marketing tests (module 20): a workspace with a Mailgun channel pointed at a local receiver, a
sending domain whose DNS records are published in a fake DNS, contacts, and campaigns through the API."""
import json
import urllib.parse
from email import message_from_bytes, policy

import pytest
from helpers import H, drain, make_record
from inbox_helpers import add_channel

from app.inbox import gateway
from app.marketing import dnscheck

DOMAIN = "mg.example.com"
DOC = {"version": 1, "blocks": [
    {"type": "heading", "text": "Hello {{first_name|there}}"},
    {"type": "text", "text": "Our autumn update is here, with everything we shipped this month and what comes next "
                             "for your team. [Read the notes](https://example.com/notes)."},
    {"type": "button", "label": "See what is new", "url": "https://example.com/new"}]}


class FakeDns:
    """Answers TXT lookups from `records` (name to strings); `down` makes every lookup time out."""

    def __init__(self):
        self.records: dict[str, list[str]] = {}
        self.down = False

    def txt(self, name: str) -> list[str]:
        if self.down:
            raise dnscheck.Unreachable(f"DNS did not answer for {name}: Timeout")
        return list(self.records.get(name.lower(), []))

    def publish(self, domain: dict) -> None:
        """Publishes what the domain's screen asks for (with Mailgun's include, a real DKIM key in provider mode)."""
        for r in domain["records"]:
            value = r["value"].replace("<your provider>", "mailgun.org")
            if "DKIM" in r["purpose"] and "p=" not in value:
                value = "v=DKIM1; k=rsa; p=MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQC"
            self.records.setdefault(r["host"].lower(), []).append(value)


@pytest.fixture
def fake_dns(monkeypatch):
    dns = FakeDns()
    monkeypatch.setattr(dnscheck, "txt", dns.txt)
    return dns


class Mailgun:
    """The local stand-in for Mailgun's API: every send is recorded and answered with an id of its own."""

    def __init__(self, receiver, monkeypatch):
        self.receiver = receiver
        monkeypatch.setitem(gateway.BASE_URLS, "mailgun", receiver.url(""))
        receiver.default = (200, b'{"id": "<queued@mg.example.com>", "message": "Queued"}', {})

    def sent(self) -> list[dict]:
        """The form of each accepted send, as a dict (headers as `h:Name`)."""
        out = []
        for r in self.receiver.requests:
            if r["path"].endswith("/messages"):
                out.append(form_of(r))
        return out

    def to(self) -> list[str]:
        return [m["to"] for m in self.sent()]


def form_of(request: dict) -> dict:
    ctype = request["headers"].get("content-type", "")
    if ctype.startswith("multipart/"):
        msg = message_from_bytes(b"Content-Type: " + ctype.encode() + b"\r\n\r\n" + request["body"],
                                 policy=policy.default)
        return {p.get_param("name", header="content-disposition"): p.get_content() for p in msg.iter_parts()}
    return dict(urllib.parse.parse_qsl(request["body"].decode()))


class Email:
    """A workspace ready to send campaigns: `client`, `ws`, the Mailgun `channel`, the verified `domain`."""

    def __init__(self, client, ws, ids, dns, mailgun):
        self.client, self.ws, self.ids, self.dns, self.mailgun = client, ws, ids, dns, mailgun
        self.channel = add_channel(client, ws, "mailgun")
        self.domain = self.add_domain(DOMAIN, dkim_mode="provider", dkim_selector="mx", spf_include="mailgun.org")
        dns.publish(self.domain)
        # past its warm-up, so a test sends at once; the throttle tests set their own limits
        self.patch(f"/api/v1/email/domains/{self.domain['id']}", {"hourly_limit": 1_000_000})
        self.domain = self.post(f"/api/v1/email/domains/{self.domain['id']}/check", status=200)
        assert self.domain["status"] == "verified", self.domain["checks"]
        self.put("/api/v1/email/settings", {"company_name": "Acme", "postal_address": "1 Main St, Springfield",
                                            "track_opens": True, "track_clicks": True})

    def h(self) -> dict:
        return {H: self.ws}

    def post(self, path: str, body: dict | None = None, status: int = 201, **kw) -> dict:
        r = self.client.post(path, json=body, headers=self.h(), **kw)
        assert r.status_code == status, r.text
        return r.json()

    def put(self, path: str, body: dict, status: int = 200) -> dict:
        r = self.client.put(path, json=body, headers=self.h())
        assert r.status_code == status, r.text
        return r.json()

    def patch(self, path: str, body: dict, status: int = 200) -> dict:
        r = self.client.patch(path, json=body, headers=self.h())
        assert r.status_code == status, r.text
        return r.json()

    def get(self, path: str, expect: int = 200, **params) -> dict:
        r = self.client.get(path, params=params, headers=self.h())
        assert r.status_code == expect, r.text
        return r.json()

    def add_domain(self, domain: str, **body) -> dict:
        return self.post("/api/v1/email/domains", {"domain": domain, **body})

    def contacts(self, n: int, prefix: str = "person", **values) -> list[dict]:
        return [make_record(self.client, self.ws, first_name=f"{prefix.title()}{i}", email=f"{prefix}{i}@example.net",
                            **values) for i in range(n)]

    def campaign(self, audience: dict | None = None, **patch) -> dict:
        made = self.post("/api/v1/email/campaigns", {"name": "Autumn update"})
        body = {"subject": "Autumn update for {{first_name|you}}", "preheader": "What shipped this month",
                "document": DOC, "audience": audience or {"all": True}, "from_email": f"news@{DOMAIN}",
                "from_name": "Acme", "channel_id": self.channel["id"], **patch}
        return self.patch(f"/api/v1/email/campaigns/{made['id']}", body)

    def schedule(self, campaign: dict, status: int = 200, **body) -> dict:
        return self.post(f"/api/v1/email/campaigns/{campaign['id']}/schedule", body, status=status)

    def send(self, campaign: dict, **body) -> dict:
        """Schedules for now and runs the worker until it is idle."""
        self.schedule(campaign, **body)
        drain(limit=2000)
        return self.get(f"/api/v1/email/campaigns/{campaign['id']}")

    def report(self, campaign: dict) -> dict:
        return self.get(f"/api/v1/email/campaigns/{campaign['id']}/report")


@pytest.fixture(name="email")
def email_fixture(crm, fake_dns, receiver, monkeypatch):
    client, ws, ids = crm
    return Email(client, ws, ids, fake_dns, Mailgun(receiver, monkeypatch))


def html_links(html: str) -> list[str]:
    import re
    return re.findall(r'href="([^"]+)"', html)


def jsonish(value) -> str:
    return json.dumps(value, default=str)
