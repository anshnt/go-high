// A campaign's report: totals and rates (people only: privacy proxy opens and scanner clicks are shown apart), the A/B
// variants, each link, why some sends did not go, and every recipient.
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { errorText } from "../lib/api";
import { Badge, Button, EmptyState, Select, Skeleton, Table, type Column } from "../ui";
import { CircleAlert } from "lucide-react";
import { email, type Campaign, type Recipient, type Report as Data } from "./api";
import { percent } from "./blocks";

const SEND_STATUS: Record<string, string> = {
  queued: "Waiting",
  held: "Waiting for the A/B winner",
  sending: "Sending",
  sent: "Sent",
  delivered: "Delivered",
  bounced: "Bounced",
  complained: "Marked as spam",
  failed: "Failed",
  skipped: "Skipped",
  cancelled: "Cancelled",
  uncertain: "Unknown (not resent)",
};
const SEND_TONE: Record<string, "neutral" | "success" | "warning" | "danger" | "info"> = {
  sent: "success",
  delivered: "success",
  bounced: "danger",
  complained: "danger",
  failed: "danger",
  skipped: "warning",
  uncertain: "warning",
};

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="em-tile">
      <span className="em-tile-label">{label}</span>
      <strong className="em-tile-value">{value}</strong>
      {note && <span className="em-tile-note">{note}</span>}
    </div>
  );
}

export function Report({ campaign }: { campaign: Campaign }) {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string>();
  const load = useCallback(() => {
    email
      .report(campaign.id)
      .then((d) => (setData(d), setError(undefined)))
      .catch((e) => setError(errorText(e)));
  }, [campaign.id]);
  useEffect(load, [load, campaign.updated_at, campaign.stats.sent]);
  if (error) return <EmptyState icon={CircleAlert} title="We could not load the report" text={error} action={<Button onClick={load}>Try again</Button>} />;
  if (!data) return <Skeleton className="em-skel-block" />;
  const t = data.totals;
  const base = data.rates.base === "delivered" ? t.delivered : t.sent;
  return (
    <div className="em-report">
      <section aria-labelledby="totals-h">
        <h2 id="totals-h" className="em-h2">
          Results
        </h2>
        <div className="em-tiles">
          <Tile label="Recipients" value={t.recipients.toLocaleString()} note={t.waiting ? `${t.waiting.toLocaleString()} still to go` : undefined} />
          <Tile label={data.rates.base === "delivered" ? "Delivered" : "Sent"} value={base.toLocaleString()} note={data.rates.base === "sent" ? "Your provider sends no delivery reports" : undefined} />
          <Tile label="Opened" value={percent(data.rates.open)} note={`${t.opened.toLocaleString()} people`} />
          <Tile label="Clicked" value={percent(data.rates.click)} note={`${t.clicked.toLocaleString()} people`} />
          <Tile label="Unsubscribed" value={percent(data.rates.unsubscribe)} note={`${t.unsubscribed.toLocaleString()} people`} />
          <Tile label="Bounced" value={percent(data.rates.bounce)} note={`${t.bounced.toLocaleString()} addresses, now suppressed`} />
          <Tile label="Spam complaints" value={percent(data.rates.complaint)} note="Keep this under 0.1%" />
        </div>
        <p className="em-muted">
          Opens and clicks count people only. Left out: {t.machine_opens.toLocaleString()} opens by privacy proxies and scanners
          {t.privacy_proxy_only ? ` (${t.privacy_proxy_only.toLocaleString()} recipients opened only through Apple's privacy proxy, so we cannot tell if they read it)` : ""} and{" "}
          {t.machine_clicks.toLocaleString()} clicks by link scanners.
        </p>
      </section>

      {data.variants.length > 1 && (
        <section aria-labelledby="ab-r-h">
          <h2 id="ab-r-h" className="em-h2">
            A/B test
          </h2>
          <Table
            caption="Variants"
            rowId={(v) => v.variant}
            rows={data.variants}
            columns={[
              { key: "v", header: "Variant", cell: (v) => <span className="em-row">{v.variant}{v.winner && <Badge tone="success">Winner</Badge>}</span> },
              { key: "s", header: "Subject", cell: (v) => v.subject },
              { key: "n", header: "Sent", align: "right", mono: true, cell: (v) => v.sent.toLocaleString() },
              { key: "o", header: "Opened", align: "right", mono: true, cell: (v) => percent(v.open_rate) },
              { key: "c", header: "Clicked", align: "right", mono: true, cell: (v) => percent(v.click_rate) },
            ]}
          />
        </section>
      )}

      <section aria-labelledby="links-h">
        <h2 id="links-h" className="em-h2">
          Links
        </h2>
        <Table
          caption="Clicks per link"
          rowId={(l) => String(l.idx)}
          rows={data.links}
          empty={<p className="em-muted">This email has no tracked links.</p>}
          columns={[
            { key: "u", header: "Link", cell: (l) => <span className="em-url">{l.url}</span> },
            { key: "p", header: "People", align: "right", mono: true, cell: (l) => l.people.toLocaleString() },
            { key: "c", header: "Clicks", align: "right", mono: true, cell: (l) => l.clicks.toLocaleString() },
            { key: "m", header: "Scanner clicks", align: "right", mono: true, cell: (l) => l.machine_clicks.toLocaleString() },
          ]}
        />
      </section>

      {Object.keys(data.reasons).length > 0 && (
        <section aria-labelledby="why-h">
          <h2 id="why-h" className="em-h2">
            Not sent, or not delivered
          </h2>
          <ul className="em-small-list">
            {Object.entries(data.reasons)
              .sort((a, b) => b[1] - a[1])
              .map(([why, n]) => (
                <li key={why}>
                  <strong className="mono">{n.toLocaleString()}</strong> {why}
                </li>
              ))}
          </ul>
        </section>
      )}
      <Recipients campaign={campaign} />
    </div>
  );
}

