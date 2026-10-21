import { Archive, CircleAlert, EllipsisVertical, LockKeyhole, Pause, Play, Plus, Rocket, Workflow } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { ApiError, errorText } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { timeAgo } from "../lib/device";
import { session } from "../lib/session";
import { useStore } from "../lib/store";
import { useMediaQuery } from "../lib/useMediaQuery";
import { PageHeader } from "../shell/PageHeader";
import { TYPING } from "../shell/useShortcuts";
import { Badge, Button, Dialog, DropdownMenu, EmptyState, Input, MenuItem, MenuSeparator, Select, Skeleton, Table, useToast, type Column } from "../ui";
import { workflows, type Status, type WorkflowRow } from "./api";
import { eventLabel } from "./graph";
import { dateTime, enrolled, StatusBadge, versionText } from "./parts";
import { PublishDialog } from "./PublishDialog";
import { inChord, onSurface } from "./keys";
import { STARTERS, type Starter } from "./starters";
import "./workflows.css";

const STATUSES = [
  { value: "all", label: "All but archived" },
  { value: "published", label: "Live" },
  { value: "paused", label: "Paused" },
  { value: "draft", label: "Draft" },
  { value: "archived", label: "Archived" },
];

/** Live, paused or ready to publish: what the row's menu offers. */
export function useWorkflowActions(onChanged: (row: WorkflowRow) => void) {
  const toast = useToast();
  const [publishing, setPublishing] = useState<WorkflowRow | null>(null);
  const [archiving, setArchiving] = useState<WorkflowRow | null>(null);
  const [busy, setBusy] = useState(false);

  const flip = async (w: WorkflowRow) => {
    try {
      const row = w.status === "paused" ? await workflows.resume(w.id) : await workflows.pause(w.id);
      onChanged(row);
      toast({
        title: row.status === "paused" ? "Workflow paused" : "Workflow resumed",
        description: row.status === "paused" ? "No new records enter, and runs in flight wait where they are." : "Records enter again, and runs in flight carry on.",
        tone: "success",
      });
    } catch (e) {
      toast({ title: w.status === "paused" ? "Could not resume" : "Could not pause", description: errorText(e), tone: "danger" });
    }
  };

  const dialogs = (
    <>
      {publishing && (
        <PublishDialog
          workflow={publishing}
          open
          onOpenChange={(o) => !o && setPublishing(null)}
          onPublished={(row, plan) => {
            onChanged(row);
            toast({ title: `Version ${row.published_version} is live`, description: plan.moved || plan.exited ? `${plan.moved ?? 0} runs moved, ${plan.exited ?? 0} exited.` : row.name, tone: "success" });
          }}
          onInvalid={(e) => toast({ title: "This version cannot be published", description: Object.values(e.fields ?? {})[0] ?? e.message, tone: "danger" })}
        />
      )}
      <Dialog
        open={!!archiving}
        onOpenChange={(o) => !o && !busy && setArchiving(null)}
        title={`Archive "${archiving?.name ?? ""}"?`}
        description="It stops for good: no record enters it again. Its versions, runs and traces are kept and stay readable under Archived."
        footer={
          <>
            <Button onClick={() => setArchiving(null)} disabled={busy}>
              Cancel
            </Button>
            {archiving?.status === "published" && (
              <Button
                disabled={busy}
                onClick={() => {
                  const w = archiving;
                  setArchiving(null);
                  void flip(w);
                }}
              >
                Pause instead
              </Button>
            )}
            <Button
              variant="danger"
              loading={busy}
              onClick={async () => {
                const w = archiving!;
                setBusy(true);
                try {
                  await workflows.archive(w.id);
                  onChanged({ ...w, status: "archived", runs: { ...w.runs, running: 0, waiting: 0 } });
                  toast({ title: "Workflow archived", description: w.name, tone: "success" });
                  setArchiving(null);
                } catch (e) {
                  toast({ title: "Could not archive", description: errorText(e), tone: "danger" });
                } finally {
                  setBusy(false);
                }
              }}
            >
              Archive
            </Button>
          </>
        }
      >
        {archiving && enrolled(archiving) > 0 ? (
          <p className="wf-alert" data-tone="warning">
            <CircleAlert size={16} aria-hidden />
            {enrolled(archiving).toLocaleString()} {enrolled(archiving) === 1 ? "record is" : "records are"} in it now. {enrolled(archiving) === 1 ? "Its run is" : "Their runs are"} cancelled, and this cannot be undone. Pausing keeps them where they are instead.
          </p>
        ) : (
          <p className="wf-muted">No record is in it now, so no run is cancelled.</p>
        )}
      </Dialog>
    </>
  );
  return { flip, publish: setPublishing, archive: setArchiving, dialogs };
}

