import { Kanban, LockKeyhole, Plus, Search, SearchX, Settings2, SlidersHorizontal, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, Navigate, useNavigate, useParams, useSearchParams } from "react-router";
import { persisted, useStore } from "../lib/store";
import { useMe } from "../lib/session";
import { PageHeader } from "../shell/PageHeader";
import { TYPING } from "../shell/useShortcuts";
import { Badge, Button, Checkbox, EmptyState, Input, Kbd, Select, Skeleton, Tabs, TabsList, TabsTrigger, useToast } from "../ui";
import { Popover } from "../ui/Popover";
import { recordsClient } from "../records/client.ts";
import { errorMessage, errorStatus, RecordsError } from "../records/errors.ts";
import { formatMoney } from "../records/format.ts";
import { primeRefs, useFields, useMeta } from "../records/meta.tsx";
import { NewRecordDialog } from "../records/NewRecordDialog";
import { RecordDetail } from "../records/RecordDetail";
import { DISPLAY_NAME } from "../records/schema.ts";
import type { RecordRow } from "../records/types.ts";
import { ConfirmDialog } from "../records/Views";
import { moneyOf, NO_FILTER, isFiltered, stageOf, type Quick } from "./board.ts";
import { BoardView } from "./BoardView";
import { pipelineClient } from "./client.ts";
import { ForecastView } from "./ForecastView";
import { MetaGate } from "./MetaGate";
import { MoveDialog, type Ask } from "./MoveDialog";
import { Segmented } from "./Segmented";
import { useBoard } from "./useBoard.ts";
import { useCan } from "./useCan.ts";
import { usePipelines } from "./usePipelines.ts";
import type { BoardStage, Card, Pipeline } from "./types.ts";
import "../records/records.css";
import "./pipeline.css";

const sumsPref = persisted<"total" | "weighted">("gh:board-sums", "total", (v) => (v === "weighted" || v === "total" ? v : undefined));
const lastPipeline = persisted<string | null>("gh:pipeline", null, (v) => (typeof v === "string" ? v : undefined));

/** /pipeline, /pipeline/:pipelineId and /pipeline/:pipelineId/forecast: one pipeline as a board or as a forecast. */
export function PipelinePage() {
  return (
    <MetaGate skeleton={<PageSkeleton />}>
      <Pipelines />
    </MetaGate>
  );
}

function PageSkeleton() {
  return (
    <div className="rec-page" aria-busy="true" aria-label="Loading">
      <Skeleton style={{ width: 150, height: 26 }} />
      <div className="rec-skel-toolbar">
        <Skeleton style={{ width: 240, height: 32 }} />
        <Skeleton style={{ width: 120, height: 32 }} />
      </div>
      <BoardSkeleton />
    </div>
  );
}

