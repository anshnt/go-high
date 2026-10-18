"""A speed check for lists: 20 000 contacts in one workspace, a filtered, sorted page in under 300 ms.
Marked `perf`: the number depends on the machine, so CI can leave it out with `pytest -m "not perf"`."""
import json
import statistics
import time

import pytest
from helpers import H
from sqlalchemy import text

pytestmark = pytest.mark.perf
CONTACTS = 20_000
BUDGET = 0.3  # seconds for one page, including authentication and JSON


def fill(db, ws: str) -> None:
    db.execute(text("""
        INSERT INTO records (workspace_id, object_id, display_name, "values", email_norm, created_at, updated_at)
        SELECT w.id, o.id, 'Person ' || g || ' Example',
               jsonb_build_object('first_name', 'Person ' || g, 'last_name', 'Example',
                                  'email', 'person' || g || '@example.com',
                                  'lifecycle', (ARRAY['lead', 'customer', 'other', 'churned'])[1 + g % 4]),
               'person' || g || '@example.com',
               now() - (g % 90) * interval '1 day' - g * interval '1 second', now() - g * interval '1 second'
        FROM workspaces w JOIN objects o ON o.workspace_id = w.id AND o.key = 'contact',
             generate_series(1, :n) g WHERE w.id = CAST(:w AS uuid)"""), {"n": CONTACTS, "w": ws})
    db.execute(text("ANALYZE records"))
    db.commit()


def timed(client, ws: str, **params) -> tuple[float, dict]:
    runs = []
    for _ in range(6):  # the first run warms the connection and the caches
        start = time.perf_counter()
        r = client.get("/api/v1/objects/contact/records", params=params, headers={H: ws})
        runs.append(time.perf_counter() - start)
        assert r.status_code == 200, r.text
    return statistics.median(runs[1:]), r.json()


def test_a_filtered_sorted_page_of_20000_contacts_is_quick(crm, db):
    client, ws, _ = crm
    fill(db, ws)
    assert db.scalar(text("SELECT count(*) FROM records")) == CONTACTS
    recent_leads = {"and": [{"field": "lifecycle", "op": "is", "value": "lead"},
                            {"field": "created_at", "op": "within_last", "value": {"days": 30}},
                            {"field": "email", "op": "contains", "value": "example.com"}]}
    cases = {
        "filtered, sorted by name": dict(filter=json.dumps(recent_leads), sort="display_name"),
        "filtered, sorted by newest": dict(filter=json.dumps(recent_leads), sort="-created_at"),
        "filtered, sorted, counted": dict(filter=json.dumps(recent_leads), sort="lifecycle,-display_name",
                                          count="true"),
        "default list": {},
        "text search by prefix": dict(q="person 19"),
    }
    for label, params in cases.items():
        seconds, page = timed(client, ws, limit=50, **params)
        print(f"perf: {label}: {seconds * 1000:.0f} ms for {len(page['data'])} rows")
        assert len(page["data"]) == 50, label
        assert seconds < BUDGET, f"{label} took {seconds * 1000:.0f} ms"
    # a second page through a cursor is as quick
    first = client.get("/api/v1/objects/contact/records", params={"filter": json.dumps(recent_leads),
                                                                  "sort": "display_name", "limit": 50},
                       headers={H: ws}).json()
    start = time.perf_counter()
    second = client.get("/api/v1/objects/contact/records", params={"filter": json.dumps(recent_leads),
                                                                   "sort": "display_name", "limit": 50,
                                                                   "cursor": first["next_cursor"]}, headers={H: ws})
    assert second.status_code == 200 and time.perf_counter() - start < BUDGET
    assert not {r["id"] for r in first["data"]} & {r["id"] for r in second.json()["data"]}
