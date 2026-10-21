// A test run: one record walks a saved version now, on a virtual clock. Waits end at once (and say how long they
// skipped), messages and webhooks say what they would send and send nothing, and nothing is written to the record.
import { CircleAlert, CircleCheck, FlaskConical } from "lucide-react";
import { useEffect, useState } from "react";
import { ApiError, errorText } from "../lib/api";
import { useMeta } from "../records/meta.tsx";
import { Button, Dialog, Select } from "../ui";
import { workflows, type Glance, type TestResult } from "./api";
import { branchLabel, title, type Names } from "./describe";
import { exits, place, secondsText, type Graph } from "./graph";
import { firstError } from "./Canvas";
import { RecordSearch } from "./parts";
import { Trace } from "./Trace";

type Props = {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  workflowId: string;
  version: number;
  graph: Graph;
  names: Names;
  onRan: (r: TestResult, record: Glance) => void;
  /** the version has problems in this workspace: the builder marks them on the steps */
  onInvalid: (e: ApiError) => void;
};

export function TestDialog({ open, onOpenChange, workflowId, version, graph, names, onRan, onInvalid }: Props) {
  const meta = useMeta();
  const object = graph.trigger.object ?? "contact";
  const noun = meta.objects.find((o) => o.key === object)?.plural.toLowerCase() ?? "records";
  const [record, setRecord] = useState<Glance | null>(null);
  const [paths, setPaths] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);
  const [error, setError] = useState<string>();
  useEffect(() => {
    if (open) {
      setResult(null);
      setError(undefined);
      setPaths({});
    }
  }, [open, version]);

  // the steps whose branch a test may choose: a split (by chance, live) and an event wait (the event never comes in a test)
  const choosable = Object.entries(graph.nodes).filter(([, n]) => n.type === "split" || (n.type === "wait" && !!n.config.event));

  async function run() {
    if (!record) return setError(`Choose one of your ${noun} to test with.`);
    setBusy(true);
    setError(undefined);
    try {
      const r = await workflows.test(workflowId, { record_id: record.id, version, paths: Object.fromEntries(Object.entries(paths).filter(([, v]) => v)) });
      setResult(r);
      onRan(r, record);
    } catch (e) {
      if (e instanceof ApiError && e.fields && Object.keys(e.fields).some((k) => k.startsWith("graph"))) {
        onInvalid(e);
        const placed = place(e.fields);
        const first = Object.entries(placed.nodes)[0];
        setError(`Version ${version} cannot run in this workspace as it is${first ? `: ${graph.nodes[first[0]] ? title(graph.nodes[first[0]]!, names) : first[0]}, ${firstError(first[1]).replace(/^./, (c) => c.toLowerCase())}` : ""}. The problems are marked on the steps; fix them and save, then test again.`);
      } else setError(e instanceof ApiError && e.fields ? Object.values(e.fields).join(". ") : errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !busy && onOpenChange(o)}
      title={`Test version ${version}`}
      description="Walks the version for one record, now: waits are skipped on a virtual clock, messages and webhooks are not sent, and nothing about the record changes."
      footer={
        <>
          <Button onClick={() => onOpenChange(false)} disabled={busy}>
            Close
          </Button>
          <Button variant="primary" onClick={() => void run()} loading={busy}>
            <FlaskConical size={16} aria-hidden /> {result ? "Run again" : "Run the test"}
          </Button>
        </>
      }
    >
      <div className="wf-stack">
        <RecordSearch object={object} noun={noun} value={record} onChange={(r) => (setRecord(r), setResult(null))} label={`Test with one of your ${noun}`} autoFocus />
        {choosable.length > 0 && (
          <fieldset className="wf-rows">
            <legend className="ui-label">Branches to take</legend>
            {choosable.map(([id, n]) => {
              const ex = exits(n);
              const branches = ex.kind === "branches" ? ex.names : [];
              return (
                <Select
                  key={id}
                  label={`${title(n, names)} (${id})`}
                  value={paths[id] ?? "auto"}
                  onValueChange={(v) => setPaths((p) => ({ ...p, [id]: v === "auto" ? "" : v }))}
                  options={[{ value: "auto", label: n.type === "split" ? "As the run's id decides" : "It times out (the event does not come)" }, ...branches.map((b) => ({ value: b, label: branchLabel(n, b) }))]}
                />
              );
            })}
          </fieldset>
        )}
        {error && (
          <p className="wf-alert" role="alert">
            <CircleAlert size={16} aria-hidden /> {error}
          </p>
        )}
        {result && (
          <section aria-live="polite" className="wf-stack">
            <p className={result.run.status === "failed" ? "wf-alert" : "wf-ok"}>
              {result.run.status === "failed" ? <CircleAlert size={16} aria-hidden /> : <CircleCheck size={16} aria-hidden />}
              {result.run.status === "failed" ? `It failed at ${result.run.node_id && graph.nodes[result.run.node_id] ? `${title(graph.nodes[result.run.node_id]!, names)} (${result.run.node_id})` : result.run.node_id}: ${(result.run.error ?? "see the step below").replace(/\.$/, "")}.` : `It ran to the end in ${result.steps.length} ${result.steps.length === 1 ? "step" : "steps"}.`}
              {result.skipped_seconds > 0 ? ` The virtual clock skipped ${secondsText(result.skipped_seconds)}.` : ""}
            </p>
            <Trace steps={result.steps} graph={graph} names={names} hidden={result.steps.length > 0 && result.steps.every((s) => s.input === null)} />
          </section>
        )}
      </div>
    </Dialog>
  );
}
