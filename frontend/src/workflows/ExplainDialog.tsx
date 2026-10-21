// "Why did this record not enter?": the log of trigger checks for one record (kept 7 days, misses too, each with the
// clause that failed), or, with no check in the log, the trigger judged against the record as it is now.
import { CircleAlert, CircleCheck, Info } from "lucide-react";
import { useEffect, useState } from "react";
import { errorText } from "../lib/api";
import { useMeta } from "../records/meta.tsx";
import { Badge, Button, Dialog, Skeleton } from "../ui";
import { workflows, type CheckOutcome, type Explanation, type Glance } from "./api";
import { eventLabel } from "./graph";
import { dateTime, RunBadge, RecordSearch } from "./parts";

const OUTCOME: Record<CheckOutcome, string> = {
  entered: "Entered",
  filter: "The record did not match",
  object: "Another kind of record",
  data: "The event's details did not match",
  reentry: "Was in it before (re-entry is off)",
  running: "Already in it",
  self: "The workflow's own change",
  no_record: "The record was gone",
  error: "The filter could not be judged",
};

export function ExplainDialog({ open, onOpenChange, workflowId, object, initial, onOpenRun }: { open: boolean; onOpenChange: (o: boolean) => void; workflowId: string; object: string; initial?: Glance | null; onOpenRun: (id: string) => void }) {
  const meta = useMeta();
  const noun = meta.objects.find((o) => o.key === object)?.plural.toLowerCase() ?? "records";
  const [record, setRecord] = useState<Glance | null>(null);
  const [answer, setAnswer] = useState<Explanation | null>(null);
  const [error, setError] = useState<string>();
  useEffect(() => {
    if (open) setRecord(initial ?? null);
  }, [open, initial]);
  useEffect(() => {
    setAnswer(null);
    setError(undefined);
    if (!open || !record) return;
    let alive = true;
    workflows
      .explain(workflowId, record.id)
      .then((a) => alive && setAnswer(a))
      .catch((e) => alive && setError(errorText(e)));
    return () => {
      alive = false;
    };
  }, [open, record, workflowId]);

  const Icon = !answer ? Info : answer.in_workflow || answer.checks[0]?.outcome === "entered" ? CircleCheck : answer.evaluation?.matched ? Info : CircleAlert;
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Why did a record not enter?"
      description="Every time the trigger's event happens to a record, the check is kept for 7 days with the reason, hits and misses."
      footer={<Button onClick={() => onOpenChange(false)}>Close</Button>}
    >
      <div className="wf-stack">
        <RecordSearch object={object} noun={noun} value={record} onChange={setRecord} autoFocus label={`One of your ${noun}`} />
        {error && (
          <p className="wf-alert" role="alert">
            <CircleAlert size={16} aria-hidden /> {error}
          </p>
        )}
        {record && !answer && !error && (
          <div className="wf-stack" aria-busy="true">
            <Skeleton style={{ height: 18, width: "80%" }} />
            <Skeleton style={{ height: 18, width: "60%" }} />
          </div>
        )}
        {answer && (
          <div className="wf-stack" aria-live="polite">
            <p className="wf-answer">
              <Icon size={18} aria-hidden />
              <span>{/[.!?]$/.test(answer.answer) ? answer.answer : `${answer.answer}.`}</span>
            </p>
            {answer.checks.length > 0 && (
              <section>
                <h3 className="wf-h3">Checks in the last 7 days</h3>
                <ol className="wf-checks">
                  {answer.checks.map((c) => (
                    <li key={`${c.event_id}-${c.at}`}>
                      <div className="wf-check-head">
                        <Badge tone={c.outcome === "entered" ? "success" : "neutral"}>{OUTCOME[c.outcome] ?? c.outcome}</Badge>
                        <span>{eventLabel(c.event_type)}</span>
                        <time className="wf-muted" dateTime={c.at}>
                          {dateTime(c.at)}
                        </time>
                      </div>
                      {c.reason && <p className="wf-muted">{c.reason}</p>}
                      {c.run_id && (
                        <button type="button" className="wf-link" onClick={() => onOpenRun(c.run_id!)}>
                          See its run
                        </button>
                      )}
                    </li>
                  ))}
                </ol>
              </section>
            )}
            {answer.runs.length > 0 && (
              <section>
                <h3 className="wf-h3">Its runs of this workflow</h3>
                <ul className="wf-list">
                  {answer.runs.map((r) => (
                    <li key={r.id}>
                      <RunBadge status={r.status} /> <button type="button" className="wf-link" onClick={() => onOpenRun(r.id)}>started {dateTime(r.started_at)}</button>
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </div>
        )}
      </div>
    </Dialog>
  );
}
