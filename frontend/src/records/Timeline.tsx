import { ArrowRight, History, Link2, Pencil, Plus, Tag as TagIcon } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Button, EmptyState, Skeleton } from "../ui";
import type { RecordsClient } from "./client.ts";
import { FieldValue, RecordChip, TagBadge } from "./fields/FieldValue";
import { dayHeading, dayKey, formatDateTime, LOCALE } from "./format.ts";
import { errorMessage } from "./errors.ts";
import { useMeta } from "./meta.tsx";
import { valueType } from "./schema.ts";
import type { FieldDef, TimelineEvent } from "./types.ts";
import { isEmptyValue } from "./validate.ts";

type State = { events: TimelineEvent[]; next: string | null; status: "loading" | "ready" | "error"; loadingMore: boolean; error?: unknown };

/** The record's events, newest first. Bump `version` after a save to fetch again without clearing the list. */
function useTimeline(client: RecordsClient, id: string, version: number) {
  const [s, setS] = useState<State>({ events: [], next: null, status: "loading", loadingMore: false });
  const gen = useRef(0);
  useEffect(() => {
    const mine = ++gen.current;
    client.timeline(id).then(
      (p) => mine === gen.current && setS({ events: p.data, next: p.next_cursor, status: "ready", loadingMore: false }),
      (error) => mine === gen.current && setS((x) => ({ ...x, status: "error", error })),
    );
  }, [client, id, version]);
  const more = useCallback(() => {
    if (!s.next || s.loadingMore) return;
    const mine = gen.current;
    setS((x) => ({ ...x, loadingMore: true }));
    client.timeline(id, s.next).then(
      (p) => mine === gen.current && setS((x) => ({ ...x, events: [...x.events, ...p.data.filter((e) => !x.events.some((o) => o.id === e.id))], next: p.next_cursor, loadingMore: false })),
      (error) => mine === gen.current && setS((x) => ({ ...x, loadingMore: false, error })),
    );
  }, [client, id, s.next, s.loadingMore]);
  return { ...s, more };
}

const timeFmt = new Intl.DateTimeFormat(LOCALE, { hour: "numeric", minute: "2-digit" });

function Change({ field, from, to }: { field: FieldDef | undefined; from: unknown; to: unknown }) {
  // An archived or unknown field still shows its key, so history never goes blank.
  const f: FieldDef = field ?? { key: "?", label: "A field", type: "text", options: {}, rules: {}, is_system: false, position: 0, archived: false };
  const show = (v: unknown) => (isEmptyValue(v) && valueType(f) !== "boolean" ? <span className="rec-placeholder">empty</span> : <FieldValue field={f} value={v} />);
  return (
    <li className="rec-tl-change">
      <span className="rec-tl-field">{f.label}</span>
      <span className="rec-tl-old">{show(from)}</span>
      <ArrowRight size={12} aria-label="changed to" role="img" />
      <span className="rec-tl-new">{show(to)}</span>
    </li>
  );
}

function Event({ e, fields }: { e: TimelineEvent; fields: Map<string, FieldDef> }) {
  const { users } = useMeta();
  const who = e.actor_id ? (users.find((u) => u.id === e.actor_id)?.name ?? "Someone") : "System";
  const at = Date.parse(e.at);
  const Icon = e.type === "created" ? Plus : e.type === "updated" ? Pencil : e.type === "linked" || e.type === "unlinked" ? Link2 : TagIcon;
  return (
    <li className="rec-tl-item">
      <span className="rec-tl-icon" aria-hidden>
        <Icon size={12} />
      </span>
      <div className="rec-tl-body">
        <p className="rec-tl-line">
          <strong>{who}</strong>{" "}
          {e.type === "created" && "created this record"}
          {e.type === "updated" && (e.changes && e.changes.length > 1 ? `changed ${e.changes.length} fields` : "changed")}
          {e.type === "tagged" && (
            <>
              added the tag {e.tag && <TagBadge tag={e.tag} />}
            </>
          )}
          {e.type === "untagged" && (
            <>
              removed the tag {e.tag && <TagBadge tag={e.tag} />}
            </>
          )}
          {(e.type === "linked" || e.type === "unlinked") && e.link && (
            <>
              {e.type === "linked" ? "added" : "removed"} the link <em className="rec-tl-link">{e.link.label}</em> <RecordChip object={e.link.object} id={e.link.id} />
            </>
          )}
          <time className="rec-tl-time" dateTime={e.at} title={formatDateTime(e.at)}>
            {timeFmt.format(at)}
          </time>
        </p>
        {e.type === "updated" && (
          <ul className="rec-tl-changes">
            {e.changes?.map((c) => (
              <Change key={c.field} field={fields.get(c.field)} from={c.from} to={c.to} />
            ))}
          </ul>
        )}
      </div>
    </li>
  );
}

export function Timeline({ client, recordId, version, fields }: { client: RecordsClient; recordId: string; version: number; fields: FieldDef[] }) {
  const t = useTimeline(client, recordId, version);
  const byKey = useMemo(() => new Map(fields.map((f) => [f.key, f])), [fields]);
  const groups = useMemo(() => {
    const out: { key: string; heading: string; events: TimelineEvent[] }[] = [];
    const now = Date.now();
    for (const e of t.events) {
      const k = dayKey(e.at);
      const last = out[out.length - 1];
      if (last && last.key === k) last.events.push(e);
      else out.push({ key: k, heading: dayHeading(e.at, now), events: [e] });
    }
    return out;
  }, [t.events]);

  return (
    <section className="rec-tl" aria-label="Timeline">
      <h3 className="rec-section-title">Timeline</h3>
      {t.status === "loading" && (
        <div className="rec-tl-skel" aria-busy="true">
          <Skeleton style={{ width: "40%" }} />
          <Skeleton style={{ width: "85%" }} />
          <Skeleton style={{ width: "70%" }} />
        </div>
      )}
      {t.status === "error" && t.events.length === 0 && (
        <EmptyState icon={History} title="Could not load the timeline" text={errorMessage(t.error)} />
      )}
      {groups.map((g) => (
        <div key={g.key} className="rec-tl-group">
          <h4 className="rec-tl-day">{g.heading}</h4>
          <ol className="rec-tl-list">
            {g.events.map((e) => (
              <Event key={e.id} e={e} fields={byKey} />
            ))}
          </ol>
        </div>
      ))}
      {t.next && (
        <Button variant="ghost" size="sm" onClick={t.more} loading={t.loadingMore}>
          Show older activity
        </Button>
      )}
    </section>
  );
}
