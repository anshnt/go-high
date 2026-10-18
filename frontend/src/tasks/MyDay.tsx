import { CalendarClock, CircleCheck, ListChecks, MessagesSquare, type LucideIcon } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { errorText } from "../lib/api";
import { DAY_NAMES, MONTH_NAMES, startOfDay } from "../lib/dates";
import { useMe } from "../lib/session";
import { useStore } from "../lib/store";
import { getMyDay, tasksVersion, touch, useMembers, type MyDay as Day, type Task } from "../lib/tasks";
import { PageHeader } from "../shell/PageHeader";
import { Button, EmptyState, Skeleton } from "../ui";
import { QuickAdd } from "./QuickAdd";
import { TaskList } from "./TaskList";
import { TaskSheet, type Target } from "./TaskSheet";
import { useTaskKeys } from "./useTaskKeys";
import { useToggleTask } from "./useToggleTask";
import "./tasks.css";

const greeting = (now: Date) => (now.getHours() < 12 ? "Good morning" : now.getHours() < 18 ? "Good afternoon" : "Good evening");

/** What a module that does not exist yet will put on the day. No sample data: it says what will appear and when. */
function Soon({ icon: Icon, title, text }: { icon: LucideIcon; title: string; text: string }) {
  return (
    <section className="tk-soon" aria-labelledby={`soon-${title}`}>
      <span className="tk-soon-icon">
        <Icon size={18} aria-hidden />
      </span>
      <div>
        <h2 id={`soon-${title}`}>{title}</h2>
        <p>{text}</p>
      </div>
    </section>
  );
}

/** The page you land on: your overdue and today's tasks first, with a place for appointments and conversations. */
export function MyDay() {
  const me = useMe();
  const version = useStore(tasksVersion);
  const members = useMembers();
  const toggle = useToggleTask();
  const [day, setDay] = useState<Day | null>(null);
  const [error, setError] = useState<string>();
  const [sheet, setSheet] = useState<Target | null>(null);
  const [active, setActive] = useState(0);
  const [keys, setKeys] = useState(false); // the cursor shows once j or k has been used
  const move = (i: number) => {
    setKeys(true);
    setActive(i);
  };
  const now = new Date();

  useEffect(() => {
    let alive = true;
    getMyDay()
      .then((d) => {
        if (!alive) return;
        setDay(d);
        setError(undefined);
      })
      .catch((e) => alive && setError(errorText(e)));
    return () => {
      alive = false;
    };
  }, [version]);

  const overdue = day?.tasks.overdue ?? [];
  const today = day?.tasks.today ?? [];
  const groups = useMemo(
    () => [
      ...(overdue.length ? [{ bucket: "overdue" as const, label: "Overdue", tasks: overdue }] : []),
      ...(today.length ? [{ bucket: "today" as const, label: "Today", tasks: today }] : []),
    ],
    [overdue, today],
  );
  const flat = [...overdue, ...today];
  const onOpen = (t: Task) => setSheet({ kind: "edit", id: t.id });
  const onToggle = (t: Task) => {
    setDay((d) => d && { ...d, tasks: { ...d.tasks, overdue: d.tasks.overdue.map((x) => (x.id === t.id ? { ...x, status: "done" } : x)), today: d.tasks.today.map((x) => (x.id === t.id ? { ...x, status: "done" } : x)) } });
    void toggle(t);
  };
  useTaskKeys({
    tasks: flat,
    active,
    setActive: move,
    onToggle,
    onEdit: onOpen,
    onNew: () => document.querySelector<HTMLInputElement>(".tk-quick input")?.focus(),
  });

  const first = me?.user.name.split(/\s+/)[0];
  const counts = day?.tasks.counts;
  const summary = !counts
    ? ""
    : counts.today + counts.overdue === 0
      ? counts.done_today ? `Nothing left. You finished ${counts.done_today} today.` : "Nothing is due today."
      : [counts.today && `${counts.today} due today`, counts.overdue && `${counts.overdue} overdue`, counts.done_today && `${counts.done_today} done`].filter(Boolean).join(", ");

  return (
    <div className="sh-page tk-page">
      <PageHeader title="My Day" description={`${DAY_NAMES[now.getDay()]}, ${MONTH_NAMES[now.getMonth()]} ${now.getDate()}`} />
      <div className="tk-hello">
        <h2>
          {greeting(now)}
          {first ? `, ${first}` : ""}
        </h2>
        <p aria-live="polite">{summary}</p>
      </div>
      <div className="tk-day">
        <div className="tk-day-main">
          <QuickAdd assigneeId={me?.user.id ?? null} defaultDue={startOfDay(now)} placeholder="Add a task for today, like: Send the quote at 3pm" />
          {error && !day ? (
            <EmptyState icon={ListChecks} title="Could not load your day" text={error} action={<Button onClick={touch}>Try again</Button>} />
          ) : !day ? (
            <div className="tk-skeleton" aria-busy aria-label="Loading your day">
              {Array.from({ length: 4 }, (_, i) => (
                <Skeleton key={i} style={{ height: 52 }} />
              ))}
            </div>
          ) : flat.length === 0 ? (
            <EmptyState
              icon={CircleCheck}
              title="You are clear for today"
              text="Nothing is due today and nothing is overdue. Add a task above, or look at all of your tasks."
              action={
                <Link to="/tasks" className="ui-btn" data-variant="secondary" data-size="md">
                  Open tasks
                </Link>
              }
            />
          ) : (
            <TaskList groups={groups} members={members} now={now} active={keys ? active : undefined} onOpen={onOpen} onToggle={onToggle} />
          )}
        </div>
        <aside className="tk-day-side" aria-label="Also today">
          <Soon icon={CalendarClock} title="Appointments" text="Today's calls and meetings will show up here once calendars are set up and people book time with you." />
          <Soon icon={MessagesSquare} title="Conversations" text="Conversations assigned to you that are waiting for a reply will show up here once the inbox is live." />
        </aside>
      </div>
      {sheet && <TaskSheet key={sheet.kind === "edit" ? sheet.id : "new"} target={sheet} onClose={() => setSheet(null)} />}
    </div>
  );
}
