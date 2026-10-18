import { Download, Inbox } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { errorText } from "../lib/api";
import { timeAgo } from "../lib/device";
import { Badge, Button, EmptyState, Input, Select, Sheet, Skeleton, Table, useToast, type Column } from "../ui";
import type { Definition, Field } from "../forms-runtime/types";
import { allFields } from "./edit.ts";
import { downloadCsv, forms, type FormDetail, type Submission } from "./api";

const STATUS = [{ value: "all", label: "All responses" }, { value: "complete", label: "Completed" }, { value: "partial", label: "Not finished" }];

export function shown(value: unknown, f?: { type: string; options?: { id: string; label: string }[] }): string {
  const label = (v: unknown) => f?.options?.find((o) => o.id === v)?.label ?? String(v);
  if (Array.isArray(value)) return value.map(label).join(", ");
  if (typeof value === "boolean") return f?.type === "yes_no" ? (value ? "Yes" : "No") : value ? "Ticked" : "Not ticked";
  return label(value);
}

/** The first answers of a response, for a row of the table. */
function preview(row: Submission, fields: Field[]): string {
  return fields.filter((f) => row.answers[f.key] !== undefined).slice(0, 3).map((f) => shown(row.answers[f.key], f)).join(" · ");
}

export function Responses({ form, def }: { form: FormDetail; def: Definition }) {
  const toast = useToast();
  const [rows, setRows] = useState<Submission[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string>();
  const [status, setStatus] = useState("all");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [open, setOpen] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const filters = { status: status === "all" ? undefined : status, from: from || undefined, to: to || undefined };
  const fields = allFields(def).filter((f) => !["heading", "paragraph", "hidden"].includes(f.type));

  const load = useCallback(
    (after: string | null) => {
      setError(undefined);
      forms
        .submissions(form.id, { status: status === "all" ? undefined : status, from: from || undefined, to: to || undefined, cursor: after })
        .then((page) => {
          setRows((old) => (after ? [...(old ?? []), ...page.data] : page.data));
          setCursor(page.next_cursor);
        })
        .catch((e) => setError(errorText(e)));
    },
    [form.id, status, from, to],
  );
  useEffect(() => load(null), [load]);

  const quiz = form.kind === "quiz";
  const columns: Column<Submission>[] = [
    {
      key: "when",
      header: "Started",
      cell: (r) => (
        <button type="button" className="fm-linkbtn" onClick={() => setOpen(r.id)} title={new Date(r.created_at).toLocaleString()}>
          {timeAgo(r.created_at)}
        </button>
      ),
    },
    { key: "status", header: "Status", cell: (r) => <Badge tone={r.status === "complete" ? "success" : "neutral"}>{r.status === "complete" ? "Completed" : "Not finished"}</Badge> },
    ...(quiz ? [{ key: "score", header: "Score", align: "right" as const, mono: true, cell: (r: Submission) => (r.score === null ? "" : `${r.score} / ${r.max_score}`) }] : []),
    { key: "answers", header: "Answers", cell: (r) => <span className="fm-trunc">{preview(r, fields) || "No answers yet"}</span> },
    { key: "contact", header: "Contact", cell: (r) => (r.contact_id ? "Saved" : r.contact_error ? <Badge tone="warning">Not saved</Badge> : "") },
  ];

  return (
    <div className="fm-responses">
      <div className="fm-filters">
        <Select value={status} onValueChange={setStatus} options={STATUS} />
        <Input aria-label="From date" type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
        <Input aria-label="To date" type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
        <Button
          loading={busy}
          onClick={async () => {
            setBusy(true);
            try {
              await downloadCsv(form.id, filters);
            } catch (e) {
              toast({ title: "Could not export", description: errorText(e), tone: "danger" });
            } finally {
              setBusy(false);
            }
          }}
        >
          <Download size={16} aria-hidden />
          Export CSV
        </Button>
      </div>
      {error ? (
        <EmptyState icon={Inbox} title="We could not load the responses" text={error} action={<Button onClick={() => load(null)}>Try again</Button>} />
      ) : (
        <>
          <Table caption="Responses" columns={columns} rows={rows ?? []} rowId={(r) => r.id} loading={rows === null} empty={<EmptyState icon={Inbox} title="No responses yet" text={form.status === "published" ? "They appear here as people fill the form in, including the ones who stop part way." : "Publish the form and share its link to start collecting responses."} />} />
          {cursor && (
            <div className="fm-more">
              <Button onClick={() => load(cursor)}>Load more</Button>
            </div>
          )}
        </>
      )}
      <Detail form={form} id={open} onClose={() => setOpen(null)} />
    </div>
  );
}

function Detail({ form, id, onClose }: { form: FormDetail; id: string | null; onClose: () => void }) {
  const [sub, setSub] = useState<Submission | null>(null);
  const [error, setError] = useState<string>();
  useEffect(() => {
    setSub(null);
    setError(undefined);
    if (id) forms.submission(form.id, id).then(setSub).catch((e) => setError(errorText(e)));
  }, [form.id, id]);
  const by = new Map((sub?.fields ?? []).map((f) => [f.key, f]));
  const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "Not yet");
  return (
    <Sheet open={!!id} onOpenChange={(o) => !o && onClose()} title="Response" description={sub ? `${sub.status === "complete" ? "Completed" : "Not finished"} · version ${sub.version}` : undefined}>
      {error && <p className="fm-issue" role="alert">{error}</p>}
      {!sub && !error && <Skeleton />}
      {sub && (
        <div className="fm-detail">
          <dl>
            {(sub.fields ?? []).map((f) => (
              <div key={f.key} className="fm-dl-row">
                <dt>{f.label}</dt>
                <dd>{sub.answers[f.key] === undefined ? <span className="fm-none">No answer</span> : shown(sub.answers[f.key], f)}</dd>
              </div>
            ))}
            {Object.keys(sub.answers).filter((k) => !by.has(k)).map((k) => (
              <div key={k} className="fm-dl-row">
                <dt className="mono">{k}</dt>
                <dd>{shown(sub.answers[k])}</dd>
              </div>
            ))}
          </dl>
          <h3>Details</h3>
          <dl>
            {sub.score !== null && <Row k="Score" v={`${sub.score} out of ${sub.max_score}`} />}
            <Row k="Started" v={when(sub.started_at)} />
            <Row k="Completed" v={when(sub.completed_at)} />
            <Row k="Contact" v={sub.contact_id ? <span className="mono">{sub.contact_id}</span> : sub.contact_error ? `Not saved: ${sub.contact_error}` : "None"} />
            {sub.source_url && <Row k="Page" v={<span className="fm-wrap">{sub.source_url}</span>} />}
            {sub.referrer && <Row k="Came from" v={<span className="fm-wrap">{sub.referrer}</span>} />}
            {Object.entries(sub.utm).map(([k, v]) => <Row key={k} k={k.replace("utm_", "Campaign ")} v={v} />)}
          </dl>
          {Object.keys(sub.consent).length > 0 && (
            <>
              <h3>Consent</h3>
              <dl>
                {Object.entries(sub.consent).map(([k, c]) => (
                  <Row key={k} k={`Accepted ${new Date(c.at).toLocaleString()}`} v={c.text} />
                ))}
              </dl>
            </>
          )}
        </div>
      )}
    </Sheet>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="fm-dl-row">
      <dt>{k}</dt>
      <dd>{v}</dd>
    </div>
  );
}
