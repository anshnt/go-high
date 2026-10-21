// Small pieces the workflow screens share: status badges, a record search, a value viewer.
import { Search } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";
import { errorText } from "../lib/api";
import { Badge, Input, type Tone } from "../ui";
import { searchRecords, type Glance, type RunStatus, type Status, type WorkflowRow } from "./api";

export const STATUS_LABEL: Record<Status, string> = { draft: "Draft", published: "Live", paused: "Paused", archived: "Archived" };
export const STATUS_TONE: Record<Status, Tone> = { draft: "neutral", published: "success", paused: "warning", archived: "neutral" };
export const RUN_LABEL: Record<RunStatus, string> = { running: "Running", waiting: "Waiting", completed: "Completed", failed: "Failed", exited: "Exited", cancelled: "Cancelled" };
const RUN_TONE: Record<RunStatus, Tone> = { running: "info", waiting: "accent", completed: "success", failed: "danger", exited: "neutral", cancelled: "neutral" };

export const StatusBadge = ({ status }: { status: Status }) => <Badge tone={STATUS_TONE[status]}>{STATUS_LABEL[status]}</Badge>;
export const RunBadge = ({ status }: { status: RunStatus }) => <Badge tone={RUN_TONE[status]}>{RUN_LABEL[status]}</Badge>;

/** Records in the workflow now (running or waiting). */
export const enrolled = (w: Pick<WorkflowRow, "runs">) => (w.runs.running ?? 0) + (w.runs.waiting ?? 0);

export function versionText(w: Pick<WorkflowRow, "published_version" | "latest_version" | "has_draft_changes">): string {
  if (w.latest_version === null) return "No steps saved yet";
  if (w.published_version === null) return `Version ${w.latest_version}, never published`;
  return w.has_draft_changes ? `Version ${w.published_version} live, ${w.latest_version} saved` : `Version ${w.published_version}`;
}

export const dateTime = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }) : "";

/** Searches the records of one object and picks one. Arrows move through the results, Enter picks. */
export function RecordSearch({ object, noun, value, onChange, label = "Record", autoFocus }: { object: string; noun: string; value: Glance | null; onChange: (r: Glance | null) => void; label?: string; autoFocus?: boolean }) {
  const id = useId();
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Glance[] | null>(null);
  const [error, setError] = useState<string>();
  const [active, setActive] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let alive = true;
    const t = setTimeout(() => {
      searchRecords(object, q)
        .then((rows) => alive && (setFound(rows), setActive(0), setError(undefined)))
        .catch((e) => alive && (setFound([]), setError(errorText(e))));
    }, q ? 250 : 0);
    return () => {
      alive = false;
      clearTimeout(t);
    };
  }, [object, q]);

  if (value)
    return (
      <div className="ui-field">
        <span className="ui-label">{label}</span>
        <div className="wf-picked">
          <strong>{value.display_name}</strong>
          <button
            type="button"
            className="wf-link"
            onClick={() => {
              onChange(null);
              requestAnimationFrame(() => input.current?.focus());
            }}
          >
            Change
          </button>
        </div>
      </div>
    );
  const list = found ?? [];
  return (
    <div className="wf-search">
      <Input
        ref={input}
        id={id}
        label={label}
        type="search"
        autoFocus={autoFocus}
        data-autofocus={autoFocus || undefined}
        placeholder={`Search ${noun}`}
        value={q}
        autoComplete="off"
        role="combobox"
        aria-expanded={list.length > 0}
        aria-controls={`${id}-list`}
        aria-activedescendant={list[active] ? `${id}-${list[active]!.id}` : undefined}
        error={error}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") (e.preventDefault(), setActive((a) => Math.min(list.length - 1, a + 1)));
          else if (e.key === "ArrowUp") (e.preventDefault(), setActive((a) => Math.max(0, a - 1)));
          else if (e.key === "Enter" && list[active]) (e.preventDefault(), onChange(list[active]!));
        }}
      />
      <ul id={`${id}-list`} className="wf-found" role="listbox" aria-label={`Matching ${noun}`}>
        {found === null ? (
          <li className="wf-found-note">Searching</li>
        ) : list.length === 0 ? (
          <li className="wf-found-note">{q ? `No ${noun} match "${q}"` : `No ${noun} yet`}</li>
        ) : (
          list.map((r, i) => (
            <li key={r.id} id={`${id}-${r.id}`} role="option" aria-selected={i === active} data-active={i === active || undefined} onMouseDown={(e) => e.preventDefault()} onClick={() => onChange(r)}>
              <Search size={14} aria-hidden />
              {r.display_name}
            </li>
          ))
        )}
      </ul>
    </div>
  );
}

/** A value from a step's input or output, readable: text as text, the rest as indented JSON. */
export function Value({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className="wf-muted">none</span>;
  if (typeof value === "string") return <span className="wf-value-text">{value}</span>;
  if (typeof value === "number" || typeof value === "boolean") return <span className="mono">{String(value)}</span>;
  return <pre className="wf-json">{JSON.stringify(value, null, 2)}</pre>;
}

/** Key, value rows of a step's input or output. */
export function Fields({ data, empty = "Nothing" }: { data: Record<string, unknown> | null | undefined; empty?: string }) {
  const entries = Object.entries(data ?? {});
  if (!entries.length) return <p className="wf-muted">{empty}</p>;
  return (
    <dl className="wf-kv">
      {entries.map(([k, v]) => (
        <div key={k}>
          <dt>{k.replace(/_/g, " ")}</dt>
          <dd>
            <Value value={v} />
          </dd>
        </div>
      ))}
    </dl>
  );
}
