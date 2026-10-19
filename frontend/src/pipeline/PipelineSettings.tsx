import { ArchiveRestore, ChevronDown, ChevronLeft, ChevronUp, GripVertical, LockKeyhole, Pencil, Plus, Trash2, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent, type FormEvent } from "react";
import { Link } from "react-router";
import { PageHeader } from "../shell/PageHeader";
import { Badge, Button, Dialog, EmptyState, Input, Select, Skeleton, Tooltip, useToast } from "../ui";
import { Popover } from "../ui/Popover";
import { FilterBuilder } from "../records/FilterBuilder";
import { cleanFilter, countConditions, filterFields, filterToText, groupItems, isGroup, toRoot } from "../records/filter.ts";
import { errorMessage, errorStatus } from "../records/errors.ts";
import { useMeta } from "../records/meta.tsx";
import { isComputed } from "../records/schema.ts";
import type { Filter } from "../records/types.ts";
import { ConfirmDialog } from "../records/Views";
import { pipelineClient } from "./client.ts";
import { MetaGate } from "./MetaGate";
import { dotColor } from "./DealCard";
import { useCan } from "./useCan.ts";
import type { Pipeline, Stage, StageKind, StagePatch } from "./types.ts";
import "../records/records.css";
import "./pipeline.css";

const COLORS = ["gray", "blue", "teal", "green", "amber", "orange", "red", "pink", "purple", "indigo"].map((c) => ({ value: c, label: c[0]!.toUpperCase() + c.slice(1) }));
const KINDS: { value: StageKind; label: string }[] = [
  { value: "open", label: "Open" },
  { value: "won", label: "Won" },
  { value: "lost", label: "Lost" },
];
const FIXED: Record<string, number> = { won: 100, lost: 0 };

/** Settings > Pipelines: pipelines and their stages. Needs the pipelines.manage capability to change anything. */
export function PipelineSettings() {
  return (
    <MetaGate
      skeleton={
        <div className="sh-page">
          <Skeleton style={{ width: 150, height: 26 }} />
          <Skeleton style={{ width: "100%", height: 320, marginTop: 24 }} />
        </div>
      }
    >
      <Settings />
    </MetaGate>
  );
}

type Rename = { id: string; name: string } | null;

