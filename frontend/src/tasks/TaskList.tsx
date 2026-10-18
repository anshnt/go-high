import { bucketOf, dueDate, type Bucket } from "../lib/dates";
import type { Member, Task } from "../lib/tasks";
import { TaskRow } from "./TaskRow";

export const GROUPS: { bucket: Bucket; label: string }[] = [
  { bucket: "overdue", label: "Overdue" },
  { bucket: "today", label: "Today" },
  { bucket: "upcoming", label: "Upcoming" },
  { bucket: "none", label: "No date" },
];

/** Tasks in the four groups of the list. Within a group the earlier due time comes first, then the manual order. */
export function groupTasks(tasks: Task[], now: Date): { bucket: Bucket; label: string; tasks: Task[] }[] {
  const time = (t: Task) => dueDate(t)?.getTime() ?? 0;
  return GROUPS.map((g) => ({
    ...g,
    tasks: tasks.filter((t) => bucketOf(t, now) === g.bucket).sort((a, b) => (g.bucket === "none" ? 0 : time(a) - time(b)) || a.position - b.position),
  })).filter((g) => g.tasks.length > 0);
}

type Props = {
  groups: ReturnType<typeof groupTasks>;
  members: Member[];
  now: Date;
  /** Index into the flat order of `groups` of the task the keyboard is on; leave out when the list has no j and k. */
  active?: number;
  onOpen: (task: Task) => void;
  onToggle: (task: Task) => void;
};

export function TaskList({ groups, members, now, active, onOpen, onToggle }: Props) {
  let index = -1;
  return (
    <div className="tk-groups">
      {groups.map((g) => (
        <section key={g.bucket} className="tk-group" aria-labelledby={`tk-group-${g.bucket}`}>
          <h2 id={`tk-group-${g.bucket}`} className="tk-group-title" data-bucket={g.bucket}>
            {g.label}
            <span className="tk-count">{g.tasks.length}</span>
          </h2>
          <ul className="tk-list">
            {g.tasks.map((t) => {
              index += 1;
              return <TaskRow key={t.id} task={t} members={members} now={now} active={active === undefined ? undefined : index === active} onOpen={onOpen} onToggle={onToggle} />;
            })}
          </ul>
        </section>
      ))}
    </div>
  );
}
