"""Tasks: CRUD and validation, filters and cursors, finishing, recurrence through the API, dependencies, bulk changes,
the manual order, My Day, the people list, and the events every change emits."""
import uuid
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from helpers import H, add_member, make_record
from sqlalchemy import text

T = "/api/v1/tasks"
NOW = datetime.now(UTC)
TODAY = NOW.date()


def iso(when) -> str:
    return when.astimezone(UTC).isoformat().replace("+00:00", "Z")


def midnight(days: int = 0) -> str:
    """An all-day task's due date: midnight UTC of the date `days` from today."""
    return iso(datetime.combine(TODAY + timedelta(days=days), datetime.min.time(), UTC))


def due(task: dict) -> str | None:
    """A task's due time as UTC with a Z, however the server wrote the offset."""
    return task["due_at"] and iso(datetime.fromisoformat(task["due_at"]))


def make(client, ws, title="Call Ada", **body) -> dict:
    r = client.post(T, json={"title": title, **body}, headers={H: ws})
    assert r.status_code == 201, r.text
    return r.json()


def listing(client, ws, **params) -> dict:
    r = client.get(T, params=params, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


def titles(client, ws, **params) -> list[str]:
    return [t["title"] for t in listing(client, ws, **params)["data"]]


def complete(client, ws, task_id, tz="UTC", status=200) -> dict:
    r = client.post(f"{T}/{task_id}/complete", params={"tz": tz}, headers={H: ws})
    assert r.status_code == status, r.text
    return r.json()


def patch(client, ws, task_id, **body) -> dict:
    r = client.patch(f"{T}/{task_id}", json=body, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


def events_of(db, kind) -> list[dict]:
    db.expire_all()
    return [e for (e,) in db.execute(text("SELECT data FROM events WHERE type = :t ORDER BY id"), {"t": kind})]


def error_fields(response) -> dict:
    assert response.status_code == 422, response.text
    return response.json()["error"]["fields"]


def test_a_task_has_sensible_defaults_and_is_returned_with_its_record_and_dependency(crm):
    client, ws, ids = crm
    ada = make_record(client, ws, first_name="Ada", last_name="Lovelace")
    first = make(client, ws, "Draft the proposal")
    assert first["status"] == "open" and first["priority"] == "none" and first["notes"] == ""
    assert first["due_at"] is None and first["all_day"] is False and first["assignee_id"] is None
    assert first["record"] is None and first["depends_on"] is None and first["recurrence"] is None
    assert first["completed_at"] is None and first["parent_task_id"] is None and first["created_by"]
    second = make(client, ws, "Send it", record_id=ada["id"], depends_on_task_id=first["id"], priority="high",
                  notes="  keep the notes as typed ", due_at="2026-11-05T15:30:00+01:00")
    assert second["record"] == {"id": ada["id"], "object": "contact", "display_name": "Ada Lovelace"}
    assert second["depends_on"] == {"id": first["id"], "title": "Draft the proposal", "status": "open"}
    assert second["priority"] == "high" and second["notes"] == "  keep the notes as typed "
    assert due(second) == "2026-11-05T14:30:00Z"
    assert client.get(f"{T}/{second['id']}", headers={H: ws}).json() == second
    assert second["position"] > first["position"]  # new tasks go last


def test_creating_a_task_validates_every_field(crm, db):
    client, ws, ids = crm

    def post(body):
        return client.post(T, json=body, headers={H: ws})

    assert error_fields(post({})) == {"title": "Field required"}
    assert "title" in error_fields(post({"title": "   "}))
    assert "title" in error_fields(post({"title": "x" * 301}))
    assert "priority" in error_fields(post({"title": "a", "priority": "urgent"}))
    assert "due_at" in error_fields(post({"title": "a", "due_at": "2026-11-05T10:00:00"}))  # no time zone
    assert "assignee_id" in error_fields(post({"title": "a", "assignee_id": str(uuid.uuid4())}))
    assert "record_id" in error_fields(post({"title": "a", "record_id": str(uuid.uuid4())}))
    assert "depends_on_task_id" in error_fields(post({"title": "a", "depends_on_task_id": str(uuid.uuid4())}))
    assert "recurrence" in error_fields(post({"title": "a", "due_at": midnight(), "recurrence": "FREQ=HOURLY"}))
    assert error_fields(post({"title": "a", "recurrence": "FREQ=DAILY"})) == {
        "recurrence": "a repeating task needs a due date"}
    assert post({"title": "a\u0000b"}).status_code == 422
    # a trashed record cannot be linked, nor can someone who is in the organization but not this workspace be assigned
    trashed = make_record(client, ws, first_name="Gone")
    client.delete(f"/api/v1/objects/contact/records/{trashed['id']}", headers={H: ws})
    assert "record_id" in error_fields(post({"title": "a", "record_id": trashed["id"]}))
    outsider = add_member(db, ids["org_id"], "outsider@example.com")
    outsider_id = outsider.get("/api/me").json()["user"]["id"]
    assert "assignee_id" in error_fields(post({"title": "a", "assignee_id": outsider_id}))
    assert listing(client, ws)["data"] == []  # nothing half-saved


def test_an_idempotency_key_makes_a_retried_create_return_the_same_task(crm):
    client, ws, ids = crm
    first = client.post(T, json={"title": "Once"}, headers={H: ws, "Idempotency-Key": "k-1"})
    again = client.post(T, json={"title": "Once"}, headers={H: ws, "Idempotency-Key": "k-1"})
    assert first.status_code == again.status_code == 201 and again.headers["Idempotent-Replayed"] == "true"
    assert again.json() == first.json() and titles(client, ws) == ["Once"]


def test_an_all_day_task_is_due_on_a_date_whatever_time_is_sent(crm):
    client, ws, ids = crm
    task = make(client, ws, due_at="2026-11-05T23:15:00+05:00", all_day=True)  # 18:15 UTC on the 5th
    assert due(task) == "2026-11-05T00:00:00Z" and task["all_day"] is True
    assert due(patch(client, ws, task["id"], all_day=False)) == "2026-11-05T00:00:00Z"
    assert due(patch(client, ws, task["id"], due_at="2026-11-06T09:30:00Z", all_day=True)) == "2026-11-06T00:00:00Z"


def test_updating_a_task_changes_only_what_is_sent_and_nulls_clear(crm, db):
    client, ws, ids = crm
    me = client.get("/api/me").json()["user"]["id"]
    task = make(client, ws, "Draft", notes="n", due_at=midnight(3), all_day=True, assignee_id=me, priority="low")
    changed = patch(client, ws, task["id"], title="Final draft", priority="high", due_at=None, all_day=False)
    assert (changed["title"], changed["priority"], changed["due_at"], changed["notes"], changed["assignee_id"]) == (
        "Final draft", "high", None, "n", me)
    assert patch(client, ws, task["id"], assignee_id=None)["assignee_id"] is None
    for field in ("title", "notes", "priority", "all_day"):
        assert field in error_fields(client.patch(f"{T}/{task['id']}", json={field: None}, headers={H: ws}))
    assert client.patch(f"{T}/{uuid.uuid4()}", json={"title": "x"}, headers={H: ws}).status_code == 404
    updates = events_of(db, "task.updated")
    assert len(updates) == 2
    assert updates[0]["changes"].keys() == {"title", "priority", "due_at", "all_day"}
    assert updates[0]["changes"]["title"] == {"old": "Draft", "new": "Final draft"}
    assert patch(client, ws, task["id"], title="Final draft")["title"] == "Final draft"
    assert len(events_of(db, "task.updated")) == 2  # no change, no event


def test_every_change_emits_its_event_with_the_full_state(crm, db):
    client, ws, ids = crm
    task = make(client, ws, "Chase", due_at=midnight(1), all_day=True, recurrence="FREQ=DAILY")
    created = events_of(db, "task.created")[0]
    assert created["id"] == task["id"] and created["title"] == "Chase" and created["status"] == "open"
    assert created["recurrence"] == "FREQ=DAILY" and created["parent_task_id"] is None
    done = complete(client, ws, task["id"])
    finished = events_of(db, "task.completed")[0]
    assert finished["status"] == "done" and finished["next_task_id"] == done["next"]["id"]
    assert events_of(db, "task.created")[1]["parent_task_id"] == task["id"]  # the next occurrence announces itself
    assert client.delete(f"{T}/{done['next']['id']}", headers={H: ws}).status_code == 204
    assert events_of(db, "task.deleted") == [{"id": done["next"]["id"], "title": "Chase"}]
    actors = db.execute(text("SELECT DISTINCT actor_type FROM events WHERE type LIKE 'task.%'")).scalars().all()
    assert actors == ["user"]


def test_deleting_a_task_is_a_404_the_second_time_and_takes_nothing_else(crm):
    client, ws, ids = crm
    make(client, ws, "Keep")
    gone = make(client, ws, "Gone")
    assert client.delete(f"{T}/{gone['id']}", headers={H: ws}).status_code == 204
    assert client.delete(f"{T}/{gone['id']}", headers={H: ws}).status_code == 404
    assert client.get(f"{T}/{gone['id']}", headers={H: ws}).status_code == 404
    assert titles(client, ws) == ["Keep"]


# --- listing --------------------------------------------------------------------------------------------------

@pytest.fixture
def board(crm, db):
    """Two people in one workspace and tasks in every state: (my client, their client, ws, my id, their id, tasks)."""
    mine, ws, ids = crm
    theirs = add_member(db, ids["org_id"], "ben@example.com", workspace_id=ws)
    me, ben = (c.get("/api/me").json()["user"]["id"] for c in (mine, theirs))
    ada = make_record(mine, ws, first_name="Ada")
    tasks = {
        "late": make(mine, ws, "late", assignee_id=me, due_at=iso(NOW - timedelta(hours=2))),
        "yesterday": make(mine, ws, "yesterday", assignee_id=me, due_at=midnight(-1), all_day=True),
        "today": make(mine, ws, "today", assignee_id=me, due_at=midnight(0), all_day=True),
        "soon": make(mine, ws, "soon", assignee_id=ben, due_at=midnight(2), all_day=True, record_id=ada["id"]),
        "someday": make(mine, ws, "someday"),
        "free": make(mine, ws, "free", assignee_id=ben),
    }
    tasks["finished"] = make(mine, ws, "finished", assignee_id=me, due_at=midnight(-1), all_day=True)
    complete(mine, ws, tasks["finished"]["id"])
    return mine, theirs, ws, me, ben, tasks, ada


def test_listing_filters_by_assignee(board):
    mine, theirs, ws, me, ben, tasks, ada = board
    assert titles(mine, ws, assignee="me") == ["late", "yesterday", "today", "finished"]
    assert titles(theirs, ws, assignee="me") == ["soon", "free"]
    assert titles(mine, ws, assignee="unassigned") == ["someday"]
    assert titles(mine, ws, assignee=ben) == ["soon", "free"]
    assert titles(mine, ws) == titles(mine, ws, assignee="anyone") == [
        "late", "yesterday", "today", "soon", "someday", "free", "finished"]
    assert "assignee" in error_fields(mine.get(T, params={"assignee": "nobody"}, headers={H: ws}))


def test_listing_filters_by_status_record_and_completion(board):
    mine, theirs, ws, me, ben, tasks, ada = board
    assert titles(mine, ws, status="done") == ["finished"]
    assert titles(mine, ws, status="open") == ["late", "yesterday", "today", "soon", "someday", "free"]
    assert titles(mine, ws, record_id=ada["id"]) == ["soon"]
    assert titles(mine, ws, record_id=str(uuid.uuid4())) == []
    fresh = datetime.now(UTC)  # not NOW: a long test run starts this test long after the module was imported
    assert titles(mine, ws, status="done", completed_after=iso(fresh - timedelta(minutes=5))) == ["finished"]
    assert titles(mine, ws, status="done", completed_after=iso(fresh + timedelta(minutes=5))) == []
    assert titles(mine, ws, assignee="me", status="open") == ["late", "yesterday", "today"]


def test_listing_filters_by_due_bucket_in_the_readers_time_zone(board):
    mine, theirs, ws, me, ben, tasks, ada = board
    assert titles(mine, ws, due="overdue") == ["late", "yesterday"]  # a finished task is never overdue
    assert titles(mine, ws, due="today") == ["today"]
    assert titles(mine, ws, due="upcoming") == ["soon"]
    assert titles(mine, ws, due="none") == ["someday", "free"]
    assert titles(mine, ws, due="overdue", assignee="me", status="open") == ["late", "yesterday"]
    # an all-day task is due on its date whoever looks, but which date is today depends on the reader's zone
    for tz in ("Pacific/Kiritimati", "Pacific/Pago_Pago", "America/New_York"):
        local = datetime.now(ZoneInfo(tz)).date()
        for title, days in (("yesterday", -1), ("today", 0), ("soon", 2)):
            when = TODAY + timedelta(days=days)
            expected = "overdue" if when < local else "today" if when == local else "upcoming"
            for bucket in ("overdue", "today", "upcoming"):
                found = title in titles(mine, ws, due=bucket, tz=tz)
                assert found == (bucket == expected), (tz, title, bucket)
    assert "tz" in error_fields(mine.get(T, params={"tz": "Mars/Olympus"}, headers={H: ws}))
    assert "tz" in error_fields(mine.get(T, params={"tz": "../etc"}, headers={H: ws}))


def test_listing_filters_by_a_due_range_for_calendars(board):
    mine, theirs, ws, me, ben, tasks, ada = board
    window = {"due_after": midnight(-1), "due_before": midnight(1)}
    assert titles(mine, ws, **window) == ["late", "yesterday", "today", "finished"]
    assert titles(mine, ws, due_after=midnight(1)) == ["soon"]
    assert "due_after" in error_fields(mine.get(T, params={"due_after": "2026-01-01"}, headers={H: ws}))


def test_listing_pages_with_a_cursor_in_manual_order(crm):
    client, ws, ids = crm
    for n in range(7):
        make(client, ws, f"t{n}")
    seen, cursor = [], None
    while True:
        page = listing(client, ws, limit=3, **({"cursor": cursor} if cursor else {}))
        seen += [t["title"] for t in page["data"]]
        cursor = page["next_cursor"]
        if not cursor:
            break
    assert seen == [f"t{n}" for n in range(7)]
    r = client.get(T, params={"cursor": "garbage"}, headers={H: ws})
    assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_cursor"
    assert client.get(T, params={"limit": 0}, headers={H: ws}).status_code == 422


def test_the_manual_order_can_be_changed(crm, db):
    client, ws, ids = crm
    a, b, c, d = (make(client, ws, name) for name in "abcd")

    def move(task, before):
        r = client.post(f"{T}/{task['id']}/reorder", json={"before_id": before and before["id"]}, headers={H: ws})
        assert r.status_code == 200, r.text
        return titles(client, ws)

    assert move(d, a) == ["d", "a", "b", "c"]
    assert move(a, None) == ["d", "b", "c", "a"]
    assert move(c, b) == ["d", "c", "b", "a"]
    assert move(c, c) == ["d", "c", "b", "a"]  # in front of itself: nothing moves
    assert client.post(f"{T}/{a['id']}/reorder", json={"before_id": str(uuid.uuid4())},
                       headers={H: ws}).status_code == 404
    moves = [e for e in events_of(db, "task.updated") if e["changes"].keys() == {"position"}]
    assert len(moves) == 3


# --- finishing, recurrence ----------------------------------------------------------------------------------

def test_finishing_and_reopening_a_task(crm, db):
    client, ws, ids = crm
    task = make(client, ws, "Send invoice")
    done = complete(client, ws, task["id"])
    assert done["status"] == "done" and done["completed_at"] and done["next"] is None
    again = complete(client, ws, task["id"])
    assert again["completed_at"] == done["completed_at"]  # finishing twice changes nothing
    assert len(events_of(db, "task.completed")) == 1
    reopened = client.post(f"{T}/{task['id']}/reopen", headers={H: ws}).json()
    assert reopened["status"] == "open" and reopened["completed_at"] is None
    assert client.post(f"{T}/{task['id']}/reopen", headers={H: ws}).json()["status"] == "open"
    assert len(events_of(db, "task.updated")) == 1
    assert complete(client, ws, uuid.uuid4(), status=404)["error"]["code"] == "not_found"
    assert client.post(f"{T}/{uuid.uuid4()}/reopen", headers={H: ws}).status_code == 404


def test_finishing_a_daily_task_creates_tomorrows_in_the_same_transaction(crm):
    client, ws, ids = crm
    me = client.get("/api/me").json()["user"]["id"]
    ada = make_record(client, ws, first_name="Ada")
    task = make(client, ws, "Stand up", due_at="2026-10-19T09:00:00Z", recurrence="FREQ=DAILY", assignee_id=me,
                priority="medium", notes="bring notes", record_id=ada["id"])
    following = complete(client, ws, task["id"])["next"]
    assert due(following) == "2026-10-20T09:00:00Z" and following["status"] == "open"
    assert following["recurrence"] == "FREQ=DAILY" and following["parent_task_id"] == task["id"]
    assert (following["title"], following["assignee_id"], following["priority"], following["notes"]) == (
        "Stand up", me, "medium", "bring notes")
    assert following["record"]["id"] == ada["id"] and following["position"] == task["position"]
    assert following["depends_on"] is None and following["id"] != task["id"]
    assert [t["title"] for t in listing(client, ws, status="open")["data"]] == ["Stand up"]
    third = complete(client, ws, following["id"])["next"]
    assert due(third) == "2026-10-21T09:00:00Z" and third["parent_task_id"] == task["id"]  # the series root


def test_a_task_that_fails_to_finish_leaves_no_next_occurrence_behind(crm):
    client, ws, ids = crm
    gate = make(client, ws, "Gate")
    task = make(client, ws, "Blocked", due_at=midnight(), all_day=True, recurrence="FREQ=DAILY",
                depends_on_task_id=gate["id"])
    assert complete(client, ws, task["id"], status=409)["error"]["code"] == "task_blocked"
    assert titles(client, ws) == ["Gate", "Blocked"]


def test_weekly_rules_with_days(crm):
    client, ws, ids = crm
    task = make(client, ws, "Report", due_at="2026-10-19T09:00:00Z", recurrence="FREQ=WEEKLY;BYDAY=WE,MO")
    assert task["recurrence"] == "FREQ=WEEKLY;BYDAY=MO,WE"  # stored in its canonical form
    found = []
    for _ in range(3):
        task = complete(client, ws, task["id"])["next"]
        found.append(due(task))
    assert found == ["2026-10-21T09:00:00Z", "2026-10-26T09:00:00Z", "2026-10-28T09:00:00Z"]


def test_monthly_on_the_last_day_does_not_drift(crm):
    client, ws, ids = crm
    task = make(client, ws, "Close the books", due_at="2027-01-31T17:00:00Z", recurrence="FREQ=MONTHLY")
    found = []
    for _ in range(3):
        task = complete(client, ws, task["id"])["next"]
        found.append(due(task))
    assert found == ["2027-02-28T17:00:00Z", "2027-03-31T17:00:00Z", "2027-04-30T17:00:00Z"]
    assert task["recurrence"] == "FREQ=MONTHLY;BYMONTHDAY=31"
    last = make(client, ws, "Invoice", due_at="2027-01-10T08:00:00Z", recurrence="FREQ=MONTHLY;BYMONTHDAY=-1")
    assert due(complete(client, ws, last["id"])["next"]) == "2027-01-31T08:00:00Z"


def test_count_and_until_end_a_series(crm):
    client, ws, ids = crm
    task = make(client, ws, "Three times", due_at="2026-10-19T09:00:00Z", recurrence="FREQ=DAILY;COUNT=3")
    task = complete(client, ws, task["id"])["next"]
    task = complete(client, ws, task["id"])["next"]
    assert due(task) == "2026-10-21T09:00:00Z"
    last = complete(client, ws, task["id"])
    assert last["status"] == "done" and last["next"] is None
    assert titles(client, ws, status="open") == []
    until = make(client, ws, "Until", due_at="2026-10-19T09:00:00Z", recurrence="FREQ=DAILY;UNTIL=20261021")
    until = complete(client, ws, until["id"])["next"]
    until = complete(client, ws, until["id"])["next"]
    assert due(until) == "2026-10-21T09:00:00Z"
    assert complete(client, ws, until["id"])["next"] is None


def test_a_timed_recurring_task_keeps_the_readers_wall_clock_through_a_clock_change(crm):
    client, ws, ids = crm
    task = make(client, ws, "Morning check", due_at="2026-10-31T13:00:00Z", recurrence="FREQ=DAILY")  # 9:00 in New York
    following = complete(client, ws, task["id"], tz="America/New_York")["next"]
    assert due(following) == "2026-11-01T14:00:00Z"  # 09:00 EST: the clocks went back that night
    after = complete(client, ws, following["id"], tz="America/New_York")["next"]
    assert due(after) == "2026-11-02T14:00:00Z"
    assert complete(client, ws, after["id"], tz="Not/AZone", status=422)["error"]["fields"] == {
        "tz": "is not a time zone"}


def test_an_all_day_recurring_task_moves_by_dates(crm):
    client, ws, ids = crm
    task = make(client, ws, "Water the plants", due_at="2026-10-19T00:00:00Z", all_day=True,
                recurrence="FREQ=WEEKLY;INTERVAL=2")
    following = complete(client, ws, task["id"], tz="Pacific/Auckland")["next"]
    assert due(following) == "2026-11-02T00:00:00Z" and following["all_day"] is True


def test_the_due_date_of_a_repeating_task_cannot_be_removed(crm):
    client, ws, ids = crm
    task = make(client, ws, "Weekly", due_at=midnight(), all_day=True, recurrence="FREQ=WEEKLY")
    r = client.patch(f"{T}/{task['id']}", json={"due_at": None}, headers={H: ws})
    assert error_fields(r) == {"due_at": "a repeating task needs a due date"}
    assert patch(client, ws, task["id"], due_at=None, recurrence=None)["recurrence"] is None
    plain = make(client, ws, "Plain")
    r = client.patch(f"{T}/{plain['id']}", json={"recurrence": "FREQ=DAILY"}, headers={H: ws})
    assert error_fields(r) == {"recurrence": "a repeating task needs a due date"}
    r = client.patch(f"{T}/{plain['id']}", json={"recurrence": "every day"}, headers={H: ws})
    assert "recurrence" in error_fields(r)


# --- dependencies -----------------------------------------------------------------------------------------------

def test_a_task_waits_for_the_task_it_depends_on(crm):
    client, ws, ids = crm
    design = make(client, ws, "Design")
    build = make(client, ws, "Build", depends_on_task_id=design["id"])
    blocked = complete(client, ws, build["id"], status=409)
    assert blocked["error"]["code"] == "task_blocked" and "Design" in blocked["error"]["message"]
    assert client.get(f"{T}/{build['id']}", headers={H: ws}).json()["status"] == "open"
    complete(client, ws, design["id"])
    assert complete(client, ws, build["id"])["status"] == "done"
    client.post(f"{T}/{design['id']}/reopen", headers={H: ws})  # reopening the first does not undo the second
    assert client.get(f"{T}/{build['id']}", headers={H: ws}).json()["status"] == "done"


def test_dependencies_cannot_be_circular_or_point_at_the_task_itself(crm):
    client, ws, ids = crm
    a = make(client, ws, "a")
    b = make(client, ws, "b", depends_on_task_id=a["id"])
    c = make(client, ws, "c", depends_on_task_id=b["id"])
    for target, wants in ((a, c), (a, b), (a, a)):
        r = client.patch(f"{T}/{target['id']}", json={"depends_on_task_id": wants["id"]}, headers={H: ws})
        assert "depends_on_task_id" in error_fields(r), (target["title"], wants["title"])
    assert patch(client, ws, c["id"], depends_on_task_id=a["id"])["depends_on"]["title"] == "a"  # a diamond is fine
    assert patch(client, ws, c["id"], depends_on_task_id=None)["depends_on"] is None


def test_deleting_a_task_frees_the_tasks_that_waited_for_it(crm, db):
    client, ws, ids = crm
    gate = make(client, ws, "Gate")
    waiting = make(client, ws, "Waiting", depends_on_task_id=gate["id"])
    assert client.delete(f"{T}/{gate['id']}", headers={H: ws}).status_code == 204
    freed = client.get(f"{T}/{waiting['id']}", headers={H: ws}).json()
    assert freed["depends_on_task_id"] is None and freed["depends_on"] is None
    assert complete(client, ws, waiting["id"])["status"] == "done"
    assert events_of(db, "task.updated")[0]["changes"]["depends_on_task_id"]["new"] is None


def test_deleting_the_first_task_of_a_series_keeps_the_rest(crm):
    client, ws, ids = crm
    first = make(client, ws, "Daily", due_at="2026-10-19T09:00:00Z", recurrence="FREQ=DAILY")
    second = complete(client, ws, first["id"])["next"]
    assert client.delete(f"{T}/{first['id']}", headers={H: ws}).status_code == 204
    kept = client.get(f"{T}/{second['id']}", headers={H: ws}).json()
    assert kept["parent_task_id"] is None and kept["status"] == "open"
    assert due(complete(client, ws, second["id"])["next"]) == "2026-10-21T09:00:00Z"


# --- bulk -------------------------------------------------------------------------------------------------------

def bulk(client, ws, ids, action, status=200, **body) -> dict:
    r = client.post(f"{T}/bulk", json={"ids": ids, "action": action, **body}, headers={H: ws})
    assert r.status_code == status, r.text
    return r.json()


def test_bulk_complete_finishes_many_and_recurs_each(board):
    mine, theirs, ws, me, ben, tasks, ada = board
    repeating = make(mine, ws, "Daily", due_at="2026-10-19T09:00:00Z", recurrence="FREQ=DAILY")
    ids = [tasks[k]["id"] for k in ("late", "today", "finished", "someday")] + [repeating["id"]]
    result = bulk(mine, ws, ids, "complete")
    assert [t["title"] for t in result["data"]] == ["late", "today", "someday", "Daily"]  # not the finished one again
    assert result["skipped"] == []
    assert titles(mine, ws, status="open") == ["yesterday", "soon", "free", "Daily"]
    assert due(listing(mine, ws, status="open")["data"][-1]) == "2026-10-20T09:00:00Z"


def test_bulk_complete_respects_dependencies_and_orders_them(crm):
    client, ws, ids = crm
    gate = make(client, ws, "Gate")
    after = make(client, ws, "After", depends_on_task_id=gate["id"])
    outside = make(client, ws, "Outside gate")
    stuck = make(client, ws, "Stuck", depends_on_task_id=outside["id"])
    # the dependent is listed first, and still finishes because its gate finishes in the same request
    result = bulk(client, ws, [after["id"], gate["id"], stuck["id"]], "complete")
    assert sorted(t["title"] for t in result["data"]) == ["After", "Gate"]
    assert result["skipped"] == [{"id": stuck["id"], "title": "Stuck", "reason": 'waits for "Outside gate"'}]
    assert titles(client, ws, status="open") == ["Outside gate", "Stuck"]


def test_bulk_assign_and_unassign(board, db):
    mine, theirs, ws, me, ben, tasks, ada = board
    ids = [tasks[k]["id"] for k in ("late", "today", "free")]
    result = bulk(mine, ws, ids, "assign", assignee_id=ben)
    assert [t["title"] for t in result["data"]] == ["late", "today"]  # "free" was already Ben's
    assert titles(mine, ws, assignee=ben) == ["late", "today", "soon", "free"]
    assert len(bulk(mine, ws, ids, "assign", assignee_id=None)["data"]) == 3
    assert titles(mine, ws, assignee="unassigned") == ["late", "today", "someday", "free"]
    refused = bulk(mine, ws, ids, "assign", status=422, assignee_id=str(uuid.uuid4()))
    assert "assignee_id" in refused["error"]["fields"]
    updates = [e for e in events_of(db, "task.updated") if "assignee_id" in e["changes"]]
    assert len(updates) == 2 + 3


def test_bulk_validates_its_request_and_ignores_ids_that_are_not_tasks(crm):
    client, ws, ids = crm
    task = make(client, ws, "Mine")
    assert client.post(f"{T}/bulk", json={"ids": [], "action": "complete"}, headers={H: ws}).status_code == 422
    assert client.post(f"{T}/bulk", json={"ids": [task["id"]], "action": "delete"}, headers={H: ws}).status_code == 422
    too_many = [str(uuid.uuid4()) for _ in range(201)]
    assert client.post(f"{T}/bulk", json={"ids": too_many, "action": "complete"}, headers={H: ws}).status_code == 422
    assert bulk(client, ws, [str(uuid.uuid4())], "complete") == {"data": [], "skipped": []}
    assert len(bulk(client, ws, [task["id"], str(uuid.uuid4())], "complete")["data"]) == 1


# --- My Day, people ---------------------------------------------------------------------------------------------

def test_my_day_lists_my_overdue_and_todays_tasks_with_counts(board):
    mine, theirs, ws, me, ben, tasks, ada = board
    r = mine.get("/api/v1/my-day", headers={H: ws})
    assert r.status_code == 200, r.text
    day = r.json()
    assert day["date"] == TODAY.isoformat() and day["timezone"] == "UTC"
    assert [t["title"] for t in day["tasks"]["overdue"]] == ["yesterday", "late"]  # oldest first
    assert [t["title"] for t in day["tasks"]["today"]] == ["today"]
    assert day["tasks"]["counts"] == {"overdue": 2, "today": 1, "done_today": 1}
    assert set(day) == {"date", "timezone", "tasks"}  # appointments and conversations add sections later
    other = theirs.get("/api/v1/my-day", headers={H: ws}).json()["tasks"]  # Ben's tasks have no dates
    assert other["overdue"] == [] and other["today"] == [] and other["counts"]["done_today"] == 0
    zoned = mine.get("/api/v1/my-day", params={"tz": "Pacific/Kiritimati"}, headers={H: ws}).json()
    assert zoned["timezone"] == "Pacific/Kiritimati"
    assert mine.get("/api/v1/my-day", params={"tz": "nope"}, headers={H: ws}).status_code == 422


def test_my_day_leaves_out_finished_unassigned_and_other_peoples_tasks(crm, db):
    client, ws, ids = crm
    ben = add_member(db, ids["org_id"], "ben@example.com", workspace_id=ws)
    me, theirs = client.get("/api/me").json()["user"]["id"], ben.get("/api/me").json()["user"]["id"]
    make(client, ws, "newer", assignee_id=me, due_at=midnight(-1), all_day=True)
    make(client, ws, "older", assignee_id=me, due_at=midnight(-5), all_day=True)
    make(client, ws, "nobody's", due_at=midnight(-3), all_day=True)
    make(client, ws, "ben's", assignee_id=theirs, due_at=midnight(-3), all_day=True)
    done = make(client, ws, "done", assignee_id=me, due_at=midnight(-2), all_day=True)
    complete(client, ws, done["id"])
    overdue = client.get("/api/v1/my-day", headers={H: ws}).json()["tasks"]["overdue"]
    assert [t["title"] for t in overdue] == ["older", "newer"]


def test_members_lists_the_people_of_this_workspace_only(crm, db, make_user):
    client, ws, ids = crm
    ben = add_member(db, ids["org_id"], "ben@example.com", workspace_id=ws)
    add_member(db, ids["org_id"], "outsider@example.com")  # in the organization, not in this workspace
    admin = add_member(db, ids["org_id"], "root@example.com", org_role="admin")
    stranger, stranger_ids = make_user("stranger@example.com")
    people = client.get("/api/v1/members", headers={H: ws}).json()["data"]
    assert [(p["email"], p["role"]) for p in people] == [
        ("a@example.com", "admin"), ("ben@example.com", "member"), ("root@example.com", "admin")]
    assert set(people[0]) == {"id", "name", "email", "role"}
    assert ben.get("/api/v1/members", headers={H: ws}).json()["data"] == people
    assert admin.get("/api/v1/members", headers={H: ws}).status_code == 200
    assert stranger.get("/api/v1/members", headers={H: ws}).status_code == 404  # not their workspace
    own = stranger.get("/api/v1/members", headers={H: stranger_ids["workspace_id"]}).json()["data"]
    assert [p["email"] for p in own] == ["stranger@example.com"]
    assert client.get("/api/v1/members").status_code == 400  # needs the workspace header
