import { useState } from "react";
import { cn } from "../lib/cn";
import type { Member, Task } from "../lib/tasks";
import { Checkbox } from "../ui";
import { AssigneeChip, PriorityChip, TaskFacts } from "./TaskRow";

type Column = "todo" | "blocked" | "done";
const COLUMNS: { id: Column; label: string; hint: string }[] = [
  { id: "todo", label: "To do", hint: "Open tasks you can start now" },
  { id: "blocked", label: "Blocked", hint: "Open tasks waiting for another task" },
  { id: "done", label: "Done", hint: "Finished in the last 7 days" },
];

export const columnOf = (t: Task): Column => (t.status === "done" ? "done" : t.depends_on?.status === "open" ? "blocked" : "todo");

type Props = {
  tasks: Task[];
  members: Member[];
  now: Date;
  onOpen: (task: Task) => void;
  onToggle: (task: Task) => void;
};

/**
 * Tasks by status. Dragging a card to Done completes it and dragging it back to To do reopens it; the checkbox does the
 * same for the keyboard. A blocked task moves out of Blocked when the task it waits for is finished.
 */
export function TaskBoard({ tasks, members, now, onOpen, onToggle }: Props) {
  const [over, setOver] = useState<Column | null>(null);
  const dropOn = (column: Column, e: React.DragEvent) => {
    e.preventDefault();
    setOver(null);
    const task = tasks.find((t) => t.id === e.dataTransfer.getData("text/plain"));
    if (task && ((column === "done" && task.status === "open") || (column === "todo" && task.status === "done"))) onToggle(task);
  };
  return (
    <div className="tk-board">
      {COLUMNS.map((c) => {
        const cards = tasks.filter((t) => columnOf(t) === c.id);
        return (
          <section
            key={c.id}
            className={cn("tk-column")}
            data-over={over === c.id || undefined}
            aria-labelledby={`tk-col-${c.id}`}
            onDragOver={(e) => {
              if (c.id !== "blocked") {
                e.preventDefault();
                setOver(c.id);
              }
            }}
            onDragLeave={() => setOver((o) => (o === c.id ? null : o))}
            onDrop={(e) => dropOn(c.id, e)}
          >
            <h2 id={`tk-col-${c.id}`} className="tk-column-title" title={c.hint}>
              {c.label}
              <span className="tk-count">{cards.length}</span>
            </h2>
            <ul className="tk-cards">
              {cards.map((t) => (
                <li key={t.id} className="tk-card" data-task-id={t.id} data-done={t.status === "done" || undefined} draggable={c.id !== "blocked"} onDragStart={(e) => e.dataTransfer.setData("text/plain", t.id)}>
                  <div className="tk-card-top">
                    <Checkbox aria-label={`${t.status === "done" ? "Reopen" : "Complete"} ${t.title}`} checked={t.status === "done"} onCheckedChange={() => onToggle(t)} />
                    <button type="button" className="tk-title" onClick={() => onOpen(t)}>
                      {t.title}
                    </button>
                  </div>
                  <div className="tk-meta">
                    <TaskFacts task={t} now={now} />
                  </div>
                  <div className="tk-chips">
                    <PriorityChip priority={t.priority} />
                    <AssigneeChip task={t} members={members} />
                  </div>
                </li>
              ))}
              {cards.length === 0 && <li className="tk-column-empty">{c.id === "blocked" ? "Nothing is waiting" : c.id === "done" ? "Nothing finished lately" : "Nothing to do"}</li>}
            </ul>
          </section>
        );
      })}
    </div>
  );
}