function Recipients({ campaign }: { campaign: Campaign }) {
  const [status, setStatus] = useState("all");
  const [rows, setRows] = useState<Recipient[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const load = useCallback(
    (after: string | null) => {
      email
        .recipients(campaign.id, { status: status === "all" ? undefined : status, cursor: after })
        .then((p) => {
          setRows((old) => (after ? [...(old ?? []), ...p.data] : p.data));
          setCursor(p.next_cursor);
        })
        .catch(() => setRows([]));
    },
    [campaign.id, status],
  );
  useEffect(() => load(null), [load, campaign.stats.sent]);
  const columns: Column<Recipient>[] = [
    {
      key: "who",
      header: "Recipient",
      cell: (r) => (
        <div className="em-name">
          <Link to={`/contacts/${r.contact_id}`}>{r.display_name}</Link>
          <span className="em-sub">{r.email ?? "(hidden)"}</span>
        </div>
      ),
    },
    { key: "s", header: "Status", cell: (r) => <Badge tone={SEND_TONE[r.status] ?? "neutral"}>{SEND_STATUS[r.status] ?? r.status}</Badge> },
    { key: "v", header: "Variant", cell: (r) => r.variant ?? "" },
    { key: "o", header: "Opened", cell: (r) => (r.opened_at ? new Date(r.opened_at).toLocaleString() : "") },
    { key: "c", header: "Clicked", cell: (r) => (r.clicked_at ? new Date(r.clicked_at).toLocaleString() : "") },
    { key: "why", header: "Note", cell: (r) => <span className="em-sub">{r.unsubscribed_at ? "Unsubscribed" : (r.reason ?? "")}</span> },
  ];
  return (
    <section aria-labelledby="rcpt-h">
      <div className="em-card-head">
        <h2 id="rcpt-h" className="em-h2">
          Recipients
        </h2>
        <Select
          aria-label="Show recipients"
          value={status}
          onValueChange={setStatus}
          options={[{ value: "all", label: "Everyone" }, ...Object.entries(SEND_STATUS).map(([value, label]) => ({ value, label }))]}
        />
      </div>
      <Table caption="Recipients" columns={columns} rows={rows ?? []} rowId={(r) => r.id} loading={rows === null} empty={<p className="em-muted">Nobody here.</p>} />
      {cursor && (
        <div className="em-more">
          <Button onClick={() => load(cursor)}>Load more</Button>
        </div>
      )}
    </section>
  );
}
