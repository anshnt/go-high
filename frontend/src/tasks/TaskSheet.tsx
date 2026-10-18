import { Lock } from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent } from "react";
import { errorText } from "../lib/api";
import { dueDate, dueIso, fromInputDate, toInputDate, toInputTime } from "../lib/dates";
import { presetOf, ruleFor, type Preset } from "../lib/recurrence";
import { useMe } from "../lib/session";
import { createTask, deleteTask, getTask, listTasks, PRIORITY_LABEL, touch, updateTask, useMembers, type Priority, type Task, type TaskInput } from "../lib/tasks";
import { Button, Checkbox, Dialog, Input, Select, Sheet, Skeleton, Textarea, useToast } from "../ui";
import { RecordPicker, type Linked } from "./RecordPicker";
import { RecurrencePicker } from "./RecurrencePicker";
import { useToggleTask } from "./useToggleTask";

export type Target = { kind: "new"; preset?: TaskInput & { record?: Linked | null } } | { kind: "edit"; id: string };
export const targetKey = (t: Target) => (t.kind === "edit" ? t.id : "new");

type Draft = {
  title: string;
  notes: string;
  date: string;
  time: string;
  assignee: string;
  priority: Priority;
  preset: Preset;
  recurrence: string | null;
  dependsOn: string;
  record: Linked | null;
};

const NONE = "none";
const BLANK: Draft = { title: "", notes: "", date: "", time: "", assignee: NONE, priority: "none", preset: "none", recurrence: null, dependsOn: NONE, record: null };

function draftOf(t: TaskInput & { record?: Linked | null }): Draft {
  const due = t.due_at ? dueDate({ due_at: t.due_at, all_day: !!t.all_day }) : null;
  return {
    title: t.title ?? "",
    notes: t.notes ?? "",
    date: due ? toInputDate(due) : "",
    time: due && !t.all_day ? toInputTime(due) : "",
    assignee: t.assignee_id ?? NONE,
    priority: t.priority ?? "none",
    preset: presetOf(t.recurrence ?? null, due),
    recurrence: t.recurrence ?? null,
    dependsOn: t.depends_on_task_id ?? NONE,
    record: t.record ?? null,
  };
}

/** The due date a draft means: a date alone is all day, a date with a time is that moment. */
function dueOf(d: Draft): { date: Date; allDay: boolean } | null {
  const date = fromInputDate(d.date);
  if (!date) return null;
  const [h, m] = d.time ? d.time.split(":").map(Number) : [0, 0];
  if (d.time) date.setHours(h!, m!);
  return { date, allDay: !d.time };
}

const ruleOf = (d: Draft) => (d.preset === "custom" ? d.recurrence : ruleFor(d.preset, dueOf(d)?.date ?? null));

