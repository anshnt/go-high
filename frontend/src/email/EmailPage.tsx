// The Email area: campaigns, templates, sending domains, the suppression list and settings, one tab each.
import { CircleAlert, Copy, EllipsisVertical, Mail, Plus, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { Link, NavLink, useNavigate } from "react-router";
import { errorText } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { timeAgo } from "../lib/device";
import { PageHeader } from "../shell/PageHeader";
import { Badge, Button, Dialog, DropdownMenu, EmptyState, Input, MenuItem, MenuSeparator, Select, Table, useToast, type Column } from "../ui";
import { email, type Campaign, type Template } from "./api";
import { percent, ratio, STATUS_LABEL, STATUS_TONE } from "./blocks";
import "./email.css";

const TABS = [
  { to: "/email", label: "Campaigns", end: true },
  { to: "/email/templates", label: "Templates" },
  { to: "/email/domains", label: "Domains" },
  { to: "/email/suppressions", label: "Suppressions" },
  { to: "/email/settings", label: "Settings" },
];

/** The header and tab row every Email screen shares. */
export function EmailShell({ title, description, actions, children }: { title: string; description: string; actions?: ReactNode; children: ReactNode }) {
  return (
    <div className="sh-page em-page">
      <PageHeader
        title={title}
        description={description}
        actions={actions}
        views={
          <nav className="em-tabs" aria-label="Email">
            {TABS.map((t) => (
              <NavLink key={t.to} to={t.to} end={t.end} className="em-tab">
                {t.label}
              </NavLink>
            ))}
          </nav>
        }
      />
      {children}
    </div>
  );
}

const FILTERS = [
  { value: "all", label: "All campaigns" },
  { value: "draft", label: "Drafts" },
  { value: "scheduled", label: "Scheduled" },
  { value: "sending", label: "Sending" },
  { value: "sent", label: "Sent" },
  { value: "paused", label: "Paused" },
  { value: "cancelled", label: "Cancelled" },
  { value: "failed", label: "Failed" },
];

export function CampaignsPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const { can } = useCan();
  const [rows, setRows] = useState<Campaign[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string>();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");
  const [creating, setCreating] = useState(false);
  const [removing, setRemoving] = useState<Campaign | null>(null);

  const load = useCallback(
    (after: string | null) => {
      setError(undefined);
      email
        .campaigns({ q, status: status === "all" ? undefined : status, cursor: after })
        .then((page) => {
          setRows((old) => (after ? [...(old ?? []), ...page.data] : page.data));
          setCursor(page.next_cursor);
        })
        .catch((e) => setError(errorText(e)));
    },
    [q, status],
  );
  useEffect(() => {
    const t = setTimeout(() => load(null), q ? 250 : 0);
    return () => clearTimeout(t);
  }, [load, q]);

  async function duplicate(c: Campaign) {
    try {
      navigate(`/email/campaigns/${(await email.duplicateCampaign(c.id)).id}`);
    } catch (e) {
      toast({ title: "Could not duplicate", description: errorText(e), tone: "danger" });
    }
  }

  const columns: Column<Campaign>[] = [
    {
      key: "name",
      header: "Campaign",
      cell: (c) => (
        <div className="em-name">
          <Link to={`/email/campaigns/${c.id}`}>{c.name}</Link>
          <span className="em-sub">{c.subject || "No subject yet"}</span>
        </div>
      ),
    },
    { key: "status", header: "Status", cell: (c) => <Badge tone={STATUS_TONE[c.status]}>{STATUS_LABEL[c.status]}</Badge> },
    { key: "recipients", header: "Recipients", align: "right", mono: true, cell: (c) => (c.stats.recipients || c.audience_count || 0).toLocaleString() },
    { key: "open", header: "Opened", align: "right", mono: true, cell: (c) => (c.stats.sent ? percent(ratio(c.stats.opened, c.stats.sent)) : "") },
    { key: "click", header: "Clicked", align: "right", mono: true, cell: (c) => (c.stats.sent ? percent(ratio(c.stats.clicked, c.stats.sent)) : "") },
    {
      key: "when",
      header: "When",
      cell: (c) => {
        const at = c.finished_at ?? c.started_at ?? c.scheduled_at ?? c.updated_at;
        return <time dateTime={at}>{c.status === "scheduled" && c.scheduled_at ? new Date(c.scheduled_at).toLocaleString() : timeAgo(at)}</time>;
      },
    },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (c) =>
        can("marketing.write") ? (
          <DropdownMenu
            label={`Actions for ${c.name}`}
            trigger={
              <Button variant="ghost" size="icon" aria-label={`Actions for ${c.name}`}>
                <EllipsisVertical size={16} aria-hidden />
              </Button>
            }
          >
            <MenuItem icon={<Copy size={16} aria-hidden />} onSelect={() => void duplicate(c)}>
              Duplicate
            </MenuItem>
            {c.status === "draft" && (
              <>
                <MenuSeparator />
                <MenuItem icon={<Trash2 size={16} aria-hidden />} onSelect={() => setRemoving(c)}>
                  Delete draft
                </MenuItem>
              </>
            )}
          </DropdownMenu>
        ) : null,
    },
  ];

  const empty = rows !== null && rows.length === 0 && !q && status === "all";
  return (
    <EmailShell
      title="Email"
      description="Campaigns that reach the inbox: checked before they go, paced for your domain's reputation."
      actions={
        can("marketing.write") && (
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus size={16} aria-hidden />
            New campaign
          </Button>
        )
      }
    >
      {empty ? (
        <EmptyState
          icon={Mail}
          title="Send your first campaign"
          text="Set up a sending domain, design an email from blocks, choose a saved view of contacts and send. Every campaign is checked for deliverability first."
          action={
            <div className="em-row">
              <Button onClick={() => navigate("/email/domains")}>Set up a domain</Button>
              {can("marketing.write") && (
                <Button variant="primary" onClick={() => setCreating(true)}>
                  New campaign
                </Button>
              )}
            </div>
          }
        />
      ) : (
        <>
          <div className="em-filters">
            <Input type="search" aria-label="Search campaigns" placeholder="Search campaigns" value={q} onChange={(e) => setQ(e.target.value)} />
            <Select aria-label="Status" value={status} onValueChange={setStatus} options={FILTERS} />
          </div>
          {error ? (
            <EmptyState icon={CircleAlert} title="We could not load your campaigns" text={error} action={<Button onClick={() => load(null)}>Try again</Button>} />
          ) : (
            <>
              <Table caption="Campaigns" columns={columns} rows={rows ?? []} rowId={(c) => c.id} loading={rows === null} empty={<EmptyState icon={Mail} title="No campaigns match" text="Try another search or status." />} />
              {cursor && (
                <div className="em-more">
                  <Button onClick={() => load(cursor)}>Load more</Button>
                </div>
              )}
            </>
          )}
        </>
      )}
      <NewCampaign open={creating} onClose={() => setCreating(false)} onCreated={(id) => navigate(`/email/campaigns/${id}`)} />
      <Dialog
        open={!!removing}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`Delete "${removing?.name ?? ""}"?`}
        description="The draft and its content are deleted. This cannot be undone; duplicate it first to keep a copy."
        footer={
          <>
            <Button onClick={() => setRemoving(null)}>Cancel</Button>
            <Button
              variant="danger"
              onClick={async () => {
                const c = removing!;
                setRemoving(null);
                try {
                  await email.deleteCampaign(c.id);
                  toast({ title: "Draft deleted", description: c.name, tone: "success" });
                  load(null);
                } catch (e) {
                  toast({ title: "Could not delete it", description: errorText(e), tone: "danger" });
                }
              }}
            >
              Delete draft
            </Button>
          </>
        }
      />
    </EmailShell>
  );
}

