import { Archive, ChevronLeft, CircleAlert, EllipsisVertical, FlaskConical, LockKeyhole, Minus, NotebookPen, Pause, Play, Plus, Redo2, SearchCheck, Undo2, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useBlocker, useNavigate, useParams, useSearchParams } from "react-router";
import { ApiError, errorText } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { timeAgo } from "../lib/device";
import { MOD } from "../lib/platform";
import { useMediaQuery } from "../lib/useMediaQuery";
import { MetaGate } from "../pipeline/MetaGate";
import { filterFields, filterToText } from "../records/filter.ts";
import { zoneName } from "../records/format.ts";
import { useMeta } from "../records/meta.tsx";
import type { Filter } from "../records/types.ts";
import { PageHeader } from "../shell/PageHeader";
import { TYPING } from "../shell/useShortcuts";
import { Badge, Button, Dialog, DropdownMenu, EmptyState, Input, Kbd, MenuItem, MenuSeparator, Select, Sheet, Skeleton, Switch, Tabs, TabsContent, TabsList, TabsTrigger, useToast } from "../ui";
import { lookups as loadLookups, workflows, type Catalog, type Glance, type StepStatus, type TestResult, type WorkflowDetail, type WorkflowRow } from "./api";
import { Canvas, firstError, type AddChoice } from "./Canvas";
import { LookupsCtx, type Lookups } from "./ConfigForm";
import { title, type Names } from "./describe";
import { ExplainDialog } from "./ExplainDialog";
import { addGoal, blank, connect, exits, insert, move, newId, order, place, remove, removalImpact, same, secondsText, update, type Graph, type Placed, type Slot, type WfNode } from "./graph";
import { History } from "./History";
import { NodePanel, TriggerPanel } from "./Panel";
import { enrolled, StatusBadge, versionText } from "./parts";
import { PublishDialog } from "./PublishDialog";
import { RunSheet, Runs } from "./Runs";
import { defaults } from "./schema";
import { TestDialog } from "./TestDialog";
import { useWorkflowActions } from "./WorkflowsPage";
import "./workflows.css";

const NO_ERRORS: Placed = { trigger: {}, nodes: {}, general: [] };
const TABS = ["build", "runs", "history", "settings"] as const;
const ZOOMS = [0.5, 0.67, 0.8, 1, 1.25];
type Stored = { base: number | null; graph: Graph; at: string };
const draftKey = (id: string) => `gh:wf-draft:${id}`;
function readDraft(id: string): Stored | null {
  try {
    const raw = localStorage.getItem(draftKey(id));
    const v = raw ? (JSON.parse(raw) as Stored) : null;
    return v && v.graph && typeof v.graph === "object" && v.graph.nodes ? v : null;
  } catch {
    return null;
  }
}
function writeDraft(id: string, v: Stored | null) {
  try {
    if (v) localStorage.setItem(draftKey(id), JSON.stringify(v));
    else localStorage.removeItem(draftKey(id));
  } catch {
    /* storage full or blocked: the blocker still guards the changes */
  }
}

export function WorkflowBuilder() {
  const { id = "" } = useParams();
  return (
    <MetaGate skeleton={<BuilderSkeleton />}>
      <Builder key={id} id={id} />
    </MetaGate>
  );
}

function BuilderSkeleton() {
  return (
    <div className="sh-page wf-page" aria-busy="true">
      <Skeleton style={{ height: 14, width: 90, marginBottom: 16 }} />
      <Skeleton style={{ height: 24, width: 260, marginBottom: 24 }} />
      <div className="wf-stack wf-skeleton-canvas">
        {[0, 1, 2].map((i) => (
          <Skeleton key={i} style={{ height: 64, width: 280 }} />
        ))}
      </div>
    </div>
  );
}

