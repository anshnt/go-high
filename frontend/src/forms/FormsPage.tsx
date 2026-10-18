import { ClipboardList, CircleAlert, Copy, EllipsisVertical, Link2, Plus, Trash2, Undo2 } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { errorText } from "../lib/api";
import { timeAgo } from "../lib/device";
import { PageHeader } from "../shell/PageHeader";
import { Badge, Button, Dialog, DropdownMenu, EmptyState, Input, MenuItem, MenuSeparator, Select, Switch, Table, useToast, type Column, type Tone } from "../ui";
import { forms, shareLink, type FormRow, type Kind, type Status } from "./api";
import "./forms.css";

export const KIND_LABEL: Record<Kind, string> = { form: "Form", survey: "Survey", quiz: "Quiz" };
const KIND_TEXT: Record<Kind, string> = {
  form: "Collects leads and details, and creates a contact.",
  survey: "Asks questions, with branching, and summarizes the answers.",
  quiz: "Scores answers and shows a result by score band.",
};
export const STATUS_TONE: Record<Status, Tone> = { draft: "neutral", published: "success", closed: "warning" };
export const STATUS_LABEL: Record<Status, string> = { draft: "Draft", published: "Live", closed: "Closed" };
const percent = (x: number | null) => (x === null ? "None yet" : `${Math.round(x * 100)}%`);
const STATUSES = [{ value: "all", label: "All statuses" }, { value: "published", label: "Live" }, { value: "draft", label: "Draft" }, { value: "closed", label: "Closed" }];

