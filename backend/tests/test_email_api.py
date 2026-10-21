"""The email marketing API (module 20): templates and the render preview, sending domains with live DNS checks,
settings, topics, the suppression list, campaign drafts and the pre-send check, and who may do what."""
from helpers import H, add_member
from sqlalchemy import text

from app.marketing import dnscheck

T, D, C = "/api/v1/email/templates", "/api/v1/email/domains", "/api/v1/email/campaigns"


# --- templates ------------------------------------------------------------------------------------------------

def test_templates_are_saved_checked_listed_duplicated_and_archived(email):
    made = email.post(T, {"name": "Welcome"})
    assert made["document"]["blocks"][0]["type"] == "heading" and made["blocks"] == 3  # a working starter
    saved = email.patch(f"{T}/{made['id']}", {"subject": "Welcome {{first_name|aboard}}", "document": {"blocks": [
        {"type": "text", "text": "Hi {{first_name}}, [start here](https://example.com/start)"}]}})
    assert saved["subject"] == "Welcome {{first_name|aboard}}" and saved["document"]["version"] == 1
    r = email.client.patch(f"{T}/{made['id']}", headers=email.h(), json={"subject": "Hi {{nickname}}"})
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"subject": "unknown merge field {{nickname}}"}
    r = email.client.patch(f"{T}/{made['id']}", headers=email.h(), json={"document": {"blocks": [
        {"type": "button", "label": "Go", "url": "javascript:alert(1)"}]}})
    assert r.status_code == 422 and "document.blocks.0.url" in r.json()["error"]["fields"]
    copy = email.post(f"{T}/{made['id']}/duplicate")
    assert copy["name"] == "Welcome (copy)" and copy["document"] == saved["document"]
    listed = email.get(T)["data"]
    assert [t["name"] for t in listed] == ["Welcome (copy)", "Welcome"] and "document" not in listed[0]
    assert [t["name"] for t in email.get(T, q="copy")["data"]] == ["Welcome (copy)"]
    email.patch(f"{T}/{copy['id']}", {"archived": True})
    assert [t["name"] for t in email.get(T)["data"]] == ["Welcome"]
    assert [t["name"] for t in email.get(T, archived="true")["data"]] == ["Welcome (copy)"]


def test_the_render_preview_is_the_real_renderer_with_a_sample_contacts_values(email):
    ada = email.contacts(1, "ada")[0]
    body = {"subject": "For {{first_name}}", "preheader": "p", "contact_id": ada["id"], "document": {"blocks": [
        {"type": "heading", "text": "Hi {{first_name|there}}"},
        {"type": "image", "src": "https://example.com/a.png"},
        {"type": "text", "text": "FREE MONEY, act now: [paypal.com](https://evil.test/x) {{nickname}}"}]}}
    out = email.post("/api/v1/email/render", body, status=200)
    assert out["subject"] == "For Ada0" and "Hi Ada0" in out["html"] and "Hi Ada0" in out["text"]
    assert out["size"] == len(out["html"].encode()) and "Acme" in out["html"]  # the workspace's footer
    codes = {i["code"] for i in out["issues"]}
    assert {"spam_words", "missing_alt", "mismatched_link"} <= codes
    assert out["merge_errors"] == {"document.blocks.2.text": "unknown merge field {{nickname}}"}
    fields = {f["key"] for f in email.get("/api/v1/email/merge-fields")["data"]}
    assert {"first_name", "email", "display_name", "unsubscribe_url"} <= fields


# --- domains --------------------------------------------------------------------------------------------------

def test_a_managed_domain_gets_its_own_dkim_key_and_the_records_to_publish(email, db):
    d = email.add_domain("News.Example.ORG")
    assert d["domain"] == "news.example.org" and d["dkim_mode"] == "managed" and d["dkim_selector"] == "gh1"
    assert d["status"] == "pending" and d["limits"]["stage"] == "not_verified"
    records = {r["host"]: r for r in d["records"]}
    assert records["news.example.org"]["value"] == "v=spf1 include:<your provider> ~all"
    assert records["gh1._domainkey.news.example.org"]["value"].startswith("v=DKIM1; k=rsa; p=MII")
    assert records["_dmarc.news.example.org"]["value"].startswith("v=DMARC1; p=quarantine")
    # the private key is a vault secret, which the API role cannot read
    ref = db.execute(text("SELECT dkim_secret_ref FROM email_domains WHERE domain = 'news.example.org'")).scalar()
    assert ref and "PRIVATE KEY" not in str(d)
    checked = email.post(f"{D}/{d['id']}/check", status=200)
    assert checked["status"] == "failing" and checked["checks"]["dkim"]["status"] == "fail"
    assert "No DKIM key at gh1._domainkey.news.example.org" in checked["checks"]["dkim"]["message"]
    email.dns.publish(checked)
    verified = email.post(f"{D}/{d['id']}/check", status=200)
    assert verified["status"] == "verified" and verified["verified_at"] and verified["warmup_started_at"]
    assert verified["limits"]["stage"] == "warming" and verified["limits"]["day"] == 1
    assert [s["daily"] for s in verified["limits"]["schedule"]][:3] == [200, 500, 1000]


