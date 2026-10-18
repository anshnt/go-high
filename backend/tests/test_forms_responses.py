"""Responses and analytics of a form: the list, one response, the CSV export, and the numbers."""
import csv
import io
import uuid
from datetime import date, timedelta

from forms_helpers import form, lead, pick, q, step
from sqlalchemy import text

from app.forms import responses

ROOT = "/api/v1/forms"
ANSWERS = {"first_name": "Ada", "email": "ada@example.com"}


def parse(response) -> list[list[str]]:
    assert response.headers["content-type"].startswith("text/csv")
    assert response.text.startswith("﻿")  # the byte order mark Excel needs for UTF-8
    return list(csv.reader(io.StringIO(response.text.removeprefix("﻿"))))


def table(site, form_id: str, **params) -> list[dict]:
    r = site.get(f"forms/{form_id}/submissions/export.csv", **params)
    assert r.status_code == 200, r.text
    head, *body = parse(r)
    return [dict(zip(head, row, strict=True)) for row in body]


def set_created(db, submission_id: str, when: str) -> None:
    db.execute(text("UPDATE form_submissions SET created_at = :w WHERE id = :i"), {"w": when, "i": submission_id})
    db.commit()


# --- the list and one response -------------------------------------------------------------------------------

def test_the_list_filters_by_status_and_date_and_pages_newest_first(site, db):
    made = site.live(definition=lead(q("note")))
    key = made["public_key"]
    done = [site.submit(made, {**ANSWERS, "note": f"n{i}", "email": f"p{i}@example.com"})["id"] for i in range(3)]
    partial = [site.start(key, {"first_name": f"Half {i}"}).json()["id"] for i in range(2)]
    for sid, day in zip([*done, *partial], ["2026-01-10", "2026-01-11", "2026-01-12", "2026-01-13", "2026-01-14"],
                        strict=True):
        set_created(db, sid, f"{day}T12:00:00+00:00")
    path = f"forms/{made['id']}/submissions"
    everything = site.get(path).json()
    assert [r["id"] for r in everything["data"]] == [*reversed(partial), *reversed(done)]  # newest first
    assert everything["next_cursor"] is None and {r["status"] for r in everything["data"]} == {"partial", "complete"}
    assert [r["id"] for r in site.get(path, status="complete").json()["data"]] == list(reversed(done))
    assert [r["id"] for r in site.get(path, status="partial").json()["data"]] == list(reversed(partial))
    assert [r["id"] for r in site.get(path, **{"from": "2026-01-11", "to": "2026-01-12"}).json()["data"]] == [
        done[2], done[1]]  # both days are inclusive
    assert [r["id"] for r in site.get(path, **{"from": "2026-01-13"}).json()["data"]] == [partial[1], partial[0]]
    assert site.get(path, **{"to": "2026-01-09"}).json()["data"] == []
    page = site.get(path, limit=2).json()
    assert [r["id"] for r in page["data"]] == [partial[1], partial[0]] and page["next_cursor"]
    rest = site.get(path, limit=10, cursor=page["next_cursor"]).json()
    assert [r["id"] for r in rest["data"]] == list(reversed(done)) and rest["next_cursor"] is None
    for bad in ({"status": "all"}, {"from": "yesterday"}, {"limit": 0}, {"cursor": "forged"}):
        assert site.get(path, **bad).status_code in (400, 422), bad
    first = everything["data"][-1]
    assert first["answers"]["note"] == "n0" and first["version"] == 1 and first["contact_id"]
    assert set(first) >= {"id", "status", "answers", "score", "max_score", "source_url", "referrer", "utm", "consent",
                          "started_at", "created_at", "completed_at", "contact_error"}
    assert "ip_hash" not in first and "resume_token_hash" not in first and "user_agent" not in first


