import { CalendarDays, Link2, Lock, Repeat } from "lucide-react";
import { Link } from "react-router";
import { bucketOf, dueLabel } from "../lib/dates";
import { summarize } from "../lib/recurrence";
import { PRIORITY_LABEL, personName, recordPath, type Member, type Task } from "../lib/tasks";
import { Avatar, Badge, Checkbox, type Tone } from "../ui";

const PRIORITY_TONE: Record<string, Tone> = { high: "danger", medium: "warning", low: "info" };

type Props = {
  task: Task;
  members: Member[];
  now: Date;
  active?: boolean;
  onOpen: (task: Task) => void;
  onToggle: (task: Task) => void;
};

/** The small facts about a task: due date, repeat, linked record, what it waits for. Shared by the list, board and day. */
export function TaskFacts({ task, now }: { task: Task; now: Date }) {
  const bucket = task.due_at ? bucketOf(task, now) : "none";
  const waiting = task.status === "open" && task.depends_on?.status === "open";
  return (
    <>
      {task.due_at && (
        <span className="tk-fact" data-bucket={task.status === "open" ? bucket : undefined}>
          <CalendarDays size={13} aria-hidden />
          {dueLabel(task, now)}
          {bucket === "overdue" && <span className="sr-only"> (overdue)</span>}
        </span>
      )}
      {task.recurrence && (
        <span className="tk-fact" title={summarize(task.recurrence)}>
          <Repeat size={13} aria-hidden />
          <span className="tk-fact-text">{summarize(task.recurrence)}</span>
        </span>
      )}
      {waiting && (
        <span className="tk-fact" data-bucket="waiting">
          <Lock size={13} aria-hidden />
          <span className="tk-fact-text">Waiting for {task.depends_on!.title}</span>
        </span>
      )}
      {task.record && (
        <Link to={recordPath(task.record)} className="tk-fact tk-fact-link" onClick={(e) => e.stopPropagation()}>
          <Link2 size={13} aria-hidden />
          <span className="tk-fact-text">{task.record.display_name}</span>
        </Link>
      )}
    </>
  );
}

export function PriorityChip({ priority }: { priority: Task["priority"] }) {
  return priority === "none" ? null : <Badge tone={PRIORITY_TONE[priority]}>{PRIORITY_LABEL[priority]}</Badge>;
}

export function AssigneeChip({ task, members }: { task: Task; members: Member[] }) {
  if (!task.assignee_id) return null;
  const name = personName(members, task.assignee_id);
  return (
    <span className="tk-assignee" title={name}>
      <Avatar name={name} size="sm" />
      <span className="tk-assignee-name">{name.split(/\s+/)[0]}</span>
    </span>
  );
}

/** One task: a checkbox, the title (opens the detail), its facts and its priority and assignee chips. */
export function TaskRow({ task, members, now, active, onOpen, onToggle }: Props) {
  const done = task.status === "done";
  return (
    <li className="tk-row" data-task-id={task.id} data-active={active || undefined} data-done={done || undefined}>
      <Checkbox aria-label={`${done ? "Reopen" : "Complete"} ${task.title}`} checked={done} onCheckedChange={() => onToggle(task)} />
      <div className="tk-body">
        <button type="button" className="tk-title" onClick={() => onOpen(task)} tabIndex={active === false ? -1 : 0}>
          {task.title}
        </button>
        <div className="tk-meta">
          <TaskFacts task={task} now={now} />
        </div>
      </div>
      <div className="tk-chips">
        <PriorityChip priority={task.priority} />
        <AssigneeChip task={task} members={members} />
      </div>
    </li>
  );
}