def test_domain_validation_conflicts_and_provider_mode(email):
    for bad in ("localhost", "203.0.113.9", "no spaces.com", "-bad.com", "x" * 260 + ".com"):
        r = email.client.post(D, json={"domain": bad}, headers=email.h())
        assert r.status_code == 422, bad
    r = email.client.post(D, json={"domain": "mg.example.com"}, headers=email.h())
    assert r.status_code == 409
    r = email.client.post(D, json={"domain": "ses.example.com", "dkim_mode": "provider"}, headers=email.h())
    assert r.status_code == 422 and "dkim_selector" in r.json()["error"]["fields"]
    p = email.add_domain("ses.example.com", dkim_mode="provider", dkim_selector="abc123", spf_include="amazonses.com")
    records = {r["host"]: r for r in p["records"]}
    assert records["abc123._domainkey.ses.example.com"]["value"] == "the DKIM record your provider gives you"
    assert records["ses.example.com"]["value"] == "v=spf1 include:amazonses.com ~all"
    r = email.client.patch(f"{D}/{email.add_domain('m.example.com')['id']}", json={"dkim_selector": "x1"},
                           headers=email.h())
    assert r.status_code == 422  # a managed key keeps its selector


def test_a_dns_that_does_not_answer_says_so(email):
    d = email.add_domain("down.example.com")
    email.dns.down = True
    checked = email.post(f"{D}/{d['id']}/check", status=200)
    assert checked["status"] == "failing"
    assert {checked["checks"][k]["status"] for k in ("spf", "dkim", "dmarc")} == {"error"}
    assert "did not answer" in checked["checks"]["spf"]["message"]


def test_a_domain_in_use_cannot_be_deleted(email):
    email.contacts(1)
    email.send(email.campaign())
    r = email.client.delete(f"{D}/{email.domain['id']}", headers=email.h())
    assert r.status_code == 409 and r.json()["error"]["code"] == "domain_in_use"
    spare = email.add_domain("spare.example.com")
    assert email.client.delete(f"{D}/{spare['id']}", headers=email.h()).status_code == 204


def test_domain_stats_show_the_last_hour_and_day(email):
    email.contacts(2)
    email.send(email.campaign())
    d = email.get(f"{D}/{email.domain['id']}")
    assert d["sent"] == {"last_hour": 2, "last_day": 2}


# --- settings, topics, suppressions ---------------------------------------------------------------------------

def test_settings_and_topics(email, db):
    assert email.get("/api/v1/email/settings")["company_name"] == "Acme"
    saved = email.put("/api/v1/email/settings", {"company_name": "Acme Inc", "postal_address": "2 Side St",
                                                 "track_opens": False, "track_clicks": True})
    assert saved["track_opens"] is False
    events = db.execute(text("SELECT data FROM events WHERE type = 'email_settings.updated' ORDER BY id")).all()
    assert events[-1][0]["changes"]["track_opens"] == {"old": True, "new": False}
    news = email.post("/api/v1/email/topics", {"name": "Newsletter"})
    r = email.client.post("/api/v1/email/topics", json={"name": "newsletter"}, headers=email.h())
    assert r.status_code == 409
    email.patch(f"/api/v1/email/topics/{news['id']}", {"description": "Monthly", "archived": True})
    assert email.get("/api/v1/email/topics")["data"] == []
    assert email.get("/api/v1/email/topics", archived="true")["data"][0]["description"] == "Monthly"


def test_tracking_switched_off_leaves_links_and_pixel_out(email):
    email.put("/api/v1/email/settings", {"company_name": "Acme", "postal_address": "1 Main St", "track_opens": False,
                                         "track_clicks": False})
    email.contacts(1)
    email.send(email.campaign())
    html = email.mailgun.sent()[0]["html"]
    assert "/api/public/email/o/" not in html and "/api/public/email/c/" not in html
    assert 'href="https://example.com/notes"' in html and "/api/public/email/u/" in html  # unsubscribe always