def test_one_response_comes_with_the_questions_it_was_asked(site):
    defn = form(step("s1", q("first_name", maps_to="first_name"), q("plan", "select", **pick("solo", "team")),
                     q("intro", "heading", label="Welcome")))
    made = site.live(definition=defn)
    done = site.submit(made, {"first_name": "Ada", "plan": "team"})
    got = site.get(f"forms/{made['id']}/submissions/{done['id']}").json()
    assert got["answers"] == {"first_name": "Ada", "plan": "team"} and got["version"] == 1
    assert [(f["key"], f["type"], f["label"]) for f in got["fields"]] == [("first_name", "short_text", "First Name"),
                                                                           ("plan", "select", "Plan")]
    assert got["fields"][1]["options"] == [{"id": "solo", "label": "Solo"}, {"id": "team", "label": "Team"}]
    assert site.get(f"forms/{made['id']}/submissions/{uuid.uuid4()}").status_code == 404
    other = site.live(name="Other")
    assert site.get(f"forms/{other['id']}/submissions/{done['id']}").status_code == 404  # not that form's response
    assert site.get(f"forms/{uuid.uuid4()}/submissions").status_code == 404


# --- CSV ------------------------------------------------------------------------------------------------------

def test_the_csv_has_one_column_per_question_with_choices_by_label(site):
    defn = form(step("s1", q("first_name", required=True, maps_to="first_name"), q("email", "email", maps_to="email"),
                     q("plan", "select", **pick("solo", "team")), q("tags", "multi_select", **pick("a", "b", "c")),
                     q("ok", "yes_no"), q("age", "number"), q("news", "checkbox"), q("intro", "heading", label="Hi")))
    made = site.live(definition=defn)
    site.submit(made, {"first_name": "Ada, \"Countess\"\nLovelace", "email": "ada@example.com", "plan": "team",
                       "tags": ["a", "c"], "ok": False, "age": -5, "news": True}, url="https://example.com/p?a=1,2",
                utm={"utm_source": "news"})
    site.start(made["public_key"], {"first_name": "Half"})
    r = site.get(f"forms/{made['id']}/submissions/export.csv")
    head, *body = parse(r)
    assert head == ["Response", "Status", "Started", "Completed", "Contact", "Score", "Max score", "Source URL",
                    "Referrer", "Utm Source", "Utm Medium", "Utm Campaign", "Utm Term", "Utm Content", "First Name",
                    "Email", "Plan", "Tags", "Ok", "Age", "News"]  # no column for the heading
    assert r.headers["content-disposition"] == 'attachment; filename="lead-form-responses.csv"'
    assert r.headers["x-export-truncated"] == "false" and r.headers["cache-control"] == "no-store"
    rows = {row[1]: dict(zip(head, row, strict=True)) for row in body}
    full = rows["complete"]
    assert full["First Name"] == 'Ada, "Countess"\nLovelace'  # quoted properly
    assert (full["Plan"], full["Tags"], full["Ok"], full["Age"], full["News"]) == ("Team", "A; C", "no", "-5", "yes")
    assert full["Source URL"] == "https://example.com/p?a=1,2" and full["Utm Source"] == "news"
    assert full["Completed"] and full["Contact"] and full["Score"] == ""
    assert rows["partial"]["First Name"] == "Half" and rows["partial"]["Completed"] == ""
    only = table(site, made["id"], status="complete")
    assert len(only) == 1 and only[0]["Status"] == "complete"


def test_text_a_spreadsheet_could_run_as_a_formula_is_neutralized(site):
    defn = form(step("s1", q("first_name", maps_to="first_name"), q("email", "email", maps_to="email"),
                     q("note"), q("age", "number")))
    made = site.live(definition=defn)
    attacks = ['=HYPERLINK("http://evil.example","click")', "+1+1", "-2+3", "@SUM(A1:A9)", "=cmd|' /C calc'!A0",
               "\t=1+1", "\r=1+1"]
    for n, attack in enumerate(attacks):
        site.submit(made, {"first_name": attack, "email": f"=x{n}@example.com", "note": attack, "age": -n},
                    url="https://example.com/?x", referrer=f"https://example.com/{attack}",
                    utm={"utm_source": attack})
    r = site.get(f"forms/{made['id']}/submissions/export.csv")
    head, *body = parse(r)
    assert len(body) == len(attacks)
    for row in body:
        for name, cell in zip(head, row, strict=True):
            if name != "Age":  # numbers are written as they are
                assert not cell.startswith(responses.INJECTION), (name, cell)  # nothing starts like a formula
    notes = {row[head.index("Note")] for row in body}
    assert "'=HYPERLINK(\"http://evil.example\",\"click\")" in notes and "'+1+1" in notes and "'-2+3" in notes
    assert "'@SUM(A1:A9)" in notes
    emails = {row[head.index("Email")] for row in body}
    assert all(e.startswith("'=x") for e in emails)
    ages = {row[head.index("Age")] for row in body}
    assert ages >= {"0", "-1", "-2"}  # numbers stay numbers
    assert {row[head.index("Utm Source")] for row in body} >= {"'+1+1", "'-2+3"}
    assert [c for c in head if c.startswith(responses.INJECTION)] == []


