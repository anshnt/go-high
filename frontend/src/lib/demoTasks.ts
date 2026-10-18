import { bucketOf, dueDate, startOfDay } from "./dates";
import type { Member, MyDay, Task } from "./tasks";

// The public demo (VITE_DEMO=1) has no server, so tasks and notifications live here, in memory, and start empty: what
// you add on My Day or Tasks works until the page is reloaded. The notification bell is always quiet.
// ponytail: no repeats (completing a repeating task does not create the next one), no bulk or reorder, no search of
// records to link; the demo answers 501 for those, like any other call it does not know.

export class DemoMiss extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type Json = Record<string, unknown>;
const tasks: Task[] = [];
const PREFS = ["task_assigned", "task_due", "record_assigned"].map((kind, i) => ({
  kind,
  label: ["A task is assigned to you", "A task you own is due", "A record is assigned to you"][i],
  channels: ["in_app"],
  scope: "mine",
  quiet_start: null as string | null,
  quiet_end: null as string | null,
  tz: null as string | null,
  digest: "off",
}));

const find = (id: string) => {
  const t = tasks.find((x) => x.id === id);
  if (!t) throw new DemoMiss(404, "Task not found");
  return t;
};
const touched = (t: Task) => ({ ...t, updated_at: new Date().toISOString() });
const decorated = (t: Task): Task => {
  const dep = t.depends_on_task_id ? tasks.find((x) => x.id === t.depends_on_task_id) : undefined;
  return { ...t, depends_on: dep ? { id: dep.id, title: dep.title, status: dep.status } : null };
};
const replace = (t: Task) => {
  tasks[tasks.findIndex((x) => x.id === t.id)] = t;
  return decorated(t);
};

function create(body: Json, userId: string): Task {
  const title = typeof body.title === "string" ? body.title.trim() : "";
  if (!title) throw new DemoMiss(422, "Field required");
  const now = new Date().toISOString();
  const t: Task = {
    id: crypto.randomUUID(),
    title,
    notes: (body.notes as string) ?? "",
    due_at: (body.due_at as string | null) ?? null,
    all_day: Boolean(body.all_day),
    assignee_id: (body.assignee_id as string | null) ?? null,
    created_by: userId,
    priority: (body.priority as Task["priority"]) ?? "none",
    status: "open",
    completed_at: null,
    record_id: (body.record_id as string | null) ?? null,
    record: null,
    recurrence: (body.recurrence as string | null) ?? null,
    parent_task_id: null,
    depends_on_task_id: (body.depends_on_task_id as string | null) ?? null,
    depends_on: null,
    position: Math.max(0, ...tasks.map((x) => x.position)) + 1024,
    created_at: now,
    updated_at: now,
  };
  tasks.push(t);
  return decorated(t);
}

function list(query: URLSearchParams, userId: string) {
  const now = new Date();
  const assignee = query.get("assignee") ?? "anyone";
  const rows = tasks
    .filter((t) => (assignee === "me" ? t.assignee_id === userId : assignee === "unassigned" ? !t.assignee_id : assignee === "anyone" || t.assignee_id === assignee))
    .filter((t) => !query.get("status") || t.status === query.get("status"))
    .filter((t) => !query.get("record_id") || t.record_id === query.get("record_id"))
    .filter((t) => !query.get("due") || bucketOf(t, now) === query.get("due"))
    .filter((t) => !query.get("due_after") || (t.due_at && t.due_at >= query.get("due_after")!))
    .filter((t) => !query.get("due_before") || (t.due_at && t.due_at < query.get("due_before")!))
    .filter((t) => !query.get("completed_after") || (t.completed_at && t.completed_at >= query.get("completed_after")!))
    .sort((a, b) => a.position - b.position);
  return { data: rows.map(decorated), next_cursor: null };
}

function myDay(userId: string): MyDay {
  const now = new Date();
  const mine = tasks.filter((t) => t.assignee_id === userId);
  const open = mine.filter((t) => t.status === "open");
  const at = (t: Task) => dueDate(t)?.getTime() ?? 0;
  const overdue = open.filter((t) => bucketOf(t, now) === "overdue").sort((a, b) => at(a) - at(b));
  const today = open.filter((t) => bucketOf(t, now) === "today").sort((a, b) => at(a) - at(b));
  const midnight = startOfDay(now).toISOString();
  const done = mine.filter((t) => t.completed_at && t.completed_at >= midnight).length;
  return {
    date: new Date(now.getTime() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10),
    timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
    tasks: { overdue: overdue.map(decorated), today: today.map(decorated), counts: { overdue: overdue.length, today: today.length, done_today: done } },
  };
}

/** Answers a tasks, My Day, notifications or members call; undefined when the call is none of those. */
export function demoTasks(method: string, path: string, body: unknown, me: Member): unknown {
  const [url, search = ""] = path.split("?");
  const query = new URLSearchParams(search);
  const input = (body ?? {}) as Json;
  const route = `${method} ${url}`;
  switch (route) {
    case "GET /api/v1/tasks":
      return list(query, me.id);
    case "POST /api/v1/tasks":
      return create(input, me.id);
    case "GET /api/v1/my-day":
      return myDay(me.id);
    case "GET /api/v1/members":
      return { data: [{ user_id: me.id, name: me.name, email: me.email, implicit: false, teams: [] }], next_cursor: null };
    case "GET /api/v1/notifications":
      return { data: [], next_cursor: null };
    case "GET /api/v1/notifications/unread-count":
      return { count: 0 };
    case "POST /api/v1/notifications/read":
      return { updated: 0 };
    case "GET /api/v1/notifications/prefs":
      return { data: PREFS };
    case "PUT /api/v1/notifications/prefs": {
      for (const entry of (input.prefs as Json[]) ?? []) {
        const p = PREFS.find((x) => x.kind === entry.kind);
        if (p) Object.assign(p, entry);
      }
      return { data: PREFS };
    }
  }
  const one = /^\/api\/v1\/tasks\/([^/]+)(?:\/(complete|reopen))?$/.exec(url ?? "");
  if (!one) return undefined;
  const [, id, action] = one;
  if (method === "GET" && !action) return decorated(find(id!));
  if (method === "PATCH" && !action) {
    const t = find(id!);
    return replace(touched({ ...t, ...Object.fromEntries(Object.entries(input).filter(([k]) => k in t)) }));
  }
  if (method === "DELETE" && !action) {
    find(id!);
    tasks.splice(tasks.findIndex((x) => x.id === id), 1);
    return null; // answered: nothing to send back
  }
  if (method === "POST" && action === "complete") {
    const t = find(id!);
    const blocker = t.depends_on_task_id ? tasks.find((x) => x.id === t.depends_on_task_id && x.status === "open") : undefined;
    if (blocker) throw new DemoMiss(409, `Finish "${blocker.title}" first: this task waits for it`);
    return { ...replace(touched({ ...t, status: "done", completed_at: t.completed_at ?? new Date().toISOString() })), next: null };
  }
  if (method === "POST" && action === "reopen") return replace(touched({ ...find(id!), status: "open", completed_at: null }));
  return undefined;
}
