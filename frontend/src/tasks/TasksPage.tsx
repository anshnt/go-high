import { ListChecks, Plus } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { errorText } from "../lib/api";
import { addDays, dueIso, startOfDay } from "../lib/dates";
import { useMe } from "../lib/session";
import { useStore } from "../lib/store";
import { assigneeParam, listTasks, showStore, tasksVersion, touch, useMembers, viewStore, type Show, type Task, type View } from "../lib/tasks";
import { PageHeader } from "../shell/PageHeader";
import { Button, EmptyState, Skeleton, Tabs, TabsList, TabsTrigger } from "../ui";
import { QuickAdd } from "./QuickAdd";
import { TaskBoard } from "./TaskBoard";
import { gridOf, TaskCalendar } from "./TaskCalendar";
import { groupTasks, TaskList } from "./TaskList";
import { TaskSheet, targetKey, type Target } from "./TaskSheet";
import { useTaskKeys } from "./useTaskKeys";
import { useToggleTask } from "./useToggleTask";
import "./tasks.css";

const SHOW: { id: Show; label: string }[] = [
  { id: "mine", label: "Mine" },
  { id: "all", label: "Everyone" },
  { id: "unassigned", label: "Unassigned" },
];
const VIEWS: { id: View; label: string }[] = [
  { id: "list", label: "List" },
  { id: "board", label: "Board" },
  { id: "calendar", label: "Calendar" },
];
const EMPTY: Record<Show, string> = {
  mine: "Nothing is assigned to you. Add a task above, or look at everyone's.",
  all: "Add the first task above. Type a date in words and it is set for you.",
  unassigned: "Every task has an owner.",
};

const firstOfMonth = (d: Date) => new Date(d.getFullYear(), d.getMonth(), 1);

async function load(view: View, show: Show, month: Date): Promise<Task[]> {
  const assignee = assigneeParam(show);
  if (view === "list") return listTasks({ assignee, status: "open" });
  if (view === "board") {
    const week = new Date(Date.now() - 7 * 86_400_000).toISOString();
    const [open, done] = await Promise.all([listTasks({ assignee, status: "open" }), listTasks({ assignee, status: "done", completed_after: week })]);
    return [...open, ...done];
  }
  const days = gridOf(month); // a day of margin each side: the grid is local days, a due time is an instant
  const range = { due_after: dueIso(addDays(days[0]!, -1), true), due_before: dueIso(addDays(days[41]!, 2), true) };
  return listTasks({ assignee, ...range });
}

