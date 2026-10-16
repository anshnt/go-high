"""Sorting, keyset pagination and full text search on records."""
import json

import pytest
from helpers import H, make_record, names

OBJECTS = "/api/v1/objects"
R = f"{OBJECTS}/contact/records"


def page(client, ws, **params) -> dict:
    r = client.get(R, params={k: (json.dumps(v) if k == "filter" else v) for k, v in params.items()}, headers={H: ws})
    assert r.status_code == 200, r.text
    return r.json()


def walk(client, ws, limit=4, **params) -> list[dict]:
    """Every record of a listing, page by page."""
    out, cursor = [], None
    for _ in range(100):
        got = page(client, ws, limit=limit, **({"cursor": cursor} if cursor else {}), **params)
        out += got["data"]
        cursor = got["next_cursor"]
        if cursor is None:
            return out
    raise AssertionError("the cursor never ended")


def expected(rows: list[dict], keys: list[tuple]) -> list[str]:
    """The ids in sort order: per key (getter, descending), nulls last either way, ties by id in the direction of the
    first key, as the API promises."""
    def by(get, desc):  # a key that puts empty values last, whichever way the list is reversed
        def key(row):
            value = get(row)
            return ((value is not None) if desc else (value is None), 0 if value is None else value)
        return key

    rows = sorted(rows, key=lambda r: r["id"], reverse=keys[0][1])
    for get, desc in reversed(keys):
        rows.sort(key=by(get, desc), reverse=desc)
    return [r["id"] for r in rows]


@pytest.fixture
def people(crm):
    """Twenty-five contacts with plenty of ties and some empty values."""
    client, ws, _ = crm
    for key, type_ in (("score", "number"), ("joined", "date"), ("vip", "boolean"), ("budget", "money"),
                       ("notes", "long_text")):
        r = client.post(f"{OBJECTS}/contact/fields", json={"key": key, "label": key, "type": type_}, headers={H: ws})
        assert r.status_code == 201, r.text
    rows = []
    for i in range(25):
        values = {"first_name": f"person {i:02d}", "lifecycle": ["lead", "customer", "other"][i % 3]}
        if i % 5:
            values["score"] = i % 4  # four distinct scores, many ties
        if i % 4:
            values["joined"] = f"2024-0{1 + i % 6}-1{i % 9}"
        if i % 3:
            values["vip"] = i % 2 == 0
        if i % 6:
            values["budget"] = {"amount": (i % 5) * 1000, "currency": "USD"}
        rows.append(make_record(client, ws, **values))
    return client, ws, rows


def test_every_sort_pages_without_gaps_repeats_or_reordering(people):
    client, ws, rows = people
    getters = {"display_name": lambda r: r["display_name"], "score": lambda r: r["values"].get("score"),
               "joined": lambda r: r["values"].get("joined"), "vip": lambda r: r["values"].get("vip"),
               "budget": lambda r: (r["values"].get("budget") or {}).get("amount"),
               "lifecycle": lambda r: r["values"].get("lifecycle"), "created_at": lambda r: r["created_at"],
               "updated_at": lambda r: r["updated_at"]}
    for spec in ("display_name", "-display_name", "score", "-score", "joined", "-joined", "vip", "-vip", "budget",
                 "-budget", "lifecycle,-score", "-score,display_name", "score,joined,-budget", "-created_at",
                 "created_at", "-updated_at", "updated_at,-display_name"):
        keys = [(getters[s.removeprefix("-")], s.startswith("-")) for s in spec.split(",")]
        want = expected(rows, keys)
        got = [r["id"] for r in walk(client, ws, sort=spec)]
        assert got == want, spec  # right order, every record once
        assert [r["id"] for r in walk(client, ws, limit=25, sort=spec)] == want, spec
    assert [r["id"] for r in walk(client, ws, limit=1, sort="-score,display_name")] == expected(
        rows, [(getters["score"], True), (getters["display_name"], False)])
    # the nulls: sorting by score puts the 5 records without one last, in both directions
    for spec in ("score", "-score"):
        scores = [r["values"].get("score") for r in walk(client, ws, sort=spec)]
        assert scores[-5:] == [None] * 5 and None not in scores[:-5], spec


def test_a_cursor_keeps_its_place_while_records_are_added_and_changed(people):
    client, ws, rows = people
    first = page(client, ws, limit=5, sort="display_name")
    assert names(first) == [f"person {i:02d}" for i in range(5)]
    make_record(client, ws, first_name="person 00a")  # sorts before the cursor: not in the next page
    make_record(client, ws, first_name="person 05a")  # sorts after it: in the pages to come
    client.patch(f"{R}/{rows[2]['id']}", json={"values": {"lifecycle": "other"}}, headers={H: ws})  # a seen row moves
    rest, cursor = [], first["next_cursor"]
    while cursor:
        got = page(client, ws, limit=5, sort="display_name", cursor=cursor)
        rest += names(got)
        cursor = got["next_cursor"]
    assert rest[:3] == ["person 05", "person 05a", "person 06"] and "person 00a" not in rest
    assert len(rest) == len(set(rest)) == 21 and rest[-1] == "person 24"


