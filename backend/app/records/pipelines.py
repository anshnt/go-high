"""Pipelines and their stages (ADR 0002, module 10): the columns of the deal board. Reading is for everyone in the
workspace, changing is for workspace admins. A stage has a kind (open, won or lost), a probability, a number of days
after which a deal in it is rotting, a color and exit rules: a filter on the deal that must hold before it may leave.
A pipeline that has deals is archived instead of deleted."""
import uuid
from collections import defaultdict
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, StringConstraints
from sqlalchemy import func, select

from ..api import ApiError, Idem, idempotency
from ..security import Ctx, in_workspace, workspace_admin
from . import query, seed
from .models import Pipeline, Record, Stage
from .objects import invalid
from .schema import Catalog, Label
from .stages import DEAL

router = APIRouter(prefix="/api/v1/pipelines")
MAX_STAGES = 30  # ponytail: a board with more columns than this stops being readable
FIXED = {"won": 100, "lost": 0}  # the probability of a won or a lost stage
DEFAULT_PROBABILITY = 10
Color = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=20)]
Position = Annotated[int, Field(ge=0, le=10000)]


class NewStage(BaseModel):
    name: Label
    kind: Literal["open", "won", "lost"] = "open"
    probability: int | None = Field(None, ge=0, le=100)  # 100 for won and 0 for lost; open stages start at 10
    rotting_days: int | None = Field(None, ge=1, le=3650)
    exit_rules: dict = {}
    color: Color | None = None
    position: Position | None = None


class PatchStage(BaseModel):
    name: Label | None = None
    kind: Literal["open", "won", "lost"] | None = None
    probability: int | None = Field(None, ge=0, le=100)
    rotting_days: int | None = Field(None, ge=1, le=3650)
    exit_rules: dict | None = None
    color: Color | None = None
    position: Position | None = None


class NewPipeline(BaseModel):
    name: Label
    stages: list[NewStage] | None = Field(None, max_length=MAX_STAGES)  # left out: the stages of the Sales pipeline


class PatchPipeline(BaseModel):
    name: Label | None = None
    position: Position | None = None
    archived: bool | None = None


class Order(BaseModel):
    stage_ids: list[uuid.UUID] = Field(max_length=MAX_STAGES)


def stage_json(s: Stage) -> dict:
    return {"id": s.id, "pipeline_id": s.pipeline_id, "name": s.name, "position": s.position, "kind": s.kind,
            "probability": s.probability, "rotting_days": s.rotting_days, "exit_rules": s.exit_rules,
            "color": s.color, "created_at": s.created_at}


def pipeline_json(p: Pipeline, stages: list[Stage] | None = None) -> dict:
    return {"id": p.id, "object": p.object_key, "name": p.name, "position": p.position, "archived_at": p.archived_at,
            "created_at": p.created_at, **({"stages": [stage_json(s) for s in stages]} if stages is not None else {})}


def pipeline_or_404(c: Ctx, pipeline_id: uuid.UUID) -> Pipeline:
    pipeline = c.db.get(Pipeline, pipeline_id)  # row level security: this workspace's pipelines only
    if pipeline is None:
        raise HTTPException(404, "Pipeline not found")
    return pipeline


def stages_of(c: Ctx, pipeline: Pipeline) -> list[Stage]:
    return list(c.db.scalars(select(Stage).where(Stage.pipeline_id == pipeline.id)
                             .order_by(Stage.position, Stage.created_at, Stage.id)))


def stage_or_404(c: Ctx, pipeline: Pipeline, stage_id: uuid.UUID) -> Stage:
    stage = c.db.get(Stage, stage_id)
    if stage is None or stage.pipeline_id != pipeline.id:
        raise HTTPException(404, "Stage not found")
    return stage


def deals_in(c: Ctx, stage_ids: list[uuid.UUID]) -> int:
    """Deals that name one of these stages, the trashed included (they come back to the stage they were in)."""
    return c.db.scalar(select(func.count()).select_from(Record).where(
        Record.workspace_id == c.workspace.id, Record.stage_id.in_(stage_ids)))


def live_count(c: Ctx) -> int:
    return c.db.scalar(select(func.count()).select_from(Pipeline).where(Pipeline.object_key == DEAL,
                                                                        Pipeline.archived_at.is_(None)))


