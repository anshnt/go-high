"""Sending campaigns (module 20): through the job queue, exactly once per recipient, with consent, the suppression
list and topics respected at send time, throttled per sending domain, paused, resumed and cancelled, scheduled in any
time zone, A/B tested with an automatic winner."""
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from helpers import H, add_member, drain, due_now, make_record
from sqlalchemy import text

from app import config
from app.channels.base import ChannelError
from app.db import SessionLocal
from app.inbox import gateway
from app.marketing import campaigns, sender

C = "/api/v1/email/campaigns"


def sends(db, campaign: dict) -> list[tuple]:
    db.rollback()
    return db.execute(text("SELECT email, status, reason, variant, phase FROM email_sends WHERE campaign_id = :c "
                           "ORDER BY email"), {"c": campaign["id"]}).all()


def statuses(db, campaign: dict) -> dict[str, int]:
    out: dict[str, int] = {}
    for s in sends(db, campaign):
        out[s[1]] = out.get(s[1], 0) + 1
    return out


def jobs_of(db, kind: str) -> list[tuple]:
    db.rollback()
    return db.execute(text("SELECT status, run_at FROM jobs WHERE kind = :k ORDER BY id"), {"k": kind}).all()


def run(kind: str, campaign: dict) -> None:
    """Runs one job of the campaign the way the worker would, whatever else is queued."""
    with SessionLocal() as s:
        {"start": sender.start, "batch": sender.batch}[kind](s, {"campaign_id": campaign["id"]})
        s.commit()


def batch_job(db, campaign: dict) -> None:
    db.execute(text("INSERT INTO jobs (kind, payload) VALUES ('email.campaign.batch', CAST(:p AS jsonb))"),
               {"p": f'{{"campaign_id": "{campaign["id"]}"}}'})
    db.commit()


def test_a_campaign_goes_to_every_recipient_once_through_the_queue(email, db):
    email.contacts(3)
    campaign = email.campaign()
    done = email.send(campaign)
    assert done["status"] == "sent" and done["finished_at"] and done["audience_count"] == 3
    assert sorted(email.mailgun.to()) == ["person0@example.net", "person1@example.net", "person2@example.net"]
    assert statuses(db, campaign) == {"sent": 3}
    first = email.mailgun.sent()[0]
    assert first["subject"].startswith("Autumn update for Person") and first["from"] == "Acme <news@mg.example.com>"
    assert "Unsubscribe" in first["html"] and "\nUnsubscribe: http" in first["text"]
    assert first["h:List-Unsubscribe"].startswith("<http") and "/api/public/email/u/" in first["h:List-Unsubscribe"]
    assert first["h:Feedback-ID"].endswith(":campaign:gohigh")
    assert first["h:Message-Id"].startswith("<") and "@mg.example.com>" in first["h:Message-Id"]
    report = email.report(campaign)
    assert report["totals"]["sent"] == 3 and report["totals"]["recipients"] == 3 and report["rates"]["base"] == "sent"
    # the request did not send: it only queued the start; the worker did the rest
    kinds = [k for k, in db.execute(text("SELECT DISTINCT kind FROM jobs WHERE kind LIKE 'email.%' ORDER BY 1"))]
    assert kinds == ["email.campaign.batch", "email.campaign.start"]


def test_one_send_per_address_even_with_duplicate_contacts_and_repeated_jobs(email, db):
    email.contacts(2)
    make_record(email.client, email.ws, first_name="Twin", email="PERSON0@example.net")  # the same address
    campaign = email.campaign()
    assert email.get(f"{C}/{campaign['id']}/audience")["duplicates"] == 1
    email.schedule(campaign)
    db.execute(text("INSERT INTO jobs (kind, payload) SELECT kind, payload FROM jobs WHERE kind = "
                    "'email.campaign.start'"))  # the start job twice, as a retried or duplicated job would be
    db.commit()
    drain(limit=2000)
    for _ in range(3):  # stray batch jobs find nothing left to send
        batch_job(db, campaign)
    drain(limit=2000)
    assert sorted(email.mailgun.to()) == ["person0@example.net", "person1@example.net"]
    assert email.get(f"{C}/{campaign['id']}")["audience_count"] == 2


