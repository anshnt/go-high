// The suppression list (addresses never mailed again) and the email settings (footer, tracking, topics).
import { Archive, CircleAlert, Plus, ShieldBan, Trash2, Undo2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { errorText } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { timeAgo } from "../lib/device";
import { whatWentWrong } from "../lib/errors";
import { Badge, Button, Dialog, EmptyState, Input, Select, Skeleton, Switch, Table, Textarea, useToast, type Column } from "../ui";
import { email, type Settings, type Suppression, type Topic } from "./api";
import { SUPPRESSION_LABEL } from "./blocks";
import { EmailShell } from "./EmailPage";
import "./email.css";

const REASONS = [{ value: "all", label: "Every reason" }, ...Object.entries(SUPPRESSION_LABEL).map(([value, label]) => ({ value, label }))];
const TONE = { hard_bounce: "danger", complaint: "danger", unsubscribe: "warning", manual: "neutral" } as const;

export function SuppressionsPage() {
  const toast = useToast();
  const { can } = useCan();
  const [rows, setRows] = useState<Suppression[] | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [cursor, setCursor] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [reason, setReason] = useState("all");
  const [error, setError] = useState<string>();
  const [adding, setAdding] = useState(false);
  const load = useCallback(
    (after: string | null) => {
      setError(undefined);
      email
        .suppressions({ q, reason: reason === "all" ? undefined : reason, cursor: after })
        .then((p) => {
          setRows((old) => (after ? [...(old ?? []), ...p.data] : p.data));
          setCursor(p.next_cursor);
          setCounts(p.counts);
        })
        .catch((e) => setError(errorText(e)));
    },
    [q, reason],
  );
  useEffect(() => {
    const t = setTimeout(() => load(null), q ? 250 : 0);
    return () => clearTimeout(t);
  }, [load, q]);
  const remove = async (s: Suppression) => {
    try {
      await email.unsuppress(s.id);
      toast({ title: "Taken off the list", description: `${s.email} can get campaigns again.`, tone: "success" });
      load(null);
    } catch (e) {
      toast({ title: "Not removed", description: errorText(e), tone: "danger" });
    }
  };
  const columns: Column<Suppression>[] = [
    { key: "email", header: "Address", mono: true, cell: (s) => s.email },
    { key: "reason", header: "Why", cell: (s) => <Badge tone={TONE[s.reason]}>{SUPPRESSION_LABEL[s.reason]}</Badge> },
    { key: "detail", header: "Detail", cell: (s) => <span className="em-sub">{s.detail ?? ""}</span> },
    { key: "when", header: "Added", cell: (s) => <time dateTime={s.created_at}>{timeAgo(s.created_at)}</time> },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (s) =>
        can("marketing.manage") && s.removable ? (
          <Button variant="ghost" size="icon" aria-label={`Take ${s.email} off the list`} onClick={() => void remove(s)}>
            <Trash2 size={16} aria-hidden />
          </Button>
        ) : null,
    },
  ];
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  return (
    <EmailShell
      title="Email"
      description="Addresses that never get a campaign again: bounces and complaints come in by themselves, unsubscribes from every email's link."
      actions={
        can("marketing.manage") && (
          <Button variant="primary" onClick={() => setAdding(true)}>
            <Plus size={16} aria-hidden />
            Add address
          </Button>
        )
      }
    >
      <p className="em-muted">
        {total.toLocaleString()} suppressed
        {Object.entries(counts).map(([k, n]) => ` · ${n.toLocaleString()} ${SUPPRESSION_LABEL[k as keyof typeof SUPPRESSION_LABEL].toLowerCase()}`)}. Only the person can undo an unsubscribe or a
        complaint, from their preference page.
      </p>
      <div className="em-filters">
        <Input type="search" aria-label="Search addresses" placeholder="Search addresses" value={q} onChange={(e) => setQ(e.target.value)} />
        <Select aria-label="Reason" value={reason} onValueChange={setReason} options={REASONS} />
      </div>
      {error ? (
        <EmptyState icon={CircleAlert} title="We could not load the list" text={error} action={<Button onClick={() => load(null)}>Try again</Button>} />
      ) : (
        <>
          <Table
            caption="Suppressed addresses"
            columns={columns}
            rows={rows ?? []}
            rowId={(s) => s.id}
            loading={rows === null}
            empty={<EmptyState icon={ShieldBan} title="Nobody is suppressed" text="Hard bounces, spam complaints and unsubscribes land here by themselves, so no campaign mails them again." />}
          />
          {cursor && (
            <div className="em-more">
              <Button onClick={() => load(cursor)}>Load more</Button>
            </div>
          )}
        </>
      )}
      <AddSuppression open={adding} onClose={() => setAdding(false)} onAdded={() => (setAdding(false), load(null))} />
    </EmailShell>
  );
}

