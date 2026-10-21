"""Notifications: what turns an event into one (per each person's preferences), quiet hours, the due-time job, the
bell's API and preferences, and that nobody else in the workspace can see them."""
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from helpers import H, add_member, drain, due_now, make_record, make_role, rule
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app import jobs
from app.db import SessionLocal, engine
from app.events import Event
from app.notifications import consumer

N = "/api/v1/notifications"
T = "/api/v1/tasks"
NOW = datetime.now(UTC)


def iso(when) -> str:
    return when.astimezone(UTC).isoformat().replace("+00:00", "Z")


def user_id(client) -> str:
    return client.get("/api/me").json()["user"]["id"]


def make(client, ws, title="Call Ada", **body) -> dict:
    r = client.post(T, json={"title": title, **body}, headers={H: ws})
    assert r.status_code == 201, r.text
    return r.json()


def inbox(client, ws, **params) -> list[dict]:
    r = client.get(N, params=params, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()["data"]


def unread(client, ws) -> int:
    r = client.get(f"{N}/unread-count", headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()["count"]


def save_prefs(client, ws, status=200, **entries) -> dict:
    """PUT preferences: keyword per kind, each a dict of settings."""
    body = {"prefs": [{"kind": kind, **settings} for kind, settings in entries.items()]}
    r = client.put(f"{N}/prefs", json=body, headers={H: ws})
    assert r.status_code == status, r.text
    return r.json()


@pytest.fixture
def team(crm, db):
    """Ann (admin, acts), Ben and Cara (members) in one workspace: (clients by name, ids by name, workspace id)."""
    ann, ws, ids = crm
    clients = {"ann": ann, "ben": add_member(db, ids["org_id"], "ben@example.com", workspace_id=ws),
               "cara": add_member(db, ids["org_id"], "cara@example.com", workspace_id=ws)}
    return clients, {name: user_id(c) for name, c in clients.items()}, ws


def test_assigning_a_task_notifies_the_assignee_and_nobody_else(team):
    clients, who, ws = team
    task = make(clients["ann"], ws, "Call Ada", assignee_id=who["ben"])
    drain()
    [note] = inbox(clients["ben"], ws)
    assert note["kind"] == "task_assigned" and note["title"] == "a assigned you a task"
    assert note["body"] == "Call Ada" and note["link"] == f"/tasks?task={task['id']}"
    assert note["subject"] == {"type": "task", "id": task["id"]} and note["read_at"] is None
    assert unread(clients["ben"], ws) == 1
    assert inbox(clients["ann"], ws) == inbox(clients["cara"], ws) == []


def test_nobody_is_told_about_what_they_did_themselves(team):
    clients, who, ws = team
    make(clients["ann"], ws, "Mine", assignee_id=who["ann"])
    drain()
    assert inbox(clients["ann"], ws) == []


def test_reassigning_notifies_the_new_assignee_but_other_edits_and_unassigning_do_not(team):
    clients, who, ws = team
    ann, ws_ = clients["ann"], ws
    task = make(ann, ws_, "Draft", assignee_id=who["ben"])
    drain()
    assert len(inbox(clients["ben"], ws)) == 1
    ann.patch(f"{T}/{task['id']}", json={"title": "Draft v2", "priority": "high"}, headers={H: ws})
    ann.patch(f"{T}/{task['id']}", json={"assignee_id": None}, headers={H: ws})
    drain()
    assert len(inbox(clients["ben"], ws)) == 1
    ann.patch(f"{T}/{task['id']}", json={"assignee_id": who["cara"]}, headers={H: ws})
    drain()
    [note] = inbox(clients["cara"], ws)
    assert note["title"] == "a assigned you a task" and note["body"] == "Draft v2"
    assert len(inbox(clients["ben"], ws)) == 1


def test_bulk_assign_notifies_for_each_task(team):
    clients, who, ws = team
    tasks = [make(clients["ann"], ws, f"t{n}") for n in range(3)]
    r = clients["ann"].post(f"{T}/bulk", json={"ids": [t["id"] for t in tasks], "action": "assign",
                                               "assignee_id": who["ben"]}, headers={H: ws})
    assert r.status_code == 200
    drain()
    assert sorted(n["body"] for n in inbox(clients["ben"], ws)) == ["t0", "t1", "t2"]


def test_the_next_occurrence_of_a_repeating_task_is_not_announced_as_an_assignment(team):
    clients, who, ws = team
    task = make(clients["ann"], ws, "Weekly", assignee_id=who["ben"], due_at="2031-10-19T09:00:00Z",
                recurrence="FREQ=WEEKLY")
    drain()
    assert len(inbox(clients["ben"], ws)) == 1
    done = clients["ann"].post(f"{T}/{task['id']}/complete", headers={H: ws}).json()
    assert done["next"]["assignee_id"] == who["ben"]
    drain()
    assert len(inbox(clients["ben"], ws)) == 1
    clients["ann"].patch(f"{T}/{done['next']['id']}", json={"assignee_id": who["cara"]}, headers={H: ws})
    drain()  # handing a later occurrence to someone else is an assignment
    assert [n["title"] for n in inbox(clients["cara"], ws)] == ["a assigned you a task"]


def test_a_record_assigned_to_you_notifies_you(team):
    clients, who, ws = team
    ann = clients["ann"]
    ada = make_record(ann, ws, first_name="Ada", last_name="Lovelace", owner_id=who["ben"])
    mine = make_record(ann, ws, first_name="Grace", owner_id=who["ann"])
    drain()
    [note] = inbox(clients["ben"], ws)
    assert note["kind"] == "record_assigned" and note["title"] == "a assigned you Ada Lovelace"
    assert note["link"] == f"/contacts/{ada['id']}" and note["subject"] == {"type": "record", "id": ada["id"]}
    assert inbox(ann, ws) == []
    ann.patch(f"/api/v1/objects/contact/records/{mine['id']}", json={"owner_id": who["cara"]}, headers={H: ws})
    ann.patch(f"/api/v1/objects/contact/records/{ada['id']}", json={"values": {"last_name": "King"}}, headers={H: ws})
    drain()
    assert [n["title"] for n in inbox(clients["cara"], ws)] == ["a assigned you Grace"]
    assert len(inbox(clients["ben"], ws)) == 1  # editing a record you own is not an assignment


def test_a_notification_is_made_once_per_event(team, db):
    clients, who, ws = team
    make(clients["ann"], ws, "Once", assignee_id=who["ben"])
    drain()
    assert len(inbox(clients["ben"], ws)) == 1
    with SessionLocal() as s:  # the same event handled again, as after a crash between handling and saving the cursor
        consumer.from_events(s, list(s.scalars(select(Event).where(Event.type == "task.created"))))
        s.commit()
    assert len(inbox(clients["ben"], ws)) == 1


# --- preferences ------------------------------------------------------------------------------------------------

def test_scope_all_hears_about_every_assignment_and_scope_mine_only_your_own(team):
    clients, who, ws = team
    save_prefs(clients["cara"], ws, task_assigned={"scope": "all"})
    make(clients["ann"], ws, "For Ben", assignee_id=who["ben"])
    make(clients["ann"], ws, "For Cara", assignee_id=who["cara"])
    drain()
    assert [(n["title"], n["body"]) for n in inbox(clients["cara"], ws)] == [
        ("a assigned you a task", "For Cara"), ("a assigned a task to M", "For Ben")]
    assert [n["body"] for n in inbox(clients["ben"], ws)] == ["For Ben"]  # Ben kept the default: only his own
    assert unread(clients["cara"], ws) == 2


def test_a_scope_all_person_who_is_also_the_assignee_gets_one_notification(team):
    clients, who, ws = team
    save_prefs(clients["ben"], ws, task_assigned={"scope": "all"})
    make(clients["ann"], ws, "Both", assignee_id=who["ben"])
    drain()
    assert [n["title"] for n in inbox(clients["ben"], ws)] == ["a assigned you a task"]


def test_scope_all_hears_only_about_what_the_watchers_role_lets_them_see(team):
    clients, who, ws = team
    ann = clients["ann"]
    narrow = make_role(ann, ws, "Own contacts, no tasks", capabilities=["contacts.read", "schema.read"],
                       rules=[rule("contact", "own")])
    assert ann.put(f"/api/v1/members/{who['cara']}", json={"role_id": narrow["id"]}, headers={H: ws}).status_code == 200
    save_prefs(clients["cara"], ws, task_assigned={"scope": "all"}, record_assigned={"scope": "all"})
    make(ann, ws, "For Ben", assignee_id=who["ben"])
    make_record(ann, ws, first_name="Ada", owner_id=who["ben"])
    drain()
    assert inbox(clients["cara"], ws) == []  # no tasks.read, and Ada is outside her scope
    make_record(ann, ws, first_name="Grace", owner_id=who["cara"])
    drain()
    assert [n["title"] for n in inbox(clients["cara"], ws)] == ["a assigned you Grace"]


def test_switching_off_the_in_app_channel_stops_that_kind_only(team):
    clients, who, ws = team
    save_prefs(clients["ben"], ws, task_assigned={"channels": []})
    make(clients["ann"], ws, "Quiet", assignee_id=who["ben"])
    make_record(clients["ann"], ws, first_name="Ada", owner_id=who["ben"])
    drain()
    assert [n["kind"] for n in inbox(clients["ben"], ws)] == ["record_assigned"]


def test_preferences_are_per_person_and_per_workspace(team, make_user):
    clients, who, ws = team
    save_prefs(clients["ben"], ws, task_assigned={"scope": "all", "channels": ["in_app", "email"], "digest": "daily"})
    ben = {p["kind"]: p for p in clients["ben"].get(f"{N}/prefs", headers={H: ws}).json()["data"]}
    assert (ben["task_assigned"]["scope"], ben["task_assigned"]["channels"], ben["task_assigned"]["digest"]) == (
        "all", ["in_app", "email"], "daily")
    cara = {p["kind"]: p for p in clients["cara"].get(f"{N}/prefs", headers={H: ws}).json()["data"]}
    assert cara["task_assigned"]["scope"] == "mine" and cara["task_assigned"]["channels"] == ["in_app"]
    second = clients["ann"].post("/api/workspaces", json={"name": "Second", "brand_id": clients["ann"].get(
        "/api/me").json()["orgs"][0]["brands"][0]["id"]}).json()["id"]
    elsewhere = clients["ann"].get(f"{N}/prefs", headers={H: second}).json()["data"]
    assert all(p["scope"] == "mine" for p in elsewhere)


def test_preferences_start_from_defaults_and_save_what_is_sent(team):
    clients, who, ws = team
    first = clients["ben"].get(f"{N}/prefs", headers={H: ws}).json()["data"]
    assert [p["kind"] for p in first] == ["task_assigned", "task_due", "record_assigned", "workflow",
                                              "billing"]
    assert all(p["label"] and p["channels"] == ["in_app"] and p["scope"] == "mine" and p["digest"] == "off"
               and p["quiet_start"] is None and p["quiet_end"] is None and p["tz"] is None for p in first)
    paris = {"quiet_start": "22:00", "quiet_end": "07:30", "tz": "Europe/Paris"}
    saved = save_prefs(clients["ben"], ws, task_due=paris)
    due = {p["kind"]: p for p in saved["data"]}["task_due"]
    assert (due["quiet_start"], due["quiet_end"], due["tz"]) == ("22:00", "07:30", "Europe/Paris")
    again = save_prefs(clients["ben"], ws, task_assigned={"scope": "all"})  # task_due keeps what it had
    kept = {p["kind"]: p for p in again["data"]}
    assert kept["task_due"]["quiet_start"] == "22:00" and kept["task_assigned"]["scope"] == "all"
    assert clients["ben"].get(f"{N}/prefs", headers={H: ws}).json() == again


@pytest.mark.parametrize("entry", [
    {"kind": "nothing"}, {"kind": "task_due", "scope": "nobody"}, {"kind": "task_due", "channels": ["sms"]},
    {"kind": "task_due", "digest": "weekly"}, {"kind": "task_due", "quiet_start": "22:00"},
    {"kind": "task_due", "quiet_end": "07:00"}, {"kind": "task_due", "quiet_start": "late", "quiet_end": "07:00"},
    {"kind": "task_due", "tz": "Nowhere/Land"}, {"kind": "task_due", "quiet_start": "22:00", "quiet_end": "07:00",
                                                 "tz": "x" * 65}])
def test_invalid_preferences_are_refused(team, entry):
    clients, who, ws = team
    r = clients["ben"].put(f"{N}/prefs", json={"prefs": [entry]}, headers={H: ws})
    assert r.status_code == 422, r.text
    assert all(p["scope"] == "mine" and p["quiet_start"] is None
               for p in clients["ben"].get(f"{N}/prefs", headers={H: ws}).json()["data"])


def test_preferences_need_at_least_one_entry_and_each_kind_once(team):
    clients, who, ws = team
    for body in ({"prefs": []}, {}, {"prefs": [{"kind": "task_due"}, {"kind": "task_due"}]}):
        assert clients["ben"].put(f"{N}/prefs", json=body, headers={H: ws}).status_code == 422


# --- quiet hours ------------------------------------------------------------------------------------------------

def hhmm(offset_minutes: int) -> str:
    return (datetime.now(UTC) + timedelta(minutes=offset_minutes)).strftime("%H:%M")


def test_quiet_hours_hold_a_notification_until_they_end(team, db):
    clients, who, ws = team
    ben = clients["ben"]
    save_prefs(ben, ws, task_assigned={"quiet_start": hhmm(-60), "quiet_end": hhmm(60), "tz": "UTC"})
    make(clients["ann"], ws, "Held", assignee_id=who["ben"])
    drain()
    assert inbox(ben, ws) == [] and unread(ben, ws) == 0  # it exists, but is not shown yet
    assert ben.post(f"{N}/read", json={"all": True}, headers={H: ws}).json() == {"updated": 0}
    db.expire_all()
    shows_at, read_at = db.execute(text("SELECT created_at, read_at FROM notifications")).one()
    assert read_at is None and timedelta(minutes=55) < shows_at - datetime.now(UTC) < timedelta(minutes=65)
    db.execute(text("UPDATE notifications SET created_at = now()"))  # the quiet hours end
    db.commit()
    assert [n["body"] for n in inbox(ben, ws)] == ["Held"] and unread(ben, ws) == 1


def test_outside_quiet_hours_a_notification_shows_at_once(team):
    clients, who, ws = team
    ben = clients["ben"]
    save_prefs(ben, ws, task_assigned={"quiet_start": hhmm(120), "quiet_end": hhmm(180), "tz": "UTC"})
    make(clients["ann"], ws, "Now", assignee_id=who["ben"])
    drain()
    assert [n["body"] for n in inbox(ben, ws)] == ["Now"]


def test_quiet_hours_are_read_in_the_persons_zone_and_may_cross_midnight(team, db):
    clients, who, ws = team
    ben = clients["ben"]
    # a window around the wall clock of Paris right now (it crosses midnight at some hours of the day)
    hour = datetime.now(UTC).astimezone(ZoneInfo("Europe/Paris")).hour
    window = {"quiet_start": f"{(hour - 1) % 24:02d}:00", "quiet_end": f"{(hour + 2) % 24:02d}:00"}
    save_prefs(ben, ws, task_assigned={**window, "tz": "Europe/Paris"})
    make(clients["ann"], ws, "Paris", assignee_id=who["ben"])
    drain()
    assert inbox(ben, ws) == []  # quiet in Paris
    save_prefs(ben, ws, task_assigned={**window, "tz": "Pacific/Kiritimati"})  # the same hours, 12 or 13 hours away
    make(clients["ann"], ws, "Elsewhere", assignee_id=who["ben"])
    drain()
    assert [n["body"] for n in inbox(ben, ws)] == ["Elsewhere"]


# --- the due-time job -------------------------------------------------------------------------------------------

def due_jobs(db) -> list[dict]:
    db.expire_all()
    rows = db.execute(text("SELECT status, payload FROM jobs WHERE kind = 'task.due' ORDER BY id"))
    return [r._asdict() for r in rows]


def elapse(db, task_id) -> None:
    """Time passes for one task: its due time, and the planned job's copy of it, are a moment ago, and the job is due.
    (Waiting for a real clock would make these tests depend on how busy the machine is.)"""
    past = datetime.now(UTC) - timedelta(seconds=1)
    db.execute(text("UPDATE tasks SET due_at = :d WHERE id = :i"), {"d": past, "i": task_id})
    db.execute(text("UPDATE jobs SET run_at = now(), payload = jsonb_set(payload, '{due_at}', "
                    "to_jsonb(CAST(:s AS text))) WHERE kind = 'task.due' AND payload->>'task_id' = :i"),
               {"s": past.isoformat(), "i": task_id})
    db.commit()


def in_an_hour() -> str:
    return iso(datetime.now(UTC) + timedelta(hours=1))


def test_a_task_due_notification_is_sent_once_at_the_due_time(team, db):
    clients, who, ws = team
    task = make(clients["ann"], ws, "Send the quote", assignee_id=who["ben"], due_at=in_an_hour())
    drain()
    assert [n["kind"] for n in inbox(clients["ben"], ws)] == ["task_assigned"]  # not due yet: the job waits
    assert [j["status"] for j in due_jobs(db)] == ["queued"]
    elapse(db, task["id"])
    drain()
    assert [n["kind"] for n in inbox(clients["ben"], ws)] == ["task_due", "task_assigned"]
    note = inbox(clients["ben"], ws)[0]
    assert note["title"] == "Due now: Send the quote" and note["link"] == f"/tasks?task={task['id']}"
    assert note["subject"] == {"type": "task", "id": task["id"]}
    with SessionLocal() as s:  # a second run of the same job (a retry, a duplicate) does nothing more
        jobs.HANDLERS["task.due"](s, due_jobs(db)[0]["payload"])
        s.commit()
    assert len(inbox(clients["ben"], ws)) == 2
    assert inbox(clients["ann"], ws) == [] and inbox(clients["cara"], ws) == []


def test_a_finished_moved_or_reassigned_task_is_not_announced_as_due(team, db):
    clients, who, ws = team
    ann = clients["ann"]
    control, finished, moved, dropped, deleted = (
        make(ann, ws, title, assignee_id=who["ben"], due_at=in_an_hour())
        for title in ("Control", "Finished", "Moved", "Dropped", "Deleted"))
    ann.post(f"{T}/{finished['id']}/complete", headers={H: ws})
    ann.patch(f"{T}/{moved['id']}", json={"due_at": iso(datetime.now(UTC) + timedelta(days=1))}, headers={H: ws})
    ann.patch(f"{T}/{dropped['id']}", json={"assignee_id": None}, headers={H: ws})
    ann.delete(f"{T}/{deleted['id']}", headers={H: ws})
    drain()
    elapse(db, control["id"])  # the control is really due; every other job runs too, early, and must do nothing
    due_now(db)
    drain()
    assert [n["title"] for n in inbox(clients["ben"], ws, limit=50) if n["kind"] == "task_due"] == ["Due now: Control"]


def test_a_task_without_an_assignee_or_a_time_has_no_due_job(team, db):
    clients, who, ws = team
    ann = clients["ann"]
    later = iso(datetime.now(UTC) + timedelta(days=2))
    make(ann, ws, "Nobody", due_at=later)
    make(ann, ws, "All day", assignee_id=who["ben"], due_at=later, all_day=True)
    make(ann, ws, "No date", assignee_id=who["ben"])
    make(ann, ws, "Already late", assignee_id=who["ben"], due_at=iso(datetime.now(UTC) - timedelta(days=1)))
    assert due_jobs(db) == []
    task = make(ann, ws, "Later assigned", due_at=later)
    ann.patch(f"{T}/{task['id']}", json={"assignee_id": who["ben"]}, headers={H: ws})
    assert len(due_jobs(db)) == 1  # assigning a dated task plans the reminder


def test_scope_all_people_hear_when_any_task_is_due(team, db):
    clients, who, ws = team
    save_prefs(clients["cara"], ws, task_due={"scope": "all"})
    task = make(clients["ann"], ws, "Ben's", assignee_id=who["ben"], due_at=in_an_hour())
    elapse(db, task["id"])
    drain()
    assert [n["kind"] for n in inbox(clients["ben"], ws)] == ["task_due", "task_assigned"]
    assert [n["title"] for n in inbox(clients["cara"], ws)] == ["Due now: Ben's"]


# --- the bell's API ---------------------------------------------------------------------------------------------

def test_listing_pages_newest_first_and_filters_unread(team):
    clients, who, ws = team
    ben = clients["ben"]
    for n in range(5):
        make(clients["ann"], ws, f"t{n}", assignee_id=who["ben"])
    drain()
    seen, cursor = [], None
    while True:
        r = ben.get(N, params={"limit": 2, **({"cursor": cursor} if cursor else {})}, headers={H: ws}).json()
        seen += [n["body"] for n in r["data"]]
        cursor = r["next_cursor"]
        if not cursor:
            break
    assert sorted(seen) == [f"t{n}" for n in range(5)] and len(set(seen)) == 5
    first = inbox(ben, ws)[0]
    assert ben.post(f"{N}/read", json={"ids": [first["id"]]}, headers={H: ws}).json() == {"updated": 1}
    assert first["id"] not in [n["id"] for n in inbox(ben, ws, unread=True)] and len(inbox(ben, ws, unread=True)) == 4
    assert unread(ben, ws) == 4 and len(inbox(ben, ws)) == 5
    assert ben.post(f"{N}/read", json={"ids": [first["id"]]}, headers={H: ws}).json() == {"updated": 0}  # already read
    assert ben.get(N, params={"cursor": "garbage"}, headers={H: ws}).status_code == 400
    assert ben.get(N, params={"limit": 0}, headers={H: ws}).status_code == 422


def test_marking_read_by_ids_or_all(team):
    clients, who, ws = team
    ben = clients["ben"]
    for n in range(3):
        make(clients["ann"], ws, f"t{n}", assignee_id=who["ben"])
    drain()
    ids = [n["id"] for n in inbox(ben, ws)]
    assert ben.post(f"{N}/read", json={"ids": ids[:2]}, headers={H: ws}).json() == {"updated": 2}
    assert unread(ben, ws) == 1
    assert ben.post(f"{N}/read", json={"all": True}, headers={H: ws}).json() == {"updated": 1}
    assert unread(ben, ws) == 0 and all(n["read_at"] for n in inbox(ben, ws))
    for body in ({}, {"ids": []}, {"ids": ids, "all": True}, {"ids": ["nope"]}, {"all": False}):
        assert ben.post(f"{N}/read", json=body, headers={H: ws}).status_code == 422, body


def test_other_people_in_the_workspace_cannot_see_or_mark_a_notification(team):
    clients, who, ws = team
    make(clients["ann"], ws, "For Ben", assignee_id=who["ben"])
    drain()
    [note] = inbox(clients["ben"], ws)
    for other in ("ann", "cara"):
        assert inbox(clients[other], ws) == [] and unread(clients[other], ws) == 0
        assert clients[other].post(f"{N}/read", json={"ids": [note["id"]]}, headers={H: ws}).json() == {"updated": 0}
        assert clients[other].post(f"{N}/read", json={"all": True}, headers={H: ws}).json() == {"updated": 0}
    assert unread(clients["ben"], ws) == 1  # still unread


def context(conn, **ctx):
    conn.execute(text("SET LOCAL ROLE gohigh_app"))
    for key in ("user_id", "org_id", "workspace_id", "system"):
        conn.execute(text("SELECT set_config(:k, :v, true)"), {"k": f"app.{key}", "v": str(ctx.get(key, ""))})


def test_row_level_security_shows_a_notification_to_its_user_alone(team):
    clients, who, ws = team
    make(clients["ann"], ws, "For Ben", assignee_id=who["ben"])
    save_prefs(clients["ben"], ws, task_due={"scope": "all"})
    drain()
    def seen(conn, table):
        return conn.execute(text(f"SELECT count(*) FROM {table}")).scalar()

    with engine.connect() as conn:
        for table in ("notifications", "notification_prefs"):
            expected = {"ben": 1, "ann": 0, "cara": 0}
            for name, count in expected.items():
                with conn.begin():
                    context(conn, workspace_id=ws, user_id=who[name])
                    assert seen(conn, table) == count, (table, name)
            with conn.begin():  # the workspace alone is not enough, and neither is the user alone
                context(conn, workspace_id=ws)
                assert seen(conn, table) == 0
            with conn.begin():
                context(conn, user_id=who["ben"])
                assert seen(conn, table) == 0
            with conn.begin():
                context(conn, workspace_id=str(uuid.uuid4()), user_id=who["ben"])
                assert seen(conn, table) == 0


def test_the_app_role_can_only_mark_read_never_create_or_rewrite_a_notification(team):
    clients, who, ws = team
    make(clients["ann"], ws, "For Ben", assignee_id=who["ben"])
    drain()
    forged = ("INSERT INTO notifications (workspace_id, user_id, kind, title) "
              f"VALUES ('{ws}', '{who['cara']}', 'k', 't')")
    with engine.connect() as conn:
        for statement in (forged, "UPDATE notifications SET title = 'x'", "UPDATE notifications SET user_id = user_id",
                          "DELETE FROM notifications"):
            with pytest.raises(DBAPIError, match="permission denied"), conn.begin():
                context(conn, workspace_id=ws, user_id=who["ben"])
                conn.execute(text(statement))
        with conn.begin():
            context(conn, workspace_id=ws, user_id=who["ben"])
            assert conn.execute(text("UPDATE notifications SET read_at = now()")).rowcount == 1
        with conn.begin():
            context(conn, workspace_id=ws, user_id=who["cara"])
            assert conn.execute(text("UPDATE notifications SET read_at = NULL")).rowcount == 0