def test_a_crash_after_the_provider_took_a_send_never_sends_it_again(email, db, monkeypatch):
    email.contacts(2)
    campaign = email.campaign()
    email.schedule(campaign)
    real = gateway.send
    calls = []

    def crash_after_accepting(channel, message):
        calls.append(message.to)
        real(channel, message)  # the provider accepted it...
        raise RuntimeError("the worker died before it could record that")  # ...and nothing was recorded

    monkeypatch.setattr(gateway, "send", crash_after_accepting)
    drain(limit=2000)
    assert statuses(db, campaign) == {"uncertain": 2}
    monkeypatch.setattr(gateway, "send", real)
    for _ in range(3):
        batch_job(db, campaign)
    drain(limit=2000)
    assert len(email.mailgun.sent()) == 2 and sorted(calls) == ["person0@example.net", "person1@example.net"]
    assert email.report(campaign)["totals"]["uncertain"] == 2


def test_a_worker_lost_mid_batch_leaves_its_claimed_sends_uncertain_not_resent(email, db):
    email.contacts(3)
    campaign = email.campaign()
    email.schedule(campaign)
    run("start", campaign)  # the audience is read, a batch is queued
    with SessionLocal() as s:  # a batch claims two sends and its worker dies before calling the provider
        claimed = sender.claim(s, campaign["id"], 2)
        s.commit()
    assert len(claimed) == 2
    db.execute(text("UPDATE email_sends SET claimed_at = now() - interval '20 minutes' WHERE status = 'sending'"))
    db.commit()
    drain(limit=2000)
    assert statuses(db, campaign) == {"uncertain": 2, "sent": 1}
    assert len(email.mailgun.sent()) == 1


def test_refusals_are_retried_with_backoff_and_a_lost_answer_is_never_retried(email, db, monkeypatch):
    email.contacts(3)
    campaign = email.campaign()
    email.schedule(campaign)
    real, tries = gateway.send, {}

    def flaky(channel, message):
        tries[message.to] = tries.get(message.to, 0) + 1
        if message.to == "person0@example.net" and tries[message.to] < 3:
            raise ChannelError("HTTP 429: slow down", retryable=True, code="429")
        if message.to == "person1@example.net":
            raise ChannelError("TimeoutError: timed out", retryable=True, ambiguous=True)
        if message.to == "person2@example.net":
            raise ChannelError("HTTP 400: invalid recipient", code="400")
        return real(channel, message)

    monkeypatch.setattr(gateway, "send", flaky)
    for _ in range(6):
        drain(limit=2000)
        db.execute(text("UPDATE email_sends SET next_attempt_at = now() WHERE status = 'queued'"))
        db.commit()
        due_now(db)
    rows = {s[0]: (s[1], s[2]) for s in sends(db, campaign)}
    assert rows["person0@example.net"][0] == "sent" and tries["person0@example.net"] == 3
    assert rows["person1@example.net"][0] == "uncertain" and tries["person1@example.net"] == 1
    assert rows["person2@example.net"] == ("failed", "HTTP 400: invalid recipient")
    assert email.get(f"{C}/{campaign['id']}")["status"] == "sent"


def test_a_refused_address_is_a_hard_bounce_that_is_suppressed_for_every_later_campaign(email, db, monkeypatch):
    email.contacts(2)
    real = gateway.send

    def refuse_one(channel, message):
        if message.to == "person1@example.net":
            raise ChannelError("SMTP 550: 5.1.1 no such user", code="550")
        return real(channel, message)

    monkeypatch.setattr(gateway, "send", refuse_one)
    first = email.send(email.campaign())
    assert {s[0]: s[1] for s in sends(db, first)} == {"person0@example.net": "sent", "person1@example.net": "bounced"}
    listed = email.get("/api/v1/email/suppressions")["data"]
    assert [(s["email"], s["reason"]) for s in listed] == [("person1@example.net", "hard_bounce")]
    second = email.campaign()
    assert email.get(f"{C}/{second['id']}/audience")["excluded"] == {"suppressed": 1}
    email.send(second)
    assert {s[0]: (s[1], s[2]) for s in sends(db, second)}["person1@example.net"] == (
        "skipped", "On the suppression list")
    types = [t for t, in db.execute(text("SELECT type FROM events WHERE type LIKE 'email.%' ORDER BY id"))]
    assert "email.bounced" in types