export function FormsPage() {
  const navigate = useNavigate();
  const toast = useToast();
  const [rows, setRows] = useState<FormRow[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string>();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");
  const [trashed, setTrashed] = useState(false);
  const [creating, setCreating] = useState<Kind | null>(null);
  const [removing, setRemoving] = useState<FormRow | null>(null);

  const load = useCallback(
    (after: string | null) => {
      setError(undefined);
      forms
        .list({ q, trashed, status: status === "all" ? undefined : status, cursor: after })
        .then((page) => {
          setRows((old) => (after ? [...(old ?? []), ...page.data] : page.data));
          setCursor(page.next_cursor);
        })
        .catch((e) => setError(errorText(e)));
    },
    [q, status, trashed],
  );
  useEffect(() => {
    const t = setTimeout(() => load(null), q ? 250 : 0); // the search waits for a pause in typing
    return () => clearTimeout(t);
  }, [load, q]);

  async function copy(f: FormRow) {
    await navigator.clipboard?.writeText(shareLink(f.public_key));
    toast({ title: "Link copied", description: shareLink(f.public_key), tone: "success" });
  }
  async function duplicate(f: FormRow) {
    try {
      const copy = await forms.duplicate(f.id);
      navigate(`/forms/${copy.id}`);
    } catch (e) {
      toast({ title: "Could not duplicate", description: errorText(e), tone: "danger" });
    }
  }
  async function restore(f: FormRow) {
    try {
      await forms.restore(f.id);
      toast({ title: "Form restored", description: f.name, tone: "success" });
      load(null);
    } catch (e) {
      toast({ title: "Could not restore", description: errorText(e), tone: "danger" });
    }
  }

  const columns: Column<FormRow>[] = [
    {
      key: "name",
      header: "Name",
      cell: (f) => (
        <div className="fm-name">
          {trashed ? <strong>{f.name}</strong> : <Link to={`/forms/${f.id}`}>{f.name}</Link>}
          <span className="fm-sub mono">{f.slug}</span>
        </div>
      ),
    },
    { key: "kind", header: "Type", cell: (f) => <Badge>{KIND_LABEL[f.kind]}</Badge> },
    {
      key: "status",
      header: "Status",
      cell: (f) => (
        <span className="fm-status">
          <Badge tone={STATUS_TONE[f.status]}>{STATUS_LABEL[f.status]}</Badge>
          {f.has_draft_changes && <Badge tone="accent">Unpublished changes</Badge>}
        </span>
      ),
    },
    { key: "responses", header: "Responses", align: "right", mono: true, cell: (f) => f.responses.toLocaleString() },
    { key: "rate", header: "Completion", align: "right", mono: true, cell: (f) => percent(f.completion_rate) },
    { key: "updated", header: "Updated", cell: (f) => <time dateTime={f.updated_at}>{timeAgo(f.updated_at)}</time> },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (f) => (
        <DropdownMenu
          label={`Actions for ${f.name}`}
          trigger={
            <Button variant="ghost" size="icon" aria-label={`Actions for ${f.name}`}>
              <EllipsisVertical size={16} aria-hidden />
            </Button>
          }
        >
          {trashed ? (
            <MenuItem icon={<Undo2 size={16} aria-hidden />} onSelect={() => void restore(f)}>
              Restore
            </MenuItem>
          ) : (
            <>
              <MenuItem icon={<Copy size={16} aria-hidden />} onSelect={() => void duplicate(f)}>
                Duplicate
              </MenuItem>
              {f.status !== "draft" && (
                <MenuItem icon={<Link2 size={16} aria-hidden />} onSelect={() => void copy(f)}>
                  Copy link
                </MenuItem>
              )}
              <MenuSeparator />
              <MenuItem icon={<Trash2 size={16} aria-hidden />} onSelect={() => setRemoving(f)}>
                Move to trash
              </MenuItem>
            </>
          )}
        </DropdownMenu>
      ),
    },
  ];

  const empty = rows !== null && rows.length === 0 && !q && status === "all" && !trashed;
  return (
    <div className="sh-page fm-page">
      <PageHeader
        title="Forms"
        description="Forms, surveys and quizzes that turn visitors into contacts."
        actions={
          <Button variant="primary" onClick={() => setCreating("form")}>
            <Plus size={16} aria-hidden />
            New form
          </Button>
        }
      />
      {empty ? (
        <EmptyState
          icon={ClipboardList}
          title="Build your first form"
          text="Start from a working example and change it: a lead form creates a contact, a quiz scores the answers, a survey branches on what people say."
          action={
            <div className="fm-starters">
              {(Object.keys(KIND_LABEL) as Kind[]).map((k) => (
                <button key={k} type="button" className="fm-starter" onClick={() => setCreating(k)}>
                  <strong>{KIND_LABEL[k]}</strong>
                  <span>{KIND_TEXT[k]}</span>
                </button>
              ))}
            </div>
          }
        />
      ) : (
        <>
          <div className="fm-filters">
            <Input type="search" aria-label="Search forms" placeholder="Search forms" value={q} onChange={(e) => setQ(e.target.value)} />
            <Select value={status} onValueChange={setStatus} options={STATUSES} />
            <Switch label="Trash" checked={trashed} onCheckedChange={setTrashed} />
          </div>
          {error ? (
            <EmptyState icon={CircleAlert} title="We could not load your forms" text={error} action={<Button onClick={() => load(null)}>Try again</Button>} />
          ) : (
            <>
              <Table
                caption={trashed ? "Forms in the trash" : "Forms"}
                columns={columns}
                rows={rows ?? []}
                rowId={(f) => f.id}
                loading={rows === null}
                empty={<EmptyState icon={ClipboardList} title={trashed ? "The trash is empty" : "No forms match"} text={trashed ? "A form you move to the trash stays here, with its responses, until you restore it." : "Try a different search or status."} />}
              />
              {cursor && (
                <div className="fm-more">
                  <Button onClick={() => load(cursor)}>Load more</Button>
                </div>
              )}
            </>
          )}
        </>
      )}
      <NewForm kind={creating} onClose={() => setCreating(null)} onCreated={(id) => navigate(`/forms/${id}`)} />
      <Dialog
        open={!!removing}
        onOpenChange={(open) => !open && setRemoving(null)}
        title={`Move "${removing?.name ?? ""}" to the trash?`}
        description={`Its link stops working now. ${removing?.responses ? `Its ${removing.responses.toLocaleString()} response${removing.responses === 1 ? "" : "s"} are kept.` : ""} You can restore it from the trash.`}
        footer={
          <>
            <Button onClick={() => setRemoving(null)}>Cancel</Button>
            <Button
              variant="danger"
              onClick={async () => {
                const f = removing!;
                setRemoving(null);
                try {
                  await forms.remove(f.id);
                  toast({ title: "Moved to the trash", description: f.name, tone: "success" });
                  load(null);
                } catch (e) {
                  toast({ title: "Could not move it", description: errorText(e), tone: "danger" });
                }
              }}
            >
              Move to trash
            </Button>
          </>
        }
      />
    </div>
  );
}

function NewForm({ kind, onClose, onCreated }: { kind: Kind | null; onClose: () => void; onCreated: (id: string) => void }) {
  const [name, setName] = useState("");
  const [type, setType] = useState<Kind>("form");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  useEffect(() => {
    if (kind) {
      setType(kind);
      setName("");
      setError(undefined);
    }
  }, [kind]);

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError("Give it a name.");
    setBusy(true);
    try {
      onCreated((await forms.create({ name: name.trim(), kind: type })).id);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }
  return (
    <Dialog open={!!kind} onOpenChange={(open) => !open && !busy && onClose()} title="New form" description={KIND_TEXT[type]}>
      <form className="fm-new" onSubmit={submit} noValidate>
        <Input label="Name" autoFocus value={name} error={error} onChange={(e) => setName(e.target.value)} placeholder="Get a quote" maxLength={200} />
        <Select label="Type" value={type} onValueChange={(v) => setType(v as Kind)} options={(Object.keys(KIND_LABEL) as Kind[]).map((k) => ({ value: k, label: KIND_LABEL[k] }))} />
        <div className="fm-new-actions">
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
