// The runs of a workflow and, in a sheet, one run's trace (?run=<id>, so a trace has a link of its own).
import { CircleAlert, History, LockKeyhole, RotateCcw, SearchCheck, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { ApiError, errorText } from "../lib/api";
import { recordPath } from "../lib/tasks";
import { useMediaQuery } from "../lib/useMediaQuery";
import { Button, Dialog, EmptyState, Select, Sheet, Skeleton, Switch, Table, useToast, type Column } from "../ui";
import { workflows, type RunDetail, type RunRow, type RunStatus } from "./api";
import { title, type Names } from "./describe";
import type { Graph } from "./graph";
import { dateTime, RUN_LABEL, RunBadge } from "./parts";
import { Trace } from "./Trace";

const STATUS_OPTIONS = [{ value: "all", label: "Every status" }, ...(Object.keys(RUN_LABEL) as RunStatus[]).map((s) => ({ value: s, label: RUN_LABEL[s] }))];

/** Graphs of the versions runs are on, read once each. */
const graphs = new Map<string, Promise<Graph>>();
function versionGraph(workflowId: string, n: number): Promise<Graph> {
  const key = `${workflowId}:${n}`;
  let p = graphs.get(key);
  if (!p) {
    p = workflows.version(workflowId, n).then((v) => v.graph);
    graphs.set(key, p);
    p.catch(() => graphs.delete(key));
  }
  return p;
}

export function Runs({ workflowId, names, onOpen, initialStatus, onExplain, refreshKey }: { workflowId: string; names: Names; onOpen: (id: string) => void; initialStatus?: string | null; onExplain: () => void; refreshKey: number }) {
  const [rows, setRows] = useState<RunRow[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<{ text: string; denied: boolean }>();
  const [status, setStatus] = useState(initialStatus && initialStatus in RUN_LABEL ? initialStatus : "all");
  const [test, setTest] = useState(false);
  const [more, setMore] = useState(false);
  const [labels, setLabels] = useState<Record<string, string>>({});
  const phone = useMediaQuery("(max-width: 767px)");

  const load = useCallback(
    (after: string | null) => {
      setError(undefined);
      if (after) setMore(true);
      workflows
        .runs({ workflow_id: workflowId, status: status === "all" ? undefined : (status as RunStatus), test, cursor: after })
        .then((page) => {
          setRows((old) => (after ? [...(old ?? []), ...page.data] : page.data));
          setCursor(page.next_cursor);
          // the step each run is at, by the name its own version gives it
          for (const n of new Set(page.data.map((r) => r.version).filter((v): v is number => v !== null)))
            versionGraph(workflowId, n)
              .then((g) => setLabels((l) => ({ ...l, ...Object.fromEntries(Object.entries(g.nodes).map(([id, node]) => [`${n}:${id}`, title(node, names)])) })))
              .catch(() => {});
        })
        .catch((e) => setError({ text: errorText(e), denied: e instanceof ApiError && e.status === 403 }))
        .finally(() => setMore(false));
    },
    [workflowId, status, test, refreshKey],
  );
  useEffect(() => load(null), [load]);

  const columns: Column<RunRow>[] = [
    {
      key: "record",
      header: "Record",
      cell: (r) =>
        r.record ? (
          <button type="button" className="wf-link wf-strong" onClick={() => onOpen(r.id)}>
            {r.record.display_name}
          </button>
        ) : (
          <span className="wf-muted">A record you cannot see</span>
        ),
    },
    { key: "status", header: "Status", cell: (r) => <RunBadge status={r.status} /> },
    {
      key: "at",
      header: "At step",
      cell: (r) =>
        r.node_id ? (
          <span>
            {labels[`${r.version}:${r.node_id}`] ?? r.node_id}
            {r.status === "waiting" && r.wake_at && <span className="wf-sub"> until {dateTime(r.wake_at)}</span>}
          </span>
        ) : (
          <span className="wf-muted">Finished</span>
        ),
    },
    { key: "version", header: "Version", mono: true, cell: (r) => (r.version === null ? "" : `v${r.version}`) },
    { key: "started", header: "Started", cell: (r) => <time dateTime={r.started_at}>{dateTime(r.started_at)}</time> },
    { key: "steps", header: "Steps", align: "right", mono: true, cell: (r) => r.step_count },
  ];

  if (error?.denied) return <EmptyState icon={LockKeyhole} title="You cannot see runs" text="Ask a workspace admin for a role that can read workflows." />;
  return (
    <div className="wf-runs">
      <div className="wf-filters">
        <Select aria-label="Run status" value={status} onValueChange={setStatus} options={STATUS_OPTIONS} />
        <Switch label="Test runs" checked={test} onCheckedChange={setTest} />
        <Button variant="ghost" onClick={onExplain}>
          <SearchCheck size={16} aria-hidden /> Why is a record not in it?
        </Button>
      </div>
      {error ? (
        <EmptyState icon={CircleAlert} title="We could not load the runs" text={error.text} action={<Button onClick={() => load(null)}>Try again</Button>} />
      ) : (
        <>
          {phone && rows && rows.length > 0 ? (
            <ul className="wf-cards" aria-label={test ? "Test runs" : "Runs"}>
              {rows.map((r) => (
                <li key={r.id}>
                  <button type="button" className="wf-card wf-run-card" onClick={() => onOpen(r.id)}>
                    <span className="wf-card-top">
                      <strong>{r.record?.display_name ?? "A record you cannot see"}</strong>
                      <RunBadge status={r.status} />
                    </span>
                    <span className="wf-sub-strong">
                      {r.node_id ? `At ${labels[`${r.version}:${r.node_id}`] ?? r.node_id}${r.status === "waiting" && r.wake_at ? ` until ${dateTime(r.wake_at)}` : ""}` : "Finished"}, version {r.version}, started {dateTime(r.started_at)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
          <Table
            caption={test ? "Test runs" : "Runs"}
            columns={columns}
            rows={rows ?? []}
            rowId={(r) => r.id}
            loading={rows === null}
            onRowClick={(r) => onOpen(r.id)}
            empty={
              <EmptyState
                icon={History}
                title={test ? "No test runs yet" : status === "all" ? "No record has entered yet" : `No ${RUN_LABEL[status as RunStatus].toLowerCase()} runs`}
                text={test ? "Test the workflow on a record from the Build tab: its trace shows up here." : "Records enter when the trigger's event happens to them while the workflow is live. Each run's trace shows here, step by step."}
              />
            }
          />
          )}
          {cursor && (
            <div className="wf-more">
              <Button onClick={() => load(cursor)} loading={more}>
                Load more
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}

/** One run with its trace, what it waits for and the webhooks it queued; cancel a live run, retry a failed one. */
export function RunSheet({ runId, onClose, names, canWrite, onChanged, onExplain }: { runId: string | null; onClose: () => void; names: Names; canWrite: boolean; onChanged: () => void; onExplain: (record: { id: string; object: string; display_name: string }) => void }) {
  const toast = useToast();
  const [run, setRun] = useState<RunDetail | null>(null);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState<"cancel" | "retry" | null>(null);
  const [confirm, setConfirm] = useState(false);

  useEffect(() => {
    if (!runId) return;
    let alive = true;
    setRun(null);
    setGraph(null);
    setError(undefined);
    workflows
      .run(runId)
      .then((r) => {
        if (!alive) return;
        setRun(r);
        if (r.version !== null) versionGraph(r.workflow_id, r.version).then((g) => alive && setGraph(g), () => {});
      })
      .catch((e) => alive && setError(e instanceof ApiError && e.status === 404 ? "This run does not exist, or its record is not one you may see." : errorText(e)));
    return () => {
      alive = false;
    };
  }, [runId]);

  async function act(kind: "cancel" | "retry") {
    if (!run) return;
    setBusy(kind);
    try {
      const r = kind === "cancel" ? await workflows.cancelRun(run.id) : await workflows.retryRun(run.id);
      setRun(r);
      onChanged();
      toast({ title: kind === "cancel" ? "Run cancelled" : "Retrying the step", description: kind === "cancel" ? "The record left the workflow." : "It runs again now, as the same attempt: nothing is sent twice.", tone: "success" });
    } catch (e) {
      toast({ title: kind === "cancel" ? "Could not cancel" : "Could not retry", description: errorText(e), tone: "danger" });
    } finally {
      setBusy(null);
    }
  }

  const hidden = !!run && run.steps.length > 0 && run.steps.every((s) => s.input === null && s.output === null);
  return (
    <Sheet open={!!runId} onOpenChange={(o) => !o && onClose()} title={run?.record ? `${run.record.display_name}${run.test ? ", test run" : ""}` : "Run"} description={run ? `Version ${run.version ?? "?"}, started ${dateTime(run.started_at)}${run.ended_at ? `, ended ${dateTime(run.ended_at)}` : ""}` : undefined}>
      {error ? (
        <EmptyState icon={CircleAlert} title="We could not open this run" text={error} />
      ) : !run ? (
        <div className="wf-stack" aria-busy="true">
          <Skeleton style={{ height: 18, width: "50%" }} />
          <Skeleton style={{ height: 60 }} />
          <Skeleton style={{ height: 60 }} />
        </div>
      ) : (
        <div className="wf-stack">
          <div className="wf-run-head">
            <RunBadge status={run.status} />
            {run.record && (
              <Link to={recordPath(run.record)} className="wf-link">
                Open the record
              </Link>
            )}
            {run.record && (
              <button type="button" className="wf-link" onClick={() => onExplain(run.record!)}>
                Why did it (not) enter?
              </button>
            )}
          </div>
          {run.error && !run.steps.some((s) => s.error === run.error) && (
            <p className="wf-alert" role="alert">
              <CircleAlert size={16} aria-hidden /> {run.error}
            </p>
          )}
          {run.waiting_for.length > 0 && <p className="wf-muted">Waiting for {run.waiting_for.map((w) => w.event_type).join(", ")}{run.wake_at ? `, at most until ${dateTime(run.wake_at)}` : ""}.</p>}
          {canWrite && !run.test && (run.status === "failed" || run.status === "running" || run.status === "waiting") && (
            <div className="wf-run-actions">
              {run.status === "failed" && (
                <Button variant="primary" onClick={() => void act("retry")} loading={busy === "retry"} disabled={!!busy}>
                  <RotateCcw size={16} aria-hidden /> Retry the failed step
                </Button>
              )}
              <Button variant="danger" onClick={() => setConfirm(true)} loading={busy === "cancel"} disabled={!!busy}>
                <X size={16} aria-hidden /> Cancel the run
              </Button>
            </div>
          )}
          {hidden && <p className="wf-muted">Your role hides some fields, so what each step was asked and did is not shown.</p>}
          <Trace steps={run.steps} graph={graph} names={names} hidden={hidden} />
          {run.deliveries.length > 0 && (
            <section>
              <h3 className="wf-h3">Webhooks</h3>
              <ul className="wf-list">
                {run.deliveries.map((d) => (
                  <li key={d.id}>
                    <strong>{d.host}</strong> from {d.node_id}: {d.status}
                    {d.response_status ? `, answered ${d.response_status}` : ""}, {d.attempts} {d.attempts === 1 ? "attempt" : "attempts"}
                    {d.error ? <span className="wf-failed"> ({d.error})</span> : null}
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      )}
      <Dialog
        open={confirm}
        onOpenChange={setConfirm}
        title="Cancel this run?"
        description={`${run?.record?.display_name ?? "The record"} leaves the workflow now and takes no more steps. A cancelled run cannot be resumed; the record can enter again only if re-entry is on.`}
        footer={
          <>
            <Button onClick={() => setConfirm(false)}>Keep it running</Button>
            <Button
              variant="danger"
              onClick={() => {
                setConfirm(false);
                void act("cancel");
              }}
            >
              Cancel the run
            </Button>
          </>
        }
      />
    </Sheet>
  );
}
