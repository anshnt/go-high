"""Migration 0007 on a database that has workspaces with deals from before pipelines: each gets the Sales pipeline, the
deals' placeholder stages become its stages, and it goes both ways."""
import json

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from test_migration_records import alembic

from app import config
from app.records import seed

URL = make_url(config.DATABASE_URL)  # conftest pointed DATABASE_URL at the test database
NAME = f"{URL.database}_pipelines_migrate"  # a database of its own: the test database stays at head
OLD_CHOICES = ('{"choices": [{"id": "new", "label": "New"}, {"id": "qualified", "label": "Qualified"}, '
               '{"id": "proposal", "label": "Proposal"}, {"id": "negotiation", "label": "Negotiation"}, '
               '{"id": "won", "label": "Won"}, {"id": "lost", "label": "Lost"}]}')
DEALS = {  # workspace name: (deal name, stored stage placeholder or None, created at)
    "One": [("Old won", "won", "2026-01-01"), ("Old new", "new", "2026-02-01"), ("Odd", "weird", "2026-03-01"),
            ("Floating", None, "2026-04-01"), ("Old lost", "lost", "2026-05-01")],
    "Two": [("Prop", "proposal", "2026-06-01"), ("Neg", "negotiation", "2026-07-01")]}


@pytest.fixture
def old_database():
    admin = create_engine(URL.set(database="postgres"), isolation_level="AUTOCOMMIT")
    url = URL.set(database=NAME).render_as_string(hide_password=False)
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{NAME}"'))
    engine = None
    try:
        alembic(url, "upgrade", "0003")
        engine = create_engine(url)
        with engine.begin() as conn:
            org = conn.scalar(text("INSERT INTO organizations (name) VALUES ('Old') RETURNING id"))
            brand = conn.scalar(text("INSERT INTO brands (org_id, name) VALUES (:o, 'B') RETURNING id"), {"o": org})
            for name in DEALS:
                conn.execute(text("INSERT INTO workspaces (org_id, brand_id, name) VALUES (:o, :b, :n)"),
                             {"o": org, "b": brand, "n": name})
        alembic(url, "upgrade", "0004")
        with engine.begin() as conn:  # make the deals look like those of the first slice: a select with placeholders
            conn.execute(text("UPDATE fields SET options = CAST(:o AS jsonb) WHERE type = 'stage'"), {"o": OLD_CHOICES})
            conn.execute(text("DELETE FROM fields WHERE key IN ('lost_reason', 'lost_note')"))
            for workspace, name in conn.execute(text("SELECT w.id, w.name FROM workspaces w")).all():
                deal = conn.scalar(text("SELECT id FROM objects WHERE workspace_id = :w AND key = 'deal'"),
                                   {"w": workspace})
                for title, stage, created in DEALS[name]:
                    values = {"name": title, **({"stage": stage} if stage else {})}
                    conn.execute(text("INSERT INTO records (workspace_id, object_id, display_name, values, created_at) "
                                      "VALUES (:w, :o, :n, CAST(:v AS jsonb), :c)"),
                                 {"w": workspace, "o": deal, "n": title, "v": json.dumps(values),
                                  "c": created})
        yield url, engine
    finally:
        if engine is not None:
            engine.dispose()
        with admin.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{NAME}" WITH (FORCE)'))
        admin.dispose()


def deals(conn) -> dict[str, tuple]:
    """Deal name: (workspace name, stage name or the raw stored value, board position)."""
    rows = conn.execute(text(
        "SELECT r.display_name, w.name, coalesce(s.name, r.values ->> 'stage'), r.board_position "
        "FROM records r JOIN objects o ON o.id = r.object_id AND o.key = 'deal' "
        "JOIN workspaces w ON w.id = r.workspace_id "
        "LEFT JOIN stages s ON s.id::text = r.values ->> 'stage' AND s.workspace_id = r.workspace_id")).all()
    return {name: (workspace, stage, position) for name, workspace, stage, position in rows}


