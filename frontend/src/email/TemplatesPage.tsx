// Saved email designs: the list, and the editor (the block builder with a subject and preview text, saved on demand).
import { Archive, ChevronLeft, CircleAlert, Copy, EllipsisVertical, LayoutTemplate, Plus, Undo2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useBlocker, useNavigate, useParams } from "react-router";
import { ApiError, errorText } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { timeAgo } from "../lib/device";
import { whatWentWrong } from "../lib/errors";
import { Button, Dialog, DropdownMenu, EmptyState, Input, MenuItem, Skeleton, Switch, Table, useToast, type Column } from "../ui";
import { email, type Doc, type Template } from "./api";
import { issuesByBlock, withIds } from "./blocks";
import { Builder } from "./Builder";
import { EmailShell } from "./EmailPage";
import { IssueList } from "./Issues";
import "./email.css";

export function TemplatesPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const { can } = useCan();
  const [rows, setRows] = useState<Template[] | null>(null);
  const [archived, setArchived] = useState(false);
  const [q, setQ] = useState("");
  const [error, setError] = useState<string>();
  const [creating, setCreating] = useState(false);
  const load = useCallback(() => {
    setError(undefined);
    email
      .templates({ q, archived })
      .then((p) => setRows(p.data))
      .catch((e) => setError(errorText(e)));
  }, [q, archived]);
  useEffect(() => {
    const t = setTimeout(load, q ? 250 : 0);
    return () => clearTimeout(t);
  }, [load, q]);
  const act = async (t: Template, what: "duplicate" | "archive" | "restore") => {
    try {
      if (what === "duplicate") return navigate(`/email/templates/${(await email.duplicateTemplate(t.id)).id}`);
      await email.patchTemplate(t.id, { archived: what === "archive" });
      toast({ title: what === "archive" ? "Template archived" : "Template restored", description: t.name, tone: "success" });
      load();
    } catch (e) {
      toast({ title: "That did not work", description: errorText(e), tone: "danger" });
    }
  };
  const columns: Column<Template>[] = [
    {
      key: "name",
      header: "Template",
      cell: (t) => (
        <div className="em-name">
          <Link to={`/email/templates/${t.id}`}>{t.name}</Link>
          <span className="em-sub">{t.subject || "No subject"}</span>
        </div>
      ),
    },
    { key: "blocks", header: "Blocks", align: "right", mono: true, cell: (t) => t.blocks },
    { key: "updated", header: "Updated", cell: (t) => <time dateTime={t.updated_at}>{timeAgo(t.updated_at)}</time> },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (t) =>
        can("marketing.write") ? (
          <DropdownMenu
            label={`Actions for ${t.name}`}
            trigger={
              <Button variant="ghost" size="icon" aria-label={`Actions for ${t.name}`}>
                <EllipsisVertical size={16} aria-hidden />
              </Button>
            }
          >
            <MenuItem icon={<Copy size={16} aria-hidden />} onSelect={() => void act(t, "duplicate")}>
              Duplicate
            </MenuItem>
            {t.archived ? (
              <MenuItem icon={<Undo2 size={16} aria-hidden />} onSelect={() => void act(t, "restore")}>
                Restore
              </MenuItem>
            ) : (
              <MenuItem icon={<Archive size={16} aria-hidden />} onSelect={() => void act(t, "archive")}>
                Archive
              </MenuItem>
            )}
          </DropdownMenu>
        ) : null,
    },
  ];
  return (
    <EmailShell
      title="Email"
      description="Reusable designs built from blocks: responsive, readable in dark mode, with a plain text part."
      actions={
        can("marketing.write") && (
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus size={16} aria-hidden />
            New template
          </Button>
        )
      }
    >
      <div className="em-filters">
        <Input type="search" aria-label="Search templates" placeholder="Search templates" value={q} onChange={(e) => setQ(e.target.value)} />
        <Switch label="Archived" checked={archived} onCheckedChange={setArchived} />
      </div>
      {error ? (
        <EmptyState icon={CircleAlert} title="We could not load your templates" text={error} action={<Button onClick={load}>Try again</Button>} />
      ) : (
        <Table
          caption="Templates"
          columns={columns}
          rows={rows ?? []}
          rowId={(t) => t.id}
          loading={rows === null}
          empty={
            <EmptyState
              icon={LayoutTemplate}
              title={archived ? "Nothing archived" : q ? "No templates match" : "No templates yet"}
              text={archived ? "Archived templates wait here until you restore them." : "A template starts with a heading, some text and a button you can change. Campaigns copy it, so editing it later changes no campaign."}
              action={!archived && !q && can("marketing.write") ? <Button onClick={() => setCreating(true)}>New template</Button> : undefined}
            />
          }
        />
      )}
      <NewTemplate open={creating} onClose={() => setCreating(false)} onCreated={(id) => navigate(`/email/templates/${id}`)} />
    </EmailShell>
  );
}