function Builder({ id }: { id: string }) {
  const navigate = useNavigate();
  const toast = useToast();
  const meta = useMeta();
  const { can } = useCan();
  const canWrite = can("workflows.write");
  const canPublish = can("workflows.publish");
  const wide = useMediaQuery("(min-width: 1100px)");
  const [params, setParams] = useSearchParams();
  const tab = (TABS as readonly string[]).includes(params.get("tab") ?? "") ? params.get("tab")! : "build";
  const runId = params.get("run");

  const [wf, setWf] = useState<WorkflowDetail | null>(null);
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [loadError, setLoadError] = useState<{ text: string; status: number }>();
  const [lookups, setLookups] = useState<Lookups>({ channels: null, stages: null, forms: null, calendars: null });
  const [graph, setGraph] = useState<Graph>(blank());
  const [saved, setSaved] = useState<Graph>(blank());
  const [base, setBase] = useState<number | null>(null);
  const [past, setPast] = useState<Graph[]>([]);
  const [future, setFuture] = useState<Graph[]>([]);
  const lastEdit = useRef(0);
  const [revision, setRevision] = useState(0); // remounts the panel's editors after undo, redo and loads
  const [selected, setSelected] = useState<string | null>("trigger");
  const [sheet, setSheet] = useState(false);
  const [errors, setErrors] = useState<Placed>(NO_ERRORS);
  const [busy, setBusy] = useState<"save" | "publish" | "test" | null>(null);
  const [menuOpen, setMenuOpen] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [restore, setRestore] = useState<Stored | null>(null);
  const [conflict, setConflict] = useState<WorkflowDetail | null>(null);
  const [removing, setRemoving] = useState<{ id: string; impact: string[] } | null>(null);
  const [goto, setGoto] = useState<Slot | null>(null);
  const [noteOpen, setNoteOpen] = useState(false);
  const [publishing, setPublishing] = useState<number | null>(null);
  const [testing, setTesting] = useState<{ version: number; graph: Graph } | null>(null);
  const [lastTest, setLastTest] = useState<{ result: TestResult; record: Glance } | null>(null);
  const [explain, setExplain] = useState<{ record: Glance | null } | null>(null);
  const [runsKey, setRunsKey] = useState(0);
  const [historyKey, setHistoryKey] = useState(0);

  const load = useCallback(() => {
    setLoadError(undefined);
    Promise.all([workflows.get(id), workflows.catalog()])
      .then(([w, cat]) => {
        const g = w.graph ?? blank();
        setWf(w);
        setCatalog(cat);
        setGraph(g);
        setSaved(g);
        setBase(w.latest_version);
        setPast([]);
        setFuture([]);
        setRevision((r) => r + 1);
        setSelected(w.graph?.start ?? "trigger");
        const stored = readDraft(id);
        if (stored && !same(stored.graph, g)) setRestore(stored);
        else writeDraft(id, null);
      })
      .catch((e) => setLoadError({ text: e instanceof ApiError && e.status === 404 ? "This workflow does not exist, or it was in another workspace." : errorText(e), status: e instanceof ApiError ? e.status : 0 }));
  }, [id]);
  useEffect(load, [load]);
  useEffect(() => {
    const safe = <T,>(p: Promise<T[]>) => p.catch(() => [] as T[]); // a role that may not list channels still builds the rest
    void Promise.all([safe(loadLookups.channels()), safe(loadLookups.stages()), safe(loadLookups.forms()), safe(loadLookups.calendars())]).then(([channels, stages, forms, calendars]) => setLookups({ channels, stages, forms, calendars }));
  }, []);

  // a wide workflow opens with its trigger in the middle of the canvas, not its left edge
  const scroller = useRef<HTMLDivElement>(null);
  const loaded = !!wf && !!catalog;
  useEffect(() => {
    const el = scroller.current;
    const trigger = el?.querySelector<HTMLElement>('[data-node="trigger"]');
    if (!el || !trigger || tab !== "build") return;
    const t = trigger.getBoundingClientRect();
    const box = el.getBoundingClientRect();
    el.scrollLeft += t.left + t.width / 2 - (box.left + box.width / 2);
  }, [loaded, tab, zoom]);

  /** The largest zoom at which the whole width of the workflow shows. */
  const fitting = () => {
    const el = scroller.current;
    if (!el) return 1;
    const pad = 32; // the scroller's side padding, which zoom does not scale
    const natural = (el.scrollWidth - pad) / zoom;
    const room = el.clientWidth - pad;
    return [...ZOOMS].reverse().find((z) => z <= 1 && natural * z <= room) ?? ZOOMS[0]!;
  };
  const fit = () => setZoom(fitting());
  // a workflow a little wider than the canvas opens zoomed out to fit, where the text stays readable (not on phones)
  useEffect(() => {
    if (!loaded || !matchMedia("(min-width: 768px)").matches) return;
    const z = fitting();
    if (z >= 0.67 && z < 1) setZoom(z);
  }, [loaded]);

  const dirty = useMemo(() => !!wf && !same(graph, saved), [wf, graph, saved]);
  useEffect(() => {
    if (!wf || restore) return;
    const t = setTimeout(() => writeDraft(id, dirty ? { base, graph, at: new Date().toISOString() } : null), 400);
    return () => clearTimeout(t);
  }, [graph, dirty, base, id, wf, restore]);
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname);
  useEffect(() => {
    if (!dirty) return;
    const stop = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", stop);
    return () => window.removeEventListener("beforeunload", stop);
  }, [dirty]);

  const object = graph.trigger.object ?? "contact";
  const refs = useMemo(() => filterFields(object, meta.objects, meta.fields, meta.links), [object, meta]);
  const names: Names = useMemo(() => {
    const timeZone = zoneName(); // an Intl formatter is slow to make: once, not per condition on the canvas
    const fields = refs.map((r) => r.field);
    return {
      user: (u) => meta.users.find((x) => x.id === u)?.name,
      tag: (v) => meta.tags.find((t) => t.id === v || t.name.toLowerCase() === v.toLowerCase())?.name,
      channel: (c) => lookups.channels?.find((x) => x.id === c)?.name,
      stage: (s) => lookups.stages?.find((x) => x.id === s)?.name,
      form: (f) => lookups.forms?.find((x) => x.id === f)?.name,
      calendar: (c) => lookups.calendars?.find((x) => x.id === c)?.name,
      field: (k) => (meta.fields[object] ?? []).find((f) => f.key === k)?.label,
      filter: (ast) => filterToText(ast as Filter, fields, { tags: meta.tags, users: meta.users, timeZone }),
      action: (k) => catalog?.actions.find((a) => a.key === k)?.label,
    };
  }, [meta, lookups, object, refs, catalog]);

  // ---- editing ----

  const edit = useCallback(
    (next: Graph, opts: { coalesce?: boolean } = {}) => {
      const now = Date.now();
      if (!opts.coalesce || now - lastEdit.current > 800) setPast((p) => [...p.slice(-99), graph]);
      lastEdit.current = opts.coalesce ? now : 0;
      setFuture([]);
      setGraph(next);
    },
    [graph],
  );
  const undo = useCallback(() => {
    if (!past.length) return;
    setFuture((f) => [graph, ...f].slice(0, 100));
    setGraph(past[past.length - 1]!);
    setPast((p) => p.slice(0, -1));
    lastEdit.current = 0;
    setRevision((r) => r + 1);
  }, [past, graph]);
  const redo = useCallback(() => {
    if (!future.length) return;
    setPast((p) => [...p, graph]);
    setGraph(future[0]!);
    setFuture((f) => f.slice(1));
    lastEdit.current = 0;
    setRevision((r) => r + 1);
  }, [future, graph]);

  /** Drops the server's errors about what an edit changed (`changed`: the paths it touched, "config.body"); the
   * other errors stay until the next save. No `changed`: all of that node's. */
  const forget = (node: string | "trigger", changed?: string[]) =>
    setErrors((e) => {
      const errs = node === "trigger" ? e.trigger : e.nodes[node];
      if (!errs || !Object.keys(errs).length) return e;
      const hit = (path: string) => !changed || (path === "config" && changed.some((c) => c.startsWith("config."))) || changed.some((c) => path === c || path.startsWith(`${c}.`));
      const kept = Object.fromEntries(Object.entries(errs).filter(([p]) => !hit(p)));
      if (Object.keys(kept).length === Object.keys(errs).length) return e;
      if (node === "trigger") return { ...e, trigger: kept };
      const nodes = { ...e.nodes, [node]: kept };
      if (!Object.keys(kept).length) delete nodes[node];
      return { ...e, nodes };
    });
  const touched = (before: Record<string, unknown>, after: Record<string, unknown>, prefix = "") =>
    [...new Set([...Object.keys(before), ...Object.keys(after)])].filter((k) => !same(before[k], after[k])).map((k) => `${prefix}${k}`);

  const newNode = (choice: Exclude<AddChoice, { type: "goto" }>): { id: string; node: WfNode } => {
    if (choice.type === "action") {
      const spec = catalog!.actions.find((a) => a.key === choice.action)!;
      return { id: newId(graph, spec.key), node: { type: "action", action: spec.key, config: defaults(spec.config_schema) } };
    }
    const config: Record<string, Record<string, unknown>> = {
      wait: { duration: { days: 1 } },
      condition: { filter: {} },
      split: { paths: [{ name: "a", percent: 50 }, { name: "b", percent: 50 }] },
      end: {},
      subflow: {},
    };
    const base = { wait: "wait", condition: "check", split: "split", end: "end", subflow: "subflow", action: "step" }[choice.type];
    return { id: newId(graph, base), node: { type: choice.type, config: config[choice.type] ?? {} } };
  };

  const open = useCallback(
    (nid: string) => {
      setSelected(nid);
      if (!wide) setSheet(true);
    },
    [wide],
  );
  const add = (slot: Slot, choice: AddChoice) => {
    setMenuOpen(null);
    if (choice.type === "goto") return setGoto(slot);
    if (Object.keys(graph.nodes).length >= (catalog?.limits.max_nodes ?? 200)) return toast({ title: "This workflow is full", description: `A workflow has at most ${catalog?.limits.max_nodes ?? 200} steps.`, tone: "danger" });
    const made = newNode(choice);
    edit(insert(graph, slot, made.id, made.node));
    open(made.id);
    requestAnimationFrame(() => {
      const el = document.querySelector<HTMLElement>(`[data-node="${made.id}"]`);
      el?.focus({ preventScroll: true });
      el?.scrollIntoView({ block: "nearest", inline: "center" });
    });
  };
  const addAGoal = () => {
    const gid = newId(graph, "goal");
    edit(addGoal(graph, gid, { type: "goal", config: { filter: {}, otherwise: "continue" } }));
    open(gid);
  };
  const removeNow = (nid: string) => {
    const before = graph;
    const node = graph.nodes[nid];
    if (!node) return;
    edit(remove(graph, nid));
    forget(nid);
    setSelected(slotOf(before, nid));
    setSheet(false);
    toast({ title: "Step removed", description: title(node, names), tone: "info", action: { label: "Undo", onClick: () => (setGraph(before), setRevision((r) => r + 1), setSelected(nid)) } });
  };
  const askRemove = (nid: string) => {
    const impact = removalImpact(graph, nid);
    if (impact.length > 1) setRemoving({ id: nid, impact });
    else removeNow(nid);
  };

  // ---- saving ----

  const fail = (e: unknown, what: string) => {
    if (e instanceof ApiError && e.fields) {
      const placed = place(e.fields);
      setErrors(placed);
      const first = Object.keys(placed.nodes)[0] ?? (Object.keys(placed.trigger).length ? "trigger" : null);
      if (first) {
        setSelected(first);
        if (tab !== "build") setParams({}, { replace: true });
      }
      toast({ title: `${what}: the workflow has problems`, description: "Each one is on its step, and listed above the canvas.", tone: "danger" });
    } else toast({ title: `${what} did not work`, description: errorText(e), tone: "danger" });
  };

  const commitSaved = (g: Graph, n: number, row?: Partial<WorkflowRow>) => {
    setGraph(g);
    setSaved(g);
    setBase(n);
    setRevision((r) => r + 1);
    writeDraft(id, null);
    setHistoryKey((k) => k + 1);
    if (row) setWf((w) => (w ? { ...w, ...row } : w));
  };

  /** Saves the draft as the next version; resolves with its number, or null when it did not save. */
  const save = useCallback(
    async (note?: string, force = false): Promise<number | null> => {
      if (!wf || !canWrite || wf.status === "archived") return null;
      if (!dirty && !note) return base;
      setBusy("save");
      try {
        if (!force) {
          const fresh = await workflows.get(wf.id);
          if (fresh.latest_version !== base) {
            setConflict(fresh);
            return null;
          }
        }
        const v = await workflows.save(wf.id, graph, note);
        setErrors(NO_ERRORS);
        const row = await workflows.get(wf.id);
        commitSaved(v.graph, v.number, row);
        return v.number;
      } catch (e) {
        fail(e, "Saving");
        return null;
      } finally {
        setBusy(null);
      }
    },
    [wf, canWrite, dirty, base, graph],
  );

  async function startPublish(version?: number) {
    if (!wf) return;
    if (version !== undefined) return setPublishing(version);
    const n = dirty ? await save() : base;
    if (n !== null) setPublishing(n);
    else if (!dirty) toast({ title: "Nothing to publish yet", description: "Add a step and save it first.", tone: "info" });
  }
  async function startTest() {
    if (!wf) return;
    if (!Object.keys(graph.nodes).length) return toast({ title: "Nothing to test yet", description: "Add a step first.", tone: "info" });
    setBusy("test");
    const n = dirty ? await save() : base;
    setBusy(null);
    if (n === null) return;
    const g = n === base && !dirty ? saved : (await workflows.version(wf.id, n).catch(() => null))?.graph;
    if (g) setTesting({ version: n, graph: g });
  }

  const actions = useWorkflowActions((row) => {
    if (row.status === "archived") return navigate("/automations");
    setWf((w) => (w ? { ...w, ...row } : w));
  });

  // ---- keyboard ----

  const ids = useMemo(() => ["trigger", ...order(graph)], [graph]);
  const canEdit = canWrite && wf?.status !== "archived";
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const mod = e.ctrlKey || e.metaKey;
      const target = e.target instanceof Element ? e.target : null;
      const typing = !!target?.closest(TYPING);
      const dialog = !!document.querySelector('[role="dialog"]');
      if (mod && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (dirty && !dialog && canEdit) void save();
        return;
      }
      if (tab !== "build" || dialog) return;
      if (mod && !typing && e.key.toLowerCase() === "z") {
        e.preventDefault();
        if (e.shiftKey) redo();
        else undo();
        return;
      }
      if (mod && !typing && e.key.toLowerCase() === "y") {
        e.preventDefault();
        redo();
        return;
      }
      if (typing || mod) return;
      const onNode = !!target?.closest(".wf-node");
      const at = selected ? ids.indexOf(selected) : -1;
      const go = (i: number) => {
        const target = ids[Math.max(0, Math.min(ids.length - 1, i))];
        if (!target) return;
        setSelected(target);
        const el = document.querySelector<HTMLElement>(`[data-node="${target}"]`);
        el?.focus();
        el?.scrollIntoView({ block: "nearest", inline: "nearest" });
      };
      if (e.altKey && (e.key === "ArrowUp" || e.key === "ArrowDown") && selected && selected !== "trigger" && canEdit) {
        e.preventDefault();
        const moved = move(graph, selected, e.key === "ArrowUp" ? "up" : "down");
        if (moved !== graph) edit(moved);
        requestAnimationFrame(() => document.querySelector<HTMLElement>(`[data-node="${selected}"]`)?.focus());
        return;
      }
      if (e.altKey) return;
      if (e.key === "j" || (onNode && e.key === "ArrowDown")) (e.preventDefault(), go(at + 1));
      else if (e.key === "k" || (onNode && e.key === "ArrowUp")) (e.preventDefault(), go(at - 1));
      else if ((e.key === "e" || (e.key === "Enter" && !onNode)) && selected) {
        e.preventDefault();
        if (wide) document.querySelector<HTMLElement>(".wf-side :is(input, button, [tabindex]):not([disabled])")?.focus();
        else setSheet(true);
      } else if ((e.key === "Delete" || e.key === "Backspace") && selected && selected !== "trigger" && canEdit) {
        e.preventDefault();
        askRemove(selected);
      } else if (e.key === "a" && selected && canEdit) {
        e.preventDefault();
        const node = graph.nodes[selected];
        const ex = node ? exits(node) : { kind: "next" as const };
        const slot: Slot | null = selected === "trigger" ? { from: "start" } : ex.kind === "next" ? { from: selected } : ex.kind === "branches" ? { from: selected, branch: ex.names[0] } : null;
        if (slot) setMenuOpen("branch" in slot && slot.branch ? `${slot.from}:${slot.branch}` : slot.from);
      } else if (e.key === "t" && canEdit) {
        e.preventDefault();
        void startTest();
      } else if (e.key === "=" || e.key === "+") setZoom((z) => ZOOMS[Math.min(ZOOMS.length - 1, ZOOMS.indexOf(z) + 1)]!);
      else if (e.key === "-") setZoom((z) => ZOOMS[Math.max(0, ZOOMS.indexOf(z) - 1)]!);
      else if (e.key === "0") setZoom(1);
      else if (e.key === "f") fit();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // ---- render ----

  if (loadError)
    return (
      <div className="sh-page">
        <Link to="/automations" className="sh-back">
          <ChevronLeft size={16} aria-hidden />
          Automations
        </Link>
        <EmptyState
          icon={loadError.status === 403 ? LockKeyhole : CircleAlert}
          title={loadError.status === 403 ? "You do not have access to this workflow" : "We could not open this workflow"}
          text={loadError.status === 403 ? "Ask a workspace admin for a role that can read workflows." : loadError.text}
          action={loadError.status === 404 || loadError.status === 403 ? undefined : <Button onClick={load}>Try again</Button>}
        />
      </div>
    );
  if (!wf || !catalog) return <BuilderSkeleton />;

  const archived = wf.status === "archived";
  const editable = canWrite && !archived;
  const visits: Record<string, StepStatus> | undefined = lastTest ? Object.fromEntries(lastTest.result.steps.map((s) => [s.node_id, s.status])) : undefined;
  const sel = selected && selected !== "trigger" ? graph.nodes[selected] : undefined;
  const problems = [
    ...errors.general,
    ...(Object.keys(errors.trigger).length ? [`Trigger: ${firstError(errors.trigger)}`] : []),
    ...Object.entries(errors.nodes).map(([nid, errs]) => `${graph.nodes[nid] ? title(graph.nodes[nid]!, names) : nid} (${nid}): ${firstError(errs)}`),
  ];
  const panel =
    selected === "trigger" ? (
      <div className="wf-panel-node">
        <header className="wf-panel-head">
          <div>
            <h2>Trigger</h2>
            <p className="wf-muted">What starts the workflow for a record. Only events after it first goes live count.</p>
          </div>
        </header>
        <TriggerPanel
          trigger={graph.trigger}
          catalog={catalog}
          errors={errors.trigger}
          revision={String(revision)}
          disabled={!editable}
          onChange={(trigger) => {
            forget("trigger", touched(graph.trigger, trigger));
            edit({ ...graph, trigger }, { coalesce: true });
          }}
        />
      </div>
    ) : sel && selected ? (
      <NodePanel
        key={selected}
        id={selected}
        node={sel}
        catalog={catalog}
        object={object}
        names={names}
        errors={errors.nodes[selected] ?? {}}
        revision={String(revision)}
        disabled={!editable}
        canMove={{ up: move(graph, selected, "up") !== graph, down: move(graph, selected, "down") !== graph }}
        onMove={(dir) => edit(move(graph, selected, dir))}
        onRemove={() => askRemove(selected)}
        onChange={(patch) => {
          forget(selected, [...(patch.config ? touched(sel.config, patch.config, "config.") : []), ...("label" in patch ? ["label"] : [])]);
          const next = update(graph, selected, patch);
          const lost = Object.keys(graph.nodes).filter((n) => !(n in next.nodes));
          if (lost.length) {
            const before = graph;
            edit(next);
            toast({ title: `${lost.length} ${lost.length === 1 ? "step" : "steps"} removed with that branch`, description: lost.join(", "), tone: "info", action: { label: "Undo", onClick: () => (setGraph(before), setRevision((r) => r + 1)) } });
          } else edit(next, { coalesce: true });
        }}
      />
    ) : (
      <p className="wf-muted wf-panel-empty">Select the trigger or a step to change its settings.</p>
    );

  const savedText = busy === "save" ? "Saving" : dirty ? "Unsaved changes" : wf.latest_version ? `Saved as version ${wf.latest_version}` : "Not saved yet";
  return (
    <LookupsCtx.Provider value={lookups}>
      <div className="sh-page wf-page wf-builder">
        <Link to="/automations" className="sh-back">
          <ChevronLeft size={16} aria-hidden />
          Automations
        </Link>
        <Tabs value={tab} onValueChange={(t) => setParams(t === "build" ? {} : { tab: t }, { replace: true })}>
          <PageHeader
            title={wf.name}
            description={`${versionText(wf)}. ${enrolled(wf).toLocaleString()} ${enrolled(wf) === 1 ? "record" : "records"} in it now.`}
            actions={
              <div className="wf-head-actions">
                <StatusBadge status={wf.status} />
                {wf.has_draft_changes && !dirty && wf.status !== "draft" && <Badge tone="accent">Unpublished changes</Badge>}
                {!canWrite && <Badge>Read only</Badge>}
                {editable && (
                  <>
                    <span className="wf-saved" role="status">
                      {savedText}
                    </span>
                    <Button onClick={() => void startTest()} loading={busy === "test"} disabled={!!busy && busy !== "test"} aria-keyshortcuts="t">
                      <FlaskConical size={16} aria-hidden /> Test
                    </Button>
                    <Button onClick={() => void save()} disabled={!dirty || !!busy} loading={busy === "save"} aria-keyshortcuts="Control+S">
                      Save
                    </Button>
                  </>
                )}
                {canPublish && !archived && (
                  <Button variant="primary" onClick={() => void startPublish()} disabled={!!busy || (!dirty && wf.latest_version === null)}>
                    {wf.status !== "draft" && !wf.has_draft_changes && !dirty ? "Republish" : "Publish"}
                  </Button>
                )}
                <DropdownMenu
                  label="More"
                  trigger={
                    <Button variant="ghost" size="icon" aria-label="More actions">
                      <EllipsisVertical size={16} aria-hidden />
                    </Button>
                  }
                >
                  <MenuItem icon={<SearchCheck size={16} aria-hidden />} onSelect={() => setExplain({ record: null })}>
                    Why is a record not in it?
                  </MenuItem>
                  {editable && (
                    <MenuItem icon={<NotebookPen size={16} aria-hidden />} disabled={!dirty} onSelect={() => setNoteOpen(true)}>
                      Save with a note
                    </MenuItem>
                  )}
                  {canPublish && wf.status === "published" && (
                    <MenuItem icon={<Pause size={16} aria-hidden />} onSelect={() => void actions.flip(wf)}>
                      Pause
                    </MenuItem>
                  )}
                  {canPublish && wf.status === "paused" && (
                    <MenuItem icon={<Play size={16} aria-hidden />} onSelect={() => void actions.flip(wf)}>
                      Resume
                    </MenuItem>
                  )}
                  {canPublish && !archived && (
                    <>
                      <MenuSeparator />
                      <MenuItem icon={<Archive size={16} aria-hidden />} onSelect={() => actions.archive(wf)}>
                        Archive
                      </MenuItem>
                    </>
                  )}
                </DropdownMenu>
              </div>
            }
            views={
              <TabsList aria-label="Workflow sections">
                <TabsTrigger value="build">Build</TabsTrigger>
                <TabsTrigger value="runs">Runs{enrolled(wf) ? ` (${enrolled(wf).toLocaleString()})` : ""}</TabsTrigger>
                <TabsTrigger value="history">History</TabsTrigger>
                <TabsTrigger value="settings">Settings</TabsTrigger>
              </TabsList>
            }
          />
          {archived && (
            <p className="wf-alert" data-tone="info">
              <Archive size={16} aria-hidden /> This workflow is archived: nothing enters it, and it cannot be edited. Its versions and runs stay readable.
            </p>
          )}
          {wf.status === "paused" && (
            <p className="wf-alert" data-tone="warning">
              <Pause size={16} aria-hidden /> Paused: no record enters, and runs in flight wait where they are until you resume.
            </p>
          )}
          {restore && (
            <div className="wf-alert" data-tone="info" role="status">
              <NotebookPen size={16} aria-hidden />
              <span>
                You have changes from {timeAgo(restore.at)} that were not saved{restore.base !== wf.latest_version ? `, made on version ${restore.base ?? "none"} (version ${wf.latest_version} has been saved since)` : ""}.
              </span>
              <span className="wf-alert-actions">
                <Button
                  size="sm"
                  onClick={() => {
                    edit(restore.graph);
                    setRevision((r) => r + 1);
                    setRestore(null);
                  }}
                >
                  Restore them
                </Button>
                <Button
                  size="sm"
                  variant="ghost"
                  onClick={() => {
                    writeDraft(id, null);
                    setRestore(null);
                  }}
                >
                  Discard
                </Button>
              </span>
            </div>
          )}
          {problems.length > 0 && (
            <div className="wf-alert" role="alert">
              <CircleAlert size={16} aria-hidden />
              <div>
                <strong>Fix these, then save again:</strong>
                <ul>
                  {problems.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              </div>
              <Button variant="ghost" size="icon" aria-label="Hide the problems" onClick={() => setErrors(NO_ERRORS)}>
                <X size={16} aria-hidden />
              </Button>
            </div>
          )}
          <TabsContent value="build">
            <div className="wf-build">
              <div className="wf-canvas-wrap">
                <div className="wf-toolbar">
                  {editable && (
                    <span className="wf-undo" role="group" aria-label="History of changes">
                      <Button variant="ghost" size="icon" aria-label="Undo" title={`Undo (${MOD}+Z)`} aria-keyshortcuts="Control+Z" disabled={!past.length} onClick={undo}>
                        <Undo2 size={16} aria-hidden />
                      </Button>
                      <Button variant="ghost" size="icon" aria-label="Redo" title={`Redo (${MOD}+Shift+Z)`} aria-keyshortcuts="Control+Shift+Z" disabled={!future.length} onClick={redo}>
                        <Redo2 size={16} aria-hidden />
                      </Button>
                    </span>
                  )}
                  {lastTest ? (
                    <span className="wf-test-banner" role="status">
                      <FlaskConical size={14} aria-hidden /> Path of the test for {lastTest.record.display_name}: {lastTest.result.run.status}
                      {lastTest.result.skipped_seconds ? `, ${secondsText(lastTest.result.skipped_seconds)} skipped` : ""}
                      <button type="button" className="wf-link" onClick={() => setLastTest(null)}>
                        Hide
                      </button>
                    </span>
                  ) : (
                    <span className="wf-muted wf-keys-hint">
                      {editable ? (
                        <>
                          <Kbd>J</Kbd> <Kbd>K</Kbd> move, <Kbd>A</Kbd> add, <Kbd>Del</Kbd> remove, <Kbd>T</Kbd> test
                        </>
                      ) : (
                        <>
                          <Kbd>J</Kbd> <Kbd>K</Kbd> move through the steps, <Kbd>?</Kbd> all keys
                        </>
                      )}
                    </span>
                  )}
                  <span className="wf-zoom" role="group" aria-label="Zoom">
                    <Button variant="ghost" size="icon" aria-label="Zoom out" title="Zoom out (-)" disabled={zoom === ZOOMS[0]} onClick={() => setZoom(ZOOMS[Math.max(0, ZOOMS.indexOf(zoom) - 1)]!)}>
                      <Minus size={16} aria-hidden />
                    </Button>
                    <button type="button" className="wf-zoom-value mono" onClick={() => setZoom(1)} title="Reset the zoom (0)">
                      {Math.round(zoom * 100)}%
                    </button>
                    <Button variant="ghost" size="icon" aria-label="Zoom in" title="Zoom in (+)" disabled={zoom === ZOOMS[ZOOMS.length - 1]} onClick={() => setZoom(ZOOMS[Math.min(ZOOMS.length - 1, ZOOMS.indexOf(zoom) + 1)]!)}>
                      <Plus size={16} aria-hidden />
                    </Button>
                    <Button variant="ghost" size="sm" title="Zoom to fit the width (F)" onClick={fit}>
                      Fit
                    </Button>
                  </span>
                </div>
                <div className="wf-scroller" aria-label="Workflow canvas" role="region" ref={scroller}>
                  <Canvas
                    graph={graph}
                    catalog={catalog}
                    names={names}
                    selected={selected}
                    onSelect={setSelected}
                    onOpen={open}
                    errors={errors}
                    onAdd={editable ? add : null}
                    onUnlink={editable ? (slot) => edit(connect(graph, slot, null)) : null}
                    onAddGoal={editable ? addAGoal : null}
                    menuOpen={menuOpen}
                    onMenuOpen={setMenuOpen}
                    visits={visits}
                    zoom={zoom}
                  />
                </div>
              </div>
              {wide && (
                <aside className="wf-side" aria-label="Settings of the selected step">
                  {panel}
                </aside>
              )}
            </div>
            {!wide && (
              <Sheet open={sheet && !!selected} onOpenChange={setSheet} title={selected === "trigger" ? "Trigger" : sel ? title(sel, names) : "Step"}>
                {panel}
              </Sheet>
            )}
          </TabsContent>
          <TabsContent value="runs">
            <Runs workflowId={wf.id} names={names} refreshKey={runsKey} initialStatus={params.get("status")} onOpen={(r) => setParams({ tab: "runs", run: r }, { replace: true })} onExplain={() => setExplain({ record: null })} />
          </TabsContent>
          <TabsContent value="history">
            <History
              workflowId={wf.id}
              names={names}
              canWrite={editable}
              canPublish={canPublish && !archived}
              refreshKey={historyKey}
              onOpenVersion={async (n) => {
                try {
                  const v = await workflows.version(wf.id, n);
                  edit(v.graph);
                  setRevision((r) => r + 1);
                  setErrors(NO_ERRORS);
                  setParams({}, { replace: true });
                  toast({ title: `Version ${n} is in the builder`, description: "Save to make it the newest version; publish to make it live.", tone: "info" });
                } catch (e) {
                  toast({ title: "Could not open it", description: errorText(e), tone: "danger" });
                }
              }}
              onPublishVersion={(n) => void startPublish(n)}
            />
          </TabsContent>
          <TabsContent value="settings">
            <SettingsTab wf={wf} canWrite={editable} canPublish={canPublish && !archived} onSaved={(row) => setWf((w) => (w ? { ...w, ...row } : w))} />
          </TabsContent>
        </Tabs>

        {publishing !== null && (
          <PublishDialog
            workflow={wf}
            version={publishing}
            open
            actionLabel={names.action}
            onOpenChange={(o) => !o && setPublishing(null)}
            onInvalid={(e) => fail(e, "Publishing")}
            onPublished={(row, plan) => {
              setWf((w) => (w ? { ...w, ...row } : w));
              setHistoryKey((k) => k + 1);
              setRunsKey((k) => k + 1);
              toast({ title: `Version ${row.published_version} is live`, description: plan.moved || plan.exited ? `${plan.moved ?? 0} runs moved to it, ${plan.exited ?? 0} exited.` : "New records enter this version.", tone: "success" });
            }}
          />
        )}
        {testing && (
          <TestDialog
            open
            onOpenChange={(o) => !o && setTesting(null)}
            workflowId={wf.id}
            version={testing.version}
            graph={testing.graph}
            names={names}
            onInvalid={(e) => setErrors(place(e.fields))}
            onRan={(result, record) => {
              setLastTest({ result, record });
              setRunsKey((k) => k + 1);
            }}
          />
        )}
        <ExplainDialog
          open={!!explain}
          onOpenChange={(o) => !o && setExplain(null)}
          workflowId={wf.id}
          object={(wf.graph ?? graph).trigger.object ?? "contact"}
          initial={explain?.record}
          onOpenRun={(r) => {
            setExplain(null);
            setParams({ tab: "runs", run: r }, { replace: true });
          }}
        />
        <RunSheet
          runId={runId}
          names={names}
          canWrite={canWrite && !archived}
          onClose={() => setParams(tab === "build" ? {} : { tab }, { replace: true })}
          onChanged={() => setRunsKey((k) => k + 1)}
          onExplain={(record) => setExplain({ record })}
        />
        <Dialog
          open={!!removing}
          onOpenChange={(o) => !o && setRemoving(null)}
          title={`Remove ${removing ? `"${title(graph.nodes[removing.id] ?? { type: "end", config: {} }, names)}"` : "the step"} and its branches?`}
          description={removing ? `It takes ${removing.impact.length - 1} more ${removing.impact.length === 2 ? "step" : "steps"} with it, on its other branches: ${removing.impact.filter((x) => x !== removing.id).join(", ")}. Undo brings them back.` : undefined}
          footer={
            <>
              <Button onClick={() => setRemoving(null)}>Cancel</Button>
              <Button
                variant="danger"
                onClick={() => {
                  const r = removing!;
                  setRemoving(null);
                  removeNow(r.id);
                }}
              >
                Remove {removing?.impact.length} steps
              </Button>
            </>
          }
        />
        <GotoDialog
          slot={goto}
          graph={graph}
          names={names}
          onClose={() => setGoto(null)}
          onPick={(target) => {
            edit(connect(graph, goto!, target));
            setGoto(null);
            setSelected(target);
          }}
        />
        <NoteDialog open={noteOpen} onOpenChange={setNoteOpen} busy={busy === "save"} onSave={async (note) => (await save(note)) !== null && setNoteOpen(false)} />
        <Dialog
          open={!!conflict}
          onOpenChange={(o) => !o && setConflict(null)}
          title={`Version ${conflict?.latest_version ?? ""} was saved while you were editing`}
          description={`You started from version ${base ?? "none"}. Saving yours makes it the newest version, on top of theirs (theirs stays in the history); loading theirs drops your changes.`}
          footer={
            <>
              <Button onClick={() => setConflict(null)}>Cancel</Button>
              <Button
                onClick={() => {
                  const c = conflict!;
                  setConflict(null);
                  const g = c.graph ?? blank();
                  setWf(c);
                  commitSaved(g, c.latest_version ?? 0);
                  setBase(c.latest_version);
                  setPast([]);
                  setFuture([]);
                }}
              >
                Load theirs
              </Button>
              <Button
                variant="primary"
                onClick={() => {
                  setConflict(null);
                  void save(undefined, true);
                }}
              >
                Save mine
              </Button>
            </>
          }
        />
        <Dialog
          open={blocker.state === "blocked"}
          onOpenChange={(o) => !o && blocker.state === "blocked" && blocker.reset()}
          title="Leave without saving?"
          description="Your changes are not saved as a version. They stay in this browser, and the builder offers them back next time."
          footer={
            <>
              <Button onClick={() => blocker.state === "blocked" && blocker.reset()}>Keep editing</Button>
              <Button variant="danger" onClick={() => blocker.state === "blocked" && blocker.proceed()}>
                Leave
              </Button>
            </>
          }
        />
        {actions.dialogs}
      </div>
    </LookupsCtx.Provider>
  );
}