function AddSuppression({ open, onClose, onAdded }: { open: boolean; onClose: () => void; onAdded: () => void }) {
  const [address, setAddress] = useState("");
  const [detail, setDetail] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) (setAddress(""), setDetail(""), setError(undefined), setBusy(false));
  }, [open]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    try {
      await email.suppress({ email: address, detail: detail || undefined });
      onAdded();
    } catch (err) {
      setError(whatWentWrong(err));
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={(o) => !o && !busy && onClose()} title="Suppress an address" description="It gets no campaign from now on. Conversations in the inbox are not affected.">
      <form className="em-form" onSubmit={submit} noValidate>
        <Input label="Email address" type="email" autoFocus value={address} error={error} onChange={(e) => setAddress(e.target.value)} />
        <Input label="Why (optional)" value={detail} maxLength={300} onChange={(e) => setDetail(e.target.value)} placeholder="Asked by phone" />
        <div className="em-form-actions">
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={busy}>
            Suppress
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

export function EmailSettingsPage() {
  const toast = useToast();
  const { can } = useCan();
  const manage = can("marketing.manage");
  const [settings, setSettings] = useState<Settings | null>(null);
  const [topics, setTopics] = useState<Topic[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<string>();
  const loadTopics = useCallback(() => {
    email
      .topics(true)
      .then(setTopics)
      .catch(() => setTopics([]));
  }, []);
  useEffect(() => {
    email
      .settings()
      .then(setSettings)
      .catch((e) => setError(errorText(e)));
    loadTopics();
  }, [loadTopics]);
  const save = async (e: FormEvent) => {
    e.preventDefault();
    if (!settings) return;
    setBusy(true);
    try {
      setSettings(await email.saveSettings(settings));
      toast({ title: "Email settings saved", tone: "success" });
    } catch (err) {
      toast({ title: "Not saved", description: whatWentWrong(err), tone: "danger" });
    } finally {
      setBusy(false);
    }
  };
  const addTopic = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return;
    try {
      await email.createTopic({ name: name.trim(), description: description.trim() });
      setName("");
      setDescription("");
      loadTopics();
    } catch (err) {
      toast({ title: "Not added", description: whatWentWrong(err), tone: "danger" });
    }
  };
  const archive = async (t: Topic) => {
    try {
      await email.patchTopic(t.id, { archived: !t.archived });
      loadTopics();
    } catch (err) {
      toast({ title: "That did not work", description: errorText(err), tone: "danger" });
    }
  };
  return (
    <EmailShell title="Email" description="What every campaign carries, and the topics people can choose on their preference page.">
      {error ? (
        <EmptyState icon={CircleAlert} title="We could not load the settings" text={error} />
      ) : !settings ? (
        <Skeleton className="em-skel-block" />
      ) : (
        <div className="em-steps">
          <form className="em-card" onSubmit={save} aria-labelledby="footer-h">
            <h2 id="footer-h" className="em-h2">
              Footer
            </h2>
            <p className="em-muted">Every campaign ends with your name and postal address, an unsubscribe link and a link to the preference page. Most anti-spam laws ask for all of them.</p>
            <Input label="Company name" value={settings.company_name} maxLength={200} disabled={!manage} onChange={(e) => setSettings({ ...settings, company_name: e.target.value })} />
            <Textarea label="Postal address" rows={2} value={settings.postal_address} maxLength={500} disabled={!manage} onChange={(e) => setSettings({ ...settings, postal_address: e.target.value })} />
            <h2 className="em-h2">Tracking</h2>
            <Switch label="Track opens (a tiny image)" checked={settings.track_opens} disabled={!manage} onCheckedChange={(v) => setSettings({ ...settings, track_opens: v })} />
            <Switch label="Track clicks (links go through this app)" checked={settings.track_clicks} disabled={!manage} onCheckedChange={(v) => setSettings({ ...settings, track_clicks: v })} />
            <p className="ui-hint">Opens by Apple's privacy proxy and clicks by link scanners are counted apart, so rates reflect people.</p>
            {manage && (
              <div className="em-form-actions">
                <Button type="submit" variant="primary" loading={busy}>
                  Save settings
                </Button>
              </div>
            )}
          </form>
          <section className="em-card" aria-labelledby="topics-h">
            <h2 id="topics-h" className="em-h2">
              Topics
            </h2>
            <p className="em-muted">People can leave one topic and keep the rest. A campaign with a topic is skipped for whoever left it.</p>
            {topics === null ? (
              <Skeleton className="em-skel-line" />
            ) : topics.length === 0 ? (
              <p className="em-muted">No topics yet: one unsubscribe link stops all marketing email.</p>
            ) : (
              <ul className="em-topics">
                {topics.map((t) => (
                  <li key={t.id} data-archived={t.archived || undefined}>
                    <span>
                      <strong>{t.name}</strong>
                      {t.archived && <Badge>Archived</Badge>}
                      <span className="em-sub">{t.description}</span>
                    </span>
                    {manage && (
                      <Button variant="ghost" size="icon" aria-label={t.archived ? `Restore ${t.name}` : `Archive ${t.name}`} onClick={() => void archive(t)}>
                        {t.archived ? <Undo2 size={16} aria-hidden /> : <Archive size={16} aria-hidden />}
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            )}
            {manage && (
              <form className="em-inline-form" onSubmit={addTopic}>
                <Input label="New topic" value={name} maxLength={100} placeholder="Newsletter" onChange={(e) => setName(e.target.value)} />
                <Input label="Description (optional)" value={description} maxLength={300} placeholder="Once a month" onChange={(e) => setDescription(e.target.value)} />
                <Button type="submit">Add topic</Button>
              </form>
            )}
          </section>
        </div>
      )}
    </EmailShell>
  );
}
