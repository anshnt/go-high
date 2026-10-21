"""After a campaign email leaves (module 20): opens and clicks with machines filtered out, click redirects that only
go where the campaign links, RFC 8058 one-click unsubscribe and the preference page, signed tokens that cannot be
forged or moved across workspaces, and the provider's delivery, bounce and complaint reports."""
import re
import uuid
from datetime import UTC, datetime, timedelta

from email_helpers import Email, Mailgun
from fastapi.testclient import TestClient
from helpers import H, drain
from inbox_helpers import mailgun_event
from sqlalchemy import text

from app import config
from app.main import app
from app.marketing import public, tokens

PERSON = "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0"
visitor = TestClient(app, follow_redirects=False)  # a mail client: no session, no cookies


def sent_campaign(email, n: int = 2, **patch) -> tuple[dict, list[dict]]:
    email.contacts(n)
    campaign = email.campaign(**patch)
    email.send(campaign)
    return campaign, email.mailgun.sent()


def links_of(message: dict) -> dict[str, str]:
    """The tracked links of a sent email by kind: open, unsubscribe, preferences and each click."""
    html = message["html"]
    return {"open": re.search(r'src="([^"]+/o/[^"]+)"', html).group(1),
            "unsubscribe": message["h:List-Unsubscribe"].strip("<>"),
            "clicks": re.findall(r'href="([^"]+/api/public/email/c/[^"]+)"', html)}


def path(url: str) -> str:
    return url.split("://", 1)[1].split("/", 1)[1].join(["/", ""])


def age(db, seconds: int = 3600) -> None:
    """Pretends the emails went out a while ago (clicks seconds after sending are a scanner's)."""
    db.execute(text("UPDATE email_sends SET sent_at = now() - make_interval(secs => :s)"), {"s": seconds})
    db.commit()


def send_row(db, email_address: str) -> tuple:
    db.rollback()
    return db.execute(text("SELECT status, opens, clicks, opened_at, clicked_at, unsubscribed_at FROM email_sends "
                           "WHERE email = :e"), {"e": email_address}).one()


def test_the_open_pixel_counts_people_and_not_privacy_proxies_or_bots(email, db):
    campaign, sent = sent_campaign(email)
    age(db)
    by_to = {m["to"]: links_of(m) for m in sent}
    pixel = path(by_to["person0@example.net"]["open"])
    r = visitor.get(pixel, headers={"User-Agent": "Mozilla/5.0"})  # Apple Mail Privacy Protection
    assert r.status_code == 200 and r.headers["content-type"] == "image/gif" and r.content.startswith(b"GIF89a")
    assert "no-store" in r.headers["cache-control"]
    assert send_row(db, "person0@example.net")[1:4] == (1, 0, None)
    visitor.get(pixel, headers={"User-Agent": "Googlebot/2.1"})
    assert send_row(db, "person0@example.net")[3] is None
    visitor.get(pixel, headers={"User-Agent": PERSON})
    visitor.get(pixel, headers={"User-Agent": PERSON})
    row = send_row(db, "person0@example.net")
    assert row[1] == 4 and row[3] is not None
    report = email.report(campaign)
    assert report["totals"]["opened"] == 1 and report["totals"]["machine_opens"] == 2
    assert report["rates"]["open"] == 0.5
    opened = db.execute(text("SELECT count(*) FROM events WHERE type = 'email.opened'")).scalar()
    assert opened == 1  # the first open by a person, once
    # a forged or garbled pixel still answers with an image and counts nothing
    assert visitor.get("/api/public/email/o/" + "A" * 47 + ".gif").content.startswith(b"GIF89a")
    assert send_row(db, "person1@example.net")[1] == 0


def test_a_privacy_proxy_open_is_reported_apart_and_a_click_counts_as_an_open(email, db):
    campaign, sent = sent_campaign(email, 1)
    age(db)
    links = links_of(sent[0])
    visitor.get(path(links["open"]), headers={"User-Agent": "Mozilla/5.0"})
    assert email.report(campaign)["totals"]["privacy_proxy_only"] == 1
    visitor.get(path(links["clicks"][0]), headers={"User-Agent": PERSON})
    totals = email.report(campaign)["totals"]
    assert totals["opened"] == 1 and totals["clicked"] == 1 and totals["privacy_proxy_only"] == 0