function NewCampaign({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (id: string) => void }) {
  const [name, setName] = useState("");
  const [template, setTemplate] = useState("none");
  const [templates, setTemplates] = useState<Template[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  useEffect(() => {
    if (!open) return;
    setName("");
    setTemplate("none");
    setError(undefined);
    setBusy(false);
    email
      .templates({})
      .then((p) => setTemplates(p.data))
      .catch(() => setTemplates([]));
  }, [open]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError("Give it a name.");
    setBusy(true);
    try {
      onCreated((await email.createCampaign({ name: name.trim(), template_id: template === "none" ? undefined : template })).id);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={(o) => !o && !busy && onClose()} title="New campaign" description="A draft: nothing is sent until you review it and press send.">
      <form className="em-form" onSubmit={submit} noValidate>
        <Input label="Name" autoFocus value={name} error={error} maxLength={200} placeholder="October newsletter" onChange={(e) => setName(e.target.value)} />
        <Select
          label="Start from"
          value={template}
          onValueChange={setTemplate}
          options={[{ value: "none", label: "A blank email" }, ...templates.map((t) => ({ value: t.id, label: t.name }))]}
        />
        <div className="em-form-actions">
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={busy}>
            Create draft
          </Button>
        </div>
      </form>
    </Dialog>
  );
}