def test_the_suppression_list(email):
    added = email.post("/api/v1/email/suppressions", {"email": "Someone <ME@Example.NET>", "detail": "by phone"})
    assert added["email"] == "me@example.net" and added["reason"] == "manual" and added["removable"]
    r = email.client.post("/api/v1/email/suppressions", json={"email": "me@example.net"}, headers=email.h())
    assert r.status_code == 409
    r = email.client.post("/api/v1/email/suppressions", json={"email": "not an address"}, headers=email.h())
    assert r.status_code == 422
    page = email.get("/api/v1/email/suppressions", q="me@", reason="manual")
    assert [s["email"] for s in page["data"]] == ["me@example.net"] and page["counts"] == {"manual": 1}
    assert email.client.delete(f"/api/v1/email/suppressions/{added['id']}", headers=email.h()).status_code == 204
    assert email.get("/api/v1/email/suppressions")["data"] == []


# --- campaigns and the check ----------------------------------------------------------------------------------

def test_a_new_campaign_starts_from_a_template_with_the_channel_and_domain_filled_in(email):
    t = email.post(T, {"name": "Monthly", "subject": "This month"})
    made = email.post(C, {"name": "October", "template_id": t["id"]})
    assert made["status"] == "draft" and made["subject"] == "This month" and made["template_id"] == t["id"]
    assert made["channel_id"] == email.channel["id"] and made["from_email"] == "hello@mg.example.com"
    assert made["from_name"] == "Acme" and made["ab"]["enabled"] is False


def test_a_campaign_draft_is_validated_field_by_field(email):
    campaign = email.campaign()
    bad = {"from_email": ("news@other.example.com", "from_email"), "reply_to": ("nope", "reply_to"),
           "channel_id": ("00000000-0000-0000-0000-000000000000", "channel_id"),
           "topic_id": ("00000000-0000-0000-0000-000000000000", "topic_id"),
           "audience": ({"view_id": "00000000-0000-0000-0000-000000000000"}, "audience.view_id")}
    for key, (value, field) in bad.items():
        r = email.client.patch(f"{C}/{campaign['id']}", json={key: value}, headers=email.h())
        assert r.status_code == 422 and field in r.json()["error"]["fields"], (key, r.text)
    r = email.client.patch(f"{C}/{campaign['id']}", json={"audience": {"filter": {"field": "nope", "op": "is",
                                                                                  "value": 1}}}, headers=email.h())
    assert r.status_code == 400 and "audience.filter.field" in r.json()["error"]["fields"]
    sms = email.post("/api/v1/channels", {"kind": "sms", "provider": "twilio", "name": "Line",
                                          "address": "+15550001111", "config": {"account_sid": "AC" + "a" * 32},
                                          "secrets": {"auth_token": "test-token-not-real"}})
    r = email.client.patch(f"{C}/{campaign['id']}", json={"channel_id": sms["id"]}, headers=email.h())
    assert r.status_code == 422


def test_the_check_names_every_problem_and_blocks_on_errors(email, db):
    email.contacts(1)
    unverified = email.add_domain("cold.example.com")
    campaign = email.campaign(from_email="news@cold.example.com", subject="FREE!!! Act now", document={"blocks": [
        {"type": "image", "src": "https://example.com/big.png"}]})
    email.put("/api/v1/email/settings", {"company_name": "Acme", "postal_address": "", "track_opens": True,
                                         "track_clicks": True})
    check = email.post(f"{C}/{campaign['id']}/check", status=200)
    codes = {i["code"]: i for i in check["issues"]}
    assert check["ok"] is False
    assert codes["spf_unchecked"]["level"] == "error" and "cold.example.com" in codes["spf_unchecked"]["message"]
    assert {"image_only", "missing_alt", "spam_words", "subject_punctuation", "no_address"} <= codes.keys()
    assert check["audience"]["recipients"] == 1 and check["estimate"]["recipients"] == 1
    r = email.client.post(f"{C}/{campaign['id']}/schedule", json={}, headers=email.h())
    assert r.status_code == 422 and "has not been checked yet" in r.json()["error"]["message"]
    assert email.get(f"{C}/{campaign['id']}")["status"] == "draft"
    email.post(f"{D}/{unverified['id']}/check", status=200)
    failing = {i["code"] for i in email.post(f"{C}/{campaign['id']}/check", status=200)["issues"]}
    assert {"spf_failing", "dkim_failing", "dmarc_failing"} <= failing
    channel = email.client.patch(f"/api/v1/channels/{email.channel['id']}", json={"status": "disabled"},
                                 headers=email.h())
    assert channel.status_code == 200
    assert "channel_disabled" in {i["code"] for i in email.post(f"{C}/{campaign['id']}/check", status=200)["issues"]}