def test_workspaces_get_the_sales_pipeline_and_old_deals_land_in_its_stages(old_database):
    url, engine = old_database
    alembic(url, "upgrade", "head")
    with engine.begin() as conn:
        for (workspace,) in conn.execute(text("SELECT id FROM workspaces")).all():
            [pipeline] = conn.execute(text("SELECT id, name, object_key, position, archived_at FROM pipelines "
                                           "WHERE workspace_id = :w"), {"w": workspace}).all()
            assert (pipeline.name, pipeline.object_key, pipeline.position, pipeline.archived_at) == (
                "Sales", "deal", 0, None)
            stages = conn.execute(text("SELECT name, kind, probability, rotting_days, position FROM stages "
                                       "WHERE pipeline_id = :p ORDER BY position"), {"p": pipeline.id}).all()
            assert [tuple(s) for s in stages] == [
                (name, kind, probability, rotting, i)
                for i, (name, kind, probability, rotting, _) in enumerate(seed.DEFAULT_STAGES)]
        assert conn.scalar(text("SELECT count(DISTINCT id) FROM stages")) == 12  # not shared between workspaces

        found = deals(conn)
        assert {name: (workspace, stage) for name, (workspace, stage, _) in found.items()} == {
            "Old won": ("One", "Won"), "Old new": ("One", "Lead"), "Odd": ("One", "weird"),  # no such stage: as it was
            "Floating": ("One", None), "Old lost": ("One", "Lost"), "Prop": ("Two", "Proposal"),
            "Neg": ("Two", "Negotiation")}
        # the newest deal of a stage is on top: its position is minus its creation time
        assert found["Old new"][2] is not None and found["Odd"][2] is None and found["Floating"][2] is None
        assert found["Neg"][2] < found["Prop"][2] < 0
        assert found["Old lost"][2] < found["Old won"][2]

        # the stage_id column follows the value, and is empty where the value names no stage
        columns = conn.execute(text("SELECT display_name, stage_id IS NOT NULL, stage_id::text = values ->> 'stage' "
                                    "FROM records")).all()
        assert {name: (has, same) for name, has, same in columns} == {
            "Old won": (True, True), "Old new": (True, True), "Odd": (False, None), "Floating": (False, None),
            "Old lost": (True, True), "Prop": (True, True), "Neg": (True, True)}
        options = conn.execute(text("SELECT options FROM fields WHERE type = 'stage'")).scalars().all()
        assert options == [{}, {}]  # the stage field no longer has choices of its own
        for workspace in conn.execute(text("SELECT id FROM workspaces")).scalars().all():
            keys = conn.execute(text("SELECT f.key FROM fields f JOIN objects o ON o.id = f.object_id "
                                     "WHERE o.workspace_id = :w AND o.key = 'deal' ORDER BY f.position, f.key"),
                                {"w": workspace}).scalars().all()
            assert keys == ["name", "amount", "stage", "close_date", "lost_reason", "lost_note"]
        reason = conn.execute(text("SELECT type, is_system, options FROM fields "
                                   "WHERE key = 'lost_reason' LIMIT 1")).one()
        assert reason.type == "select" and reason.is_system
        assert [c["id"] for c in reason.options["choices"]] == ["price", "timing", "competitor", "no_decision", "other"]

        flags = conn.execute(text("SELECT relname, relrowsecurity, relforcerowsecurity FROM pg_class "
                                  "WHERE relname IN ('pipelines', 'stages', 'board_layouts')")).all()
        assert len(flags) == 3 and all(f[1] and f[2] for f in flags)
        grants = {t: {p for p in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE") if conn.scalar(
            text("SELECT has_table_privilege('gohigh_app', :t, :p)"), {"t": t, "p": p})}
            for t in ("pipelines", "stages", "board_layouts")}
        assert grants == {"pipelines": {"SELECT", "INSERT", "UPDATE", "DELETE"},
                          "stages": {"SELECT", "INSERT", "UPDATE", "DELETE"},
                          "board_layouts": {"SELECT", "INSERT", "UPDATE"}}


def test_the_migration_reverses_and_runs_again(old_database):
    url, engine = old_database
    alembic(url, "upgrade", "head")
    with engine.begin() as conn:  # a stage with another name cannot go back to a placeholder
        conn.execute(text("UPDATE stages SET name = 'Closed' WHERE name = 'Won'"))
    alembic(url, "downgrade", "0004")
    with engine.begin() as conn:
        assert conn.scalar(text("SELECT count(*) FROM pg_tables WHERE tablename IN ('pipelines', 'stages', "
                                "'board_layouts')")) == 0
        assert conn.scalar(text("SELECT count(*) FROM information_schema.columns WHERE table_name = 'records' "
                                "AND column_name IN ('board_position', 'stage_id')")) == 0
        stored = {name: values.get("stage") for name, values in conn.execute(text(
            "SELECT display_name, values FROM records")).all()}
        assert stored == {"Old won": None, "Old new": "new", "Odd": "weird", "Floating": None, "Old lost": "lost",
                          "Prop": "proposal", "Neg": "negotiation"}
        options = conn.execute(text("SELECT options FROM fields WHERE type = 'stage'")).scalars().all()
        assert all([c["id"] for c in o["choices"]] == ["new", "qualified", "proposal", "negotiation", "won", "lost"]
                   for o in options) and len(options) == 2
        assert conn.scalar(text("SELECT count(*) FROM fields WHERE key IN ('lost_reason', 'lost_note')")) == 0
        assert conn.scalar(text("SELECT count(*) FROM workspaces")) == 2  # the rest is untouched
    alembic(url, "upgrade", "head")  # and forward again
    with engine.begin() as conn:
        assert conn.scalar(text("SELECT count(*) FROM pipelines")) == 2 and conn.scalar(text(
            "SELECT count(*) FROM stages")) == 12
        found = deals(conn)
        assert found["Old new"][1] == "Lead" and found["Prop"][1] == "Proposal" and found["Old won"][1] is None