function BoardSkeleton() {
  return (
    <div className="pl-board" aria-hidden>
      {[0, 1, 2, 3].map((c) => (
        <div key={c} className="pl-col">
          <div className="pl-col-head">
            <Skeleton style={{ width: 120, height: 16 }} />
            <Skeleton style={{ width: 80, height: 12, marginTop: 8 }} />
          </div>
          <div className="pl-cards">
            {[0, 1, 2].slice(0, 3 - (c % 2)).map((r) => (
              <Skeleton key={r} style={{ width: "100%", height: 92, borderRadius: 8 }} />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function Pipelines() {
  const list = usePipelines(pipelineClient);
  const { pipelineId, tab } = useParams();
  const remembered = useStore(lastPipeline);
  const meta = useMeta();
  if (list.status === "loading") return <PageSkeleton />;
  if (list.status === "error") {
    const denied = errorStatus(list.error) === 403;
    return (
      <div className="rec-page">
        <EmptyState
          icon={denied ? LockKeyhole : TriangleAlert}
          title={denied ? "You do not have access to pipelines" : "We could not load the pipelines"}
          text={denied ? "Ask a workspace admin to give you access." : errorMessage(list.error)}
          action={denied ? undefined : <Button onClick={list.reload}>Try again</Button>}
        />
      </div>
    );
  }
  const pipelines = list.pipelines;
  if (!meta.objects.some((o) => o.key === "deal")) {
    return (
      <div className="rec-page">
        <EmptyState icon={SearchX} title="Deals are not set up here" text="This workspace has no deal object, so there is nothing to put on a board." />
      </div>
    );
  }
  if (pipelines.length === 0) {
    return (
      <div className="rec-page">
        <EmptyState icon={Kanban} title="No pipelines yet" text="Create a pipeline in the settings to give your deals stages to move through." action={<Link to="/settings/pipelines" className="ui-btn" data-variant="primary" data-size="md">Open pipeline settings</Link>} />
      </div>
    );
  }
  if (!pipelineId) return <Navigate replace to={`/pipeline/${(pipelines.find((p) => p.id === remembered) ?? pipelines[0]!).id}`} />;
  const current = pipelines.find((p) => p.id === pipelineId);
  if (!current) {
    return (
      <div className="rec-page">
        <EmptyState icon={SearchX} title="We could not find that pipeline" text="It may have been archived. You can bring it back in the pipeline settings." action={<Link to="/pipeline" className="ui-btn" data-variant="secondary" data-size="md">Back to the board</Link>} />
      </div>
    );
  }
  return tab === "forecast" ? <ForecastTab key={current.id} pipeline={current} pipelines={pipelines} /> : <BoardTab key={current.id} pipeline={current} pipelines={pipelines} />;
}

// ---- the header both tabs share ----

function PipelineHeader({ pipeline, pipelines, tab, hasAmount, actions }: { pipeline: Pipeline; pipelines: Pipeline[]; tab: "board" | "forecast"; hasAmount: boolean; actions?: React.ReactNode }) {
  const navigate = useNavigate();
  useEffect(() => lastPipeline.set(pipeline.id), [pipeline.id]);
  const go = (id: string, t: "board" | "forecast") => navigate(`/pipeline/${id}${t === "forecast" ? "/forecast" : ""}`);
  return (
    <PageHeader
      title="Pipeline"
      description={pipelines.length < 2 ? pipeline.name : undefined}
      views={
        hasAmount ? (
          <Tabs value={tab} onValueChange={(t) => go(pipeline.id, t as "board" | "forecast")} className="pl-tabs">
            <TabsList aria-label="Pipeline views">
              <TabsTrigger value="board">Board</TabsTrigger>
              <TabsTrigger value="forecast">Forecast</TabsTrigger>
            </TabsList>
          </Tabs>
        ) : undefined
      }
      actions={
        <>
          {pipelines.length > 1 && <Select aria-label="Pipeline" value={pipeline.id} onValueChange={(id) => go(id, tab)} options={pipelines.map((p) => ({ value: p.id, label: p.name }))} />}
          {actions}
        </>
      }
    />
  );
}

// ---- forecast ----

function ForecastTab({ pipeline, pipelines }: { pipeline: Pipeline; pipelines: Pipeline[] }) {
  const hasAmount = useFields("deal").some((f) => f.key === "amount");
  return (
    <div className="rec-page pl-page">
      <PipelineHeader pipeline={pipeline} pipelines={pipelines} tab="forecast" hasAmount={hasAmount} />
      <ForecastView client={pipelineClient} pipeline={pipeline} hasAmount={hasAmount} />
    </div>
  );
}

// ---- board ----

type Extra = { lost_reason?: string; lost_note?: string };
type Pending = Ask & { slot: number; extra: Extra };

const CLOSE_OPTIONS = [
  { value: "any", label: "Any close date" },
  { value: "month", label: "Closes this month" },
  { value: "quarter", label: "Closes this quarter" },
];

function BoardTab({ pipeline, pipelines }: { pipeline: Pipeline; pipelines: Pipeline[] }) {
  const toast = useToast();
  const meId = useMe()?.user.id;
  const can = useCan();
  const meta = useMeta();
  const dealDef = meta.objects.find((o) => o.key === "deal")!;
  const fieldList = useFields("deal");
  const fields = useMemo(() => new Map(fieldList.map((f) => [f.key, f])), [fieldList]);
  const hasAmount = fields.has("amount");
  const board = useBoard(pipelineClient, pipeline.id);
  const colsRef = useRef<BoardStage[]>(board.columns);
  colsRef.current = board.columns;

  const [filter, setFilter] = useState<Quick>(NO_FILTER);
  const sums = useStore(sumsPref);
  const [search, setSearch] = useSearchParams();
  const openId = search.get("deal");
  const [denied, setDenied] = useState(false);
  const canWrite = can.writeDeals && !denied;
  const [pending, setPending] = useState<Pending | null>(null);
  const [newIn, setNewIn] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<RecordRow | null>(null);
  const [announce, setAnnounce] = useState("");
  const searchRef = useRef<HTMLInputElement>(null);

  const open = useCallback(
    (id: string) =>
      setSearch(
        (p) => {
          p.set("deal", id);
          return p;
        },
        { replace: true },
      ),
    [setSearch],
  );
  const close = useCallback(
    () =>
      setSearch(
        (p) => {
          p.delete("deal");
          return p;
        },
        { replace: true },
      ),
    [setSearch],
  );

  // "/" searches, like the lists
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "/" || e.ctrlKey || e.metaKey || e.altKey) return;
      if ((e.target as HTMLElement).closest?.(TYPING) || document.querySelector('[role="dialog"], [role="menu"]')) return;
      e.preventDefault();
      searchRef.current?.focus();
      searchRef.current?.select();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // ---- moves ----

  const finished = useCallback(
    (card: Card, to: BoardStage) => {
      const col = colsRef.current.find((c) => c.id === to.id);
      const place = col ? col.deals.findIndex((d) => d.id === card.id) + 1 : 0;
      setAnnounce(`Moved ${card.display_name} to ${to.name}${place ? `, position ${place} of ${col!.deals.length}` : ""}.`);
      if (to.kind === "won") {
        const money = moneyOf(card);
        toast({ title: `Won: ${card.display_name}`, description: money && hasAmount ? formatMoney(money) : undefined, tone: "success", duration: 3500 });
      }
    },
    [toast, hasAmount],
  );

  /** One try at a move. Returns what the server still wants (a 422), or null when the deal moved or the failure was shown. */
  const attempt = useCallback(
    async (card: Card, to: BoardStage, fromName: string, slot: number, extra: Extra): Promise<Record<string, string> | null> => {
      const r = await board.move(card, to.id, slot, extra);
      if (r.ok) {
        finished(card, to);
        return null;
      }
      const e = r.error;
      if (e instanceof RecordsError && e.status === 422 && e.fields && Object.keys(e.fields).length) {
        const errors = e.fields;
        setPending((p) => (p && p.card.id === card.id && p.to.id === to.id ? { ...p, errors, extra } : { card, to, from: fromName, mode: "fix", errors, slot, extra }));
        return errors;
      }
      if (errorStatus(e) === 403) setDenied(true);
      toast({ title: `Could not move ${card.display_name || "the deal"}`, description: errorMessage(e), tone: "danger" });
      return null;
    },
    [board.move, finished, toast], // eslint-disable-line react-hooks/exhaustive-deps
  );

  const requestMove = useCallback(
    (card: Card, stageId: string, slot: number) => {
      const to = colsRef.current.find((c) => c.id === stageId);
      const from = stageOf(colsRef.current, card.id);
      if (!to || !from) return;
      if (to.kind === "lost" && from.kind !== "lost") setPending({ card, to, from: from.name, mode: "lost", errors: {}, slot, extra: {} });
      else void attempt(card, to, from.name, slot, {});
    },
    [attempt],
  );

  const submitAsk = async (values: Record<string, unknown>): Promise<Record<string, string> | null> => {
    const p = pending;
    if (!p) return null;
    const extra: Extra = { ...p.extra };
    const patch: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(values)) {
      if (k === "lost_reason" || k === "lost_note") extra[k] = String(v);
      else patch[k] = v;
    }
    if (Object.keys(patch).length) {
      try {
        const row = await recordsClient.update("deal", p.card.id, patch);
        board.patchFromRecord(row);
        primeRefs(recordsClient, [row]);
      } catch (e) {
        if (e instanceof RecordsError && e.fields) return e.fields;
        return { general: errorMessage(e) };
      }
    }
    const refused = await attempt(p.card, p.to, p.from, p.slot, extra);
    if (refused === null) {
      setPending(null);
      return null;
    }
    return refused;
  };

  // ---- the record beside the board ----

  const reloadSoon = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const onChanged = useCallback(
    (row: RecordRow) => {
      board.patchFromRecord(row);
      const col = stageOf(colsRef.current, row.id);
      if (col && typeof row.values.stage === "string" && row.values.stage !== col.id) {
        clearTimeout(reloadSoon.current); // the stage was changed in the record: the board asks again
        reloadSoon.current = setTimeout(() => void board.reload(), 300);
      }
    },
    [board.patchFromRecord, board.reload], // eslint-disable-line react-hooks/exhaustive-deps
  );
  useEffect(() => () => clearTimeout(reloadSoon.current), []);

  const confirmDelete = async () => {
    const gone = deleting;
    if (!gone) return;
    try {
      await recordsClient.remove("deal", [gone.id]);
      setDeleting(null);
      close();
      void board.reload();
      toast({
        title: "Deal deleted",
        description: gone.display_name,
        duration: 8000,
        action: {
          label: "Undo",
          onClick: () => {
            recordsClient.restore("deal", [gone.id]).then(
              () => void board.reload(),
              (e) => toast({ title: "Could not restore", description: errorMessage(e), tone: "danger" }),
            );
          },
        },
      });
    } catch (e) {
      setDeleting(null);
      toast({ title: "Could not delete", description: errorMessage(e), tone: "danger" });
    }
  };

  // ---- the layout: collapsed columns and the fields on a card ----

  const saveLayout = async (next: { collapsed: string[]; card_fields: string[] }) => {
    const err = await board.saveLayout(next);
    if (err) toast({ title: "Could not save the board layout", description: errorMessage(err), tone: "danger" });
  };
  const toggleCollapsed = useCallback(
    (stageId: string) => {
      const l = board.layout;
      void saveLayout({ ...l, collapsed: l.collapsed.includes(stageId) ? l.collapsed.filter((s) => s !== stageId) : [...l.collapsed, stageId] });
    },
    [board.layout], // eslint-disable-line react-hooks/exhaustive-deps
  );

  // fields a card can show: not the name, the stage or long text, and not a date the card cannot know
  const cardChoices = useMemo(() => fieldList.filter((f) => !["name", "stage", "created_at", "updated_at", DISPLAY_NAME].includes(f.key) && f.type !== "long_text" && f.type !== "formula" && f.type !== "rollup"), [fieldList]);
  const toggleField = (key: string, on: boolean) => {
    const keep = new Set(board.layout.card_fields);
    if (on) keep.add(key);
    else keep.delete(key);
    void saveLayout({ ...board.layout, card_fields: cardChoices.map((f) => f.key).filter((k) => keep.has(k)) });
  };

  const total = board.columns.reduce((n, c) => n + c.count, 0);
  const filtering = isFiltered(filter);
  const firstOpen = pipeline.stages.find((s) => s.kind === "open");
  const newFields = useMemo(() => fieldList.map((f) => (f.type === "stage" && newIn ? { ...f, options: { ...f.options, default: newIn } } : f)), [fieldList, newIn]);
  const detailFields = useMemo(() => fieldList.filter((f) => f.key !== DISPLAY_NAME), [fieldList]);
  const partial = filtering && board.columns.some((c) => c.next_cursor);

  let body;
  if (board.status === "loading") body = <BoardSkeleton />;
  else if (board.status === "error") {
    const denied403 = errorStatus(board.error) === 403;
    body = (
      <EmptyState
        icon={denied403 ? LockKeyhole : TriangleAlert}
        title={denied403 ? "You do not have access to this board" : "We could not load the board"}
        text={denied403 ? errorMessage(board.error) : errorMessage(board.error)}
        action={denied403 ? undefined : <Button onClick={() => void board.reload()}>Try again</Button>}
      />
    );
  } else if (total === 0 && !filtering) {
    body = (
      <EmptyState
        icon={Kanban}
        title={`No deals in ${pipeline.name} yet`}
        text={canWrite ? "Add your first deal, then drag it from stage to stage. Each stage can ask for what a deal needs before it moves on, and the forecast follows every move." : "Deals will show up here once someone adds them."}
        action={
          canWrite && firstOpen ? (
            <Button variant="primary" onClick={() => setNewIn(firstOpen.id)}>
              <Plus size={16} aria-hidden /> New deal
            </Button>
          ) : undefined
        }
      />
    );
  } else {
    body = (
      <BoardView
        columns={board.columns}
        layout={board.layout}
        filter={filter}
        me={meId}
        fields={fields}
        hasAmount={hasAmount}
        sums={sums}
        canWrite={canWrite}
        more={board.more}
        openId={openId}
        refreshing={board.refreshing}
        onOpen={open}
        onMove={requestMove}
        onToggleCollapsed={toggleCollapsed}
        onLoadMore={board.loadMore}
        onRetryMore={board.retryMore}
        onNewDeal={setNewIn}
      />
    );
  }

  return (
    <div className="rec-page pl-page" data-open={openId || undefined}>
      <PipelineHeader
        pipeline={pipeline}
        pipelines={pipelines}
        tab="board"
        hasAmount={hasAmount}
        actions={
          canWrite && firstOpen ? (
            <Button variant="primary" onClick={() => setNewIn(firstOpen.id)}>
              <Plus size={16} aria-hidden />
              <span>
                New<span className="rec-hide-sm"> deal</span>
              </span>
            </Button>
          ) : undefined
        }
      />

      <div className="rec-toolbar pl-toolbar" role="toolbar" aria-label="Board tools">
        <div className="rec-search">
          <Search size={14} aria-hidden className="rec-search-icon" />
          <Input
            ref={searchRef}
            type="search"
            aria-label="Search deals on the board"
            placeholder="Search deals"
            value={filter.q}
            onChange={(e) => setFilter((f) => ({ ...f, q: e.target.value }))}
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.stopPropagation();
                if (filter.q) setFilter((f) => ({ ...f, q: "" }));
                else e.currentTarget.blur();
              }
            }}
            autoComplete="off"
          />
          <span className="rec-search-key" aria-hidden>
            <Kbd>/</Kbd>
          </span>
        </div>
        <div className="pl-toolbar-controls">
          <Segmented label="Owner" value={filter.owner} onChange={(owner) => setFilter((f) => ({ ...f, owner }))} options={[{ value: "all", label: "All deals" }, { value: "mine", label: "My deals" }]} />
          <Select aria-label="Close date" value={filter.close} onValueChange={(close) => setFilter((f) => ({ ...f, close: close as Quick["close"] }))} options={CLOSE_OPTIONS} />
          {hasAmount && (
            <Segmented
              label="Column totals"
              value={sums}
              onChange={(v) => sumsPref.set(v)}
              options={[
                { value: "total", label: "Total", title: "The amounts of the deals in each stage" },
                { value: "weighted", label: "Weighted", title: "Each stage's amounts times its probability" },
              ]}
            />
          )}
          <span className="pl-toolbar-end">
            {!canWrite && (
              <Badge tone="neutral">{can.writeDeals ? "Read only" : "View only"}</Badge>
            )}
            <Popover
              label="Card fields"
              align="end"
              className="pl-fields-pop"
              trigger={
                <Button size="sm" aria-label="Choose the fields on a card" title="Card fields">
                  <SlidersHorizontal size={14} aria-hidden />
                  <span className="pl-lbl">Card fields</span>
                </Button>
              }
            >
              <div className="pl-fields">
                <h3 className="rec-section-title">Show on each card</h3>
                <ul>
                  {cardChoices.map((f) => (
                    <li key={f.key}>
                      <Checkbox label={f.label} checked={board.layout.card_fields.includes(f.key)} onCheckedChange={(on) => toggleField(f.key, on)} />
                    </li>
                  ))}
                </ul>
                <p className="rec-menu-note">The name, the days in the stage and the last activity always show. Your choice is saved for you on this board.</p>
              </div>
            </Popover>
            {can.managePipelines && (
              <Link to="/settings/pipelines" className="ui-btn" data-variant="secondary" data-size="sm" aria-label="Pipeline settings" title="Pipeline settings: stages, probabilities and rules">
                <Settings2 size={14} aria-hidden />
                <span className="pl-lbl">Stages</span>
              </Link>
            )}
          </span>
        </div>
      </div>

      {filtering && (
        <p className="pl-note" role="status">
          Filters work on the deals loaded on this device{partial ? ", and some columns have more than that" : ""}; the board has no server side filter yet. Column counts and totals show the matching deals.{" "}
          <Button size="sm" variant="ghost" onClick={() => setFilter(NO_FILTER)}>
            Clear filters
          </Button>
        </p>
      )}
      {!hasAmount && (
        <p className="pl-note" role="status">
          Your role cannot see deal amounts, so the board shows counts only.
        </p>
      )}

      <div className="pl-body" data-open={openId || undefined}>
        <section className="pl-board-wrap" aria-label={`${pipeline.name} board`}>
          {body}
        </section>
        {openId && <RecordDetail key={openId} client={recordsClient} def={dealDef} id={openId} fields={detailFields} onClose={close} onChanged={onChanged} onDelete={setDeleting} />}
      </div>

      <div className="sr-only" role="status" aria-live="polite">
        {announce}
      </div>

      <MoveDialog ask={pending} fields={fieldList} onSubmit={submitAsk} onClose={() => setPending(null)} />
      <NewRecordDialog
        client={recordsClient}
        def={dealDef}
        fields={newFields}
        open={newIn !== null}
        onOpenChange={(o) => !o && setNewIn(null)}
        onCreated={(row, another) => {
          primeRefs(recordsClient, [row]);
          void board.reload();
          if (!another) open(row.id);
        }}
      />
      <ConfirmDialog
        open={deleting !== null}
        onOpenChange={(o) => !o && setDeleting(null)}
        title={`Delete ${deleting?.display_name || "this deal"}?`}
        description="It moves to the trash and can be restored for 30 days. You can undo this right after."
        confirm="Delete"
        onConfirm={() => void confirmDelete()}
      />
    </div>
  );
}
