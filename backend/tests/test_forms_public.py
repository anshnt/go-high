"""The public side of forms: the published definition, views, partial responses and resume, completion with
validation, logic, scoring, contacts, consent, events, limits and the hosted page."""
import json
import uuid
from datetime import UTC, datetime, timedelta

from forms_helpers import PUBLIC, H, Site, form, lead, pick, q, step
from helpers import drain
from sqlalchemy import text

from app import config


def rows(db, sql: str, **params) -> list[dict]:
    db.expire_all()
    return [dict(r) for r in db.execute(text(sql), params).mappings()]


def events_of(db, type_: str) -> list[dict]:
    return rows(db, "SELECT data, subject_id::text AS subject, actor_type FROM events WHERE type = :t ORDER BY id",
                t=type_)


def patch_field(site, key: str, **body):
    r = site.client.patch(f"/api/v1/objects/contact/fields/{key}", json=body, headers={H: site.ws})
    assert r.status_code == 200, r.text


# --- what a visitor can read ---------------------------------------------------------------------------------

def test_the_published_definition_has_nothing_internal_in_it(site):
    scored = q("q1", "select", **pick("a", "b"), quiz={"correct": "a", "points": 2}, required=True)
    made = site.live(form(step("s1", q("email", "email", maps_to="email"), scored),
                          quiz={"pass_mark": 50, "bands": [{"min": 0, "title": "Low", "message": "Try again"}]}),
                     kind="quiz", settings={"notify_emails": ["boss@example.com"], "success_message": "Well done",
                                            "redirect_url": "https://example.com/thanks", "max_responses": 99})
    r = site.page(made["public_key"])
    body = r.json()
    assert r.status_code == 200 and r.headers["cache-control"] == "no-store"
    assert set(body) == {"key", "kind", "name", "version", "definition", "settings"} and body["kind"] == "quiz"
    assert body["settings"] == {"success_message": "Well done", "redirect_url": "https://example.com/thanks"}
    text_ = json.dumps(body)
    for secret in ("maps_to", "correct", "points", "pass_mark", "bands", "boss@example.com", made["id"], site.ws,
                   "max_responses", "notify_emails"):
        assert secret not in text_, secret
    assert [f["key"] for f in body["definition"]["steps"][0]["fields"]] == ["email", "q1"]


def test_only_a_published_form_is_found_by_its_public_key(site):
    draft = site.create()
    live = site.live()
    assert site.page(draft["public_key"]).status_code == 404  # never published
    assert site.page("a" * 16).status_code == 404
    assert site.page(live["id"]).status_code == 404  # the internal id is not a key
    assert site.page(live["slug"]).status_code == 404
    assert site.page("x").status_code == 422  # not even shaped like a key
    assert site.page(live["public_key"]).status_code == 200
    r = site.page("a" * 16)
    assert r.json()["error"]["code"] == "not_found"  # the same error envelope as the rest of the API
    site.client.delete(f"/api/v1/forms/{live['id']}", headers={H: site.ws})
    assert site.page(live["public_key"]).status_code == 404  # in the trash


def test_a_closed_form_says_so_with_its_own_message(site):
    made = site.live(settings={"closed_message": "Applications closed on Friday."})
    site.client.patch(f"/api/v1/forms/{made['id']}", json={"status": "closed"}, headers={H: site.ws})
    r = site.page(made["public_key"])
    assert r.status_code == 410 and r.json()["error"]["code"] == "form_closed"
    assert r.json()["error"]["message"] == "Applications closed on Friday."
    assert r.headers["cache-control"] == "no-store"  # a browser must not keep showing "closed" once it is open again
    assert site.page("a" * 16).headers["cache-control"] == "no-store"
    for call in (lambda: site.anonymous.post(f"{PUBLIC}/{made['public_key']}/views"),
                 lambda: site.anonymous.post(f"{PUBLIC}/{made['public_key']}/submissions", json={}),
                 lambda: site.anonymous.post(f"{PUBLIC}/{made['public_key']}/resume", json={})):
        assert call().status_code == 410


