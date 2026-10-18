import { CalendarDays, Plus } from "lucide-react";
import { useMemo, useState, type FormEvent, type Ref } from "react";
import { errorText } from "../lib/api";
import { dueIso, dueLabel, parseDue } from "../lib/dates";
import { createTask, touch, type Task } from "../lib/tasks";
import { Button } from "../ui";

type Props = {
  /** Who a new task goes to; null leaves it unassigned. */
  assigneeId: string | null;
  /** The due date when the text names none (My Day adds for today). */
  defaultDue?: Date;
  recordId?: string;
  placeholder?: string;
  inputRef?: Ref<HTMLInputElement>;
  onCreated?: (task: Task) => void;
};

/** One line: the title, then a due date in words ("Call Ada tomorrow at 3pm"). Enter adds the task. */
export function QuickAdd({ assigneeId, defaultDue, recordId, placeholder = "Add a task, like: Call Ada tomorrow", inputRef, onCreated }: Props) {
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const parsed = useMemo(() => parseDue(text, new Date()), [text]);
  const due = parsed.due ?? defaultDue ?? null;
  const allDay = parsed.due ? parsed.allDay : true;

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!parsed.title || busy) return;
    setBusy(true);
    setError(undefined);
    try {
      const task = await createTask({
        title: parsed.title,
        assignee_id: assigneeId,
        ...(due ? { due_at: dueIso(due, allDay), all_day: allDay } : {}),
        ...(recordId ? { record_id: recordId } : {}),
      });
      setText("");
      onCreated?.(task);
      touch();
    } catch (err) {
      setError(errorText(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="tk-quick" onSubmit={submit}>
      <div className="tk-quick-field">
        <Plus size={16} aria-hidden />
        <input
          ref={inputRef}
          type="text"
          value={text}
          maxLength={300}
          placeholder={placeholder}
          aria-label="Add a task"
          aria-describedby="tk-quick-hint"
          autoComplete="off"
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Escape" && e.currentTarget.blur()}
        />
        {parsed.phrase && due && (
          <span className="tk-quick-due" title={`Due ${dueLabel({ due_at: dueIso(due, allDay), all_day: allDay }, new Date())}`}>
            <CalendarDays size={13} aria-hidden />
            {dueLabel({ due_at: dueIso(due, allDay), all_day: allDay }, new Date())}
          </span>
        )}
        <Button type="submit" size="sm" variant="primary" loading={busy} disabled={!parsed.title}>
          Add
        </Button>
      </div>
      <p id="tk-quick-hint" className="tk-quick-hint" role={error ? "alert" : undefined} data-error={error ? true : undefined}>
        {error ?? "Add a date in words: tomorrow, next mon, in 3 days, oct 25, at 3pm."}
      </p>
    </form>
  );
}