export function WorkflowsPage() {
  const navigate = useNavigate();
  const { can, ready } = useCan();
  const phone = useMediaQuery("(max-width: 767px)");
  const [rows, setRows] = useState<WorkflowRow[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<{ text: string; denied: boolean }>();
  const [q, setQ] = useState("");
  const [status, setStatus] = useState("all");
  const [active, setActive] = useState<string | null>(null);
  const [creating, setCreating] = useState<Starter | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const search = useRef<HTMLInputElement>(null);

  const load = useCallback(
    (after: string | null) => {
      setError(undefined);
      if (after) setLoadingMore(true);
      workflows
        .list({ q: q.trim() || undefined, status: status === "all" ? undefined : (status as Status), cursor: after })
        .then((page) => {
          setRows((old) => (after ? [...(old ?? []), ...page.data] : page.data));
          setCursor(page.next_cursor);
        })
        .catch((e) => setError({ text: errorText(e), denied: e instanceof ApiError && e.status === 403 }))
        .finally(() => setLoadingMore(false));
    },
    [q, status],
  );
  useEffect(() => {
    const t = setTimeout(() => load(null), q ? 250 : 0);
    return () => clearTimeout(t);
  }, [load, q]);

  const changed = (row: WorkflowRow) => setRows((old) => (old ?? []).flatMap((w) => (w.id !== row.id ? [w] : status !== "archived" && row.status === "archived" ? [] : [{ ...w, ...row }])));
  const actions = useWorkflowActions(changed);
  const canWrite = can("workflows.write");
  const canPublish = can("workflows.publish");

  // j and k walk the rows, Enter opens one, / searches, n starts a new workflow
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey || inChord(e) || (e.target instanceof Element && e.target.closest(TYPING)) || document.querySelector('[role="dialog"]')) return;
      const list = rows ?? [];
      const at = list.findIndex((w) => w.id === active);
      if (e.key === "j" || e.key === "k") {
        e.preventDefault();
        const next = list[Math.max(0, Math.min(list.length - 1, at + (e.key === "j" ? 1 : -1)))] ?? list[0];
        if (next) {
          setActive(next.id);
          document.querySelector<HTMLElement>(`[data-wf-row="${next.id}"]`)?.scrollIntoView({ block: "nearest" });
        }
      } else if (e.key === "Enter" && at >= 0 && onSurface(e, "body")) {
        e.preventDefault();
        navigate(`/automations/${list[at]!.id}`);
      } else if (e.key === "/") {
        e.preventDefault();
        search.current?.focus();
      } else if (e.key === "n" && canWrite) {
        e.preventDefault();
        setCreating(STARTERS[STARTERS.length - 1]!);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [rows, active, navigate, canWrite]);

  const menu = (w: WorkflowRow) =>
    w.status === "archived" || !(canPublish || canWrite) ? null : (
      <DropdownMenu
        label={`Actions for ${w.name}`}
        trigger={
          <Button variant="ghost" size="icon" aria-label={`Actions for ${w.name}`}>
            <EllipsisVertical size={16} aria-hidden />
          </Button>
        }
      >
        <MenuItem onSelect={() => navigate(`/automations/${w.id}`)}>Open the builder</MenuItem>
        <MenuItem onSelect={() => navigate(`/automations/${w.id}?tab=runs`)}>See its runs</MenuItem>
        {canPublish && (
          <>
            <MenuSeparator />
            {w.latest_version !== null && (w.status === "draft" || w.has_draft_changes) && (
              <MenuItem icon={<Rocket size={16} aria-hidden />} onSelect={() => actions.publish(w)}>
                Publish version {w.latest_version}
              </MenuItem>
            )}
            {w.status === "published" && (
              <MenuItem icon={<Pause size={16} aria-hidden />} onSelect={() => void actions.flip(w)}>
                Pause
              </MenuItem>
            )}
            {w.status === "paused" && (
              <MenuItem icon={<Play size={16} aria-hidden />} onSelect={() => void actions.flip(w)}>
                Resume
              </MenuItem>
            )}
            <MenuSeparator />
            <MenuItem icon={<Archive size={16} aria-hidden />} onSelect={() => actions.archive(w)}>
              Archive
            </MenuItem>
          </>
        )}
      </DropdownMenu>
    );

  const counts = (w: WorkflowRow) => (
    <span className="wf-counts">
      <span>
        <strong className="mono">{enrolled(w).toLocaleString()}</strong> in it now
      </span>
      {(w.runs.completed ?? 0) + (w.runs.exited ?? 0) > 0 && <span className="wf-muted">{((w.runs.completed ?? 0) + (w.runs.exited ?? 0)).toLocaleString()} done</span>}
      {(w.runs.failed ?? 0) > 0 && (
        <Link to={`/automations/${w.id}?tab=runs&status=failed`} className="wf-failed">
          {w.runs.failed!.toLocaleString()} failed
        </Link>
      )}
    </span>
  );

  const columns: Column<WorkflowRow>[] = [
    {
      key: "name",
      header: "Name",
      cell: (w) => (
        <div className="wf-name">
          <Link to={`/automations/${w.id}`} data-wf-row={w.id}>
            {w.name}
          </Link>
          <span className="wf-sub">
            {w.trigger_event ? eventLabel(w.trigger_event) : "Not published yet"}
            {w.folder ? ` · ${w.folder}` : ""}
          </span>
        </div>
      ),
    },
    {
      key: "status",
      header: "Status",
      cell: (w) => (
        <span className="wf-badges">
          <StatusBadge status={w.status} />
          {w.has_draft_changes && w.status !== "draft" && <Badge tone="accent">Unpublished changes</Badge>}
        </span>
      ),
    },
    { key: "enrolled", header: "Enrolled", cell: counts },
    { key: "version", header: "Version", cell: (w) => <span className="wf-sub-strong">{versionText(w)}</span> },
    { key: "updated", header: "Updated", cell: (w) => <time dateTime={w.updated_at} title={dateTime(w.updated_at)}>{timeAgo(w.updated_at)}</time> },
    { key: "actions", header: "", align: "right", cell: menu },
  ];

  const filtered = !!q || status !== "all";
  const empty = rows !== null && rows.length === 0 && !filtered;
  if (error?.denied)
    return (
      <div className="sh-page">
        <PageHeader title="Automations" />
        <EmptyState icon={LockKeyhole} title="You do not have access to automations" text="Ask a workspace admin for a role that can read workflows." />
      </div>
    );

  return (
    <div className="sh-page wf-page">
      <PageHeader
        title="Automations"
        description="Workflows that follow up, route leads and update records while you sleep."
        actions={
          ready && canWrite ? (
            <Button variant="primary" onClick={() => setCreating(STARTERS[STARTERS.length - 1]!)} aria-keyshortcuts="n">
              <Plus size={16} aria-hidden />
              New workflow
            </Button>
          ) : null
        }
      />
      {empty ? (
        <EmptyState
          icon={Workflow}
          title="Automate your first follow-up"
          text="A workflow starts when something happens to a record (a form is sent, a deal moves, a tag is added) and walks it through steps: tasks, messages, waits and checks. Start from one of these and change it; test it on a real contact before it goes live."
          action={
            canWrite ? (
              <div className="wf-starters">
                {STARTERS.map((s) => (
                  <button key={s.id} type="button" className="wf-starter" onClick={() => setCreating(s)}>
                    <strong>{s.name}</strong>
                    <span>{s.text}</span>
                  </button>
                ))}
              </div>
            ) : undefined
          }
        />
      ) : (
        <>
          <div className="wf-filters">
            <Input ref={search} type="search" aria-label="Search workflows" placeholder="Search workflows" value={q} onChange={(e) => setQ(e.target.value)} aria-keyshortcuts="/" />
            <Select aria-label="Status" value={status} onValueChange={setStatus} options={STATUSES} />
          </div>
          {error ? (
            <EmptyState icon={CircleAlert} title="We could not load your workflows" text={error.text} action={<Button onClick={() => load(null)}>Try again</Button>} />
          ) : phone ? (
            <ul className="wf-cards" aria-label="Workflows" aria-busy={rows === null}>
              {rows === null
                ? [0, 1, 2].map((i) => (
                    <li key={i} className="wf-card">
                      <Skeleton style={{ height: 16, width: "60%" }} />
                      <Skeleton style={{ height: 12, width: "40%" }} />
                    </li>
                  ))
                : rows.map((w) => (
                    <li key={w.id} className="wf-card" data-active={w.id === active || undefined}>
                      <div className="wf-card-top">
                        <div className="wf-name">
                          <Link to={`/automations/${w.id}`} data-wf-row={w.id}>
                            {w.name}
                          </Link>
                          <span className="wf-sub">{w.trigger_event ? eventLabel(w.trigger_event) : "Not published yet"}</span>
                        </div>
                        {menu(w)}
                      </div>
                      <div className="wf-card-meta">
                        <span className="wf-badges">
                          <StatusBadge status={w.status} />
                          {w.has_draft_changes && w.status !== "draft" && <Badge tone="accent">Unpublished changes</Badge>}
                        </span>
                        {counts(w)}
                      </div>
                    </li>
                  ))}
              {rows?.length === 0 && <li className="wf-muted wf-card-empty">No workflows match. Try another search or status.</li>}
            </ul>
          ) : (
            <Table
              caption="Workflows"
              columns={columns}
              rows={rows ?? []}
              rowId={(w) => w.id}
              loading={rows === null}
              activeId={active}
              onRowClick={(w) => navigate(`/automations/${w.id}`)}
              empty={<EmptyState icon={Workflow} title="No workflows match" text="Try a different search or status." />}
            />
          )}
          {cursor && !error && (
            <div className="wf-more">
              <Button onClick={() => load(cursor)} loading={loadingMore}>
                Load more
              </Button>
            </div>
          )}
        </>
      )}
      <NewWorkflow starter={creating} onClose={() => setCreating(null)} onCreated={(id) => navigate(`/automations/${id}`)} />
      {actions.dialogs}
    </div>
  );
}