def test_views_are_counted_per_day(site, db):
    made = site.live()
    for _ in range(3):
        assert site.view(made["public_key"])
    counted = rows(db, "SELECT day, count FROM form_views")
    assert len(counted) == 1 and counted[0]["count"] == 3 and counted[0]["day"] == datetime.now(UTC).date()


# --- partial responses -----------------------------------------------------------------------------------

def test_a_response_starts_saves_as_it_goes_and_hands_out_its_resume_token_once(site, db):
    made = site.live(definition=lead(q("note")))
    key = made["public_key"]
    r = site.start(key, {"first_name": "Ad", "email": "ada@", "stray": "x"}, url="https://example.com/offer?a=1",
                   referrer="javascript:alert(1)", utm={"utm_source": "news", "utm_medium": "email", "evil": "x"},
                   step="s1")
    started = r.json()
    assert r.status_code == 201 and started["status"] == "partial" and len(started["resume_token"]) >= 32
    row = rows(db, "SELECT * FROM form_submissions")[0]
    assert str(row["id"]) == started["id"] and row["status"] == "partial" and row["completed_at"] is None
    assert row["answers"] == {"first_name": "Ad", "email": "ada@"}  # kept as typed, not validated yet
    assert row["steps_seen"] == ["s1"] and row["last_field"] == "email" and row["contact_id"] is None
    assert row["source_url"] == "https://example.com/offer?a=1" and row["referrer"] is None  # only http(s) links
    assert row["utm"] == {"utm_source": "news", "utm_medium": "email"}
    assert len(row["ip_hash"]) == 32 and "testclient" not in row["ip_hash"] and row["user_agent"]
    assert row["resume_token_hash"] != started["resume_token"] and started["resume_token"] not in str(row)
    again = site.start(key, {"first_name": "Ada", "email": "ada@example.com", "note": "hi"},
                       resume_token=started["resume_token"])
    assert again.status_code == 200 and again.json() == {"id": started["id"], "status": "partial"}  # no new token
    rows_ = rows(db, "SELECT answers, last_field FROM form_submissions")
    assert len(rows_) == 1 and rows_[0]["answers"]["note"] == "hi" and rows_[0]["last_field"] == "note"


def test_a_resume_token_belongs_to_one_response_of_one_form(site, make_user):
    made, other = site.live(), site.live(name="Other")
    started = site.start(made["public_key"], {"first_name": "Ada"}).json()
    token = started["resume_token"]
    bad = site.start(made["public_key"], {"first_name": "Eve"}, resume_token="nope")
    assert bad.status_code == 404 and bad.json()["error"]["code"] == "not_found"
    assert site.start(other["public_key"], {"first_name": "Eve"}, resume_token=token).status_code == 404  # other form
    assert site.finish(other["public_key"], started, {}).status_code == 404
    path = f"{PUBLIC}/{made['public_key']}/submissions/{uuid.uuid4()}/complete"
    r = site.anonymous.post(path, json={"resume_token": token, "view_token": site.view(made["public_key"])})
    assert r.status_code == 404  # right token, wrong id
    stranger, ids = make_user("b@example.com")
    theirs = Site(stranger, ids["workspace_id"]).live()  # another workspace
    assert site.start(theirs["public_key"], {}, resume_token=token).status_code == 404
    assert site.anonymous.post(f"{PUBLIC}/{theirs['public_key']}/resume", json={"resume_token": token}
                               ).status_code == 404


def test_resume_returns_the_answers_and_the_version_the_response_began_on(site):
    made = site.live(definition=lead())
    key = made["public_key"]
    started = site.start(key, {"first_name": "Ada"}, step="s1").json()
    site.save(made, lead(q("company", required=True)))
    site.publish(made)  # version 2 is live now
    assert [f["key"] for f in site.page(key).json()["definition"]["steps"][0]["fields"]] == [
        "first_name", "email", "company"]
    r = site.anonymous.post(f"{PUBLIC}/{key}/resume", json={"resume_token": started["resume_token"]})
    got = r.json()
    assert r.status_code == 200 and got["id"] == started["id"] and got["answers"] == {"first_name": "Ada"}
    assert got["step"] == "s1" and got["version"] == 1 and r.headers["cache-control"] == "no-store"
    assert [f["key"] for f in got["definition"]["steps"][0]["fields"]] == ["first_name", "email"]  # version 1
    assert "maps_to" not in json.dumps(got)
    assert site.anonymous.post(f"{PUBLIC}/{key}/resume", json={"resume_token": "nope"}).status_code == 404
    assert site.anonymous.post(f"{PUBLIC}/{key}/resume", json={}).status_code == 404