def test_the_default_order_is_the_newest_change_first_and_limits_are_bounded(people):
    client, ws, rows = people
    got = page(client, ws, limit=3)
    assert names(got) == ["person 24", "person 23", "person 22"] and got["next_cursor"]
    client.patch(f"{R}/{rows[0]['id']}", json={"values": {"lifecycle": "lead"}}, headers={H: ws})  # no change
    assert names(page(client, ws, limit=2))[0] == "person 24"
    client.patch(f"{R}/{rows[0]['id']}", json={"values": {"lifecycle": "other"}}, headers={H: ws})
    assert names(page(client, ws, limit=2))[0] == "person 00"  # an edit brings it to the top
    assert page(client, ws, limit=200)["next_cursor"] is None
    for bad in (0, 201, -1, "x"):
        assert client.get(R, params={"limit": bad}, headers={H: ws}).status_code == 422
    total = page(client, ws, limit=3, count="true")
    assert total["total"] == 25 and len(total["data"]) == 3  # the count ignores the page
    assert "total" not in page(client, ws)
    filtered = page(client, ws, filter={"field": "lifecycle", "op": "is", "value": "lead"}, count="true", limit=2)
    assert filtered["total"] == 8 and len(filtered["data"]) == 2  # nine leads, less the one changed above


def test_a_bad_cursor_or_sort_is_a_400(people):
    client, ws, _ = people
    cursor = page(client, ws, limit=2, sort="display_name")["next_cursor"]
    for bad in ("garbage", "a.b", cursor[:-3] + "xxx", cursor.split(".")[0], "." + cursor.split(".")[1]):
        r = client.get(R, params={"cursor": bad, "sort": "display_name"}, headers={H: ws})
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_cursor", bad
    for other in ("-display_name", "score", "display_name,score", None):  # a cursor belongs to the sort that made it
        r = client.get(R, params={"cursor": cursor, **({"sort": other} if other else {})}, headers={H: ws})
        assert r.status_code == 400 and r.json()["error"]["code"] == "invalid_cursor", other
    assert client.get(R, params={"cursor": cursor, "sort": "display_name"}, headers={H: ws}).status_code == 200
    newest = page(client, ws, limit=2)["next_cursor"]
    assert client.get(R, params={"cursor": newest, "q": "person"}, headers={H: ws}).status_code == 400  # a search ranks
    client.post(f"{OBJECTS}/contact/fields", json={"key": "interests", "label": "I", "type": "multi_select"},
                headers={H: ws})
    client.post(f"{OBJECTS}/contact/fields", json={"key": "calc", "label": "C", "type": "formula"}, headers={H: ws})
    for spec, message in [("nope", "cannot sort contact by 'nope'"), ("interests", "cannot sort"),
                          ("company", "cannot sort"), ("calc", "cannot sort"), ("owner_id", "cannot sort"),
                          ("relevance", "cannot sort"), ("score,score", "listed twice"), ("a,b,c,d", "at most 3"),
                          ("-", "cannot sort"), ("display_name; drop table records", "cannot sort"),
                          ("deal.name", "cannot sort")]:
        r = client.get(R, params={"sort": spec}, headers={H: ws})
        assert r.status_code == 400 and message in r.json()["error"]["fields"]["sort"], spec
    assert client.post(f"{R}/query", json={"sort": ["display_name", "-created_at"], "limit": 2},
                       headers={H: ws}).status_code == 200
    assert client.post(f"{R}/query", json={"sort": 5}, headers={H: ws}).status_code == 422


@pytest.fixture
def directory(crm):
    client, ws, _ = crm
    client.post(f"{OBJECTS}/contact/fields", json={"key": "notes", "label": "Notes", "type": "long_text"},
                headers={H: ws})
    rows = {
        "ada": make_record(client, ws, first_name="Ada", last_name="Lovelace", email="ada@analytical.example",
                           phone="+14155552671", notes="Wrote the first program"),
        "grace": make_record(client, ws, first_name="Grace", last_name="Hopper", email="grace@navy.example",
                             notes="Invented the compiler"),
        "zoe": make_record(client, ws, first_name="Zoë", last_name="Anne-Marie Quinn", notes="Fan of Lovelace"),
        "alan": make_record(client, ws, first_name="Alan", last_name="Turing", email="alan@bletchley.example",
                            phone="+442079460958", notes="Lovelace lovelace lovelace"),
        "other": make_record(client, ws, first_name="Zed", email="zed@example.org"),
    }
    return client, ws, rows


