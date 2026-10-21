// Settings > Audit log: every change in the workspace, newest first, filtered by who, what, which record and when,
// loaded a page at a time as you scroll, each event open in a drawer, and the same list as CSV.
import { Download, FilterX, History, LoaderCircle } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { whatWentWrong } from "../lib/errors";
import { Badge, Button, EmptyState, Input, Sheet, useToast } from "../ui";
import { Combobox } from "../ui/Combobox";
import { auditEventTypes, exportAudit, listAudit, listMembers, listObjects, type AuditEvent, type EventType, type ObjectDef } from "./api";
import { AdminHeader, Denied, isDenied, JsonBlock, LoadError, Loading, personName, useLoad, when, useGate } from "./common";
import { actorLabel, changesOf, exportName, families, familyLabel, isUuid, rangeError, readFilters, subjectLabel, valueText, withDayBounds, type AuditFilters } from "./logic.ts";
import "./admin.css";

const KEYS = ["actor", "subject", "type", "from", "to"] as const;
const PAGE = 50;

export function AuditLog() {
  const gate = useGate("audit.read");
  return (
    <div className="sh-page adm-page">
      <AdminHeader title="Audit log" description="Who changed what, and when. Every change is recorded in the same transaction as the change itself and cannot be edited." />
      {gate === "wait" ? <Loading label="Loading" rows={4} height={44} /> : gate === "no" ? <Denied what="read the audit log" capability="audit.read" /> : <Log />}
    </div>
  );
}