def test_a_clean_campaign_passes_with_only_information(email):
    email.contacts(2)
    campaign = email.campaign()
    check = email.post(f"{C}/{campaign['id']}/check", status=200)
    assert check["ok"] is True
    assert {i["level"] for i in check["issues"]} <= {"info"}, check["issues"]


def test_mailgun_on_another_domain_is_a_warning(email):
    other = email.add_domain("brand.example.org", dkim_mode="provider", dkim_selector="mx", spf_include="mailgun.org")
    email.dns.publish(other)
    email.post(f"{D}/{other['id']}/check", status=200)
    email.contacts(1)
    campaign = email.campaign(from_email="hi@brand.example.org")
    codes = {i["code"] for i in email.post(f"{C}/{campaign['id']}/check", status=200)["issues"]}
    assert "provider_domain" in codes


def test_drafts_can_be_deleted_and_lists_filter(email):
    a = email.campaign()
    email.patch(f"{C}/{a['id']}", {"name": "Spring sale"})
    b = email.post(C, {"name": "Autumn"})
    assert [c["name"] for c in email.get(C, q="spring")["data"]] == ["Spring sale"]
    assert len(email.get(C, status="draft")["data"]) == 2
    assert email.client.delete(f"{C}/{b['id']}", headers=email.h()).status_code == 204
    assert email.client.get(f"{C}/{b['id']}", headers=email.h()).status_code == 404


# --- who may do what ------------------------------------------------------------------------------------------

def test_capabilities_viewer_reads_member_drafts_manager_sends(email, db):
    org = email.ids["org_id"]
    viewer = add_member(db, org, "v@example.com", workspace_id=email.ws, workspace_role="viewer")
    member = add_member(db, org, "m@example.com", workspace_id=email.ws, workspace_role="member")
    manager = add_member(db, org, "g@example.com", workspace_id=email.ws, workspace_role="manager")
    email.contacts(1)
    campaign = email.campaign()
    h = {H: email.ws}
    assert viewer.get(C, headers=h).status_code == 200
    assert viewer.get(f"{C}/{campaign['id']}/report", headers=h).status_code == 200
    r = viewer.post(C, json={"name": "x"}, headers=h)
    assert r.status_code == 403 and "marketing.write" in r.json()["error"]["message"]
    assert member.post(C, json={"name": "x"}, headers=h).status_code == 201
    r = member.post(f"{C}/{campaign['id']}/schedule", json={}, headers=h)
    assert r.status_code == 403 and "marketing.send" in r.json()["error"]["message"]
    r = member.post(D, json={"domain": "x.example.com"}, headers=h)
    assert r.status_code == 403 and "marketing.manage" in r.json()["error"]["message"]
    assert member.post("/api/v1/email/suppressions", json={"email": "a@b.co"}, headers=h).status_code == 403
    assert manager.post(f"{C}/{campaign['id']}/schedule", json={}, headers=h).status_code == 200
    automation = db.execute(text("SELECT capabilities FROM roles WHERE org_id = :o AND key = 'automation'"),
                            {"o": org}).scalar()
    assert not [c for c in automation if c.startswith("marketing.")]


def test_recipients_list_only_contacts_in_scope_and_hides_hidden_emails(email, db):
    people = email.contacts(2)
    campaign = email.campaign()
    email.send(campaign)
    member = add_member(db, email.ids["org_id"], "m@example.com", workspace_id=email.ws, workspace_role="member")
    me = member.get("/api/me").json()["user"]["id"]
    role = email.post("/api/v1/roles", {"name": "Narrow", "copy_from": "member"})
    email.patch(f"/api/v1/roles/{role['id']}", {"object_rules": [
        {"object_key": "*", "scope": "own", "hidden_fields": ["email"], "readonly_fields": []}]})
    email.put(f"/api/v1/members/{me}", {"role_id": role["id"]})
    email.client.patch(f"/api/v1/objects/contact/records/{people[0]['id']}", json={"owner_id": me},
                       headers=email.h())
    seen = member.get(f"{C}/{campaign['id']}/recipients", headers={H: email.ws}).json()["data"]
    assert [r["contact_id"] for r in seen] == [people[0]["id"]] and seen[0]["email"] is None
    assert "person" not in member.get("/api/v1/email/suppressions", headers={H: email.ws}).text
    assert dnscheck  # the fixture's fake DNS stands in for it
