import { ChevronLeft, ChevronRight, Plus } from "lucide-react";
import { useMemo } from "react";
import { addDays, DAY_NAMES, dueDate, MONTH_NAMES, sameDay, startOfDay, timeLabel } from "../lib/dates";
import type { Member, Task } from "../lib/tasks";
import { Button } from "../ui";
import { TaskRow } from "./TaskRow";

/** The six-week grid (Monday first) that shows `month`: its first day and the days it covers. */
export function gridOf(month: Date): Date[] {
  const first = new Date(month.getFullYear(), month.getMonth(), 1);
  const start = addDays(first, -((first.getDay() + 6) % 7));
  return Array.from({ length: 42 }, (_, i) => addDays(start, i));
}

type Props = {
  month: Date;
  tasks: Task[];
  members: Member[];
  now: Date;
  selected: Date;
  onMonth: (month: Date) => void;
  onSelect: (day: Date) => void;
  onOpen: (task: Task) => void;
  onToggle: (task: Task) => void;
  onAdd: (day: Date) => void;
};

/** A month of tasks by due date, with the selected day's tasks listed under the grid (which is all a phone has room for). */
export function TaskCalendar({ month, tasks, members, now, selected, onMonth, onSelect, onOpen, onToggle, onAdd }: Props) {
  const days = useMemo(() => gridOf(month), [month]);
  const byDay = useMemo(() => {
    const map = new Map<number, Task[]>();
    for (const t of tasks) {
      const due = dueDate(t);
      if (!due) continue;
      const key = startOfDay(due).getTime();
      map.set(key, [...(map.get(key) ?? []), t]);
    }
    for (const list of map.values()) list.sort((a, b) => dueDate(a)!.getTime() - dueDate(b)!.getTime() || a.position - b.position);
    return map;
  }, [tasks]);
  const today = startOfDay(now);
  const chosen = byDay.get(startOfDay(selected).getTime()) ?? [];
  const heading = `${DAY_NAMES[selected.getDay()]}, ${MONTH_NAMES[selected.getMonth()]} ${selected.getDate()}`;

  return (
    <div className="tk-cal">
      <div className="tk-cal-head">
        <h2 aria-live="polite">
          {MONTH_NAMES[month.getMonth()]} {month.getFullYear()}
        </h2>
        <div className="tk-cal-nav">
          <Button variant="ghost" size="icon" aria-label="Previous month" onClick={() => onMonth(new Date(month.getFullYear(), month.getMonth() - 1, 1))}>
            <ChevronLeft size={18} aria-hidden />
          </Button>
          <Button
            size="sm"
            onClick={() => {
              onMonth(new Date(today.getFullYear(), today.getMonth(), 1));
              onSelect(today);
            }}
          >
            Today
          </Button>
          <Button variant="ghost" size="icon" aria-label="Next month" onClick={() => onMonth(new Date(month.getFullYear(), month.getMonth() + 1, 1))}>
            <ChevronRight size={18} aria-hidden />
          </Button>
        </div>
      </div>
      <div className="tk-cal-grid" role="group" aria-label={`${MONTH_NAMES[month.getMonth()]} ${month.getFullYear()}`}>
        <div className="tk-cal-weekdays" aria-hidden>
          {[1, 2, 3, 4, 5, 6, 0].map((d) => (
            <span key={d}>{DAY_NAMES[d]!.slice(0, 3)}</span>
          ))}
        </div>
        {Array.from({ length: 6 }, (_, w) => (
          <div key={w} className="tk-cal-week">
            {days.slice(w * 7, w * 7 + 7).map((d) => {
              const list = byDay.get(d.getTime()) ?? [];
              return (
                <div
                  key={d.getTime()}
                  className="tk-cal-day"
                  data-outside={d.getMonth() !== month.getMonth() || undefined}
                  data-today={sameDay(d, today) || undefined}
                  data-selected={sameDay(d, selected) || undefined}
                >
                  <button type="button" className="tk-cal-num" aria-pressed={sameDay(d, selected)} aria-label={`${DAY_NAMES[d.getDay()]} ${MONTH_NAMES[d.getMonth()]} ${d.getDate()}, ${list.length} task${list.length === 1 ? "" : "s"}`} onClick={() => onSelect(d)}>
                    {d.getDate()}
                  </button>
                  <ul className="tk-cal-tasks">
                    {list.slice(0, 3).map((t) => (
                      <li key={t.id}>
                        <button type="button" className="tk-cal-task" data-done={t.status === "done" || undefined} onClick={() => onOpen(t)} title={t.title}>
                          {!t.all_day && <span className="tk-cal-time">{timeLabel(dueDate(t)!)}</span>}
                          {t.title}
                        </button>
                      </li>
                    ))}
                  </ul>
                  {list.length > 3 && (
                    <button type="button" className="tk-cal-more" onClick={() => onSelect(d)}>
                      +{list.length - 3} more
                    </button>
                  )}
                  {list.length > 0 && <span className="tk-cal-dots" aria-hidden>{list.length}</span>}
                </div>
              );
            })}
          </div>
        ))}
      </div>
      <section className="tk-cal-day-panel" aria-labelledby="tk-cal-day-title">
        <div className="tk-cal-day-head">
          <h2 id="tk-cal-day-title">{heading}</h2>
          <Button size="sm" onClick={() => onAdd(selected)}>
            <Plus size={14} aria-hidden />
            Add task
          </Button>
        </div>
        {chosen.length === 0 ? (
          <p className="tk-muted">Nothing due this day.</p>
        ) : (
          <ul className="tk-list">
            {chosen.map((t) => (
              <TaskRow key={t.id} task={t} members={members} now={now} onOpen={onOpen} onToggle={onToggle} />
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