function Settings() {
  const client = pipelineClient;
  const toast = useToast();
  const can = useCan();
  const meta = useMeta();
  const [all, setAll] = useState<Pipeline[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [denied, setDenied] = useState(false);
  const canManage = can.managePipelines && !denied;
  const [creating, setCreating] = useState(false);
  const [archiving, setArchiving] = useState<Pipeline | null>(null);
  const [renaming, setRenaming] = useState<Rename>(null);
  const [removing, setRemoving] = useState<Stage | null>(null);
  const [focusId, setFocusId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const [live, gone] = await Promise.all([client.list(), client.list(true)]);
      setAll([...live, ...gone]);
      setError(null);
    } catch (e) {
      setError(e);
    }
  }, [client]);
  useEffect(() => void load(), [load]);

  const live = useMemo(() => (all ?? []).filter((p) => !p.archived_at), [all]);
  const archived = useMemo(() => (all ?? []).filter((p) => p.archived_at), [all]);
  const current = (all ?? []).find((p) => p.id === selected) ?? live[0] ?? archived[0] ?? null;

  // the fields an exit rule may look at: the deal's own, not its stage or computed ones
  const refs = useMemo(() => filterFields("deal", meta.objects, meta.fields, meta.links).filter((r) => !r.path.includes(".") && r.path !== "stage" && !isComputed(r.field)), [meta]);

  /** Runs a change against the server; a refusal is shown and `undo` puts the screen back. A 403 turns the editing off. */
  const guard = async <T,>(what: string, run: () => Promise<T>, undo?: () => void): Promise<T | undefined> => {
    try {
      return await run();
    } catch (e) {
      undo?.();
      if (errorStatus(e) === 403) setDenied(true);
      toast({ title: what, description: errorMessage(e), tone: "danger" });
      return undefined;
    }
  };

  const edit = (id: string, fn: (p: Pipeline) => Pipeline) => setAll((list) => (list ?? []).map((p) => (p.id === id ? fn(p) : p)));

  const patchStage = async (p: Pipeline, stage: Stage, patch: StagePatch) => {
    const before = all;
    // what the server will do with a kind: a won or lost stage has a fixed probability, an open one that was something else starts at 10
    const kind = patch.kind ?? stage.kind;
    const probability = FIXED[kind] ?? patch.probability ?? (patch.kind && patch.kind !== stage.kind ? 10 : stage.probability);
    edit(p.id, (x) => ({ ...x, stages: x.stages.map((s) => (s.id === stage.id ? ({ ...s, ...patch, probability } as Stage) : s)) }));
    const saved = await guard("Could not save the stage", () => client.updateStage(p.id, stage.id, patch), () => setAll(before));
    if (saved) edit(p.id, (x) => ({ ...x, stages: x.stages.map((s) => (s.id === stage.id ? saved : s)) }));
  };

  const reorder = async (p: Pipeline, ids: string[]) => {
    const before = all;
    edit(p.id, (x) => ({ ...x, stages: ids.map((id) => x.stages.find((s) => s.id === id)!) }));
    await guard("Could not reorder the stages", () => client.reorderStages(p.id, ids), () => setAll(before));
  };

  const addStage = async (p: Pipeline) => {
    const stage = await guard("Could not add the stage", () => client.createStage(p.id, { name: "New stage", kind: "open" }));
    if (stage) {
      edit(p.id, (x) => ({ ...x, stages: [...x.stages, stage] }));
      setFocusId(stage.id);
    }
  };

  const removeStage = async () => {
    const stage = removing;
    if (!stage || !current) return;
    setBusy(true);
    const p = current;
    const index = p.stages.findIndex((s) => s.id === stage.id);
    const ok = await guard("Could not delete the stage", () => client.deleteStage(p.id, stage.id).then(() => true));
    setBusy(false);
    setRemoving(null);
    if (!ok) return;
    edit(p.id, (x) => ({ ...x, stages: x.stages.filter((s) => s.id !== stage.id) }));
    toast({
      title: "Stage deleted",
      description: stage.name,
      duration: 8000,
      action: {
        label: "Undo",
        onClick: () => {
          void (async () => {
            const spec = { name: stage.name, kind: stage.kind, probability: stage.probability, rotting_days: stage.rotting_days, color: stage.color, exit_rules: stage.exit_rules };
            const back = await guard("Could not bring the stage back", () => client.createStage(p.id, spec));
            if (!back) return;
            const order = (await client.list()).find((x) => x.id === p.id)!.stages.map((s) => s.id).filter((id) => id !== back.id);
            order.splice(index, 0, back.id);
            await guard("Could not put the stage back in its place", () => client.reorderStages(p.id, order));
            await load();
          })();
        },
      },
    });
  };

  const create = async (name: string) => {
    const made = await guard("Could not create the pipeline", () => client.createPipeline(name));
    if (made) {
      setCreating(false);
      await load();
      setSelected(made.id);
    }
    return !!made;
  };

  const archive = async (p: Pipeline, on: boolean) => {
    setBusy(true);
    const saved = await guard(on ? "Could not archive the pipeline" : "Could not restore the pipeline", () => client.archivePipeline(p.id, on));
    setBusy(false);
    setArchiving(null);
    if (!saved) return;
    await load();
    if (on) {
      setSelected(null);
      toast({ title: "Pipeline archived", description: p.name, duration: 8000, action: { label: "Undo", onClick: () => void archive(p, false).then(() => setSelected(p.id)) } });
    } else toast({ title: "Pipeline restored", description: p.name, tone: "success" });
  };

  const rename = async (e: FormEvent) => {
    e.preventDefault();
    if (!renaming || !current) return;
    const name = renaming.name.trim();
    if (!name || name === current.name) return setRenaming(null);
    const saved = await guard("Could not rename the pipeline", () => client.renamePipeline(current.id, name));
    if (saved) edit(current.id, (x) => ({ ...x, name: saved.name }));
    setRenaming(null);
  };

  if (error) {
    const forbidden = errorStatus(error) === 403;
    return (
      <div className="sh-page">
        <EmptyState
          icon={forbidden ? LockKeyhole : TriangleAlert}
          title={forbidden ? "You do not have access to pipelines" : "We could not load the pipelines"}
          text={forbidden ? "Ask a workspace admin to give you access." : errorMessage(error)}
          action={forbidden ? undefined : <Button onClick={() => void load()}>Try again</Button>}
        />
      </div>
    );
  }
  if (!all) {
    return (
      <div className="sh-page" aria-busy="true" aria-label="Loading">
        <Skeleton style={{ width: 150, height: 26 }} />
        <Skeleton style={{ width: "100%", height: 320, marginTop: 24 }} />
      </div>
    );
  }

  return (
    <div className="sh-page">
      <PageHeader
        title="Pipelines"
        description="Stages, probabilities, when a deal starts to rot, and what a deal needs before it moves on."
        actions={
          <>
            <Link to="/settings" className="ui-btn" data-variant="ghost" data-size="md">
              <ChevronLeft size={16} aria-hidden /> Settings
            </Link>
            {canManage && (
              <Button variant="primary" onClick={() => setCreating(true)}>
                <Plus size={16} aria-hidden /> New pipeline
              </Button>
            )}
          </>
        }
      />
      {!canManage && (
        <p className="pl-note" role="status">
          <LockKeyhole size={14} aria-hidden /> Your role can see pipelines but not change them. Ask a workspace admin or manager to make changes.
        </p>
      )}

      <div className="pl-set">
        <nav className="pl-set-nav" aria-label="Pipelines">
          <ul className="pl-set-list">
            {live.map((p) => (
              <li key={p.id}>
                <button type="button" className="pl-set-pick" aria-current={current?.id === p.id} onClick={() => setSelected(p.id)}>
                  {p.name}
                  <small>{p.stages.length} stages</small>
                </button>
              </li>
            ))}
          </ul>
          {archived.length > 0 && (
            <>
              <span className="pl-set-label">Archived</span>
              <ul className="pl-set-list">
                {archived.map((p) => (
                  <li key={p.id}>
                    <button type="button" className="pl-set-pick" aria-current={current?.id === p.id} onClick={() => setSelected(p.id)}>
                      {p.name}
                      <Badge tone="neutral">Archived</Badge>
                    </button>
                  </li>
                ))}
              </ul>
            </>
          )}
        </nav>

        {current ? (
          <section className="pl-set-main" aria-label={`${current.name} stages`}>
            <div className="pl-set-head">
              {renaming?.id === current.id ? (
                <form className="pl-set-name" onSubmit={rename} style={{ display: "flex", gap: 8 }}>
                  <Input aria-label="Pipeline name" autoFocus value={renaming.name} maxLength={80} onChange={(e) => setRenaming({ id: current.id, name: e.target.value })} onKeyDown={(e) => e.key === "Escape" && setRenaming(null)} />
                  <Button type="submit" variant="primary" size="sm">
                    Save
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => setRenaming(null)}>
                    Cancel
                  </Button>
                </form>
              ) : (
                <h2>
                  {current.name} {current.archived_at && <Badge tone="neutral">Archived</Badge>}
                </h2>
              )}
              {canManage && renaming?.id !== current.id && (
                <>
                  <Button size="sm" variant="ghost" onClick={() => setRenaming({ id: current.id, name: current.name })}>
                    <Pencil size={14} aria-hidden /> Rename
                  </Button>
                  {current.archived_at ? (
                    <Button size="sm" onClick={() => void archive(current, false)} loading={busy}>
                      <ArchiveRestore size={14} aria-hidden /> Restore
                    </Button>
                  ) : (
                    <Tooltip content={live.length < 2 ? "A workspace needs at least one pipeline that is not archived" : "Archive this pipeline"}>
                      <span>
                        <Button size="sm" disabled={live.length < 2} onClick={() => setArchiving(current)}>
                          Archive
                        </Button>
                      </span>
                    </Tooltip>
                  )}
                </>
              )}
            </div>
            <p className="pl-set-note">
              A deal can leave a stage only when it meets that stage's exit rules. Won stages are 100% and lost stages 0%, and a lost stage asks why. A deal rots when it stays in a stage longer than the days you set.
            </p>
            <StageEditor
              pipeline={current}
              canManage={canManage}
              refs={refs}
              focusId={focusId}
              onFocused={() => setFocusId(null)}
              onPatch={(s, patch) => void patchStage(current, s, patch)}
              onReorder={(ids) => void reorder(current, ids)}
              onAdd={() => void addStage(current)}
              onRemove={setRemoving}
            />
          </section>
        ) : (
          <EmptyState icon={LockKeyhole} title="No pipelines" text="Create a pipeline to give your deals stages." />
        )}
      </div>

      <NewPipeline open={creating} onOpenChange={setCreating} onCreate={create} />
      <ConfirmDialog
        open={archiving !== null}
        onOpenChange={(o) => !o && setArchiving(null)}
        title={`Archive ${archiving?.name ?? "this pipeline"}?`}
        description="It leaves the board and the pipeline picker. Its deals keep their stages, and you can restore it here at any time."
        confirm="Archive"
        busy={busy}
        onConfirm={() => archiving && void archive(archiving, true)}
      />
      <ConfirmDialog
        open={removing !== null}
        onOpenChange={(o) => !o && setRemoving(null)}
        title={`Delete the stage ${removing?.name ?? ""}?`}
        description="A stage that still has deals cannot be deleted: move them to another stage first. You can undo this right after."
        confirm="Delete stage"
        busy={busy}
        onConfirm={() => void removeStage()}
      />
    </div>
  );
}