function Log() {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => readFilters(params, KEYS) as AuditFilters, [params]);
  const [events, setEvents] = useState<AuditEvent[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [more, setMore] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [open, setOpen] = useState<AuditEvent | null>(null);
  const [subjectText, setSubjectText] = useState(filters.subject ?? "");
  const seq = useRef(0);
  const sentinel = useRef<HTMLDivElement>(null);
  const members = useLoad(listMembers, []);
  const types = useLoad(auditEventTypes, []);
  const objects = useLoad(() => listObjects(), []);
  const badRange = rangeError(filters.from, filters.to);
  const api = useMemo(() => withDayBounds(filters), [filters]);

  const names = useMemo(() => new Map((members.data ?? []).map((m) => [m.user_id, personName(m)])), [members.data]);
  const set = (k: keyof AuditFilters, v: string | null) => {
    const p = new URLSearchParams(params);
    if (v) p.set(k, v);
    else p.delete(k);
    setParams(p, { replace: true });
  };

  const first = useCallback(() => {
    const mine = ++seq.current;
    setEvents(null);
    setError(null);
    setCursor(null);
    if (badRange) return setEvents([]);
    listAudit(api, null, PAGE).then(
      (page) => mine === seq.current && (setEvents(page.data), setCursor(page.next_cursor)),
      (e) => mine === seq.current && setError(e),
    );
  }, [api, badRange]);
  useEffect(first, [first]);
  useEffect(() => setSubjectText(filters.subject ?? ""), [filters.subject]);

  const loadMore = useCallback(() => {
    if (!cursor || more) return;
    const mine = seq.current;
    setMore(true);
    listAudit(api, cursor, PAGE).then(
      (page) => {
        if (mine !== seq.current) return;
        setEvents((list) => [...(list ?? []), ...page.data]);
        setCursor(page.next_cursor);
        setMore(false);
      },
      (e) => {
        if (mine !== seq.current) return;
        setMore(false);
        toast({ title: "Could not load more events", description: whatWentWrong(e), tone: "danger" });
      },
    );
  }, [api, cursor, more, toast]);

  // Infinite scroll: the next page loads when the end of the list comes near; the button does the same by keyboard.
  useEffect(() => {
    const el = sentinel.current;
    if (!el || !cursor) return;
    const io = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && loadMore(), { rootMargin: "400px" });
    io.observe(el);
    return () => io.disconnect();
  }, [cursor, loadMore]);

  const download = async () => {
    setExporting(true);
    try {
      await exportAudit(api, exportName(filters, new Date()));
      toast({ title: "Export ready", description: "The CSV holds up to 50 000 events with these filters. The export is itself in the log.", tone: "success" });
    } catch (e) {
      toast({ title: "Could not export", description: whatWentWrong(e), tone: "danger" });
    } finally {
      setExporting(false);
    }
  };

  const typeItems = useMemo(() => {
    const list = types.data ?? [];
    return families(list.map((t) => t.type)).flatMap((f) => [
      { value: `${f.family}.*`, label: `${f.family}.*`, hint: `Every ${familyLabel(f.family).toLowerCase()} event`, group: familyLabel(f.family) },
      ...f.types.map((t) => ({ value: t, label: t, group: familyLabel(f.family) })),
    ]);
  }, [types.data]);
  const describe = useMemo(() => new Map((types.data ?? []).map((t) => [t.type, t])), [types.data]);
  const objectByKey = useMemo(() => new Map((objects.data ?? []).map((o) => [o.key, o])), [objects.data]);
  const any = KEYS.some((k) => filters[k]);
  const subjectValid = !subjectText.trim() || isUuid(subjectText);

  if (error && isDenied(error)) return <Denied what="read the audit log" capability="audit.read" />;

  return (
    <div className="adm-stack">
      <form
        className="adm-filters"
        aria-label="Filter the audit log"
        onSubmit={(e) => {
          e.preventDefault();
          if (subjectValid) set("subject", subjectText.trim().toLowerCase() || null);
        }}
      >
        <div className="ui-field">
          <span className="ui-label">Who</span>
          <Combobox
            label="Who"
            placeholder="Anyone"
            items={(members.data ?? []).map((m) => ({ value: m.user_id, label: personName(m), hint: m.email }))}
            value={filters.actor ?? null}
            valueLabel={filters.actor ? (names.get(filters.actor) ?? "A former member") : undefined}
            onChange={(v) => set("actor", v)}
            onClear={() => set("actor", null)}
            clearLabel="Anyone"
          />
        </div>
        <div className="ui-field">
          <span className="ui-label">What</span>
          <Combobox label="Event type" placeholder="Every event" searchPlaceholder="record.updated, role, team..." items={typeItems} value={filters.type ?? null} onChange={(v) => set("type", v)} onClear={() => set("type", null)} clearLabel="Every event" emptyText={types.error ? "Could not load the event types" : "No event type matches"} />
        </div>
        <Input label="From" type="date" value={filters.from ?? ""} max={filters.to} onChange={(e) => set("from", e.target.value || null)} />
        <Input label="To" type="date" value={filters.to ?? ""} min={filters.from} onChange={(e) => set("to", e.target.value || null)} error={badRange} />
        <div className="adm-filter-subject">
          <Input
            label="Record or other id"
            value={subjectText}
            onChange={(e) => setSubjectText(e.target.value)}
            onBlur={() => subjectValid && subjectText.trim().toLowerCase() !== (filters.subject ?? "") && set("subject", subjectText.trim().toLowerCase() || null)}
            placeholder="Paste an id"
            className="mono"
            spellCheck={false}
            error={subjectValid ? undefined : "That is not an id."}
            hint={subjectValid ? "Its events, and the links that touch it." : undefined}
          />
        </div>
        <div className="adm-filter-actions">
          {any && (
            <Button variant="ghost" onClick={() => (setParams({}, { replace: true }), setSubjectText(""))}>
              <FilterX size={16} aria-hidden /> Clear filters
            </Button>
          )}
          <Button onClick={() => void download()} loading={exporting} disabled={!!badRange}>
            <Download size={16} aria-hidden /> Export CSV
          </Button>
        </div>
      </form>

      {error ? (
        <LoadError what="the audit log" error={error} retry={first} />
      ) : !events ? (
        <Loading label="Loading events" rows={6} height={44} />
      ) : events.length === 0 ? (
        <EmptyState
          icon={History}
          title={any ? "No events match" : "Nothing recorded yet"}
          text={any ? "Try a wider date range, or another person or type." : "Changes to records, settings, roles and webhooks will show up here as they happen."}
          action={any ? <Button onClick={() => (setParams({}, { replace: true }), setSubjectText(""))}>Clear filters</Button> : undefined}
        />
      ) : (
        <>
          <ol className="adm-events" aria-label="Events, newest first">
            {events.map((e) => (
              <li key={e.id}>
                <button type="button" className="adm-event" onClick={() => setOpen(e)} aria-haspopup="dialog">
                  <time dateTime={e.occurred_at} className="adm-event-time">
                    {when(e.occurred_at)}
                  </time>
                  <code className="adm-event-type mono">{e.type}</code>
                  <span className="adm-event-text">
                    <strong>{actorLabel(e, names)}</strong> <span className="adm-muted" aria-hidden>·</span> {subjectLabel(e, names)}
                  </span>
                </button>
              </li>
            ))}
          </ol>
          <div ref={sentinel} className="adm-more">
            {cursor ? (
              <Button onClick={loadMore} loading={more}>
                {more ? "Loading more" : "Load more"}
              </Button>
            ) : (
              <p className="adm-muted">{events.length === 1 ? "That is the only event." : `That is all: ${events.length} events.`}</p>
            )}
            {more && <LoaderCircle className="ui-spin sr-only" aria-label="Loading more events" />}
          </div>
        </>
      )}
      <EventSheet event={open} onClose={() => setOpen(null)} names={names} described={open ? describe.get(open.type) : undefined} objectByKey={objectByKey} onFilter={(k, v) => (setOpen(null), set(k, v))} />
    </div>
  );
}