def probability_of(cat: Catalog, kind: str, probability: int | None, exit_rules: dict | None, where: str = "") -> int:
    """The stage's probability (fixed for won and lost), after checking that its exit rules compile for a deal."""
    fixed = FIXED.get(kind)
    if fixed is not None and probability not in (None, fixed):
        raise invalid(**{f"{where}probability": f"is {fixed} for a {kind} stage"})
    if exit_rules:
        query.where_of(cat, cat.need(DEAL), exit_rules, root=f"{where}exit_rules")
    return fixed if fixed is not None else DEFAULT_PROBABILITY if probability is None else probability


def nulls(sent: dict, allowed: tuple[str, ...]) -> None:
    if bad := [k for k, v in sent.items() if v is None and k not in allowed]:
        raise invalid(**{k: "cannot be null" for k in bad})


@router.get("")
def list_pipelines(archived: bool = False, c: Ctx = Depends(in_workspace)):
    """Every pipeline with its stages in order (a workspace has a handful)."""
    rows = list(c.db.scalars(select(Pipeline).where(
        Pipeline.archived_at.is_not(None) if archived else Pipeline.archived_at.is_(None))
        .order_by(Pipeline.position, Pipeline.created_at, Pipeline.id)))
    stages: dict[uuid.UUID, list[Stage]] = defaultdict(list)
    for s in c.db.scalars(select(Stage).where(Stage.pipeline_id.in_([p.id for p in rows]))
                          .order_by(Stage.position, Stage.created_at, Stage.id)):
        stages[s.pipeline_id].append(s)
    return {"data": [pipeline_json(p, stages[p.id]) for p in rows], "next_cursor": None}


@router.post("", status_code=201)
def create_pipeline(body: NewPipeline, c: Ctx = Depends(workspace_admin), idem: Idem = Depends(idempotency)):
    cat = Catalog(c)
    specs = body.stages if body.stages is not None else [
        NewStage(name=name, kind=kind, probability=probability, rotting_days=rotting, color=color)
        for name, kind, probability, rotting, color in seed.DEFAULT_STAGES]
    odds = [probability_of(cat, s.kind, s.probability, s.exit_rules, f"stages.{i}.") for i, s in enumerate(specs)]
    last = c.db.scalar(select(func.max(Pipeline.position)).where(Pipeline.object_key == DEAL))
    pipeline = Pipeline(workspace_id=c.workspace.id, name=body.name, position=0 if last is None else last + 1)
    c.db.add(pipeline)
    c.db.flush()
    rows = [Stage(workspace_id=c.workspace.id, pipeline_id=pipeline.id, name=s.name, position=i, kind=s.kind,
                  probability=p, rotting_days=s.rotting_days, exit_rules=s.exit_rules, color=s.color)
            for i, (s, p) in enumerate(zip(specs, odds, strict=True))]
    c.db.add_all(rows)
    c.db.flush()
    return idem.commit(201, pipeline_json(pipeline, rows))


@router.get("/{pipeline_id}")
def get_pipeline(pipeline_id: uuid.UUID, c: Ctx = Depends(in_workspace)):
    pipeline = pipeline_or_404(c, pipeline_id)
    return pipeline_json(pipeline, stages_of(c, pipeline))


@router.patch("/{pipeline_id}")
def update_pipeline(pipeline_id: uuid.UUID, body: PatchPipeline, c: Ctx = Depends(workspace_admin)):
    """`archived: true` hides a pipeline from lists and from new deals and keeps its deals; `false` brings it back."""
    pipeline, sent = pipeline_or_404(c, pipeline_id), body.model_dump(exclude_unset=True)
    nulls(sent, ())
    if "archived" in sent:
        if sent.pop("archived"):
            if pipeline.archived_at is None and live_count(c) == 1:
                raise ApiError(409, "conflict", "A workspace needs at least one pipeline that is not archived")
            pipeline.archived_at = pipeline.archived_at or func.now()
        else:
            pipeline.archived_at = None
    for name, value in sent.items():
        setattr(pipeline, name, value)
    c.db.flush()
    c.db.refresh(pipeline, ["archived_at"])
    c.db.commit()
    return pipeline_json(pipeline, stages_of(c, pipeline))