function NewTemplate({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (id: string) => void }) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  useEffect(() => {
    if (open) (setName(""), setError(undefined), setBusy(false));
  }, [open]);
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError("Give it a name.");
    setBusy(true);
    try {
      onCreated((await email.createTemplate({ name: name.trim() })).id);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }
  return (
    <Dialog open={open} onOpenChange={(o) => !o && !busy && onClose()} title="New template">
      <form className="em-form" onSubmit={submit} noValidate>
        <Input label="Name" autoFocus value={name} error={error} maxLength={200} placeholder="Monthly newsletter" onChange={(e) => setName(e.target.value)} />
        <div className="em-form-actions">
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button type="submit" variant="primary" loading={busy}>
            Create
          </Button>
        </div>
      </form>
    </Dialog>
  );
}

type Draft = { name: string; subject: string; preheader: string; document: Doc };

export function TemplateEditor() {
  const { id = "" } = useParams();
  const toast = useToast();
  const { can } = useCan();
  const readOnly = !can("marketing.write");
  const [draft, setDraft] = useState<Draft | null>(null);
  const saved = useRef("");
  const [, setPast] = useState<Draft[]>([]); // what Ctrl+Z goes back to
  const [error, setError] = useState<string>();
  const [fields, setFields] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    email
      .template(id)
      .then((t) => {
        const d = { name: t.name, subject: t.subject, preheader: t.preheader, document: withIds(t.document) };
        saved.current = JSON.stringify(d);
        setDraft(d);
      })
      .catch((e) => setError(e instanceof ApiError && e.status === 404 ? "This template does not exist." : errorText(e)));
  }, [id]);
  const dirty = !!draft && JSON.stringify(draft) !== saved.current;
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname);
  useEffect(() => {
    if (!dirty) return;
    const stop = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", stop);
    return () => window.removeEventListener("beforeunload", stop);
  }, [dirty]);
  const edit = (patch: Partial<Draft>) =>
    setDraft((d) => {
      if (d) setPast((p) => [...p.slice(-49), d]);
      return d ? { ...d, ...patch } : d;
    });
  const save = useCallback(async () => {
    if (!draft) return;
    setBusy(true);
    try {
      await email.patchTemplate(id, draft);
      saved.current = JSON.stringify(draft);
      setFields({});
      setDraft({ ...draft });
      toast({ title: "Template saved", tone: "success" });
    } catch (e) {
      setFields(e instanceof ApiError && e.fields ? e.fields : {});
      toast({ title: "Not saved", description: whatWentWrong(e), tone: "danger" });
    } finally {
      setBusy(false);
    }
  }, [draft, id, toast]);
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = (e.target as HTMLElement).closest("input, textarea, [contenteditable]");
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        void save();
      } else if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "z" && !e.shiftKey && !typing) {
        e.preventDefault();
        setPast((p) => {
          if (p.length) setDraft(p[p.length - 1]!);
          return p.slice(0, -1);
        });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [save]);
  useEffect(() => {
    if (draft) document.title = `${draft.name} | Templates | go-high`;
  }, [draft]);

  if (error)
    return (
      <div className="sh-page em-page">
        <EmptyState icon={CircleAlert} title="We could not open this template" text={error} action={<Link to="/email/templates">Back to templates</Link>} />
      </div>
    );
  if (!draft)
    return (
      <div className="sh-page em-page" aria-busy>
        <Skeleton className="em-skel-title" />
        <Skeleton className="em-skel-block" />
      </div>
    );
  const issues = issuesByBlock(draft.document, fields);
  return (
    <div className="sh-page em-page">
      <header className="em-head">
        <Link to="/email/templates" className="em-back">
          <ChevronLeft size={16} aria-hidden />
          Templates
        </Link>
        <div className="em-head-row">
          <div className="em-head-title">
            <h1>{draft.name}</h1>
            {dirty && <span className="em-muted">Unsaved changes</span>}
          </div>
          {!readOnly && (
            <Button variant="primary" onClick={() => void save()} loading={busy} disabled={!dirty} title="Ctrl+S">
              Save template
            </Button>
          )}
        </div>
      </header>
      <section className="em-card em-card-wide" aria-label="Template">
        <div className="em-grid em-grid-3">
          <Input label="Name" value={draft.name} maxLength={200} disabled={readOnly} error={fields.name} onChange={(e) => edit({ name: e.target.value })} />
          <Input label="Subject" value={draft.subject} maxLength={500} disabled={readOnly} error={fields.subject} onChange={(e) => edit({ subject: e.target.value })} />
          <Input label="Preview text" value={draft.preheader} maxLength={300} disabled={readOnly} error={fields.preheader} onChange={(e) => edit({ preheader: e.target.value })} />
        </div>
        {issues.other.length > 0 && <IssueList issues={issues.other.map((m) => ({ level: "error", code: "field", message: m }))} />}
        <Builder doc={draft.document} onChange={(d) => edit({ document: d })} subject={draft.subject} preheader={draft.preheader} issues={issues.blocks} readOnly={readOnly} />
      </section>
      <Dialog
        open={blocker.state === "blocked"}
        onOpenChange={(o) => !o && blocker.reset?.()}
        title="Leave without saving?"
        description="Your changes to this template are not saved."
        footer={
          <>
            <Button onClick={() => blocker.reset?.()}>Stay</Button>
            <Button variant="danger" onClick={() => blocker.proceed?.()}>
              Leave
            </Button>
          </>
        }
      />
    </div>
  );
}
