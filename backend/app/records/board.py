"""The deal board (ADR 0002, module 10): a pipeline's stages as columns, each with its count, its sums and its first
cards; moving a deal to another stage or to another place in its stage in one write; and each user's saved layout.
Cards are ordered by `board_position` (stages.py), so a drop between two cards writes only the dropped deal."""
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import BigInteger, cast, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .. import permissions
from ..api import ApiError, seal
from ..events import Event
from ..permissions import requires
from ..security import Ctx
from . import query, stages, store
from .filters import BUILTIN
from .models import BoardLayout, EventRecord, Record, Stage
from .pipelines import MAX_STAGES, pipeline_json, pipeline_or_404, stage_json, stages_of
from .schema import Catalog, FieldKey

router = APIRouter(prefix="/api/v1")
DEFAULT_CARD_FIELDS = ["amount", "close_date", "owner_id"]
MAX_CARD_FIELDS = 20


class Move(BaseModel):
    stage_id: uuid.UUID
    # Where in the stage: after the card above the drop and before the card below it (either or both), or a position
    # of your own. Left out, a deal that changes stage goes to the top and one that stays keeps its place.
    after_id: uuid.UUID | None = None
    before_id: uuid.UUID | None = None
    position: Decimal | None = Field(None, allow_inf_nan=False, max_digits=1000)
    lost_reason: str | None = None
    lost_note: Annotated[str, Field(max_length=20000)] | None = None


class Layout(BaseModel):
    collapsed: list[uuid.UUID] = Field([], max_length=MAX_STAGES)
    card_fields: list[FieldKey] = Field(DEFAULT_CARD_FIELDS, max_length=MAX_CARD_FIELDS)


def number(value: Decimal | None) -> str | None:
    """A position as text: JSON numbers are doubles, which cannot hold a position that was halved fifty times."""
    return None if value is None else format(value, "f")


def last_activity(c: Ctx, ids: list[uuid.UUID]) -> dict[uuid.UUID, datetime]:
    """The newest entry of each deal's timeline: events about the deal, and events that link it to something."""
    own = select(Event.subject_id, func.max(Event.occurred_at)).where(
        Event.workspace_id == c.workspace.id, Event.subject_id.in_(ids)).group_by(Event.subject_id)
    linked = select(EventRecord.record_id, func.max(Event.occurred_at)).join(Event, Event.id == EventRecord.event_id) \
        .where(EventRecord.record_id.in_(ids)).group_by(EventRecord.record_id)
    out: dict[uuid.UUID, datetime] = {}
    for record_id, at in (*c.db.execute(own), *c.db.execute(linked)):
        out[record_id] = max(at, out.get(record_id, at))
    return out


def cards(cat: Catalog, obj, rows: list[tuple[Record, Stage]]) -> list[dict]:
    """The board card of each deal: what the column shows, how long the deal has been there, whether it is rotting
    (more days in the stage than the stage allows) and when something last happened to it."""
    c, now = cat.c, datetime.now(UTC)
    deals = [r for r, _ in rows]
    entered = stages.entered_at(c.db, c.workspace.id, deals)
    active = last_activity(c, [r.id for r in deals])
    out = []
    for rec, stage in rows:
        values, days = store.visible_values(cat, obj, rec), (now - entered[rec.id]).days
        out.append({"id": rec.id, "display_name": store.shown_name(cat, obj, rec), "amount": values.get("amount"),
                    "close_date": values.get("close_date"), "owner_id": rec.owner_id,
                    "board_position": number(rec.board_position), "stage_id": stage.id,
                    "stage_entered_at": entered[rec.id], "days_in_stage": days,
                    "rotting": stage.rotting_days is not None and days > stage.rotting_days,
                    "last_activity_at": active.get(rec.id), "values": values})
    return out


def weigh(total: int, probability: int) -> int:
    return (total * probability + 50) // 100