def test_a_completed_response_cannot_be_resumed_or_changed(site):
    made = site.live()
    key = made["public_key"]
    started = site.start(key, {}).json()
    assert site.finish(key, started, {"first_name": "Ada", "email": "ada@example.com"}).status_code == 200
    r = site.anonymous.post(f"{PUBLIC}/{key}/resume", json={"resume_token": started["resume_token"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "already_completed"
    r = site.start(key, {"first_name": "Mallory"}, resume_token=started["resume_token"])
    assert r.status_code == 409


# --- completing ---------------------------------------------------------------------------------------------

def test_completing_checks_every_answer_and_names_each_field(site, db):
    made = site.live()
    key = made["public_key"]
    started = site.start(key, {}).json()
    r = site.finish(key, started, {"first_name": "", "email": "not-an-email"})
    error = r.json()["error"]
    assert r.status_code == 422 and error["code"] == "validation_failed"
    assert error["fields"] == {"first_name": "First Name is required",
                               "email": "Email is not an email address"}
    row = rows(db, "SELECT status, contact_id FROM form_submissions")[0]
    assert row == {"status": "partial", "contact_id": None} and rows(db, "SELECT 1 FROM records WHERE "
                                                                         "email_norm IS NOT NULL") == []
    ok = site.finish(key, started, {"first_name": "Ada", "email": "ada@example.com"})
    assert ok.status_code == 200  # the same response can be fixed and sent again


def test_a_completed_response_creates_the_contact_the_event_and_a_timeline_entry(site, db):
    made = site.live(settings={"success_message": "Thanks, Ada!", "redirect_url": "https://example.com/done"})
    done = site.submit(made, {"first_name": " Ada ", "email": "ADA@Example.com"}, url="https://example.com/p",
                       utm={"utm_campaign": "spring"})
    assert done["status"] == "complete" and done["message"] == "Thanks, Ada!" and done["result"] is None
    assert done["redirect_url"] == "https://example.com/done"
    [contact] = site.records()
    assert contact["values"] == {"first_name": "Ada", "email": "ada@example.com"}
    assert contact["display_name"] == "Ada" and contact["created_by"] is None
    row = rows(db, "SELECT * FROM form_submissions")[0]
    assert row["status"] == "complete" and row["answers"] == {"first_name": "Ada", "email": "ada@example.com"}
    assert str(row["contact_id"]) == contact["id"] and row["completed_at"] and row["steps_seen"] == ["s1"]
    assert row["utm"] == {"utm_campaign": "spring"} and row["score"] is None
    [event] = events_of(db, "form.submitted")
    assert event["subject"] == done["id"] and event["actor_type"] == "system"
    assert event["data"] == {
        "id": done["id"], "form_id": made["id"], "form_name": "Lead form", "kind": "form", "version": 1,
        "answers": {"first_name": "Ada", "email": "ada@example.com"}, "score": None, "max_score": None,
        "passed": None, "contact_id": contact["id"], "contact_created": True, "source_url": "https://example.com/p",
        "referrer": None, "utm": {"utm_campaign": "spring"}, "consent": {}}
    created = events_of(db, "record.created")[-1]
    assert created["actor_type"] == "system" and created["data"]["id"] == contact["id"]
    line = site.get(f"records/{contact['id']}/timeline").json()["data"]
    assert [e["type"] for e in line] == ["form.submitted", "record.created"]  # the response is on the timeline


def test_a_response_keeps_the_version_it_began_on(site):
    made = site.live(definition=lead())
    key = made["public_key"]
    old = site.start(key, {"first_name": "Old"}).json()
    site.save(made, lead(q("company", required=True)))
    site.publish(made)
    done = site.finish(key, old, {"first_name": "Old", "email": "old@example.com"})  # no company: version 1 had none
    assert done.status_code == 200
    fresh = site.start(key, {}).json()
    r = site.finish(key, fresh, {"first_name": "New", "email": "new@example.com"})
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"company": "Company is required"}
    assert site.finish(key, fresh, {"first_name": "New", "email": "new@example.com", "company": "Acme"}
                       ).status_code == 200
    versions = {r["answers"]["first_name"]: r["version"] for r in site.get(
        f"forms/{made['id']}/submissions").json()["data"]}
    assert versions == {"Old": 1, "New": 2}


def test_logic_runs_on_the_server_hidden_questions_are_not_required_and_their_answers_are_dropped(site, db):
    plan = q("plan", "select", **pick("solo", "team"), required=True)
    solo = {"field": "plan", "op": "is", "value": "solo"}
    defn = form(step("s1", plan, q("company", required=True), q("email", "email", maps_to="email")),
                step("s2", q("detail", required=True)), step("s3", q("note")),
                logic_=[{"when": solo, "do": "hide", "target": "company"},
                        {"when": solo, "do": "jump", "from": "s1", "target": "s3"}])
    made = site.live(definition=defn)
    site.submit(made, {"plan": "solo", "company": "Typed then hidden", "detail": "skipped step", "note": "kept",
                       "email": "a@example.com"})
    row = rows(db, "SELECT answers, steps_seen FROM form_submissions")[0]
    assert row["answers"] == {"plan": "solo", "email": "a@example.com", "note": "kept"}
    assert row["steps_seen"] == ["s1", "s3"]
    key = made["public_key"]
    started = site.start(key, {}).json()
    r = site.finish(key, started, {"plan": "team", "email": "b@example.com"})
    assert r.json()["error"]["fields"] == {"company": "Company is required", "detail": "Detail is required"}
    ok = site.finish(key, started, {"plan": "team", "company": "Acme", "detail": "d", "email": "b@example.com"})
    assert ok.status_code == 200


def test_an_end_rule_finishes_the_form_early(site, db):
    done = {"field": "ok", "op": "is", "value": True}
    made = site.live(definition=form(step("s1", q("ok", "yes_no", required=True, label="OK?"),
                                           q("email", "email", maps_to="email")),
                                     step("s2", q("why", "long_text", required=True)),
                                     logic_=[{"when": done, "do": "end", "from": "s1"}]))
    site.submit(made, {"ok": True, "email": "a@example.com", "why": "never asked"})
    assert rows(db, "SELECT answers FROM form_submissions")[0]["answers"] == {"ok": True, "email": "a@example.com"}
    key = made["public_key"]
    started = site.start(key, {}).json()
    assert site.finish(key, started, {"ok": False, "email": "a@example.com"}).status_code == 422  # "why" is required


def test_hidden_fields_carry_url_parameters_into_the_answers(site, db):
    made = site.live(definition=lead(q("campaign", "hidden", param="utm_campaign")))
    site.submit(made, {"first_name": "Ada", "email": "a@example.com", "campaign": "spring"})
    assert rows(db, "SELECT answers FROM form_submissions")[0]["answers"]["campaign"] == "spring"


# --- quizzes --------------------------------------------------------------------------------------------------

QUIZ = form(step("s1", q("capital", "select", **pick("paris", "rome"), required=True,
                         quiz={"correct": "paris", "points": 2}),
                 q("rivers", "multi_select", **pick("seine", "tiber", "loire"), quiz={"correct": ["seine", "loire"],
                                                                                        "points": 3}),
                 q("email", "email", maps_to="email")),
            quiz={"pass_mark": 60, "bands": [{"min": 0, "title": "Rookie", "message": "Keep studying"},
                                             {"min": 50, "title": "Local", "message": "Not bad"},
                                             {"min": 100, "title": "Expert", "message": "Perfect"}]})


def test_a_quiz_is_scored_on_the_server_and_the_result_is_returned_and_stored(site, db):
    made = site.live(definition=QUIZ, kind="quiz")
    done = site.submit(made, {"capital": "paris", "rivers": ["seine"], "email": "q@example.com"})
    result = done["result"]
    assert (result["score"], result["max_score"], result["percent"], result["passed"]) == (2, 5, 40, False)
    assert result["band"] == {"title": "Rookie", "message": "Keep studying"}
    assert result["review"] == {"capital": True, "rivers": False}
    row = rows(db, "SELECT score, max_score FROM form_submissions")[0]
    assert (row["score"], row["max_score"]) == (2, 5)
    assert events_of(db, "form.submitted")[0]["data"]["score"] == 2
    assert events_of(db, "form.submitted")[0]["data"]["passed"] is False
    full = site.submit(made, {"capital": "paris", "rivers": ["loire", "seine"]})["result"]
    assert (full["score"], full["percent"], full["passed"], full["band"]["title"]) == (5, 100, True, "Expert")
    mid = site.submit(made, {"capital": "rome", "rivers": ["seine", "loire"]})["result"]
    assert (mid["score"], mid["percent"], mid["passed"], mid["band"]["title"]) == (3, 60, True, "Local")
    listed = site.get(f"forms/{made['id']}/submissions").json()["data"]
    assert sorted((r["score"], r["max_score"]) for r in listed) == [(2, 5), (3, 5), (5, 5)]


def test_asking_for_a_completed_quizs_result_again_gives_the_same_answer(site, db):
    made = site.live(definition=QUIZ, kind="quiz")
    key = made["public_key"]
    started = site.start(key, {}).json()
    answers = {"capital": "paris", "rivers": ["seine"], "email": "q@example.com"}
    first = site.finish(key, started, answers).json()
    second = site.finish(key, started, answers)
    assert second.status_code == 200 and second.json() == first
    assert len(events_of(db, "form.submitted")) == 1 and len(site.records()) == 1  # nothing happened twice
    other = site.finish(key, started, {"capital": "rome"}).json()  # new answers are ignored
    assert other == first and rows(db, "SELECT answers FROM form_submissions")[0]["answers"]["capital"] == "paris"


# --- the contact ------------------------------------------------------------------------------------------

def optional_lead():
    return form(step("s1", q("first_name", maps_to="first_name"), q("email", "email", maps_to="email"),
                     q("phone", "phone", maps_to="phone")))


def test_a_known_contact_is_updated_and_an_empty_answer_never_blanks_a_field(site, db):
    made = site.live(definition=optional_lead())
    site.submit(made, {"first_name": "Ada", "email": "ada@example.com", "phone": "+14155550100"})
    [first] = site.records()
    second = site.submit(made, {"first_name": "Adaline", "email": "ADA@example.com", "phone": ""})
    [now] = site.records()  # still one contact: found by email
    assert now["id"] == first["id"] and now["values"]["first_name"] == "Adaline"
    assert now["values"]["phone"] == "+14155550100"  # an empty answer does not blank it
    assert events_of(db, "form.submitted")[-1]["data"]["contact_created"] is False
    assert events_of(db, "form.submitted")[-1]["data"]["contact_id"] == first["id"]
    assert rows(db, "SELECT count(*) AS n FROM events WHERE type = 'record.updated'")[0]["n"] == 1
    site.submit(made, {"first_name": "Adaline", "email": "ada@example.com"})  # nothing new: no update event
    assert rows(db, "SELECT count(*) AS n FROM events WHERE type = 'record.updated'")[0]["n"] == 1
    assert second["status"] == "complete"
    changed = events_of(db, "record.updated")[0]["data"]["changes"]
    assert changed == {"first_name": {"old": "Ada", "new": "Adaline"}}


def test_a_contact_is_found_by_phone_when_the_form_has_no_email(site):
    known = {"values": {"first_name": "Known", "phone": "+14155550111"}}
    site.client.post("/api/v1/objects/contact/records", json=known, headers={H: site.ws})
    made = site.live(definition=form(step("s1", q("first_name", maps_to="first_name"),
                                           q("phone", "phone", maps_to="phone"))))
    site.submit(made, {"first_name": "Renamed", "phone": "(415) 555-0111"})
    [contact] = site.records()
    assert contact["values"]["first_name"] == "Renamed" and contact["values"]["phone"] == "+14155550111"


def test_the_oldest_duplicate_gets_the_update_and_trashed_contacts_are_ignored(site):
    def add(email, name):
        r = site.client.post("/api/v1/objects/contact/records", json={"values": {"email": email, "first_name": name}},
                             headers={H: site.ws})
        return r.json()["id"]
    oldest, newer = add("dup@example.com", "Oldest"), add("dup@example.com", "Newer")
    gone = add("gone@example.com", "Gone")
    site.client.delete(f"/api/v1/objects/contact/records/{gone}", headers={H: site.ws})
    made = site.live(definition=optional_lead())
    site.submit(made, {"first_name": "Updated", "email": "dup@example.com"})
    by_id = {c["id"]: c["values"]["first_name"] for c in site.records()}
    assert by_id[oldest] == "Updated" and by_id[newer] == "Newer"
    site.submit(made, {"first_name": "Fresh", "email": "gone@example.com"})  # the trashed one is not a match
    assert [c["values"]["first_name"] for c in site.records() if c["values"].get("email") == "gone@example.com"
            ] == ["Fresh"]


def test_fill_empty_only_adds_what_the_contact_does_not_have(site):
    made = site.live(definition=optional_lead(), settings={"contact": {"existing": "fill_empty"}})
    site.submit(made, {"first_name": "Ada", "email": "ada@example.com"})
    site.submit(made, {"first_name": "Mallory", "email": "ada@example.com", "phone": "+14155550100"})
    [contact] = site.records()
    assert contact["values"]["first_name"] == "Ada" and contact["values"]["phone"] == "+14155550100"


def test_a_form_can_leave_the_contacts_alone(site, db):
    made = site.live(definition=optional_lead(), settings={"contact": {"create": False}})
    site.submit(made, {"first_name": "Anon", "email": "anon@example.com"})
    assert site.records() == []
    row = rows(db, "SELECT status, contact_id, contact_error FROM form_submissions")[0]
    assert row == {"status": "complete", "contact_id": None, "contact_error": None}
    assert events_of(db, "form.submitted")[0]["data"]["contact_id"] is None


def test_answers_without_a_contact_field_make_no_contact(site):
    made = site.live(definition=form(step("s1", q("opinion", "long_text", required=True))), kind="survey")
    done = site.submit(made, {"opinion": "Great"})
    assert done["status"] == "complete" and site.records() == []


def test_a_refusal_by_the_crm_does_not_lose_the_response(site, db):
    patch_field(site, "last_name", rules={"required": True})  # the contact object now needs a last name
    made = site.live(definition=optional_lead())
    done = site.submit(made, {"first_name": "Ada", "email": "ada@example.com"})
    assert done["status"] == "complete" and site.records() == []
    row = rows(db, "SELECT status, contact_id, contact_error, answers FROM form_submissions")[0]
    assert row["status"] == "complete" and row["contact_id"] is None and row["answers"]["first_name"] == "Ada"
    assert "Last name is required" in row["contact_error"]
    assert events_of(db, "form.submitted")[0]["data"]["contact_id"] is None
    seen = site.get(f"forms/{made['id']}/submissions").json()["data"][0]
    assert "Last name is required" in seen["contact_error"]


# --- consent --------------------------------------------------------------------------------------------------

def test_a_ticked_consent_box_is_stored_as_evidence_of_opt_in(site, db):
    defn = lead(q("terms", "consent", label="I agree to receive emails", required=True),
                q("partners", "consent", label="Partners may contact me"))
    made = site.live(definition=defn)
    key = made["public_key"]
    started = site.start(key, {}).json()
    r = site.finish(key, started, {"first_name": "Ada", "email": "ada@example.com", "terms": False})
    assert r.status_code == 422 and r.json()["error"]["fields"] == {"terms": "This box must be ticked"}
    r = site.finish(key, started, {"first_name": "Ada", "email": "ada@example.com", "terms": True, "partners": False})
    assert r.status_code == 200
    row = rows(db, "SELECT answers, consent, completed_at FROM form_submissions")[0]
    assert row["answers"]["terms"] is True and "partners" not in row["answers"]
    assert set(row["consent"]) == {"terms"}  # only what was ticked
    evidence = row["consent"]["terms"]
    assert evidence["text"] == "I agree to receive emails" and evidence["form_id"] == made["id"]
    assert datetime.fromisoformat(evidence["at"]) == row["completed_at"] and len(evidence["ip_hash"]) == 32
    sent = events_of(db, "form.submitted")[0]["data"]["consent"]
    assert sent == {"terms": {"text": "I agree to receive emails", "at": evidence["at"]}}  # no address hash leaves
    assert "ip_hash" not in json.dumps(events_of(db, "form.submitted"))


# --- events and webhooks -----------------------------------------------------------------------------------

def test_a_webhook_gets_form_submitted_with_the_answers_and_the_contact(site, receiver, db):
    r = site.client.post("/api/v1/webhooks", json={"url": receiver.url(), "event_types": ["form.submitted"]},
                         headers={H: site.ws})
    assert r.status_code == 201
    made = site.live()
    done = site.submit(made, {"first_name": "Ada", "email": "ada@example.com"})
    drain()
    [call] = receiver.requests
    body = json.loads(call["body"])
    assert body["type"] == "form.submitted" and body["subject"] == {"type": "form_submission", "id": done["id"]}
    assert body["data"]["answers"] == {"first_name": "Ada", "email": "ada@example.com"}
    assert body["data"]["contact_id"] == site.records()[0]["id"] and body["workspace_id"] == site.ws
    assert call["headers"]["gohigh-event-type"] == "form.submitted"


def test_completing_twice_changes_nothing_the_second_time(site, db):
    made = site.live()
    key = made["public_key"]
    started = site.start(key, {}).json()
    answers = {"first_name": "Ada", "email": "ada@example.com"}
    first = site.finish(key, started, answers)
    second = site.finish(key, started, answers)
    assert first.status_code == second.status_code == 200 and first.json() == second.json()
    assert len(events_of(db, "form.submitted")) == 1 and len(site.records()) == 1
    assert rows(db, "SELECT count(*) AS n FROM form_submissions WHERE status = 'complete'")[0]["n"] == 1


# --- policies and limits of a form -----------------------------------------------------------------------

def test_a_contact_may_answer_once_when_the_form_says_so(site):
    made = site.live(settings={"double_submission": "block"})
    site.submit(made, {"first_name": "Ada", "email": "ada@example.com"})
    r = site.submit(made, {"first_name": "Ada", "email": "ADA@example.com"}, expect=409)
    assert r["error"]["code"] == "already_submitted"
    site.submit(made, {"first_name": "Bob", "email": "bob@example.com"})  # someone else may
    allow = site.live(name="Open")
    for _ in range(2):
        site.submit(allow, {"first_name": "Ada", "email": "ada@example.com"})


def test_a_form_closes_after_its_response_limit(site):
    made = site.live(settings={"max_responses": 2, "closed_message": "Full."})
    key = made["public_key"]
    waiting, token = site.start(key, {}).json(), site.view(key)  # a third visitor is part way through
    site.submit(made, {"first_name": "A", "email": "a@example.com"})
    assert site.page(key).status_code == 200
    site.submit(made, {"first_name": "B", "email": "b@example.com"})
    r = site.page(key)
    assert r.status_code == 410 and r.json()["error"]["message"] == "Full."
    assert site.finish(key, waiting, {"first_name": "C", "email": "c@example.com"}, token=token).status_code == 410
    shown = site.get(f"forms/{made['id']}").json()
    assert shown["status"] == "closed" and shown["closed_reason"] == "limit" and shown["responses"] == 2
    site.client.patch(f"/api/v1/forms/{made['id']}", json={"settings": {"max_responses": 3}}, headers={H: site.ws})
    assert site.page(key).status_code == 200  # raising the limit reopens it


def test_a_form_closes_on_its_close_date(site):
    past = (datetime.now(UTC) - timedelta(minutes=1)).isoformat()
    future = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    ended, open_ = site.live(settings={"close_at": past}), site.live(name="Open", settings={"close_at": future})
    assert site.page(ended["public_key"]).status_code == 410
    assert site.page(open_["public_key"]).status_code == 200
    assert site.get(f"forms/{ended['id']}").json()["closed_reason"] == "date"
    assert site.get(f"forms/{open_['id']}").json()["status"] == "published"


# --- CORS, the hosted page and the embed script ----------------------------------------------------------------

def test_the_public_endpoints_allow_any_origin_and_never_credentials(site):
    made = site.live()
    key = made["public_key"]
    pre = site.anonymous.options(f"{PUBLIC}/{key}/submissions", headers={
        "Origin": "https://customer.example", "Access-Control-Request-Method": "POST",
        "Access-Control-Request-Headers": "content-type"})
    assert pre.status_code == 204 and pre.headers["access-control-allow-origin"] == "*"
    assert "POST" in pre.headers["access-control-allow-methods"]
    assert "content-type" in pre.headers["access-control-allow-headers"].lower()
    for response in (site.page(key), site.page("b" * 16), site.anonymous.post(f"{PUBLIC}/{key}/views"),
                     site.anonymous.post(f"{PUBLIC}/{key}/submissions", content=b"{", headers={
                         "Content-Type": "application/json"}), pre):
        assert response.headers["access-control-allow-origin"] == "*"
        assert "access-control-allow-credentials" not in response.headers
        assert "origin" not in response.headers.get("vary", "").lower()
    admin = site.client.get("/api/v1/forms", headers={H: site.ws, "Origin": "https://customer.example"})
    assert "access-control-allow-origin" not in admin.headers  # the admin API is not opened up


def test_the_hosted_page_is_a_small_shell_that_loads_the_runtime(site):
    made = site.live(name='Quote <script>alert(1)</script> "form"')
    r = site.anonymous.get(f"/f/{made['public_key']}")
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert f'data-form="{made["public_key"]}"' in r.text and 'src="/embed.js"' in r.text
    assert "<script>alert(1)</script>" not in r.text and "&lt;script&gt;alert(1)&lt;/script&gt;" in r.text
    csp = r.headers["content-security-policy"]
    assert "script-src 'self'" in csp and "default-src 'none'" in csp and "connect-src 'self'" in csp
    assert 'data-theme="light"' in r.text and 'data-theme="dark"' in site.anonymous.get(
        f"/f/{made['public_key']}", params={"theme": "dark"}).text
    assert 'data-theme="light"' in site.anonymous.get(f"/f/{made['public_key']}", params={"theme": "x\"><b>"}).text
    assert site.anonymous.get(f"/f/{'a' * 16}").status_code == 404
    assert site.anonymous.get(f"/f/{site.create()['public_key']}").status_code == 404  # a draft
    assert site.anonymous.get(f"/f/{made['id']}").status_code == 404
    assert site.anonymous.get("/f/x").status_code != 200


def test_the_embed_script_is_served_from_the_web_build(site, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FRONTEND_DIST", tmp_path)
    assert site.anonymous.get("/embed.js").status_code == 404  # not built
    (tmp_path / "embed.js").write_text("(function(){})();", encoding="utf-8")
    r = site.anonymous.get("/embed.js")
    assert r.status_code == 200 and r.text == "(function(){})();"
    assert r.headers["content-type"].startswith("text/javascript") and "max-age=300" in r.headers["cache-control"]


def test_the_public_side_never_starts_a_session(site):
    made = site.live()
    key = made["public_key"]
    for response in (site.page(key), site.anonymous.post(f"{PUBLIC}/{key}/views"),
                     site.start(key, {"first_name": "A"})):
        assert "set-cookie" not in response.headers