def test_consent_suppression_and_topics_are_respected_when_the_send_starts(email, db):
    people = email.contacts(5)
    topic = email.post("/api/v1/email/topics", {"name": "Newsletter"})
    r = email.client.put(f"/api/v1/contacts/{people[0]['id']}/consents/email", json={"dnd": True}, headers=email.h())
    assert r.status_code == 200
    email.post("/api/v1/email/suppressions", {"email": "person1@example.net", "detail": "asked by phone"})
    db.execute(text("INSERT INTO email_preferences (contact_id, topic_id, workspace_id, subscribed, source) "
                    "VALUES (:c, :t, :w, false, 'manual')"), {"c": people[2]["id"], "t": topic["id"], "w": email.ws})
    db.commit()
    campaign = email.campaign(topic_id=topic["id"])
    preview = email.get(f"{C}/{campaign['id']}/audience")
    assert preview["recipients"] == 2 and preview["excluded"] == {"suppressed": 1, "unsubscribed": 1,
                                                                  "topic_unsubscribed": 1}
    assert [p["email"] for p in preview["sample"]] == ["person3@example.net", "person4@example.net"]
    email.send(campaign)
    assert sorted(email.mailgun.to()) == ["person3@example.net", "person4@example.net"]
    reasons = {s[0]: s[2] for s in sends(db, campaign) if s[1] == "skipped"}
    assert reasons == {"person0@example.net": "Unsubscribed or do not disturb",
                       "person1@example.net": "On the suppression list",
                       "person2@example.net": "Unsubscribed from this topic"}
    assert email.report(campaign)["reasons"]["On the suppression list"] == 1


def test_someone_who_unsubscribes_or_bounces_mid_send_is_skipped(email, db, monkeypatch):
    email.contacts(4)
    monkeypatch.setattr(config, "EMAIL_BATCH_SIZE", 2)
    campaign = email.campaign()
    email.schedule(campaign)
    run("start", campaign)
    run("batch", campaign)  # the first batch of two
    sent_first = set(email.mailgun.to())
    assert len(sent_first) == 2
    rest = sorted({f"person{i}@example.net" for i in range(4)} - sent_first)
    db.execute(text("INSERT INTO email_suppressions (workspace_id, email, reason) VALUES (:w, :e, 'complaint')"),
               {"w": email.ws, "e": rest[0]})
    contact = db.execute(text("SELECT id FROM records WHERE email_norm = :e"), {"e": rest[1]}).scalar()
    db.execute(text("INSERT INTO consents (contact_id, kind, workspace_id, status, source) VALUES "
                    "(:c, 'email', :w, 'opted_out', 'unsubscribe')"), {"c": contact, "w": email.ws})
    db.commit()
    due_now(db)
    drain(limit=2000)
    assert set(email.mailgun.to()) == sent_first
    rows = {s[0]: (s[1], s[2]) for s in sends(db, campaign)}
    assert rows[rest[0]] == ("skipped", "On the suppression list (complaint)")
    assert rows[rest[1]] == ("skipped", "Unsubscribed or do not disturb")
    assert email.get(f"{C}/{campaign['id']}")["status"] == "sent"