@router.delete("/{pipeline_id}", responses={204: {"description": "Deleted"}, 200: {"description": "Archived"}})
def delete_pipeline(pipeline_id: uuid.UUID, c: Ctx = Depends(workspace_admin)):
    """Deletes a pipeline that has no deals (204). One that has deals is archived instead and comes back as it now
    is (200), so no deal is left without its stage."""
    pipeline = pipeline_or_404(c, pipeline_id)
    stages = stages_of(c, pipeline)
    if pipeline.archived_at is None and live_count(c) == 1:
        raise ApiError(409, "conflict", "A workspace needs at least one pipeline that is not archived")
    if stages and deals_in(c, [s.id for s in stages]):
        pipeline.archived_at = pipeline.archived_at or func.now()
        c.db.flush()
        c.db.refresh(pipeline, ["archived_at"])
        c.db.commit()
        return pipeline_json(pipeline, stages)
    c.db.delete(pipeline)  # its stages and saved layouts go with it (foreign key cascade)
    c.db.commit()
    return Response(status_code=204)


@router.post("/{pipeline_id}/stages", status_code=201)
def create_stage(pipeline_id: uuid.UUID, body: NewStage, c: Ctx = Depends(workspace_admin),
                 idem: Idem = Depends(idempotency)):
    cat, pipeline = Catalog(c), pipeline_or_404(c, pipeline_id)
    count, last = c.db.execute(select(func.count(), func.max(Stage.position)).where(
        Stage.pipeline_id == pipeline.id)).one()
    if count >= MAX_STAGES:
        raise ApiError(409, "conflict", f"A pipeline has at most {MAX_STAGES} stages")
    stage = Stage(workspace_id=c.workspace.id, pipeline_id=pipeline.id, name=body.name, kind=body.kind,
                  probability=probability_of(cat, body.kind, body.probability, body.exit_rules),
                  rotting_days=body.rotting_days, exit_rules=body.exit_rules, color=body.color,
                  position=body.position if body.position is not None else 0 if last is None else last + 1)
    c.db.add(stage)
    c.db.flush()
    return idem.commit(201, stage_json(stage))


@router.patch("/{pipeline_id}/stages/{stage_id}")
def update_stage(pipeline_id: uuid.UUID, stage_id: uuid.UUID, body: PatchStage, c: Ctx = Depends(workspace_admin)):
    """A won stage has probability 100 and a lost one 0; changing the kind without a probability resets it."""
    cat, pipeline = Catalog(c), pipeline_or_404(c, pipeline_id)
    stage, sent = stage_or_404(c, pipeline, stage_id), body.model_dump(exclude_unset=True)
    nulls(sent, ("rotting_days", "color"))
    kind = sent.get("kind", stage.kind)
    if {"kind", "probability", "exit_rules"} & sent.keys():
        odds = sent.get("probability", None if "kind" in sent and kind != stage.kind else stage.probability)
        sent["probability"] = probability_of(cat, kind, odds, sent.get("exit_rules"))
    for name, value in sent.items():
        setattr(stage, name, value)
    c.db.commit()
    return stage_json(stage)


@router.delete("/{pipeline_id}/stages/{stage_id}", status_code=204)
def delete_stage(pipeline_id: uuid.UUID, stage_id: uuid.UUID, c: Ctx = Depends(workspace_admin)):
    stage = stage_or_404(c, pipeline_or_404(c, pipeline_id), stage_id)
    if n := deals_in(c, [stage.id]):
        raise ApiError(409, "conflict", f"Move the {n} deal{'s' * (n != 1)} in {stage.name} to another stage first")
    c.db.delete(stage)
    c.db.commit()


@router.post("/{pipeline_id}/stages/reorder")
def reorder_stages(pipeline_id: uuid.UUID, body: Order, c: Ctx = Depends(workspace_admin)):
    """The whole order in one call: every stage of the pipeline once, first to last."""
    pipeline = pipeline_or_404(c, pipeline_id)
    stages = stages_of(c, pipeline)
    if sorted(body.stage_ids) != sorted(s.id for s in stages):
        raise invalid(stage_ids="must list every stage of the pipeline exactly once")
    by_id = {s.id: s for s in stages}
    for position, stage_id in enumerate(body.stage_ids):
        by_id[stage_id].position = position
    c.db.commit()
    return pipeline_json(pipeline, [by_id[i] for i in body.stage_ids])