def test_a_question_label_cannot_attack_through_the_header(site):
    defn = form(step("s1", q("first_name", label="=HYPERLINK(\"x\")", maps_to="first_name")))
    made = site.live(definition=defn)
    site.submit(made, {"first_name": "Ada"})
    head = parse(site.get(f"forms/{made['id']}/submissions/export.csv"))[0]
    assert "'=HYPERLINK(\"x\")" in head


def test_the_csv_covers_the_questions_of_every_version_and_can_be_cut_short(site, monkeypatch):
    made = site.live(definition=lead(q("old_question")))
    site.submit(made, {**ANSWERS, "old_question": "from v1"})
    site.save(made, lead(q("new_question")))
    site.publish(made)
    for i in range(3):
        site.submit(made, {**ANSWERS, "new_question": f"from v2 #{i}", "email": f"p{i}@example.com"})
    r = site.get(f"forms/{made['id']}/submissions/export.csv")
    head, *body = parse(r)
    assert head[-4:] == ["First Name", "Email", "New Question", "Old Question"]  # the newest version's order first
    assert len(body) == 4
    rows = [dict(zip(head, row, strict=True)) for row in body]
    assert sorted((x["Old Question"], x["New Question"]) for x in rows) == [
        ("", "from v2 #0"), ("", "from v2 #1"), ("", "from v2 #2"), ("from v1", "")]
    monkeypatch.setattr(responses, "EXPORT_MAX", 2)
    cut = site.get(f"forms/{made['id']}/submissions/export.csv")
    assert cut.headers["x-export-truncated"] == "true" and len(parse(cut)) == 3  # the header and two rows
    monkeypatch.setattr(responses, "EXPORT_MAX", 4)
    exact = site.get(f"forms/{made['id']}/submissions/export.csv")
    assert exact.headers["x-export-truncated"] == "false" and len(parse(exact)) == 5


def test_an_export_pages_through_more_responses_than_one_batch(site, monkeypatch):
    monkeypatch.setattr(responses, "PAGE", 2)
    made = site.live()
    for i in range(5):
        site.submit(made, {**ANSWERS, "email": f"p{i}@example.com"})
    emails = [row["Email"] for row in table(site, made["id"])]
    assert sorted(emails) == [f"p{i}@example.com" for i in range(5)] and len(set(emails)) == 5


def test_the_export_filename_is_safe_and_dates_filter_it(site, db):
    made = site.live(name='Q&A: The "Big" One')
    done = site.submit(made, ANSWERS)
    set_created(db, done["id"], "2026-03-01T10:00:00+00:00")
    r = site.get(f"forms/{made['id']}/submissions/export.csv")
    assert r.headers["content-disposition"] == 'attachment; filename="q-a-the-big-one-responses.csv"'
    assert len(table(site, made["id"], **{"from": "2026-03-01", "to": "2026-03-01"})) == 1
    assert table(site, made["id"], **{"from": "2026-03-02"}) == []
    assert site.get(f"forms/{uuid.uuid4()}/submissions/export.csv").status_code == 404


# --- analytics ------------------------------------------------------------------------------------------------

def crafted(site, db):
    """Six visitors: three completed (two at known speeds, one that took days), two left on the first step and one
    left on the second. Ten page views: each helper call that needs a token opens the page once."""
    defn = form(step("s1", q("first_name", required=True, maps_to="first_name"),
                     q("email", "email", maps_to="email")), step("s2", q("company"), q("note")))
    made = site.live(definition=defn)
    key = made["public_key"]
    done = {}
    for name, answers in {"A": {"first_name": "A", "email": "a@example.com", "company": "Acme", "note": "n"},
                          "B": {"first_name": "B", "email": "b@example.com"},
                          "F": {"first_name": "F", "email": "f@example.com"}}.items():
        done[name] = site.submit(made, answers)["id"]
    site.start(key, {"first_name": "C", "email": "c@example.com"}, step="s1")
    site.start(key, {"first_name": "D"}, step="s1")
    e = site.start(key, {"first_name": "E", "email": "e@example.com"}, step="s1").json()
    site.start(key, {"first_name": "E", "email": "e@example.com", "company": "Co"}, step="s2",
               resume_token=e["resume_token"])
    seconds = {"A": 60, "B": 120, "F": 3 * 86400}  # F came back three days later: left out of the average
    for name, secs in seconds.items():
        db.execute(text("UPDATE form_submissions SET started_at = completed_at - make_interval(secs => :s) "
                        "WHERE id = :i"), {"s": secs, "i": done[name]})
    db.commit()
    return made, done