def test_clicks_redirect_only_to_the_campaigns_own_links_and_scanners_are_filtered(email, db):
    campaign, sent = sent_campaign(email, 1)
    links = links_of(sent[0])
    assert len(links["clicks"]) == 2  # the notes link and the button
    first = path(links["clicks"][0])
    r = visitor.get(first, headers={"User-Agent": PERSON})  # seconds after sending: a scanner, still redirected
    assert r.status_code == 302 and r.headers["location"] == "https://example.com/notes"
    assert send_row(db, "person0@example.net")[4] is None
    age(db)
    r = visitor.head(first, headers={"User-Agent": PERSON})
    assert r.status_code == 302 and send_row(db, "person0@example.net")[2] == 1  # HEAD is not even logged
    visitor.get(first, headers={"User-Agent": "Mimecast URL protect"})
    assert send_row(db, "person0@example.net")[4] is None
    r = visitor.get(first, headers={"User-Agent": PERSON})
    assert r.headers["location"] == "https://example.com/notes" and send_row(db, "person0@example.net")[4]
    r = visitor.get(path(links["clicks"][1]), headers={"User-Agent": PERSON})
    assert r.headers["location"] == "https://example.com/new"
    report = email.report(campaign)
    assert report["totals"]["clicked"] == 1 and report["totals"]["machine_clicks"] == 2
    by_url = {link["url"]: link for link in report["links"]}
    assert by_url["https://example.com/notes"]["clicks"] == 1 and by_url["https://example.com/notes"]["people"] == 1
    assert by_url["https://example.com/notes"]["machine_clicks"] == 2
    assert db.execute(text("SELECT count(*) FROM events WHERE type = 'email.clicked'")).scalar() == 1


def test_a_scanner_that_opens_every_link_at_once_is_a_machine(email, db):
    email.patch(f"/api/v1/email/campaigns/{email.campaign()['id']}", {"name": "unused"})
    campaign, sent = sent_campaign(email, 1, document={"blocks": [
        {"type": "text", "text": "Three links: [one](https://example.com/1) [two](https://example.com/2) "
                                 "[three](https://example.com/3), and words enough to read as a real email."}]})
    age(db)
    for url in links_of(sent[0])["clicks"]:
        visitor.get(path(url), headers={"User-Agent": PERSON})
    machine = db.execute(text("SELECT link_idx, machine, detail FROM email_events WHERE type = 'click' "
                              "ORDER BY id")).all()
    assert [m[1] for m in machine] == [False, False, True] and machine[2][2] == "burst"


def test_a_click_token_cannot_be_turned_into_an_open_redirect(email, db):
    campaign, sent = sent_campaign(email, 1)
    good = links_of(sent[0])["clicks"][0].rsplit("/", 1)[1]
    found = tokens.read(good, "click")
    for forged in (tokens.make("click", found.send_id, 99),  # a link number the campaign does not have
                   tokens.make("open", found.send_id, 0), good[:-2] + "AA", "x" * 30):
        r = visitor.get(f"/api/public/email/c/{forged}?url=https://evil.test", headers={"User-Agent": PERSON})
        assert r.status_code == 404 and "evil.test" not in r.headers.get("location", ""), forged
        assert "This link is not valid" in r.text
    r = visitor.get(f"/api/public/email/c/{good}?url=https://evil.test&u=https://evil.test")
    assert r.headers["location"] == "https://example.com/notes"  # the query is never read


