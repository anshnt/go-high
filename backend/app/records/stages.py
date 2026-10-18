"""Stage rules of a record (ADR 0002, module 10). A `stage` value is the id of a stage of a pipeline. A deal leaves a
stage only when it meets that stage's exit rules (a filter on the deal), a deal in a lost stage says why, and every
change of stage is a `deal.stage_changed` event with the time the deal spent in the stage it left. `store` calls these
functions on every write, so the API, the move route, imports and workflows share one set of rules.

A deal's place in its column on the board is `records.board_position`, lower is higher up. A drop between two cards
takes the midpoint of their positions and writes only the dropped record.
ponytail: pipelines serve deals; `pipelines.object_key` and the generic stage field type are there for other objects,
but only a deal gets exit rules, lost reasons, events and a board.
ponytail: a drop between the same two cards over and over adds one digit to the position each time (exact up to 1000
digits); renumber the stage's cards when positions get that long."""
import json
import uuid
from datetime import datetime
from decimal import Context, Decimal
from typing import NamedTuple

from sqlalchemy import DateTime, String, Uuid, func, literal, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, aliased

from .. import events
from ..api import ApiError
from . import filters
from .models import Pipeline, Record, Stage
from .schema import Catalog

DEAL, STAGE = "deal", "stage"
EXACT = Context(prec=1000)
PHRASES = {"is_not_empty": "is required", "is_empty": "must be empty"}


class Move(NamedTuple):
    old: Stage | None
    new: Stage


def stage_of(cat: Catalog, value) -> Stage | None:
    """The stage a stored stage value names: None for no stage, or for one that is gone."""
    try:
        return cat.db.get(Stage, uuid.UUID(value)) if value else None
    except ValueError:
        return None


def unusable(cat: Catalog, obj, ids: set[str]) -> set[str]:
    """Those of `ids` that are not stages of a live pipeline of `obj`."""
    found = cat.db.scalars(select(Stage.id).join(Pipeline, Pipeline.id == Stage.pipeline_id).where(
        Stage.id.in_([uuid.UUID(i) for i in ids]), Pipeline.object_key == obj.key, Pipeline.archived_at.is_(None)))
    return ids - {str(i) for i in found}


def default(cat: Catalog, obj, values: dict) -> dict:
    """`values` of a new deal; one that names no stage starts in the first open stage of the first live pipeline."""
    if obj.key != DEAL or STAGE in values:
        return values
    first = cat.db.scalar(
        select(Stage.id).join(Pipeline, Pipeline.id == Stage.pipeline_id)
        .where(Pipeline.object_key == obj.key, Pipeline.archived_at.is_(None), Stage.kind == "open")
        .order_by(Pipeline.position, Pipeline.created_at, Pipeline.id, Stage.position, Stage.created_at, Stage.id)
        .limit(1))
    return {**values, STAGE: str(first)} if first else values


def settle(cat: Catalog, obj, current: dict, merged: dict, patch: dict, errors: dict) -> None:
    """The stage rules that need the whole deal: one in a lost stage says why, one that leaves it keeps no reason."""
    fields = cat.fields(obj)
    if obj.key != DEAL or "lost_reason" not in fields:
        return
    old, new = stage_of(cat, current.get(STAGE)), stage_of(cat, merged.get(STAGE))
    if new is not None and new.kind == "lost":
        if not merged.get("lost_reason") and (STAGE in patch or "lost_reason" in patch):
            errors["values.lost_reason"] = f"{fields['lost_reason'].label} is required to move a deal to {new.name}"
    elif new is not None and old is not None and old.kind == "lost":
        merged.pop("lost_reason", None)
        merged.pop("lost_note", None)


def snapshot(rec: Record, values: dict, owner_id):
    """The deal as it will be after the change: a one-row subquery that the filter compiler reads like the table."""
    columns = {"id": (rec.id, Uuid), "object_id": (rec.object_id, Uuid), "display_name": (rec.display_name, String),
               "owner_id": (owner_id, Uuid), "created_by": (rec.created_by, Uuid),
               "created_at": (rec.created_at, DateTime(timezone=True)),
               "updated_at": (rec.updated_at, DateTime(timezone=True)), "values": (values, JSONB)}
    row = select(*[literal(v, t).label(k) for k, (v, t) in columns.items()]).subquery()
    return aliased(Record, row, adapt_on_names=True)


def reason(cat: Catalog, obj, rule, stage: Stage) -> tuple[str, str]:
    """Where in the request and in what words one failed exit rule is reported."""
    key = rule.get("field") if isinstance(rule, dict) else None
    if not isinstance(key, str):
        return "exit_rules", f"{stage.name} needs this to hold before a deal leaves: {json.dumps(rule)}"
    field = cat.fields(obj).get(key)
    phrase = PHRASES.get(rule.get("op")) or f"must satisfy {rule.get('op')}" + (
        f" {json.dumps(rule['value'])}" if "value" in rule else "")
    name = field.label if field else key
    return (f"values.{key}" if "." not in key else key), f"{name} {phrase} to leave {stage.name}"