function NewWorkflow({ starter, onClose, onCreated }: { starter: Starter | null; onClose: () => void; onCreated: (id: string) => void }) {
  const [name, setName] = useState("");
  const [pick, setPick] = useState(STARTERS[0]!.id);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  useEffect(() => {
    if (starter) {
      setPick(starter.id);
      setName(starter.id === "blank" ? "" : starter.name);
      setError(undefined);
      setBusy(false);
    }
  }, [starter]);
  const chosen = STARTERS.find((s) => s.id === pick)!;
  const who = useStore(session);
  const me = who.status === "ready" ? who.me.user.id : null;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!name.trim()) return setError("Give it a name.");
    setBusy(true);
    try {
      const made = await workflows.create({ name: name.trim(), graph: chosen.graph(me), note: chosen.id === "blank" ? undefined : `From the starter "${chosen.name}"` });
      onCreated(made.id);
    } catch (err) {
      setError(errorText(err));
      setBusy(false);
    }
  }
  return (
    <Dialog open={!!starter} onOpenChange={(o) => !o && !busy && onClose()} title="New workflow" description={chosen.text}>
      <form className="wf-new" onSubmit={submit} noValidate>
        <Input label="Name" autoFocus data-autofocus value={name} error={error} onChange={(e) => setName(e.target.value)} placeholder="Follow up quote requests" maxLength={200} />
        <Select label="Start from" value={pick} onValueChange={(v) => {
          const s = STARTERS.find((x) => x.id === v)!;
          setPick(v);
          if (!name.trim() || STARTERS.some((x) => x.name === name)) setName(v === "blank" ? "" : s.name);
        }} options={STARTERS.map((s) => ({ value: s.id, label: s.name }))} />
        <p className="wf-muted">It starts as a draft: nothing runs until you publish it.</p>
        <div className="wf-dialog-actions">
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