def totals(cat: Catalog, obj, columns: list[Stage]) -> dict[uuid.UUID, dict]:
    """Per stage: how many deals, and their amounts and weighted amounts (amount times the stage's probability) in
    minor units, one entry per currency. One query for the whole board.
    ponytail: the sums read the amount of every deal in the stages (about 100 ms for 36 000 deals in one stage); keep
    them in a rollup table when a workspace has hundreds of thousands of open deals.
    A role that cannot read `amount` gets the counts and no sums, which would give it away."""
    where = [*store.live(cat, obj), Record.stage_id.in_([s.id for s in columns])]
    if "amount" in permissions.hidden(cat.c, obj):
        rows = [(stage_id, None, n, None) for stage_id, n in cat.db.execute(
            select(Record.stage_id, func.count()).where(*where).group_by(Record.stage_id))]
    else:
        currency = Record.values["amount"]["currency"].astext
        amount = cast(Record.values["amount"]["amount"].astext, BigInteger)
        rows = cat.db.execute(select(Record.stage_id, currency.label("cur"), func.count(), func.sum(amount))
                              .where(*where).group_by(Record.stage_id, "cur"))
    by_id = {s.id: s for s in columns}
    out = {s.id: {"count": 0, "amount": {}, "weighted": {}} for s in columns}
    for stage_id, cur, n, total in rows:
        stage = by_id[stage_id]
        out[stage.id]["count"] += n
        if cur:
            out[stage.id]["amount"][cur] = int(total)
            out[stage.id]["weighted"][cur] = weigh(int(total), stage.probability)
    return out


def column(cat: Catalog, obj, stage: Stage, limit: int, cursor: str | None) -> tuple[list[Record], str | None]:
    """One page of a stage's deals, top to bottom, with the cursor of the next page. The cursor belongs to the stage."""
    key = query.Key(f"board:{stage.id}", Record.board_position, "num", False)
    stmt = select(Record, Record.board_position).where(*store.live(cat, obj), Record.stage_id == stage.id)
    if cursor:
        values, last_id = query.read_cursor(cursor, [key])
        stmt = stmt.where(query.after([key], values, last_id, False))
    rows = cat.db.execute(stmt.order_by(Record.board_position.asc().nulls_last(), Record.id.asc())
                          .limit(limit + 1)).all()
    page = rows[:limit]
    more = seal([query.signature([key]), [query.dump(page[-1][1])], str(page[-1][0].id)]) if len(rows) > limit else None
    return [r for r, _ in page], more


@router.get("/pipelines/{pipeline_id}/board")
def board(pipeline_id: uuid.UUID, limit: int = Query(25, ge=1, le=100), stage: uuid.UUID | None = None,
          cursor: str | None = None, c: Ctx = Depends(requires("deals.read"))):
    """The pipeline with, per stage: `count`, `amount` and `weighted` by currency, the first `limit` deals as cards
    and `next_cursor`. Send `stage` and that stage's `next_cursor` for its next page (that column only)."""
    cat = Catalog(c)
    obj, pipeline = cat.need(stages.DEAL), pipeline_or_404(c, pipeline_id)
    permissions.need_visible(c, obj, stages.STAGE)  # the columns are the stage field
    columns = stages_of(c, pipeline)
    if stage:
        columns = [s for s in columns if s.id == stage]
        if not columns:
            raise ApiError(404, "not_found", "Stage not found")
    elif cursor:
        raise ApiError(400, "invalid_cursor", "A cursor belongs to one stage: send stage as well")
    sums = totals(cat, obj, columns)
    pages = {s.id: column(cat, obj, s, limit, cursor) for s in columns}
    shown = cards(cat, obj, [(r, s) for s in columns for r in pages[s.id][0]])
    return {**pipeline_json(pipeline), "stages": [
        {**stage_json(s), **sums[s.id], "deals": [d for d in shown if d["stage_id"] == s.id],
         "next_cursor": pages[s.id][1]} for s in columns]}


def neighbour(cat: Catalog, obj, stage: Stage, deal: Record, other_id: uuid.UUID | None, name: str) -> Decimal | None:
    """The board position of the card the deal is dropped next to, which must be another deal of that stage."""
    if other_id is None:
        return None
    other = cat.db.scalar(select(Record).where(
        *store.live(cat, obj), Record.id == other_id, Record.id != deal.id,
        Record.stage_id == stage.id, Record.board_position.is_not(None)))
    if other is None:
        raise ApiError(422, "validation_failed", "The move is not valid", {name: "is not another deal of that stage"})
    return other.board_position