def test_the_segment_is_read_when_the_send_starts_not_when_it_is_scheduled(email, db):
    email.contacts(1, "early")
    view = email.post("/api/v1/views", {"object": "contact", "name": "Everyone", "filter": {}, "shared": True})
    campaign = email.campaign(audience={"view_id": view["id"]})
    email.schedule(campaign, scheduled_at=(datetime.now(UTC) + timedelta(hours=2)).isoformat())
    email.contacts(1, "late")  # joins the segment after scheduling, before the send
    drain()
    assert email.mailgun.sent() == []  # not yet: the start job waits for its time
    db.execute(text("UPDATE email_campaigns SET scheduled_at = now()"))
    db.commit()
    due_now(db)
    drain(limit=2000)
    assert sorted(email.mailgun.to()) == ["early0@example.net", "late0@example.net"]


def test_the_audience_is_what_the_scheduler_may_see(email, db):
    member = add_member(db, email.ids["org_id"], "m@example.com", workspace_id=email.ws, workspace_role="manager")
    me = member.get("/api/me").json()["user"]["id"]
    own = email.post("/api/v1/roles", {"name": "Own sender", "copy_from": "manager"})
    email.patch(f"/api/v1/roles/{own['id']}", {"object_rules": [
        {"object_key": "*", "scope": "own", "hidden_fields": [], "readonly_fields": []}]})
    email.put(f"/api/v1/members/{me}", {"role_id": own["id"]})
    make_record(email.client, email.ws, owner_id=me, first_name="Mine", email="mine@example.net")
    make_record(email.client, email.ws, first_name="Theirs", email="theirs@example.net")
    made = member.post(C, json={"name": "Mine only"}, headers={H: email.ws}).json()
    r = member.patch(f"{C}/{made['id']}", headers={H: email.ws}, json={
        "subject": "Hi", "document": {"blocks": [{"type": "text", "text": "A calm update with notes for the "
                                                                         "season."}]},
        "audience": {"all": True}, "from_email": "news@mg.example.com", "channel_id": email.channel["id"]})
    assert r.status_code == 200, r.text
    assert member.get(f"{C}/{made['id']}/audience", headers={H: email.ws}).json()["recipients"] == 1
    r = member.post(f"{C}/{made['id']}/schedule", json={}, headers={H: email.ws})
    assert r.status_code == 200, r.text
    drain(limit=2000)
    assert email.mailgun.to() == ["mine@example.net"]


def test_an_empty_audience_cannot_be_scheduled_and_one_that_empties_finishes_cleanly(email, db):
    campaign = email.campaign(audience={"filter": {"field": "first_name", "op": "is", "value": "Nobody"}})
    r = email.client.post(f"{C}/{campaign['id']}/schedule", json={}, headers=email.h())
    assert r.status_code == 422 and r.json()["error"]["code"] == "check_failed"
    assert "Nobody in this audience" in r.json()["error"]["message"]
    person = email.contacts(1)[0]
    ok = email.campaign()
    email.schedule(ok)
    email.client.delete(f"/api/v1/objects/contact/records/{person['id']}", headers=email.h())  # gone before the start
    drain(limit=2000)
    done = email.get(f"{C}/{ok['id']}")
    assert done["status"] == "sent" and done["audience_count"] == 0 and email.mailgun.sent() == []


def test_throttling_is_per_sending_domain_across_campaigns(email, db):
    email.patch(f"/api/v1/email/domains/{email.domain['id']}", {"hourly_limit": 3})
    email.contacts(4, "a")
    first = email.campaign()
    second = email.campaign()
    email.schedule(first)
    email.schedule(second)
    for _ in range(12):  # every batch slot, as fast as the queue allows
        due_now(db)
        drain(limit=2000)
    assert len(email.mailgun.sent()) == 3  # the domain's hour is used up, by both campaigns together
    waiting = [j for j in jobs_of(db, "email.campaign.batch") if j[0] == "queued"]
    assert waiting and all(j[1] > datetime.now(UTC) + timedelta(minutes=50) for j in waiting)
    db.execute(text("UPDATE email_sends SET claimed_at = claimed_at - interval '61 minutes' "
                    "WHERE claimed_at IS NOT NULL"))  # an hour later the next three go
    db.commit()
    for _ in range(12):
        due_now(db)
        drain(limit=2000)
    assert len(email.mailgun.sent()) == 6
    assert email.get(f"/api/v1/email/domains/{email.domain['id']}")["sent"]["last_hour"] == 3


