import { CircleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError, errorText } from "../lib/api";
import { Button, Dialog, Select, Skeleton } from "../ui";
import { workflows, type PublishPlan, type WorkflowRow } from "./api";
import { title } from "./describe";
import type { Graph } from "./graph";

type Props = {
  workflow: Pick<WorkflowRow, "id" | "name" | "status" | "latest_version" | "published_version">;
  /** the version to publish; the newest when left out */
  version?: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPublished: (row: WorkflowRow, plan: PublishPlan) => void;
  /** a 422 with field errors: the builder puts them on the steps */
  onInvalid?: (e: ApiError) => void;
  actionLabel?: (key: string) => string | undefined;
};

/** Publishing, with a preview first (docs/UI.md: safe by default): how many runs are in flight, and for each step the new
 * version removes, how many runs are at it and where they should go. Nothing changes until "Publish". */
export function PublishDialog({ workflow, version, open, onOpenChange, onPublished, onInvalid, actionLabel }: Props) {
  const number = version ?? workflow.latest_version ?? undefined;
  const [plan, setPlan] = useState<PublishPlan | null>(null);
  const [graph, setGraph] = useState<Graph | null>(null);
  const [error, setError] = useState<string>();
  const [move, setMove] = useState(false);
  const [targets, setTargets] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!open || number === undefined) return;
    let alive = true;
    setPlan(null);
    setError(undefined);
    setMove(false);
    setTargets({});
    Promise.all([workflows.publish(workflow.id, { version: number, migrate: {}, dry_run: true }), workflows.version(workflow.id, number)])
      .then(([res, v]) => {
        if (!alive) return;
        setPlan(res.publish);
        setGraph(v.graph);
      })
      .catch((e) => {
        if (!alive) return;
        if (e instanceof ApiError && e.fields && onInvalid) {
          onInvalid(e);
          onOpenChange(false);
        } else setError(errorText(e));
      });
    return () => {
      alive = false;
    };
  }, [open, number, workflow.id]);

  const removed = plan?.removed_nodes ?? [];
  const unmapped = move && removed.some((n) => !targets[n.node_id]);
  const nodeOptions = graph
    ? [{ value: "exit", label: "End their run (exit)" }, ...Object.entries(graph.nodes).map(([id, n]) => ({ value: id, label: `${title(n, { action: actionLabel })} (${id})` }))]
    : [];

  async function publish() {
    if (number === undefined) return;
    setBusy(true);
    try {
      const res = await workflows.publish(workflow.id, { version: number, ...(move ? { migrate: targets } : {}) });
      onPublished(res, res.publish);
      onOpenChange(false);
    } catch (e) {
      if (e instanceof ApiError && e.fields && onInvalid && !Object.keys(e.fields).some((k) => k.startsWith("migrate."))) {
        onInvalid(e);
        onOpenChange(false);
      } else setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  const repub = workflow.published_version === number;
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !busy && onOpenChange(o)}
      title={`Publish version ${number ?? ""} of "${workflow.name}"?`}
      description={
        workflow.status === "paused"
          ? "The workflow stays paused: records start entering this version when you resume it."
          : repub
            ? "This version is live already. Publishing it again can move runs in flight onto it."
            : "New records enter this version from now on."
      }
      footer={
        <>
          <Button onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" onClick={() => void publish()} loading={busy} disabled={!plan || unmapped}>
            Publish
          </Button>
        </>
      }
    >
      {error ? (
        <p className="wf-alert" role="alert">
          <CircleAlert size={16} aria-hidden /> {error}
        </p>
      ) : !plan ? (
        <div className="wf-stack" aria-busy="true">
          <Skeleton style={{ height: 16, width: "70%" }} />
          <Skeleton style={{ height: 16, width: "50%" }} />
        </div>
      ) : plan.in_flight === 0 ? (
        <p className="wf-muted">No records are in another version of this workflow, so nothing else changes.</p>
      ) : (
        <div className="wf-stack">
          <p>
            <strong>{plan.in_flight.toLocaleString()}</strong> {plan.in_flight === 1 ? "record is" : "records are"} part way through another version.
          </p>
          <fieldset className="wf-radios">
            <legend className="ui-label">Runs in flight</legend>
            <label>
              <input type="radio" name="wf-migrate" checked={!move} onChange={() => setMove(false)} /> Let them finish on the version they started on
            </label>
            <label>
              <input type="radio" name="wf-migrate" checked={move} onChange={() => setMove(true)} /> Move them to version {number}
            </label>
          </fieldset>
          {move && (
            <>
              <p className="wf-muted">
                {plan.same_node > 0 && `${plan.same_node.toLocaleString()} ${plan.same_node === 1 ? "is at a step this version still has and stays" : "are at steps this version still has and stay"} there. `}
                {removed.length > 0 && "These steps are gone in this version; choose where their runs go:"}
              </p>
              {removed.map((n) => (
                <Select
                  key={n.node_id}
                  label={`${n.runs.toLocaleString()} ${n.runs === 1 ? "run" : "runs"} at "${n.node_id}"`}
                  value={targets[n.node_id]}
                  placeholder="Choose a step, or exit"
                  onValueChange={(v) => setTargets((t) => ({ ...t, [n.node_id]: v }))}
                  options={nodeOptions}
                />
              ))}
            </>
          )}
        </div>
      )}
    </Dialog>
  );
}