function EventSheet({ event, onClose, names, described, objectByKey, onFilter }: { event: AuditEvent | null; onClose: () => void; names: Map<string, string>; described?: EventType; objectByKey: Map<string, ObjectDef>; onFilter: (k: keyof AuditFilters, v: string) => void }) {
  const changes = event ? changesOf(event.data) : [];
  const object = event && typeof event.data.object === "string" ? objectByKey.get(event.data.object) : undefined;
  const recordLink = event && event.subject.type === "record" && object ? (object.is_system ? `/${object.plural.toLowerCase()}/${event.subject.id}` : `/objects/${object.key}/${event.subject.id}`) : null;
  return (
    <Sheet open={!!event} onOpenChange={(o) => !o && onClose()} title={event?.type ?? "Event"} description={described?.description}>
      {event && (
        <div className="adm-stack">
          <dl className="adm-dl">
            <dt>When</dt>
            <dd>
              <time dateTime={event.occurred_at}>{when(event.occurred_at, true)}</time>
              <span className="adm-muted mono"> {event.occurred_at}</span>
            </dd>
            <dt>Who</dt>
            <dd>
              {actorLabel(event, names)} {event.actor.type !== "user" && <Badge>{event.actor.type}</Badge>}
              {event.actor.id && event.actor.type === "user" && (
                <Button size="sm" variant="ghost" onClick={() => onFilter("actor", event.actor.id!)}>
                  Only their events
                </Button>
              )}
            </dd>
            <dt>About</dt>
            <dd>
              {subjectLabel(event, names)}
              <div className="adm-inline">
                {recordLink && <Link to={recordLink}>Open the record</Link>}
                <Button size="sm" variant="ghost" onClick={() => onFilter("subject", event.subject.id)}>
                  Only events about it
                </Button>
              </div>
              <span className="adm-muted mono adm-break">
                {event.subject.type} {event.subject.id}
              </span>
            </dd>
            <dt>Event id</dt>
            <dd className="mono">{event.id}</dd>
          </dl>
          {changes.length > 0 && (
            <div className="adm-matrix-wrap">
              <table className="adm-matrix adm-changes">
                <caption className="adm-h3">What changed</caption>
                <thead>
                  <tr>
                    <th scope="col">Field</th>
                    <th scope="col">Before</th>
                    <th scope="col">After</th>
                  </tr>
                </thead>
                <tbody>
                  {changes.map((c) => (
                    <tr key={c.field}>
                      <th scope="row" className="mono">
                        {c.field}
                      </th>
                      <td className="adm-wrap">{valueText(c.old)}</td>
                      <td className="adm-wrap">{valueText(c.new)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          <div>
            <h3 className="adm-h3">Data</h3>
            <JsonBlock label="Event data" value={event.data} />
          </div>
        </div>
      )}
    </Sheet>
  );
}