def test_a_warming_domain_sends_at_its_stage_pace(email, db, monkeypatch):
    email.patch(f"/api/v1/email/domains/{email.domain['id']}", {"hourly_limit": None})
    monkeypatch.setattr(config, "EMAIL_BATCH_SECONDS", 60)
    domain = email.get(f"/api/v1/email/domains/{email.domain['id']}")
    assert domain["limits"]["stage"] == "warming" and domain["limits"]["day"] == 1
    assert domain["limits"]["daily"] == 200 and domain["limits"]["hourly"] == 20
    email.contacts(3)
    campaign = email.campaign()
    check = email.post(f"{C}/{campaign['id']}/check", status=200)
    assert "warming" in {i["code"] for i in check["issues"]}
    email.schedule(campaign)
    drain(limit=2000)
    # 20 an hour is one a minute: the first batch sends one and the next waits its minute
    assert len(email.mailgun.sent()) == 1
    nxt = [j for j in jobs_of(db, "email.campaign.batch") if j[0] == "queued"]
    assert len(nxt) == 1 and nxt[0][1] > datetime.now(UTC) + timedelta(seconds=50)


def test_large_audiences_go_out_in_batches(email, db, monkeypatch):
    monkeypatch.setattr(config, "EMAIL_BATCH_SIZE", 40)
    db.execute(text(
        "INSERT INTO records (workspace_id, object_id, values, display_name, email_norm) "
        "SELECT :w, o.id, jsonb_build_object('first_name', 'P' || g, 'email', 'p' || g || '@example.net'), "
        "'P' || g, 'p' || g || '@example.net' FROM objects o, generate_series(1, 250) g "
        "WHERE o.workspace_id = :w AND o.key = 'contact'"), {"w": email.ws})
    db.commit()
    campaign = email.campaign()
    assert email.get(f"{C}/{campaign['id']}/audience")["recipients"] == 250
    email.send(campaign)
    batches = len([j for j in jobs_of(db, "email.campaign.batch") if j[0] == "done"])
    assert len(email.mailgun.sent()) == 250 and len(set(email.mailgun.to())) == 250
    assert batches >= 7  # 250 at 40 a batch
    assert email.get(f"{C}/{campaign['id']}")["status"] == "sent"


def test_pause_resume_and_cancel(email, db, monkeypatch):
    monkeypatch.setattr(config, "EMAIL_BATCH_SIZE", 2)
    email.contacts(6)
    campaign = email.campaign()
    email.schedule(campaign)
    run("start", campaign)
    run("batch", campaign)  # the first batch of two
    paused = email.post(f"{C}/{campaign['id']}/pause", status=200)
    assert paused["status"] == "paused" and paused["paused_from"] == "sending"
    due_now(db)
    drain(limit=2000)
    assert len(email.mailgun.sent()) == 2  # nothing goes while paused
    resumed = email.post(f"{C}/{campaign['id']}/resume", status=200)
    assert resumed["status"] == "sending"
    run("batch", campaign)
    assert len(email.mailgun.sent()) == 4
    cancelled = email.post(f"{C}/{campaign['id']}/cancel", status=200)
    assert cancelled["status"] == "cancelled"
    due_now(db)
    drain(limit=2000)
    assert len(email.mailgun.sent()) == 4 and statuses(db, campaign) == {"sent": 4, "cancelled": 2}
    assert email.client.post(f"{C}/{campaign['id']}/resume", headers=email.h()).status_code == 409
    totals = email.report(campaign)["totals"]
    assert (totals["sent"], totals["cancelled"]) == (4, 2)
    # a cancelled campaign is not edited or deleted; a copy is how it goes again
    assert email.client.patch(f"{C}/{campaign['id']}", json={"name": "x"}, headers=email.h()).status_code == 409
    assert email.client.delete(f"{C}/{campaign['id']}", headers=email.h()).status_code == 409
    copy = email.post(f"{C}/{campaign['id']}/duplicate")
    assert copy["status"] == "draft" and copy["subject"] == campaign["subject"]