function NewPipeline({ open, onOpenChange, onCreate }: { open: boolean; onOpenChange: (o: boolean) => void; onCreate: (name: string) => Promise<boolean> }) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) setName("");
  }, [open]);
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    setBusy(true);
    await onCreate(name.trim());
    setBusy(false);
  };
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="New pipeline"
      description="It starts with the stages of the Sales pipeline (Lead, Qualified, Proposal, Negotiation, Won, Lost). Change them once it exists."
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" type="submit" form="new-pipeline-form" loading={busy} disabled={!name.trim()}>
            Create pipeline
          </Button>
        </>
      }
    >
      <form id="new-pipeline-form" className="rec-form" onSubmit={submit}>
        <Input label="Name" autoFocus value={name} maxLength={80} onChange={(e) => setName(e.target.value)} placeholder="Partnerships" />
      </form>
    </Dialog>
  );
}

// ---- the stages ----

type Over = { id: string; where: "before" | "after" } | null;

function StageEditor({ pipeline, canManage, refs, focusId, onFocused, onPatch, onReorder, onAdd, onRemove }: {
  pipeline: Pipeline;
  canManage: boolean;
  refs: ReturnType<typeof filterFields>;
  focusId: string | null;
  onFocused: () => void;
  onPatch: (stage: Stage, patch: StagePatch) => void;
  onReorder: (ids: string[]) => void;
  onAdd: () => void;
  onRemove: (stage: Stage) => void;
}) {
  const [dragging, setDragging] = useState<string | null>(null);
  const [over, setOver] = useState<Over>(null);
  const ids = pipeline.stages.map((s) => s.id);

  const dragOver = (id: string, e: DragEvent<HTMLElement>) => {
    if (!dragging || dragging === id) return;
    e.preventDefault();
    const r = e.currentTarget.getBoundingClientRect();
    const where = e.clientY < r.top + r.height / 2 ? "before" : "after";
    setOver((o) => (o && o.id === id && o.where === where ? o : { id, where }));
  };
  const drop = (e: DragEvent<HTMLElement>) => {
    e.preventDefault();
    if (dragging && over) {
      const rest = ids.filter((i) => i !== dragging);
      const at = rest.indexOf(over.id) + (over.where === "after" ? 1 : 0);
      const next = [...rest.slice(0, at), dragging, ...rest.slice(at)];
      if (next.join() !== ids.join()) onReorder(next);
    }
    setDragging(null);
    setOver(null);
  };

  return (
    <>
      <ul className="pl-stages" aria-label="Stages" onDrop={drop} onDragOver={(e) => dragging && e.preventDefault()}>
        <li className="pl-stage-head" aria-hidden>
          <span />
          <span>Color</span>
          <span>Name</span>
          <span>Type</span>
          <span>Probability</span>
          <span>Rots after</span>
          <span>Exit rules</span>
          <span />
        </li>
        {pipeline.stages.map((s, i) => (
          <StageRow
            key={s.id}
            stage={s}
            index={i}
            count={pipeline.stages.length}
            canManage={canManage}
            refs={refs}
            focus={focusId === s.id}
            onFocused={onFocused}
            dragging={dragging === s.id}
            over={over?.id === s.id ? over.where : null}
            onDragStart={() => setDragging(s.id)}
            onDragEnd={() => {
              setDragging(null);
              setOver(null);
            }}
            onDragOver={(e) => dragOver(s.id, e)}
            onPatch={(patch) => onPatch(s, patch)}
            onMove={(by) => {
              const to = i + by;
              if (to < 0 || to >= ids.length) return;
              const next = [...ids];
              next.splice(i, 1);
              next.splice(to, 0, s.id);
              onReorder(next);
            }}
            onRemove={() => onRemove(s)}
          />
        ))}
      </ul>
      {canManage && (
        <div className="pl-stage-add">
          <Button size="sm" onClick={onAdd} disabled={pipeline.stages.length >= 30}>
            <Plus size={14} aria-hidden /> Add stage
          </Button>
        </div>
      )}
    </>
  );
}

