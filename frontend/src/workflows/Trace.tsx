// A run's trace: every step it took, what it was asked and what it did. The same for a live run and a test run.
import { CircleAlert, CircleCheck, Clock, CornerDownRight, Ban } from "lucide-react";
import type { Step } from "./api";
import { title, type Names } from "./describe";
import { secondsText, type Graph } from "./graph";
import { dateTime, Fields } from "./parts";

const STEP_ICON = { completed: CircleCheck, waiting: Clock, failed: CircleAlert, migrated: CornerDownRight, cancelled: Ban };
const STEP_WORDS: Record<Step["status"], string> = { completed: "Done", waiting: "Waiting", failed: "Failed", migrated: "Moved to a new version", cancelled: "Cancelled" };

/** What a step did, in a line, from its output. */
function outcome(s: Step): string | null {
  const o = s.output ?? {};
  if (typeof o.skipped_seconds === "number") return `Skipped ${secondsText(o.skipped_seconds)} on the virtual clock`;
  if (o.resumed_by) return o.resumed_by === "timer" ? "The wait ended" : o.resumed_by === "event" ? "The event happened" : o.resumed_by === "timeout" ? "Timed out" : `Resumed by ${String(o.resumed_by)}`;
  if (o.jumped) return `Goal met: jumped here from ${String(o.from)}`;
  if (o.would_send) return "Would send this (a test sends nothing)";
  if (o.skipped) return `Skipped: ${String(o.skipped)}`;
  if (o.deferred_until) return `Quiet hours: waits until ${dateTime(String(o.deferred_until))}`;
  if (typeof o.branch === "string") return `${o.matched ? "Matched" : "Did not match"}: went down ${o.branch === "yes" ? "Yes" : o.branch === "no" ? "No" : o.branch}${o.why ? `. ${String(o.why).replace(/^./, (c) => c.toUpperCase())}` : ""}`;
  if (typeof o.path === "string") return `Took path ${o.path}`;
  if (typeof o.met === "boolean") return o.met ? "The goal is met" : `The goal is not met yet${o.ended ? ", so the run ended" : ", so the run goes on"}`;
  if (o.until && s.status === "waiting") return `Waits until ${dateTime(String(o.until))}`;
  if (o.reason) return String(o.reason);
  return null;
}

export function Trace({ steps, graph, names, hidden }: { steps: Step[]; graph: Graph | null; names: Names; hidden?: boolean }) {
  if (!steps.length) return <p className="wf-muted">No steps yet: the run has not started its first step.</p>;
  return (
    <ol className="wf-trace">
      {steps.map((s) => {
        const node = graph?.nodes[s.node_id];
        const Icon = STEP_ICON[s.status] ?? CircleCheck;
        const line = outcome(s);
        return (
          <li key={`${s.seq}-${s.node_id}-${s.status}`} className="wf-trace-step" data-status={s.status}>
            <span className="wf-trace-icon" aria-hidden>
              <Icon size={16} />
            </span>
            <div className="wf-trace-body">
              <div className="wf-trace-head">
                <strong>{node ? title(node, names) : s.node_id ? (graph ? "A step this version no longer has" : s.node_id) : "The run"}</strong>
                <span className="mono wf-muted">{s.node_id}</span>
                <span className="wf-trace-status">{STEP_WORDS[s.status] ?? s.status}</span>
                <time className="wf-muted" dateTime={s.started_at}>
                  {dateTime(s.started_at)}
                </time>
              </div>
              {s.error && (
                <p className="wf-trace-error" role="note">
                  {s.error}
                </p>
              )}
              {line && <p className="wf-trace-line">{line}</p>}
              {hidden ? null : (s.input && Object.keys(s.input).length) || (s.output && Object.keys(s.output).length) ? (
                <details className="wf-trace-details">
                  <summary>What it was asked and what it did</summary>
                  <h4>Asked</h4>
                  <Fields data={s.input} />
                  <h4>Did</h4>
                  <Fields data={s.output} />
                </details>
              ) : null}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