def test_a_paused_scheduled_campaign_does_not_start_and_unschedule_returns_a_draft(email, db):
    email.contacts(1)
    campaign = email.campaign()
    email.schedule(campaign, scheduled_at=(datetime.now(UTC) + timedelta(minutes=30)).isoformat())
    email.post(f"{C}/{campaign['id']}/pause", status=200)
    db.execute(text("UPDATE email_campaigns SET scheduled_at = now()"))
    db.commit()
    due_now(db)
    drain()
    assert email.mailgun.sent() == [] and email.get(f"{C}/{campaign['id']}")["status"] == "paused"
    back = email.post(f"{C}/{campaign['id']}/unschedule", status=200)
    assert back["status"] == "draft" and back["scheduled_at"] is None
    due_now(db)
    drain()
    assert email.mailgun.sent() == []
    assert email.send(email.get(f"{C}/{campaign['id']}"))["status"] == "sent"


def test_scheduling_reads_a_local_time_in_its_zone_and_refuses_one_that_does_not_exist(email, monkeypatch):
    email.contacts(1)
    campaign = email.campaign()
    monkeypatch.setattr(campaigns, "clock", lambda: datetime(2027, 3, 1, 12, tzinfo=UTC))
    r = email.client.post(f"{C}/{campaign['id']}/schedule", headers=email.h(),
                          json={"scheduled_at": "2027-03-14T02:30:00", "timezone": "America/New_York"})
    assert r.status_code == 422 and "does not exist in America/New_York" in r.json()["error"]["fields"]["scheduled_at"]
    r = email.client.post(f"{C}/{campaign['id']}/schedule", headers=email.h(),
                          json={"scheduled_at": "2027-03-14T09:00:00", "timezone": "America/New_York"})
    assert r.status_code == 200, r.text
    at = datetime.fromisoformat(r.json()["scheduled_at"])
    assert at == datetime(2027, 3, 14, 9, tzinfo=ZoneInfo("America/New_York")) == datetime(2027, 3, 14, 13, tzinfo=UTC)
    assert r.json()["timezone"] == "America/New_York"
    email.post(f"{C}/{campaign['id']}/unschedule", status=200)
    for body, field in (({"scheduled_at": "2027-02-01T09:00:00Z"}, "scheduled_at"),
                        ({"scheduled_at": "2029-02-01T09:00:00Z"}, "scheduled_at"),
                        ({"timezone": "Mars/Base"}, "timezone")):
        r = email.client.post(f"{C}/{campaign['id']}/schedule", json=body, headers=email.h())
        assert r.status_code == 422 and field in r.json()["error"]["fields"], body


def test_a_domain_that_stops_passing_dns_fails_the_campaign_at_its_start(email, db):
    email.contacts(1)
    campaign = email.campaign()
    email.schedule(campaign)
    email.dns.records.pop("_dmarc.mg.example.com", None)
    drain(limit=2000)
    done = email.get(f"{C}/{campaign['id']}")
    assert done["status"] == "failed" and "SPF, DKIM and DMARC" in done["error"] and email.mailgun.sent() == []


# --- A/B tests ------------------------------------------------------------------------------------------------

def ab(variant_subject="Our autumn notes are in", **more) -> dict:
    return {"enabled": True, "metric": "opens", "test_percent": 50, "wait_hours": 2,
            "variants": [{"key": "B", "subject": variant_subject}], **more}


def open_some(db, campaign: dict, variant: str, n: int) -> None:
    db.execute(text("UPDATE email_sends SET opened_at = now() WHERE id IN (SELECT id FROM email_sends WHERE "
                    "campaign_id = :c AND variant = :v AND phase = 'test' ORDER BY id LIMIT :n)"),
               {"c": campaign["id"], "v": variant, "n": n})
    db.commit()