def test_search_matches_names_values_and_prefixes(directory):
    client, ws, d = directory

    def search(q, **params):
        return sorted(names(page(client, ws, q=q, **params)))

    assert search("ada") == ["Ada Lovelace"]
    assert search("ADA") == ["Ada Lovelace"]  # not case sensitive
    assert search("ad") == ["Ada Lovelace"]  # a prefix
    assert search("gra hop") == ["Grace Hopper"]  # every word, each as a prefix
    assert search("hopper grace") == ["Grace Hopper"]
    assert search("ada hopper") == []
    assert search("lovel") == ["Ada Lovelace", "Alan Turing", "Zoë Anne-Marie Quinn"]  # last name, and notes
    assert search("compil") == ["Grace Hopper"]  # inside a long text value
    assert search("ada@analytical.example") == ["Ada Lovelace"]
    assert search("ada@ana") == ["Ada Lovelace"]  # an email by its first characters
    assert search("grace@") == ["Grace Hopper"]
    assert search("+14155") == ["Ada Lovelace"]  # a phone number by its first digits
    assert search("+4420") == ["Alan Turing"]
    assert search("zo") == ["Zoë Anne-Marie Quinn"]  # accented letters
    assert search("zoë") == ["Zoë Anne-Marie Quinn"]
    assert search("anne-marie") == ["Zoë Anne-Marie Quinn"]
    assert search("quinn") == ["Zoë Anne-Marie Quinn"]
    assert search("zed") == ["Zed"] and search("zed@exa") == ["Zed"]
    assert search("nobody") == [] and search("first") == ["Ada Lovelace"]  # "first program"
    for noise in ("!!!", "???", "()", "&|", ":*", "'"):
        assert search(noise) == [], noise  # a query without words finds nothing, and is not an error
    for hostile in ("'; drop table records; --", "a & | ! ( ) : * \\ ' \"", "ada' & 'x", "\u0000"):
        r = client.get(R, params={"q": hostile}, headers={H: ws})
        assert r.status_code == 200, (hostile, r.text)
    assert client.get(R, params={"q": "x" * 201}, headers={H: ws}).status_code == 422
    assert client.get(R, params={"q": ""}, headers={H: ws}).json()["data"] != []  # an empty q is no search


def test_search_combines_with_filters_sorts_pages_and_the_trash(directory):
    client, ws, d = directory
    got = page(client, ws, q="lovel", filter={"field": "email", "op": "is_not_empty"})
    assert sorted(names(got)) == ["Ada Lovelace", "Alan Turing"]
    got = page(client, ws, q="lovel", sort="-display_name", count="true")
    assert names(got) == ["Zoë Anne-Marie Quinn", "Alan Turing", "Ada Lovelace"] and got["total"] == 3
    # a search pages like any list
    seen, cursor = [], None
    for _ in range(5):
        got = page(client, ws, q="lovel", limit=1, **({"cursor": cursor} if cursor else {}))
        seen += names(got)
        cursor = got["next_cursor"]
        if not cursor:
            break
    assert len(seen) == len(set(seen)) == 3
    # the search follows edits and the trash
    client.patch(f"{R}/{d['grace']['id']}", json={"values": {"notes": "Admired Lovelace"}}, headers={H: ws})
    assert "Grace Hopper" in names(page(client, ws, q="lovel"))
    client.delete(f"{R}/{d['ada']['id']}", headers={H: ws})
    assert "Ada Lovelace" not in names(page(client, ws, q="lovel"))
    client.post(f"{R}/{d['ada']['id']}/restore", headers={H: ws})
    assert "Ada Lovelace" in names(page(client, ws, q="lovel"))
    # other objects have their own searches
    make_record(client, ws, "company", name="Lovelace Labs")
    assert names(page(client, ws, q="lovel")).count("Lovelace Labs") == 0
    assert client.get(f"{OBJECTS}/company/records", params={"q": "lovel"}, headers={H: ws}).json()["data"][0][
        "display_name"] == "Lovelace Labs"


def test_search_ranks_a_name_above_a_mention_and_sorts_can_override_it(directory):
    client, ws, d = directory
    best = names(page(client, ws, q="lovelace"))
    assert best[0] == "Ada Lovelace"  # in her name; the others only have it in their notes
    assert set(best) == {"Ada Lovelace", "Alan Turing", "Zoë Anne-Marie Quinn"}
    assert names(page(client, ws, q="lovelace", sort="-relevance")) == best
    assert names(page(client, ws, q="lovelace", sort="display_name")) == sorted(best)
    assert names(page(client, ws, q="lovelace", sort="relevance"))[-1] == "Ada Lovelace"  # worst first
    # relevance ties break by id, so pages never repeat
    walked = [r["display_name"] for r in walk(client, ws, limit=1, q="lovelace")]
    assert walked == best
