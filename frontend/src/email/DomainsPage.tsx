// Sending domains: the DNS records to publish (with copy buttons), the live SPF, DKIM and DMARC check in plain words,
// and the warm-up schedule that paces a new domain.
import { CircleCheck, CircleAlert, Copy, Globe, Plus, RefreshCw, Trash2, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { errorText } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { timeAgo } from "../lib/device";
import { whatWentWrong } from "../lib/errors";
import { Badge, Button, Dialog, EmptyState, Input, Select, Skeleton, useToast } from "../ui";
import { email, type CheckResult, type Domain } from "./api";
import { EmailShell } from "./EmailPage";
import "./email.css";

const PROVIDERS = [
  { value: "mailgun", label: "Mailgun", include: "mailgun.org", mode: "provider", selector: "mx" },
  { value: "ses", label: "Amazon SES", include: "amazonses.com", mode: "provider", selector: "" },
  { value: "smtp", label: "Another SMTP server (we sign with our own DKIM key)", include: "", mode: "managed", selector: "" },
] as const;
const STATUS = { pending: ["Not checked", "neutral"], verified: ["Verified", "success"], failing: ["Needs a fix", "danger"] } as const;
const STAGE = { not_verified: "Not sending yet: verify the DNS records first", warming: "Warming up", warm: "Warm", custom: "Custom limit" };

export function DomainsPage() {
  const { can } = useCan();
  const [domains, setDomains] = useState<Domain[] | null>(null);
  const [error, setError] = useState<string>();
  const [adding, setAdding] = useState(false);
  const load = useCallback(() => {
    email
      .domains()
      .then((d) => (setDomains(d), setError(undefined)))
      .catch((e) => setError(errorText(e)));
  }, []);
  useEffect(load, [load]);
  const replace = (d: Domain) => setDomains((all) => (all ?? []).map((x) => (x.id === d.id ? d : x)));
  return (
    <EmailShell
      title="Email"
      description="Send from your own domain, proved with SPF, DKIM and DMARC: the first thing inbox providers look at."
      actions={
        can("marketing.manage") && (
          <Button variant="primary" onClick={() => setAdding(true)}>
            <Plus size={16} aria-hidden />
            Add domain
          </Button>
        )
      }
    >
      {error ? (
        <EmptyState icon={CircleAlert} title="We could not load your domains" text={error} action={<Button onClick={load}>Try again</Button>} />
      ) : domains === null ? (
        <Skeleton className="em-skel-block" />
      ) : domains.length === 0 ? (
        <EmptyState
          icon={Globe}
          title="Add the domain you send from"
          text="Use a subdomain such as mail.yourcompany.com. We show the three DNS records to add, check them live and pace sending while the domain earns a reputation."
          action={can("marketing.manage") ? <Button onClick={() => setAdding(true)}>Add domain</Button> : undefined}
        />
      ) : (
        <div className="em-domains">
          {domains.map((d) => (
            <DomainCard key={d.id} domain={d} onChange={replace} onRemoved={load} />
          ))}
        </div>
      )}
      <AddDomain open={adding} onClose={() => setAdding(false)} onAdded={(d) => (setAdding(false), setDomains((all) => [d, ...(all ?? [])]))} />
    </EmailShell>
  );
}

function Copyable({ value, label }: { value: string; label: string }) {
  const toast = useToast();
  return (
    <span className="em-copy">
      <code>{value}</code>
      <Button
        variant="ghost"
        size="icon"
        aria-label={`Copy ${label}`}
        onClick={async () => {
          await navigator.clipboard?.writeText(value);
          toast({ title: "Copied", description: label, tone: "success" });
        }}
      >
        <Copy size={14} aria-hidden />
      </Button>
    </span>
  );
}

const RESULT_ICON = { pass: CircleCheck, warn: TriangleAlert, fail: CircleAlert, error: CircleAlert };
const RESULT_WORD = { pass: "Passes", warn: "Passes, with a warning", fail: "Fails", error: "Could not check" };

function Result({ name, result }: { name: string; result?: CheckResult }) {
  if (!result)
    return (
      <li className="em-check" data-status="none">
        <strong>{name}</strong>
        <span className="em-muted">Not checked yet</span>
      </li>
    );
  const Icon = RESULT_ICON[result.status];
  return (
    <li className="em-check" data-status={result.status}>
      <Icon size={16} aria-hidden />
      <strong>{name}</strong>
      <span>
        <span className="sr-only">{RESULT_WORD[result.status]}: </span>
        {result.message}
      </span>
      {result.found && result.found.length > 0 && result.status !== "pass" && (
        <span className="em-found">
          Found: <code>{result.found.join(" | ")}</code>
        </span>
      )}
    </li>
  );
}

function DomainCard({ domain: d, onChange, onRemoved }: { domain: Domain; onChange: (d: Domain) => void; onRemoved: () => void }) {
  const toast = useToast();
  const { can } = useCan();
  const manage = can("marketing.manage");
  const [checking, setChecking] = useState(false);
  const [limit, setLimit] = useState(d.hourly_limit ? String(d.hourly_limit) : "");
  const [removing, setRemoving] = useState(false);
  const [label, tone] = STATUS[d.status];
  const check = async () => {
    setChecking(true);
    try {
      const next = await email.checkDomain(d.id);
      onChange(next);
      toast({ title: next.status === "verified" ? `${d.domain} is verified` : `${d.domain} needs a fix`, tone: next.status === "verified" ? "success" : "danger" });
    } catch (e) {
      toast({ title: "The check did not run", description: errorText(e), tone: "danger" });
    } finally {
      setChecking(false);
    }
  };
  const saveLimit = async () => {
    try {
      onChange(await email.patchDomain(d.id, { hourly_limit: limit ? Number(limit) : null }));
      toast({ title: limit ? "Hourly limit saved" : "Back to the warm-up schedule", tone: "success" });
    } catch (e) {
      toast({ title: "Not saved", description: whatWentWrong(e), tone: "danger" });
    }
  };
  const lim = d.limits;
  return (
    <section className="em-card" aria-labelledby={`dom-${d.id}`}>
      <div className="em-card-head">
        <div className="em-head-title">
          <h2 id={`dom-${d.id}`} className="em-h2 mono">
            {d.domain}
          </h2>
          <Badge tone={tone}>{label}</Badge>
        </div>
        {manage && (
          <div className="em-row">
            <Button onClick={() => void check()} loading={checking}>
              <RefreshCw size={16} aria-hidden />
              Check DNS now
            </Button>
            <Button variant="ghost" size="icon" aria-label={`Remove ${d.domain}`} onClick={() => setRemoving(true)}>
              <Trash2 size={16} aria-hidden />
            </Button>
          </div>
        )}
      </div>
      <ul className="em-checks" aria-label="DNS checks">
        <Result name="SPF" result={d.checks.spf} />
        <Result name="DKIM" result={d.checks.dkim} />
        <Result name="DMARC" result={d.checks.dmarc} />
      </ul>
      {d.checked_at && <p className="em-muted">Last checked {timeAgo(d.checked_at)}.</p>}
      <details open={d.status !== "verified"}>
        <summary>DNS records to add at your DNS host</summary>
        <div className="em-records" role="table" aria-label={`DNS records for ${d.domain}`}>
          {d.records.map((r) => (
            <div key={r.host + r.type} className="em-record" role="row">
              <span role="cell" className="em-record-type">
                {r.type}
              </span>
              <span role="cell">
                <span className="em-record-label">Host</span>
                <Copyable value={r.host} label={`${r.type} host`} />
              </span>
              <span role="cell">
                <span className="em-record-label">Value</span>
                <Copyable value={r.value} label={`${r.type} value for ${r.host}`} />
              </span>
              <span role="cell" className="em-muted em-record-why">
                {r.purpose}
              </span>
            </div>
          ))}
        </div>
      </details>
      <div className="em-warmup">
        <h3 className="em-h3">Sending pace</h3>
        <p>
          <strong>{STAGE[lim.stage]}</strong>
          {lim.stage === "not_verified" && "."}
          {lim.stage === "warming" && ` (day ${lim.day} of 28): up to ${lim.daily?.toLocaleString()} a day, ${lim.hourly.toLocaleString()} an hour.`}
          {lim.stage === "warm" && `: up to ${lim.hourly.toLocaleString()} an hour.`}
          {lim.stage === "custom" && `: ${lim.hourly.toLocaleString()} an hour.`} Sent in the last hour: {d.sent.last_hour.toLocaleString()}, last day: {d.sent.last_day.toLocaleString()}.
        </p>
        <ol className="em-ladder" aria-label="Warm-up schedule">
          {lim.schedule.map((s, i) => {
            const next = lim.schedule[i + 1]?.day;
            const now = lim.stage === "warming" && lim.day !== null && lim.day >= s.day && (next === undefined || lim.day < next);
            return (
              <li key={s.day} data-now={now || undefined}>
                <span>Day {s.day}</span>
                <strong>{s.daily.toLocaleString()}</strong>
              </li>
            );
          })}
          <li data-now={lim.stage === "warm" || undefined}>
            <span>Day 28</span>
            <strong>Warm</strong>
          </li>
        </ol>
        {manage && (
          <div className="em-inline-form">
            <Input label="Hourly limit (optional)" type="number" min={1} value={limit} placeholder="Follow the warm-up" onChange={(e) => setLimit(e.target.value)} />
            <Button onClick={() => void saveLimit()}>Save limit</Button>
          </div>
        )}
        {manage && <p className="ui-hint">Set a limit only for a domain that already has a sending history elsewhere; leave it empty to follow the warm-up.</p>}
      </div>
      <Dialog
        open={removing}
        onOpenChange={setRemoving}
        title={`Remove ${d.domain}?`}
        description="A domain that campaigns used stays, for their reports. You can add it again later; a new DKIM key is made then."
        footer={
          <>
            <Button onClick={() => setRemoving(false)}>Keep it</Button>
            <Button
              variant="danger"
              onClick={async () => {
                setRemoving(false);
                try {
                  await email.deleteDomain(d.id);
                  toast({ title: "Domain removed", description: d.domain, tone: "success" });
                  onRemoved();
                } catch (e) {
                  toast({ title: "Not removed", description: errorText(e), tone: "danger" });
                }
              }}
            >
              Remove
            </Button>
          </>
        }
      />
    </section>
  );
}

function AddDomain({ open, onClose, onAdded }: { open: boolean; onClose: () => void; onAdded: (d: Domain) => void }) {
  const [domain, setDomain] = useState("");
  const [provider, setProvider] = useState<(typeof PROVIDERS)[number]["value"]>("mailgun");
  const [selector, setSelector] = useState("mx");
  const [busy, setBusy] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const spec = PROVIDERS.find((p) => p.value === provider)!;
  useEffect(() => {
    if (open) (setDomain(""), setProvider("mailgun"), setSelector("mx"), setErrors({}), setBusy(false));
  }, [open]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      onAdded(await email.createDomain({ domain, dkim_mode: spec.mode, dkim_selector: spec.mode === "provider" ? selector : undefined, spf_include: spec.include || undefined }));
    } catch (err) {
      const fields = (err as { fields?: Record<string, string> }).fields;
      setErrors(fields ?? { domain: whatWentWrong(err) });
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={(o) => !o && !busy && onClose()} title="Add a sending domain" description="A subdomain (mail.yourcompany.com) keeps campaign reputation apart from your everyday mail.">
      <form className="em-form" onSubmit={submit} noValidate>
        <Input label="Domain" autoFocus value={domain} error={errors.domain} placeholder="mail.yourcompany.com" onChange={(e) => setDomain(e.target.value)} />
        <Select
          label="You send through"
          value={provider}
          options={PROVIDERS.map((p) => ({ value: p.value, label: p.label }))}
          onValueChange={(v) => {
            setProvider(v as typeof provider);
            setSelector(PROVIDERS.find((p) => p.value === v)!.selector);
          }}
        />
        {spec.mode === "provider" && (
          <Input label="DKIM selector" value={selector} error={errors.dkim_selector} onChange={(e) => setSelector(e.target.value)} hint={provider === "mailgun" ? "Mailgun shows it under Domain settings > DNS records (often mx, k1 or smtp)." : "SES shows three CNAME records; use the part before ._domainkey of one of them."} />
        )}
        <div className="em-form-actions">
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={busy}>
            Add domain
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