function StageRow({ stage, index, count, canManage, refs, focus, onFocused, dragging, over, onDragStart, onDragEnd, onDragOver, onPatch, onMove, onRemove }: {
  stage: Stage;
  index: number;
  count: number;
  canManage: boolean;
  refs: ReturnType<typeof filterFields>;
  focus: boolean;
  onFocused: () => void;
  dragging: boolean;
  over: "before" | "after" | null;
  onDragStart: () => void;
  onDragEnd: () => void;
  onDragOver: (e: DragEvent<HTMLElement>) => void;
  onPatch: (patch: StagePatch) => void;
  onMove: (by: number) => void;
  onRemove: () => void;
}) {
  const [name, setName] = useState(stage.name);
  const [prob, setProb] = useState(String(stage.probability));
  const [rot, setRot] = useState(stage.rotting_days === null ? "" : String(stage.rotting_days));
  const rowRef = useRef<HTMLLIElement>(null);
  const nameRef = useRef<HTMLInputElement>(null);
  useEffect(() => setName(stage.name), [stage.name]);
  useEffect(() => setProb(String(stage.probability)), [stage.probability]);
  useEffect(() => setRot(stage.rotting_days === null ? "" : String(stage.rotting_days)), [stage.rotting_days]);
  useEffect(() => {
    if (focus) {
      nameRef.current?.focus();
      nameRef.current?.select();
      onFocused();
    }
  }, [focus]); // eslint-disable-line react-hooks/exhaustive-deps

  const fixed = FIXED[stage.kind] !== undefined;
  const commitName = () => {
    const v = name.trim();
    if (!v) return setName(stage.name);
    if (v !== stage.name) onPatch({ name: v });
  };
  const commitProb = () => {
    const n = Math.round(Number(prob));
    if (prob.trim() === "" || !Number.isFinite(n) || n < 0 || n > 100) return setProb(String(stage.probability));
    if (n !== stage.probability) onPatch({ probability: n });
  };
  const commitRot = () => {
    if (rot.trim() === "") return stage.rotting_days === null ? undefined : onPatch({ rotting_days: null });
    const n = Math.round(Number(rot));
    if (!Number.isFinite(n) || n < 1 || n > 3650) return setRot(stage.rotting_days === null ? "" : String(stage.rotting_days));
    if (n !== stage.rotting_days) onPatch({ rotting_days: n });
  };
  const enter = (commit: () => void) => (e: React.KeyboardEvent) => e.key === "Enter" && (e.preventDefault(), commit());

  return (
    <li ref={rowRef} className="pl-stage" data-dragging={dragging || undefined} data-over={over ?? undefined} onDragOver={onDragOver}>
      <span className="pl-stage-move">
        {canManage && (
          <>
            <button
              type="button"
              className="ui-btn pl-handle"
              data-variant="ghost"
              data-size="icon"
              draggable
              aria-label={`Drag ${stage.name} to reorder`}
              onDragStart={(e) => {
                e.dataTransfer.effectAllowed = "move";
                e.dataTransfer.setData("text/plain", stage.id);
                if (rowRef.current) e.dataTransfer.setDragImage(rowRef.current, 16, 16);
                setTimeout(onDragStart, 0);
              }}
              onDragEnd={onDragEnd}
            >
              <GripVertical size={14} aria-hidden />
            </button>
            <Button size="icon" variant="ghost" aria-label={`Move ${stage.name} up`} disabled={index === 0} onClick={() => onMove(-1)}>
              <ChevronUp size={14} aria-hidden />
            </Button>
            <Button size="icon" variant="ghost" aria-label={`Move ${stage.name} down`} disabled={index === count - 1} onClick={() => onMove(1)}>
              <ChevronDown size={14} aria-hidden />
            </Button>
          </>
        )}
      </span>

      <div className="pl-stage-cell pl-stage-color">
        <span className="pl-cell-label">Color</span>
        <span className="pl-dot" style={{ background: dotColor(stage.color) }} aria-hidden />
        <Select aria-label={`Color of ${stage.name}`} value={stage.color ?? "gray"} disabled={!canManage} onValueChange={(color) => onPatch({ color })} options={COLORS} />
      </div>

      <div className="pl-stage-cell pl-stage-name">
        <span className="pl-cell-label">Name</span>
        <input ref={nameRef} className="ui-input" aria-label={`Name of stage ${index + 1}`} value={name} maxLength={80} disabled={!canManage} onChange={(e) => setName(e.target.value)} onBlur={commitName} onKeyDown={enter(commitName)} />
      </div>

      <div className="pl-stage-cell pl-stage-kind">
        <span className="pl-cell-label">Type</span>
        <Select aria-label={`Type of ${stage.name}`} value={stage.kind} disabled={!canManage} onValueChange={(kind) => onPatch({ kind: kind as StageKind })} options={KINDS} />
      </div>

      <div className="pl-stage-cell pl-stage-prob">
        <span className="pl-cell-label">Probability (%)</span>
        <input className="ui-input num" type="number" inputMode="numeric" min={0} max={100} aria-label={`Probability of ${stage.name}, percent`} value={prob} disabled={!canManage || fixed} title={fixed ? `A ${stage.kind} stage is always ${FIXED[stage.kind]}%` : undefined} onChange={(e) => setProb(e.target.value)} onBlur={commitProb} onKeyDown={enter(commitProb)} />
      </div>

      <div className="pl-stage-cell pl-stage-rot">
        <span className="pl-cell-label">Rots after (days)</span>
        <input className="ui-input num" type="number" inputMode="numeric" min={1} max={3650} placeholder="Never" aria-label={`Days after which a deal in ${stage.name} is rotting`} value={rot} disabled={!canManage || fixed} title={fixed ? "Only open stages rot" : undefined} onChange={(e) => setRot(e.target.value)} onBlur={commitRot} onKeyDown={enter(commitRot)} />
      </div>

      <div className="pl-stage-cell pl-stage-rules">
        <span className="pl-cell-label">Exit rules</span>
        <ExitRules stage={stage} refs={refs} canManage={canManage} onSave={(rules) => onPatch({ exit_rules: rules })} />
      </div>

      <div className="pl-stage-cell pl-stage-del">
        {canManage && (
          <Button size="icon" variant="ghost" aria-label={`Delete stage ${stage.name}`} onClick={onRemove}>
            <Trash2 size={14} aria-hidden />
          </Button>
        )}
      </div>
    </li>
  );
}