def test_rfc_8058_one_click_unsubscribe(email, db, monkeypatch):
    campaign, sent = sent_campaign(email, 2)
    url = path(links_of(sent[0])["unsubscribe"])
    who = sent[0]["to"]
    r = visitor.post(url, content=b"List-Unsubscribe=One-Click",
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert r.status_code == 200 and "unsubscribed" in r.text.lower()
    assert send_row(db, who)[5] is not None
    contact = db.execute(text("SELECT id FROM records WHERE email_norm = :e"), {"e": who}).scalar()
    consent = db.execute(text("SELECT status, source FROM consents WHERE contact_id = :c AND kind = 'email'"),
                         {"c": contact}).one()
    assert tuple(consent) == ("opted_out", "unsubscribe")
    assert db.execute(text("SELECT reason FROM email_suppressions WHERE email = :e"), {"e": who}).scalar() == \
        "unsubscribe"
    # again, as mail clients sometimes do: nothing more happens
    visitor.post(url, content=b"List-Unsubscribe=One-Click",
                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert db.execute(text("SELECT count(*) FROM events WHERE type = 'email.unsubscribed'")).scalar() == 1
    assert email.report(campaign)["totals"]["unsubscribed"] == 1
    # multipart bodies are accepted too (RFC 8058 allows either)
    other = path(links_of(sent[1])["unsubscribe"])
    r = visitor.post(other, files={"List-Unsubscribe": (None, "One-Click")})
    assert r.status_code == 200 and send_row(db, sent[1]["to"])[5] is not None
    # the next campaign skips both
    second = email.campaign()
    assert email.get(f"/api/v1/email/campaigns/{second['id']}/audience")["recipients"] == 0


def test_one_click_on_a_topic_campaign_leaves_the_topic_only(email, db):
    topic = email.post("/api/v1/email/topics", {"name": "Product updates", "description": "New features"})
    campaign, sent = sent_campaign(email, 1, topic_id=topic["id"])
    visitor.post(path(links_of(sent[0])["unsubscribe"]), content=b"List-Unsubscribe=One-Click",
                 headers={"Content-Type": "application/x-www-form-urlencoded"})
    pref = db.execute(text("SELECT subscribed, source FROM email_preferences")).one()
    assert tuple(pref) == (False, "one_click")
    assert db.execute(text("SELECT count(*) FROM consents")).scalar() == 0  # other mail still reaches them
    assert db.execute(text("SELECT count(*) FROM email_suppressions")).scalar() == 0


def test_list_unsubscribe_post_is_sent_with_an_https_address(email, monkeypatch):
    monkeypatch.setattr(config, "ALLOWED_ORIGINS", ["https://app.example.com"])
    _, sent = sent_campaign(email, 1)
    assert sent[0]["h:List-Unsubscribe"].startswith("<https://app.example.com/api/public/email/u/")
    assert sent[0]["h:List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"
    assert "https://app.example.com/api/public/email/o/" in sent[0]["html"]


def test_the_preference_page_shows_topics_saves_choices_and_lets_people_come_back(email, db):
    news = email.post("/api/v1/email/topics", {"name": "Newsletter", "description": "Monthly"})
    email.post("/api/v1/email/topics", {"name": "Offers"})
    _, sent = sent_campaign(email, 1)
    url = path(links_of(sent[0])["unsubscribe"])
    page = visitor.get(url)
    assert page.status_code == 200 and "Email preferences" in page.text and "Newsletter" in page.text
    assert "default-src 'none'" in page.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
    assert page.headers["referrer-policy"] == "no-referrer" and "<script" not in page.text
    assert "Acme" in page.text and "1 Main St, Springfield" in page.text
    saved = visitor.post(url, data={"action": "save", "topic": news["id"]})
    assert "Your choices are saved" in saved.text
    prefs = db.execute(text("SELECT t.name, p.subscribed FROM email_preferences p JOIN email_topics t "
                            "ON t.id = p.topic_id")).all()
    assert [tuple(p) for p in prefs] == [("Offers", False)]
    gone = visitor.post(url, data={"action": "unsubscribe"})
    assert "unsubscribed from all marketing email" in gone.text and "Subscribe again" in gone.text
    back = visitor.post(url, data={"action": "resubscribe"})
    assert "You are subscribed again" in back.text
    assert db.execute(text("SELECT count(*) FROM email_suppressions")).scalar() == 0
    assert db.execute(text("SELECT status FROM consents WHERE kind = 'email'")).scalar() == "opted_in"
    types = [t for t, in db.execute(text("SELECT type FROM events WHERE type LIKE 'email.%' ORDER BY id"))]
    assert {"email.preferences_changed", "email.unsubscribed", "email.resubscribed"} <= set(types)
    assert visitor.post(url, data={"action": "nonsense"}).status_code == 400


def test_a_bounced_address_cannot_resubscribe_itself(email, db):
    _, sent = sent_campaign(email, 1)
    db.execute(text("INSERT INTO email_suppressions (workspace_id, email, reason) VALUES (:w, :e, 'hard_bounce')"),
               {"w": email.ws, "e": sent[0]["to"]})
    db.commit()
    url = path(links_of(sent[0])["unsubscribe"])
    assert "could not be delivered" in visitor.get(url).text
    visitor.post(url, data={"action": "resubscribe"})
    assert db.execute(text("SELECT reason FROM email_suppressions")).scalar() == "hard_bounce"


def test_tokens_are_unforgeable_and_bound_to_their_send(email, db):
    _, sent = sent_campaign(email, 2)
    mine = links_of(sent[0])["unsubscribe"].rsplit("/", 1)[1]
    found = tokens.read(mine, "unsubscribe")
    for bad in (mine[:-1] + ("A" if mine[-1] != "A" else "B"), tokens.make("click", found.send_id),
                tokens.make("unsubscribe", uuid.uuid4()), "short", "a" * 64):
        assert visitor.get(f"/api/public/email/u/{bad}").status_code in (404, 422), bad
        r = visitor.post(f"/api/public/email/u/{bad}", content=b"List-Unsubscribe=One-Click",
                         headers={"Content-Type": "application/x-www-form-urlencoded"})
        assert r.status_code in (404, 422)
    assert db.execute(text("SELECT count(*) FROM email_sends WHERE unsubscribed_at IS NOT NULL")).scalar() == 0


def test_tokens_of_one_workspace_reach_nothing_of_another(make_user, fake_dns, receiver, monkeypatch, db):
    a_client, a_ids = make_user("a@example.com")
    b_client, b_ids = make_user("b@example.com")
    mailgun = Mailgun(receiver, monkeypatch)
    a = Email(a_client, a_ids["workspace_id"], a_ids, fake_dns, mailgun)
    _, sent = sent_campaign(a, 1)
    a_send = tokens.read(links_of(sent[0])["unsubscribe"].rsplit("/", 1)[1], "unsubscribe").send_id
    receiver.requests.clear()
    fake_dns.records.clear()
    b = Email(b_client, b_ids["workspace_id"], b_ids, fake_dns, mailgun)
    b.contacts(1, "bee")
    b.send(b.campaign())
    b_mail = mailgun.sent()[-1]
    page = visitor.get(path(links_of(b_mail)["unsubscribe"]))
    assert "bee0@example.net" in page.text and "person0@example.net" not in page.text and "Acme" in page.text
    # B's page and pixel act on B's send only: A's send is untouched
    visitor.post(path(links_of(b_mail)["unsubscribe"]), data={"action": "unsubscribe"})
    assert db.execute(text("SELECT unsubscribed_at FROM email_sends WHERE id = :s"), {"s": a_send}).scalar() is None
    # B's API cannot see A's campaign, send or suppressions
    assert "person0@example.net" not in b.client.get("/api/v1/email/suppressions", headers=b.h()).text


# --- the provider's reports ------------------------------------------------------------------------------------

def mailgun_report(email, event: str, message_id: str, **more):
    return mailgun_event(TestClient(app), email.channel, event, message_id, **more)


def test_delivery_bounce_and_complaint_reports_feed_the_report_and_the_suppression_list(email, db):
    campaign, sent = sent_campaign(email, 3)
    ids = {m["to"]: m["h:Message-Id"].strip("<>") for m in sent}
    assert mailgun_report(email, "delivered", ids["person0@example.net"]).status_code == 200
    assert mailgun_report(email, "failed", ids["person1@example.net"], severity="permanent",
                          **{"delivery-status": {"code": 550, "description": "mailbox does not exist"}}
                          ).status_code == 200
    assert mailgun_report(email, "complained", ids["person2@example.net"]).status_code == 200
    assert mailgun_report(email, "delivered", ids["person1@example.net"]).status_code == 200  # late: ignored
    rows = {r[0]: r[1:] for r in db.execute(text("SELECT email, status, reason FROM email_sends ORDER BY email"))}
    assert rows["person0@example.net"][0] == "delivered"
    assert rows["person1@example.net"] == ("bounced", "550 mailbox does not exist")
    assert rows["person2@example.net"][0] == "complained"
    listed = {s["email"]: s for s in email.get("/api/v1/email/suppressions")["data"]}
    assert listed["person1@example.net"]["reason"] == "hard_bounce" and listed["person1@example.net"]["removable"]
    assert listed["person2@example.net"]["reason"] == "complaint" and not listed["person2@example.net"]["removable"]
    report = email.report(campaign)
    assert (report["totals"]["delivered"], report["totals"]["bounced"], report["totals"]["complained"]) == (1, 1, 1)
    assert report["rates"]["base"] == "delivered" and report["rates"]["complaint"] == round(1 / 3, 4)
    types = [t for t, in db.execute(text("SELECT type FROM events WHERE type IN ('email.bounced', "
                                         "'email.complained', 'consent.changed') ORDER BY id"))]
    assert types == ["email.bounced", "email.complained", "consent.changed"]
    # the complaint cannot be undone by staff; the bounce can (the address may have been fixed)
    r = email.client.delete(f"/api/v1/email/suppressions/{listed['person2@example.net']['id']}", headers=email.h())
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_removable"
    r = email.client.delete(f"/api/v1/email/suppressions/{listed['person1@example.net']['id']}", headers=email.h())
    assert r.status_code == 204


def test_a_report_from_another_channel_for_a_send_id_changes_nothing(email, db):
    campaign, sent = sent_campaign(email, 1)
    other = email.post("/api/v1/channels", {"kind": "email", "provider": "mailgun", "name": "Other",
                                            "address": "x@other.example.com", "config": {"domain": "other.example.com"},
                                            "secrets": {"api_key": "k", "signing_key": "test-signing-key-not-real"}})
    mailgun_event(TestClient(app), other, "complained", sent[0]["h:Message-Id"].strip("<>"))
    assert db.execute(text("SELECT status FROM email_sends")).scalar() == "sent"
    assert db.execute(text("SELECT count(*) FROM email_suppressions")).scalar() == 0


def test_an_inbox_email_that_bounces_is_suppressed_for_campaigns_too(email, db):
    from inbox_helpers import mailgun_in, outbound_row
    hooks = TestClient(app)
    mailgun_in(hooks, email.channel, "carol@example.net", "Question", "Hi there")
    conv = email.get("/api/v1/conversations")["data"][0]
    outbound_row(db, conv["id"], email.channel["id"], "reply-1@mg.example.com")
    mailgun_report(email, "failed", "reply-1@mg.example.com", severity="permanent")
    assert db.execute(text("SELECT email, reason FROM email_suppressions")).one() == ("carol@example.net",
                                                                                      "hard_bounce")


def test_old_tokens_keep_working_after_the_campaign_ends(email, db):
    campaign, sent = sent_campaign(email, 1)
    db.execute(text("UPDATE email_sends SET sent_at = now() - interval '400 days'"))
    db.commit()
    assert visitor.get(path(links_of(sent[0])["unsubscribe"])).status_code == 200
    assert visitor.get(path(links_of(sent[0])["clicks"][0]), headers={"User-Agent": PERSON}).status_code == 302


def test_public_routes_never_answer_with_a_server_error(email, db):
    campaign, sent = sent_campaign(email, 1)
    for url in ("/api/public/email/u/!!!", "/api/public/email/c/%00", "/api/public/email/o/x.gif",
                "/api/public/email/u/" + "A" * 200):
        assert visitor.get(url).status_code < 500, url
    r = visitor.post(path(links_of(sent[0])["unsubscribe"]), content=b"\xff\xfe garbage",
                     headers={"Content-Type": "multipart/form-data; boundary=x"})
    assert r.status_code < 500
    _ = (H, drain, datetime, UTC, timedelta, public)