def test_analytics_numbers_on_a_crafted_set(site, db):
    made, _ = crafted(site, db)
    got = site.get(f"forms/{made['id']}/analytics").json()
    assert (got["views"], got["starts"], got["completions"]) == (10, 6, 3)
    assert got["completion_rate"] == 0.5 and got["conversion_rate"] == 0.3 and got["avg_seconds"] == 90.0
    assert got["from"] is None and got["to"] is None
    assert got["steps"] == [{"key": "s1", "title": "S1", "reached": 6, "dropped": 2},
                            {"key": "s2", "title": "S2", "reached": 4, "dropped": 1}]
    assert [(f["key"], f["step"], f["type"], f["answered"], f["dropped_after"]) for f in got["fields"]] == [
        ("first_name", "s1", "short_text", 6, 1), ("email", "s1", "email", 5, 1),
        ("company", "s2", "short_text", 2, 1), ("note", "s2", "short_text", 1, 0)]
    assert got["fields"][0]["label"] == "First Name"


def test_analytics_can_be_cut_to_a_date_range(site, db):
    made, done = crafted(site, db)
    db.execute(text("UPDATE form_submissions SET created_at = '2026-01-05T12:00:00+00:00' WHERE id = :i"),
               {"i": done["F"]})
    db.execute(text("UPDATE form_views SET day = '2026-01-05'"))
    db.commit()
    path = f"forms/{made['id']}/analytics"
    early = site.get(path, **{"to": "2026-01-31"}).json()
    assert (early["views"], early["starts"], early["completions"]) == (10, 1, 1) and early["to"] == "2026-01-31"
    assert early["avg_seconds"] is None  # the only response in range took days
    late = site.get(path, **{"from": "2026-02-01"}).json()
    assert (late["views"], late["starts"], late["completions"]) == (0, 5, 2) and late["conversion_rate"] is None
    assert late["avg_seconds"] == 90.0 and late["completion_rate"] == 0.4
    none = site.get(path, **{"from": "2026-01-06", "to": "2026-01-07"}).json()
    assert (none["views"], none["starts"], none["completion_rate"], none["avg_seconds"]) == (0, 0, None, None)
    today = date.today()
    assert site.get(path, **{"from": str(today - timedelta(days=1)), "to": str(today + timedelta(days=1))}
                    ).json()["starts"] == 5
    assert site.get(path, **{"from": "last week"}).status_code == 422


def test_analytics_of_a_form_nobody_has_seen(site):
    made = site.live()
    got = site.get(f"forms/{made['id']}/analytics").json()
    assert (got["views"], got["starts"], got["completions"]) == (0, 0, 0)
    assert got["completion_rate"] is None and got["conversion_rate"] is None and got["avg_seconds"] is None
    assert [s["reached"] for s in got["steps"]] == [0] and [f["answered"] for f in got["fields"]] == [0, 0]
    assert site.get(f"forms/{uuid.uuid4()}/analytics").status_code == 404


def test_analytics_names_the_steps_and_questions_of_older_versions_too(site):
    made = site.live(definition=form(step("s1", q("first_name", maps_to="first_name"), q("old_q"))))
    site.submit(made, {"first_name": "A", "old_q": "x"})
    site.save(made, form(step("s1", q("first_name", maps_to="first_name"), q("new_q")), step("s2", q("extra"))))
    site.publish(made)
    site.submit(made, {"first_name": "B", "new_q": "y", "extra": "z"})
    got = site.get(f"forms/{made['id']}/analytics").json()
    assert [s["key"] for s in got["steps"]] == ["s1", "s2"]
    assert [(f["key"], f["answered"]) for f in got["fields"]] == [("first_name", 2), ("new_q", 1), ("extra", 1),
                                                                   ("old_q", 1)]
    assert [s["reached"] for s in got["steps"]] == [2, 1]