// ---- exit rules, built with the records filter builder on the deal's own fields ----

function ExitRules({ stage, refs, canManage, onSave }: { stage: Stage; refs: ReturnType<typeof filterFields>; canManage: boolean; onSave: (rules: Filter | Record<string, never>) => void }) {
  const [open, setOpen] = useState(false);
  const rules = (Object.keys(stage.exit_rules).length ? stage.exit_rules : null) as Filter | null;
  const n = countConditions(rules);
  return (
    <Popover
      label={`Exit rules of ${stage.name}`}
      open={open}
      onOpenChange={setOpen}
      className="pl-rules-pop"
      trigger={
        <Button size="sm" aria-label={`Exit rules of ${stage.name}: ${n ? `${n} rule${n === 1 ? "" : "s"}` : "none"}`}>
          {n ? `${n} rule${n === 1 ? "" : "s"}` : canManage ? "Add rules" : "None"}
        </Button>
      }
    >
      {open && <RulesBody stage={stage} rules={rules} refs={refs} canManage={canManage} onCancel={() => setOpen(false)} onSave={(r) => (setOpen(false), onSave(r))} />}
    </Popover>
  );
}

function RulesBody({ stage, rules, refs, canManage, onCancel, onSave }: { stage: Stage; rules: Filter | null; refs: ReturnType<typeof filterFields>; canManage: boolean; onCancel: () => void; onSave: (rules: Filter | Record<string, never>) => void }) {
  const meta = useMeta();
  const [draft, setDraft] = useState<Filter | null>(rules);
  const fields = useMemo(() => refs.map((r) => r.field), [refs]);
  if (!canManage) {
    const parts = rules ? (isGroup(toRoot(rules)) ? groupItems(toRoot(rules)) : [rules]) : [];
    return (
      <div className="pl-rules-head">
        <h3 className="rec-section-title">Exit rules of {stage.name}</h3>
        {parts.length === 0 ? <p>A deal can leave {stage.name} at any time.</p> : <ul>{parts.map((p, i) => <li key={i}>{filterToText(p, fields, { users: meta.users, tags: meta.tags })}</li>)}</ul>}
      </div>
    );
  }
  const clean = cleanFilter(draft);
  return (
    <>
      <div className="pl-rules-head">
        <h3 className="rec-section-title">Exit rules of {stage.name}</h3>
        <p>A deal must meet every rule here before it can leave {stage.name}. The board asks for what is missing when someone moves it.</p>
      </div>
      <FilterBuilder value={rules} onChange={setDraft} refs={refs} noun="deals" />
      <div className="pl-rules-foot">
        <span className="pl-rules-text">{clean ? `${countConditions(clean)} rule${countConditions(clean) === 1 ? "" : "s"}` : "No rules: a deal can leave at any time"}</span>
        <Button size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button size="sm" variant="primary" onClick={() => onSave(clean ?? {})}>
          Save rules
        </Button>
      </div>
    </>
  );
}