/** The detail of one task, or a new one, in a side sheet (a bottom sheet on a phone). */
export function TaskSheet({ target, onClose }: { target: Target; onClose: () => void }) {
  const toast = useToast();
  const toggle = useToggleTask();
  const members = useMembers();
  const myId = useMe()?.user.id;
  const [task, setTask] = useState<Task | null>(null);
  const [draft, setDraft] = useState<Draft | null>(target.kind === "new" ? { ...BLANK, ...draftOf(target.preset ?? {}) } : null);
  const [others, setOthers] = useState<Task[]>([]);
  const [error, setError] = useState<string>();
  const [fieldError, setFieldError] = useState<Partial<Record<"title" | "date", string>>>({});
  const [busy, setBusy] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const id = target.kind === "edit" ? target.id : null;

  useEffect(() => {
    if (!id) return;
    let alive = true;
    getTask(id)
      .then((t) => {
        if (!alive) return;
        setTask(t);
        setDraft(draftOf(t));
      })
      .catch((e) => alive && setError(errorText(e)));
    return () => {
      alive = false;
    };
  }, [id]);

  useEffect(() => {
    let alive = true;
    listTasks({ status: "open" })
      .then((list) => alive && setOthers(list))
      .catch(() => {});
    return () => {
      alive = false;
    };
  }, []);

  const set = (patch: Partial<Draft>) => setDraft((d) => d && { ...d, ...patch });
  const memberOptions = useMemo(
    () => [{ value: NONE, label: "Unassigned" }, ...members.map((m) => ({ value: m.id, label: m.id === myId ? `${m.name} (you)` : m.name }))],
    [members, myId],
  );
  const dependencyOptions = useMemo(() => {
    const open = others.filter((t) => t.id !== id);
    const current = task?.depends_on && !open.some((t) => t.id === task.depends_on!.id) ? [{ value: task.depends_on.id, label: task.depends_on.title }] : [];
    return [{ value: NONE, label: "Nothing" }, ...current, ...open.map((t) => ({ value: t.id, label: t.title }))];
  }, [others, id, task]);

  async function save(e?: FormEvent) {
    e?.preventDefault();
    if (!draft || busy) return;
    const errors: typeof fieldError = {};
    if (!draft.title.trim()) errors.title = "Give the task a title.";
    const due = dueOf(draft);
    const rule = ruleOf(draft);
    if (rule && !due) errors.date = "A repeating task needs a due date.";
    setFieldError(errors);
    if (Object.keys(errors).length) return;
    const body = {
      title: draft.title.trim(),
      notes: draft.notes,
      due_at: due ? dueIso(due.date, due.allDay) : null,
      all_day: due?.allDay ?? false,
      assignee_id: draft.assignee === NONE ? null : draft.assignee,
      priority: draft.priority,
      record_id: draft.record?.id ?? null,
      recurrence: rule,
      depends_on_task_id: draft.dependsOn === NONE ? null : draft.dependsOn,
    };
    setBusy(true);
    setError(undefined);
    try {
      if (id) await updateTask(id, body);
      else await createTask(body);
      touch();
      onClose();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  async function remove() {
    if (!task) return;
    setBusy(true);
    try {
      await deleteTask(task.id);
      touch();
      setConfirmDelete(false);
      onClose();
      const { title, notes, due_at, all_day, assignee_id, priority, record_id, recurrence } = task;
      toast({
        title: "Task deleted",
        description: title,
        action: {
          label: "Undo",
          onClick: () =>
            createTask({ title, notes, due_at, all_day, assignee_id, priority, record_id, recurrence })
              .catch((e) => toast({ title: "Could not restore the task", description: errorText(e), tone: "danger" }))
              .finally(touch),
        },
      });
    } catch (err) {
      setError(errorText(err));
      setConfirmDelete(false);
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    if (!task) return;
    await toggle(task);
    setTask(await getTask(task.id));
  }

  const waiting = task?.status === "open" && task.depends_on?.status === "open";
  const due = draft ? dueOf(draft) : null;

  return (
    <>
      <Sheet
        open
        onOpenChange={(open) => !open && !busy && onClose()}
        title={id ? "Task" : "New task"}
        footer={
          <>
            {task && (
              <Button variant="danger" className="tk-delete" onClick={() => setConfirmDelete(true)} disabled={busy}>
                Delete
              </Button>
            )}
            <Button onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button variant="primary" onClick={() => void save()} loading={busy} disabled={!draft}>
              {id ? "Save" : "Add task"}
            </Button>
          </>
        }
      >
        {!draft ? (
          error ? (
            <p role="alert" className="tk-error">
              {error}
            </p>
          ) : (
            <div className="tk-sheet-loading" aria-busy>
              <Skeleton style={{ height: 36 }} />
              <Skeleton style={{ height: 96 }} />
              <Skeleton style={{ height: 36 }} />
            </div>
          )
        ) : (
          <form
            className="tk-form"
            onSubmit={save}
            onKeyDown={(e) => {
              if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void save();
            }}
          >
            {task && (
              <Checkbox label={task.status === "done" ? "Completed. Uncheck to reopen." : "Mark as completed"} checked={task.status === "done"} onCheckedChange={() => void finish()} />
            )}
            {waiting && (
              <p className="tk-waiting">
                <Lock size={14} aria-hidden /> Waiting for “{task!.depends_on!.title}”. It cannot be completed until that is done.
              </p>
            )}
            <Input label="Title" value={draft.title} maxLength={300} error={fieldError.title} onChange={(e) => set({ title: e.target.value })} autoComplete="off" />
            <Textarea label="Notes" value={draft.notes} rows={4} onChange={(e) => set({ notes: e.target.value })} />
            <div className="tk-grid2">
              <Input label="Due date" type="date" value={draft.date} error={fieldError.date} onChange={(e) => set({ date: e.target.value, ...(e.target.value ? {} : { time: "" }) })} />
              <Input label="Time" type="time" value={draft.time} disabled={!draft.date} hint={draft.date && !draft.time ? "All day" : undefined} onChange={(e) => set({ time: e.target.value })} />
            </div>
            <div className="tk-grid2">
              <Select label="Assigned to" value={draft.assignee} onValueChange={(assignee) => set({ assignee })} options={memberOptions} />
              <Select
                label="Priority"
                value={draft.priority}
                onValueChange={(priority) => set({ priority: priority as Priority })}
                options={(["none", "low", "medium", "high"] as const).map((p) => ({ value: p, label: PRIORITY_LABEL[p] }))}
              />
            </div>
            <RecurrencePicker value={ruleOf(draft)} due={due?.date ?? null} preset={draft.preset} onChange={(preset, recurrence) => set({ preset, recurrence })} />
            <Select label="Waits for" value={draft.dependsOn} onValueChange={(dependsOn) => set({ dependsOn })} options={dependencyOptions} />
            <RecordPicker value={draft.record} onChange={(record) => set({ record })} />
            {error && (
              <p role="alert" className="tk-error">
                {error}
              </p>
            )}
          </form>
        )}
      </Sheet>
      <Dialog
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title="Delete this task?"
        description={task ? `“${task.title}” will be removed. You can undo it right after.` : undefined}
        footer={
          <>
            <Button onClick={() => setConfirmDelete(false)}>Cancel</Button>
            <Button variant="danger" onClick={() => void remove()} loading={busy}>
              Delete task
            </Button>
          </>
        }
      />
    </>
  );
}