/** Tasks: a list grouped by when they are due, a board by status and a calendar by month. */
export function TasksPage() {
  const show = useStore(showStore);
  const view = useStore(viewStore);
  const version = useStore(tasksVersion);
  const members = useMembers();
  const me = useMe()?.user.id ?? null;
  const toggle = useToggleTask();
  const [params, setParams] = useSearchParams();
  const [month, setMonth] = useState(() => firstOfMonth(new Date()));
  const [selected, setSelected] = useState(() => startOfDay(new Date()));
  const [sheet, setSheet] = useState<Target | null>(null);
  const [active, setActive] = useState(0);
  const [keys, setKeys] = useState(false); // the cursor shows once j or k has been used
  const move = (i: number) => {
    setKeys(true);
    setActive(i);
  };
  const [loaded, setLoaded] = useState<{ key: string; tasks: Task[] } | null>(null);
  const [error, setError] = useState<string>();
  const quick = useRef<HTMLInputElement>(null);
  const key = `${view}:${show}:${month.getTime()}`;
  const tasks = loaded?.key === key ? loaded.tasks : null;
  const now = new Date();

  useEffect(() => {
    let alive = true;
    load(view, show, month)
      .then((list) => {
        if (!alive) return;
        setLoaded({ key, tasks: list });
        setError(undefined);
      })
      .catch((e) => alive && setError(errorText(e)));
    return () => {
      alive = false;
    };
  }, [view, show, month, key, version]);

  // A link such as /tasks?task=<id> (from a notification) opens that task.
  const linked = params.get("task");
  useEffect(() => {
    if (linked) setSheet({ kind: "edit", id: linked });
  }, [linked]);
  const closeSheet = () => {
    setSheet(null);
    if (params.has("task")) {
      params.delete("task");
      setParams(params, { replace: true });
    }
  };

  const groups = useMemo(() => groupTasks(tasks ?? [], new Date()), [tasks]);
  const flat = useMemo(() => groups.flatMap((g) => g.tasks), [groups]);
  useEffect(() => setActive((a) => Math.min(a, Math.max(0, flat.length - 1))), [flat.length]);

  const onToggle = (t: Task) => {
    setLoaded((l) => l && { ...l, tasks: l.tasks.map((x) => (x.id === t.id ? { ...x, status: t.status === "open" ? "done" : "open" } : x)) });
    void toggle(t);
  };
  const onOpen = (t: Task) => setSheet({ kind: "edit", id: t.id });
  const addNew = (due?: Date) =>
    setSheet({ kind: "new", preset: { assignee_id: show === "unassigned" ? null : me, ...(due ? { due_at: dueIso(due, true), all_day: true } : {}) } });
  const inList = view === "list";
  useTaskKeys({
    tasks: inList ? flat : [],
    active,
    setActive: move,
    onToggle,
    onEdit: onOpen,
    onNew: () => (inList ? quick.current?.focus() : addNew()),
  });

  return (
    <div className="sh-page tk-page">
      <PageHeader
        title="Tasks"
        description="Everything to do in this workspace, on a record or on its own."
        views={
          <Tabs value={view} onValueChange={(v) => viewStore.set(v as View)}>
            <TabsList aria-label="View" className="tk-views">
              {VIEWS.map((v) => (
                <TabsTrigger key={v.id} value={v.id}>
                  {v.label}
                </TabsTrigger>
              ))}
            </TabsList>
          </Tabs>
        }
        actions={
          <>
            <div className="tk-seg" role="group" aria-label="Show tasks">
              {SHOW.map((s) => (
                <button key={s.id} type="button" aria-pressed={show === s.id} onClick={() => showStore.set(s.id)}>
                  {s.label}
                </button>
              ))}
            </div>
            <Button variant="primary" onClick={() => addNew(view === "calendar" ? selected : undefined)}>
              <Plus size={16} aria-hidden />
              New task
            </Button>
          </>
        }
      />

      {inList && <QuickAdd assigneeId={show === "unassigned" ? null : me} inputRef={quick} />}

      {error && !tasks ? (
        <EmptyState icon={ListChecks} title="Could not load tasks" text={error} action={<Button onClick={touch}>Try again</Button>} />
      ) : !tasks ? (
        <div className="tk-skeleton" aria-busy aria-label="Loading tasks">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} style={{ height: 52 }} />
          ))}
        </div>
      ) : view === "list" ? (
        flat.length === 0 ? (
          <EmptyState icon={ListChecks} title="No open tasks" text={EMPTY[show]} />
        ) : (
          <TaskList groups={groups} members={members} now={now} active={keys ? active : undefined} onOpen={onOpen} onToggle={onToggle} />
        )
      ) : view === "board" ? (
        <TaskBoard tasks={tasks} members={members} now={now} onOpen={onOpen} onToggle={onToggle} />
      ) : (
        <TaskCalendar month={month} tasks={tasks} members={members} now={now} selected={selected} onMonth={setMonth} onSelect={setSelected} onOpen={onOpen} onToggle={onToggle} onAdd={addNew} />
      )}
      {error && tasks && (
        <p role="alert" className="tk-error">
          {error}
        </p>
      )}

      {sheet && <TaskSheet key={targetKey(sheet)} target={sheet} onClose={closeSheet} />}
    </div>
  );
}