@router.post("/deals/{deal_id}/move")
def move_deal(deal_id: uuid.UUID, body: Move, c: Ctx = Depends(requires("deals.write"))):
    """Moves a deal to a stage and a place in it, in one write. The stage it leaves may refuse (422, with a field
    error for each thing that is missing), a lost stage needs `lost_reason`, and a change of stage emits
    `deal.stage_changed`. Answers with the deal's card. It is a write of the deal's stage, so it needs `deals.write`
    and a stage that the role may read and change."""
    cat = Catalog(c)
    obj = cat.need(stages.DEAL)
    target = c.db.get(Stage, body.stage_id)
    if target is None:
        raise ApiError(404, "not_found", "Stage not found")
    if body.position is not None and (body.after_id or body.before_id):
        raise ApiError(422, "validation_failed", "The move is not valid",
                       {"position": "cannot be combined with after_id or before_id"})
    deal = store.get(cat, obj, deal_id, lock=True)
    above = neighbour(cat, obj, target, deal, body.after_id, "after_id")
    below = neighbour(cat, obj, target, deal, body.before_id, "before_id")
    if above is not None and below is not None and above >= below:
        raise ApiError(409, "conflict", "The cards are no longer in that order: reload the board")
    position = body.position
    if body.after_id or body.before_id:
        position = stages.between(above, below)
    patch = {stages.STAGE: str(target.id), **{k: v for k, v in (("lost_reason", body.lost_reason),
                                                                ("lost_note", body.lost_note)) if v is not None}}
    store.update(cat, obj, deal, patch, position=position)
    c.db.commit()
    return cards(cat, obj, [(deal, target)])[0]


def layout_json(pipeline_id: uuid.UUID, row: BoardLayout | None, known: set[uuid.UUID]) -> dict:
    stored = row.layout if row else {}
    return {"pipeline_id": pipeline_id,
            "collapsed": [i for i in stored.get("collapsed", []) if uuid.UUID(i) in known],
            "card_fields": stored.get("card_fields", DEFAULT_CARD_FIELDS),
            "updated_at": row.updated_at if row else None}


@router.get("/pipelines/{pipeline_id}/layout")
def get_layout(pipeline_id: uuid.UUID, c: Ctx = Depends(requires("deals.read"))):
    """The caller's own layout of this board: which stages are collapsed and which fields the cards show."""
    pipeline = pipeline_or_404(c, pipeline_id)
    row = c.db.get(BoardLayout, (pipeline.id, c.user_id))  # row level security: the caller's rows only
    return layout_json(pipeline.id, row, {s.id for s in stages_of(c, pipeline)})


@router.put("/pipelines/{pipeline_id}/layout")
def save_layout(pipeline_id: uuid.UUID, body: Layout, c: Ctx = Depends(requires("deals.read"))):
    cat = Catalog(c)
    pipeline, deal = pipeline_or_404(c, pipeline_id), cat.need(stages.DEAL)
    known = {s.id for s in stages_of(c, pipeline)}
    fields = (cat.fields(deal) | BUILTIN).keys() - permissions.hidden(c, deal)  # a hidden field is not one to show
    errors = {f"collapsed.{i}": "is not a stage of this pipeline" for i, s in enumerate(body.collapsed)
              if s not in known}
    errors |= {f"card_fields.{i}": f"unknown field {k!r}" for i, k in enumerate(body.card_fields) if k not in fields}
    if errors:
        raise ApiError(422, "validation_failed", "The layout is not valid", errors)
    layout = {"collapsed": [str(i) for i in dict.fromkeys(body.collapsed)],
              "card_fields": list(dict.fromkeys(body.card_fields))}
    c.db.execute(pg_insert(BoardLayout).values(pipeline_id=pipeline.id, user_id=c.user_id,
                                               workspace_id=c.workspace.id, layout=layout)
                 .on_conflict_do_update(index_elements=["pipeline_id", "user_id"],
                                        set_={"layout": layout, "updated_at": func.now()}))
    c.db.commit()
    row = c.db.get(BoardLayout, (pipeline.id, c.user_id), populate_existing=True)
    return layout_json(pipeline.id, row, known)