/** Where selection goes when a node is removed: what led to it, else the trigger. */
function slotOf(g: Graph, id: string): string {
  if (g.start === id) return "trigger";
  return Object.entries(g.nodes).find(([, n]) => n.next === id || Object.values(n.branches ?? {}).includes(id))?.[0] ?? "trigger";
}

function GotoDialog({ slot, graph, names, onClose, onPick }: { slot: Slot | null; graph: Graph; names: Names; onClose: () => void; onPick: (id: string) => void }) {
  const [target, setTarget] = useState<string>();
  useEffect(() => setTarget(undefined), [slot]);
  return (
    <Dialog
      open={!!slot}
      onOpenChange={(o) => !o && onClose()}
      title="Go to a step"
      description="The run carries on at that step, which makes a loop or joins two branches. A loop needs a wait in it, or it would run all its steps at once."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" disabled={!target} onClick={() => target && onPick(target)}>
            Go there
          </Button>
        </>
      }
    >
      <Select label="Step" value={target} placeholder="Choose a step" onValueChange={setTarget} options={order(graph).map((nid) => ({ value: nid, label: `${title(graph.nodes[nid]!, names)} (${nid})` }))} />
    </Dialog>
  );
}

function NoteDialog({ open, onOpenChange, busy, onSave }: { open: boolean; onOpenChange: (o: boolean) => void; busy: boolean; onSave: (note: string) => void }) {
  const [note, setNote] = useState("");
  useEffect(() => {
    if (open) setNote("");
  }, [open]);
  return (
    <Dialog open={open} onOpenChange={(o) => !busy && onOpenChange(o)} title="Save with a note" description="The note shows in the history next to the version.">
      <form
        className="wf-new"
        onSubmit={(e) => {
          e.preventDefault();
          if (note.trim()) onSave(note.trim());
        }}
      >
        <Input label="Note" autoFocus value={note} maxLength={500} placeholder="Wait 3 days instead of 2" onChange={(e) => setNote(e.target.value)} />
        <div className="wf-dialog-actions">
          <Button onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={busy} disabled={!note.trim()}>
            Save
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

function SettingsTab({ wf, canWrite, canPublish, onSaved }: { wf: WorkflowDetail; canWrite: boolean; canPublish: boolean; onSaved: (row: WorkflowRow) => void }) {
  const toast = useToast();
  const [name, setName] = useState(wf.name);
  const [folder, setFolder] = useState(wf.folder ?? "");
  const [reentry, setReentry] = useState(wf.settings.reentry);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [secret, setSecret] = useState<string | null>(null);
  const live = wf.status === "published" || wf.status === "paused";
  const changed = name.trim() !== wf.name || (folder.trim() || null) !== wf.folder || reentry !== wf.settings.reentry;
  const reentryLocked = live && !canPublish;

  async function submit() {
    setBusy(true);
    setErrors({});
    try {
      const row = await workflows.patch(wf.id, { name: name.trim(), folder: folder.trim() || null, settings: { reentry } });
      onSaved(row);
      toast({ title: "Settings saved", tone: "success" });
    } catch (e) {
      if (e instanceof ApiError && e.fields) setErrors(e.fields);
      else toast({ title: "Could not save the settings", description: errorText(e), tone: "danger" });
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="wf-settings">
      <form
        className="wf-stack"
        onSubmit={(e) => {
          e.preventDefault();
          if (changed && name.trim()) void submit();
        }}
      >
        <fieldset className="wf-stack" disabled={!canWrite}>
          <Input label="Name" value={name} maxLength={200} error={errors.name ?? (!name.trim() ? "Give it a name." : undefined)} onChange={(e) => setName(e.target.value)} />
          <Input label="Folder (optional)" value={folder} maxLength={100} error={errors.folder} placeholder="Onboarding" onChange={(e) => setFolder(e.target.value)} />
          <div>
            <Switch label="A record may enter again after its run ends" checked={reentry} disabled={reentryLocked} onCheckedChange={setReentry} />
            <p className="ui-hint">{reentryLocked ? "The workflow is live: changing who enters it needs a role that publishes." : "Off: each record goes through once. A record is never in it twice at the same time either way."}</p>
            {errors["settings.reentry"] && (
              <p className="ui-hint" data-tone="danger">
                {errors["settings.reentry"]}
              </p>
            )}
          </div>
          {canWrite && (
            <div>
              <Button type="submit" variant="primary" disabled={!changed || !name.trim()} loading={busy}>
                Save settings
              </Button>
            </div>
          )}
        </fieldset>
      </form>
      <section className="wf-stack wf-secret">
        <h2 className="wf-h3">Webhook signing secret</h2>
        <p className="wf-muted">The webhook steps sign each request with it (GoHigh-Signature). It was shown once when the workflow was made; make a new one if you need it again. Receivers using the old one fail until they take the new one.</p>
        {canPublish && (
          <div>
            <Button onClick={() => setRotating(true)}>Make a new secret</Button>
          </div>
        )}
      </section>
      <Dialog
        open={rotating}
        onOpenChange={(o) => {
          setRotating(o);
          if (!o) setSecret(null);
        }}
        title={secret ? "The new secret" : "Make a new signing secret?"}
        description={secret ? "Copy it now: it is not shown again." : "The old secret stops working at once: webhook receivers that check it reject requests until they have the new one."}
        footer={
          secret ? (
            <Button variant="primary" onClick={() => (setRotating(false), setSecret(null))}>
              Done
            </Button>
          ) : (
            <>
              <Button onClick={() => setRotating(false)}>Cancel</Button>
              <Button
                variant="danger"
                onClick={async () => {
                  try {
                    setSecret((await workflows.rotateSecret(wf.id)).signing_secret);
                  } catch (e) {
                    toast({ title: "Could not make a new secret", description: errorText(e), tone: "danger" });
                    setRotating(false);
                  }
                }}
              >
                Make a new one
              </Button>
            </>
          )
        }
      >
        {secret && (
          <div className="wf-secret-row">
            <code className="mono">{secret}</code>
            <Button size="sm" onClick={() => void navigator.clipboard?.writeText(secret).then(() => toast({ title: "Copied", tone: "success" }))}>
              Copy
            </Button>
          </div>
        )}
      </Dialog>
    </div>
  );
}
