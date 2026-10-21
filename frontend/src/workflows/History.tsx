// Every version, newest first (nothing is pruned), and what changed between any two, step by step.
import { CircleAlert, History as HistoryIcon, Rocket, Undo2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { errorText } from "../lib/api";
import { timeAgo } from "../lib/device";
import { Badge, Button, EmptyState, Select, Skeleton } from "../ui";
import { workflows, type Diff, type Version } from "./api";
import { summary, title, triggerSummary, type Names } from "./describe";
import { same, type WfNode } from "./graph";
import { dateTime, Value } from "./parts";
import { settingLabel } from "./schema";

type Props = {
  workflowId: string;
  names: Names;
  canWrite: boolean;
  canPublish: boolean;
  /** changes when a version is saved or published, so the list reads again */
  refreshKey: number;
  onOpenVersion: (n: number) => void;
  onPublishVersion: (n: number) => void;
};

export function History({ workflowId, names, canWrite, canPublish, refreshKey, onOpenVersion, onPublishVersion }: Props) {
  const [versions, setVersions] = useState<Version[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string>();
  const [from, setFrom] = useState<number | null>(null);
  const [to, setTo] = useState<number | null>(null);
  const pane = useRef<HTMLElement>(null);

  const load = useCallback(
    (after: string | null) => {
      setError(undefined);
      workflows
        .versions(workflowId, after)
        .then((page) => {
          if (after) setVersions((old) => [...(old ?? []), ...page.data]);
          else {
            setVersions(page.data);
            setTo(page.data[0]?.number ?? null);
            setFrom(page.data[1]?.number ?? null);
          }
          setCursor(page.next_cursor);
        })
        .catch((e) => setError(errorText(e)));
    },
    [workflowId, refreshKey],
  );
  useEffect(() => load(null), [load]);

  if (error) return <EmptyState icon={CircleAlert} title="We could not load the history" text={error} action={<Button onClick={() => load(null)}>Try again</Button>} />;
  if (!versions)
    return (
      <div className="wf-stack" aria-busy="true">
        <Skeleton style={{ height: 48 }} />
        <Skeleton style={{ height: 48 }} />
      </div>
    );
  if (!versions.length) return <EmptyState icon={HistoryIcon} title="No versions yet" text="Each save makes a version, kept forever. Add a step and save to make the first." />;

  const options = versions.map((v) => ({ value: String(v.number), label: `Version ${v.number}${v.published ? " (live)" : ""}` }));
  return (
    <div className="wf-history">
      <section aria-label="Versions">
        <ol className="wf-versions">
          {versions.map((v) => (
            <li key={v.id} className="wf-version" data-live={v.published || undefined}>
              <div className="wf-version-main">
                <strong>Version {v.number}</strong>
                {v.published && <Badge tone="success">Live</Badge>}
                {!v.published && v.published_at && <Badge>Was live</Badge>}
                <span className="wf-muted">
                  {v.nodes} {v.nodes === 1 ? "step" : "steps"}, saved <time dateTime={v.created_at} title={dateTime(v.created_at)}>{timeAgo(v.created_at)}</time>
                </span>
              </div>
              {v.note && <p className="wf-version-note">{v.note}</p>}
              <div className="wf-version-actions">
                <Button variant="ghost" size="sm" onClick={() => {
                    setTo(v.number);
                    setFrom(versions.find((x) => x.number < v.number)?.number ?? null);
                    requestAnimationFrame(() => pane.current?.scrollIntoView({ block: "nearest", behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" }));
                  }} disabled={v.number === versions[versions.length - 1]?.number && !cursor}>
                  Compare with the one before
                </Button>
                {canWrite && (
                  <Button variant="ghost" size="sm" onClick={() => onOpenVersion(v.number)}>
                    <Undo2 size={14} aria-hidden /> Edit from this version
                  </Button>
                )}
                {canPublish && !v.published && (
                  <Button variant="ghost" size="sm" onClick={() => onPublishVersion(v.number)}>
                    <Rocket size={14} aria-hidden /> {versions.some((x) => x.published && x.number > v.number) ? "Roll back to it" : "Publish it"}
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ol>
        {cursor && (
          <div className="wf-more">
            <Button onClick={() => load(cursor)}>Load older versions</Button>
          </div>
        )}
      </section>
      <section className="wf-diff-pane" aria-label="Compare versions" ref={pane}>
        <div className="wf-diff-pick">
          <Select label="From" value={from === null ? undefined : String(from)} placeholder="Choose" onValueChange={(v) => setFrom(Number(v))} options={options} />
          <Select label="To" value={to === null ? undefined : String(to)} placeholder="Choose" onValueChange={(v) => setTo(Number(v))} options={options} />
        </div>
        {from !== null && to !== null && from !== to ? <DiffView workflowId={workflowId} from={from} to={to} names={names} /> : <p className="wf-muted">{versions.length === 1 ? "There is one version so far: save another to compare." : "Choose two different versions."}</p>}
      </section>
    </div>
  );
}

const isObject = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);

/** The keys that differ, with a step's config opened up into its settings ("Message", "Channel"). */
function changes(keys: string[], before: Record<string, unknown>, after: Record<string, unknown>) {
  return keys.flatMap((k) => {
    const b = before[k];
    const a = after[k];
    if (k === "config" && isObject(b) && isObject(a))
      return [...new Set([...Object.keys(b), ...Object.keys(a)])].filter((s) => !same(b[s], a[s])).map((s) => ({ key: s, label: settingLabel(s), before: b[s], after: a[s] }));
    return [{ key: k, label: settingLabel(k), before: b, after: a }];
  });
}

/** An id as the name of what it names, where we know it. */
function named(key: string, v: unknown, names: Names): unknown {
  if (typeof v !== "string") return v;
  const look = key === "tag" ? names.tag : key === "channel_id" ? names.channel : key === "stage_id" ? names.stage : key === "user_id" || key === "assignee" ? names.user : undefined;
  if (v === "owner") return "The record's owner";
  if (!look) return v;
  return look(v) ?? (/^[0-9a-f-]{36}$/i.test(v) ? "Something that no longer exists" : v);
}

function DiffView({ workflowId, from, to, names }: { workflowId: string; from: number; to: number; names: Names }) {
  const [diff, setDiff] = useState<Diff | null>(null);
  const [error, setError] = useState<string>();
  useEffect(() => {
    let alive = true;
    setDiff(null);
    setError(undefined);
    workflows
      .diff(workflowId, from, to)
      .then((d) => alive && setDiff(d))
      .catch((e) => alive && setError(errorText(e)));
    return () => {
      alive = false;
    };
  }, [workflowId, from, to]);
  if (error)
    return (
      <p className="wf-alert" role="alert">
        <CircleAlert size={16} aria-hidden /> {error}
      </p>
    );
  if (!diff) return <Skeleton style={{ height: 80 }} />;
  const n = diff.nodes;
  const nothing = !diff.trigger.changed && !diff.start.changed && !n.added.length && !n.removed.length && !n.changed.length;
  const line = (node: Record<string, unknown>) => {
    const w = node as unknown as WfNode;
    return `${title(w, names)}: ${summary(w, names)}`;
  };
  return (
    <div className="wf-diff" aria-live="polite">
      <h3 className="wf-h3">
        Version {diff.from} to version {diff.to}
      </h3>
      {nothing && <p className="wf-muted">The steps are the same. Only where they are drawn may differ.</p>}
      {diff.trigger.changed && (
        <div className="wf-diff-item" data-kind="changed">
          <strong>Trigger changed</strong>
          <p className="wf-diff-before">{triggerSummary(diff.trigger.before, names)}</p>
          <p className="wf-diff-after">{triggerSummary(diff.trigger.after, names)}</p>
        </div>
      )}
      {diff.start.changed && (
        <div className="wf-diff-item" data-kind="changed">
          <strong>First step changed</strong>
          <p className="wf-diff-before mono">{diff.start.before ?? "none"}</p>
          <p className="wf-diff-after mono">{diff.start.after ?? "none"}</p>
        </div>
      )}
      {n.added.map((a) => (
        <div key={`a-${a.id}`} className="wf-diff-item" data-kind="added">
          <strong>Added</strong> <span className="mono">{a.id}</span>
          <p>{line(a.node)}</p>
        </div>
      ))}
      {n.removed.map((r) => (
        <div key={`r-${r.id}`} className="wf-diff-item" data-kind="removed">
          <strong>Removed</strong> <span className="mono">{r.id}</span>
          <p>{line(r.node)}</p>
        </div>
      ))}
      {n.changed.map((c) => (
        <div key={`c-${c.id}`} className="wf-diff-item" data-kind="changed">
          <strong>Changed</strong> <span className="mono">{c.id}</span> <span className="wf-muted">({c.keys.join(", ")})</span>
          <p>{line(c.after)}</p>
          <dl className="wf-diff-keys">
            {changes(c.keys, c.before, c.after).map((d) => (
              <div key={d.key}>
                <dt>{d.label}</dt>
                <dd>
                  <span className="wf-diff-before">{d.before === undefined ? <span className="wf-muted">not set</span> : <Value value={named(d.key, d.before, names)} />}</span>
                  <span className="wf-diff-after">{d.after === undefined ? <span className="wf-muted">not set</span> : <Value value={named(d.key, d.after, names)} />}</span>
                </dd>
              </div>
            ))}
          </dl>
        </div>
      ))}
    </div>
  );
}