def test_an_ab_test_sends_the_variants_then_the_winner_to_the_rest(email, db):
    email.contacts(60)
    campaign = email.campaign(ab=ab())
    email.send(campaign)
    state = email.get(f"{C}/{campaign['id']}")
    assert state["status"] == "testing" and state["test_ends_at"]
    rows = sends(db, campaign)
    test = [r for r in rows if r[4] == "test"]
    assert len(test) == 30 and {r[3] for r in test} == {"A", "B"} and sum(r[3] == "B" for r in test) == 15
    assert sum(r[1] == "held" for r in rows) == 30 and len(email.mailgun.sent()) == 30
    subjects = {m["subject"] for m in email.mailgun.sent()}
    assert "Our autumn notes are in" in subjects and any(s.startswith("Autumn update for") for s in subjects)
    open_some(db, campaign, "A", 3)
    open_some(db, campaign, "B", 9)
    db.execute(text("UPDATE email_campaigns SET test_ends_at = now()"))  # the wait is over
    db.commit()
    due_now(db)
    drain(limit=2000)
    done = email.get(f"{C}/{campaign['id']}")
    assert done["status"] == "sent" and done["winner"] == "B"
    rest = email.mailgun.sent()[30:]
    assert len(rest) == 30 and {m["subject"] for m in rest} == {"Our autumn notes are in"}
    report = email.report(campaign)
    assert [v["winner"] for v in report["variants"]] == [False, True]
    assert report["variants"][1]["opened"] == 9


def test_an_ab_tie_goes_to_the_first_variant_and_clicks_can_decide(email, db):
    email.contacts(40)
    campaign = email.campaign(ab=ab(metric="clicks"))
    email.send(campaign)
    db.execute(text("UPDATE email_campaigns SET test_ends_at = now()"))
    db.commit()
    due_now(db)
    drain(limit=2000)
    assert email.get(f"{C}/{campaign['id']}")["winner"] == "A"  # no clicks on either: a tie


def test_an_ab_test_on_too_small_an_audience_sends_everyone_variant_a(email, db):
    email.contacts(12)
    campaign = email.campaign(ab=ab())
    check = email.post(f"{C}/{campaign['id']}/check", status=200)
    assert "ab_small" in {i["code"] for i in check["issues"]}
    done = email.send(campaign)
    assert done["status"] == "sent" and done["winner"] == "A" and "did not run" in done["error"]
    assert {r[3] for r in sends(db, campaign)} == {"A"} and len(email.mailgun.sent()) == 12


def test_ab_variants_are_checked(email):
    campaign = email.campaign()
    r = email.client.patch(f"{C}/{campaign['id']}", headers=email.h(), json={"ab": {
        "enabled": True, "variants": [{"key": "B"}]}})
    assert r.status_code == 422 and "ab.variants.0" in r.json()["error"]["fields"]
    r = email.client.patch(f"{C}/{campaign['id']}", headers=email.h(), json={"ab": {
        "enabled": True, "variants": [{"key": "C", "subject": "x"}]}})
    assert r.status_code == 422
    r = email.client.patch(f"{C}/{campaign['id']}", headers=email.h(), json={"ab": {
        "enabled": True, "variants": [{"key": "B", "document": {"blocks": [{"type": "text", "text": "{{nope}}"}]}}]}})
    assert r.status_code == 422 and "ab.variants.0.document.blocks.0.text" in r.json()["error"]["fields"]


@pytest.mark.parametrize("rates, metric, winner", [
    ([(100, 10, 1), (100, 20, 0)], "opens", "B"), ([(100, 10, 5), (100, 20, 1)], "clicks", "A"),
    ([(100, 10, 0), (50, 5, 0)], "opens", "A"), ([(0, 0, 0), (0, 0, 0)], "opens", "A")])
def test_the_winner_rule(rates, metric, winner):
    rows = [{"variant": k, "sent": s, "opened": o, "clicked": c, "open_rate": o / s if s else 0.0,
             "click_rate": c / s if s else 0.0} for k, (s, o, c) in zip("AB", rates, strict=True)]
    assert sender.pick(SimpleNamespace(ab={"metric": metric}), rows) == winner