def check_exit(cat: Catalog, obj, rec: Record, values: dict, owner_id, stage: Stage) -> None:
    """Refuses (422) while the deal, as it will be after the change, does not meet an exit rule of `stage`. A rule is
    each condition of a top level `and`, so every one that fails is named with the field that is missing."""
    rules = stage.exit_rules
    parts = rules["and"] if set(rules) == {"and"} and isinstance(rules["and"], list) else [rules]
    if not rules or not parts:
        return
    after = snapshot(rec, values, owner_id)
    try:
        tests = [filters.compile(cat, obj, part, entity=after, root="exit_rules") for part in parts]
    except filters.FilterError as e:
        raise ApiError(409, "conflict", f"The exit rules of {stage.name} are not valid ({e.path}: {e.message}); "
                                        "an admin has to fix them before a deal can leave it") from None
    held = cat.db.execute(select(*tests).select_from(after)).one()
    failed = dict(reason(cat, obj, part, stage) for part, ok in zip(parts, held, strict=True) if not ok)
    if failed:
        raise ApiError(422, "validation_failed", f"The deal cannot leave {stage.name} yet", failed)


def moving(cat: Catalog, obj, rec: Record, merged: dict, owner_id) -> Move | None:
    """The change of stage that `merged` makes to the deal `rec`, or None when it stays where it is (or loses its
    stage). Raises when the stage it leaves has exit rules the deal does not meet."""
    if obj.key != DEAL:
        return None
    old, new = stage_of(cat, rec.values.get(STAGE)), stage_of(cat, merged.get(STAGE))
    if new is None or (old is not None and old.id == new.id):
        return None
    if old is not None and old.exit_rules:
        check_exit(cat, obj, rec, merged, owner_id, old)
    return Move(old, new)


def top(cat: Catalog, stage_id: str) -> Decimal:
    """A board position above every live card of the stage."""
    low = cat.db.scalar(select(func.min(Record.board_position)).where(
        Record.workspace_id == cat.c.workspace.id, Record.values[STAGE].astext == stage_id,
        Record.deleted_at.is_(None)))
    return Decimal(0) if low is None else EXACT.subtract(low, 1)


def between(above: Decimal | None, below: Decimal | None) -> Decimal:
    """A position between two cards: the midpoint, or one step beyond the only neighbour there is."""
    if above is None and below is None:
        return Decimal(0)
    if below is None:
        return EXACT.add(above, 1)
    if above is None:
        return EXACT.subtract(below, 1)
    return EXACT.divide(EXACT.add(above, below), 2)


def place(cat: Catalog, obj, before: dict, after: dict, explicit: Decimal | None) -> Decimal | None:
    """The deal's new board position: the one asked for, else the top of the stage it moved into, else None (it
    keeps its place)."""
    if obj.key != DEAL:
        return None
    if explicit is not None:
        return explicit
    stage = after.get(STAGE)
    return top(cat, stage) if stage and stage != before.get(STAGE) else None


def entered_at(db: Session, workspace_id: uuid.UUID, records: list[Record]) -> dict[uuid.UUID, datetime]:
    """When each deal reached the stage it is in: its last stage change, else its creation. The event log is the
    history, so nothing else has to be kept in step."""
    last = dict(db.execute(select(events.Event.subject_id, func.max(events.Event.occurred_at)).where(
        events.Event.workspace_id == workspace_id, events.Event.type == "deal.stage_changed",
        events.Event.subject_id.in_([r.id for r in records])).group_by(events.Event.subject_id)).all())
    return {r.id: last.get(r.id, r.created_at) for r in records}


def emit_moved(cat: Catalog, obj, rec: Record, move: Move) -> None:
    """The `deal.stage_changed` event: from and to, and the seconds spent in the stage that was left (a deal that had
    no stage has spent none)."""
    c = cat.c
    spent = None
    if move.old is not None:
        since = entered_at(c.db, c.workspace.id, [rec])[rec.id]
        spent = int((c.db.scalar(select(func.now())) - since).total_seconds())
    events.emit(c.db, "deal.stage_changed", "record", rec.id, {
        "id": rec.id, "object": obj.key, "display_name": rec.display_name, "pipeline_id": move.new.pipeline_id,
        "from_stage_id": move.old and move.old.id, "from_stage": move.old and move.old.name,
        "from_kind": move.old and move.old.kind, "to_stage_id": move.new.id, "to_stage": move.new.name,
        "to_kind": move.new.kind, "seconds_in_stage": spent}, actor=("user", c.user_id))
