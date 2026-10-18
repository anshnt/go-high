import { api, workspaceId } from "./api";
import { memory, persisted, useStore } from "./store";
import { useEffect, useState } from "react";

export type Priority = "none" | "low" | "medium" | "high";
export type Brief = { id: string; title: string; status: "open" | "done" };
export type Task = {
  id: string;
  title: string;
  notes: string;
  due_at: string | null;
  all_day: boolean;
  assignee_id: string | null;
  created_by: string | null;
  priority: Priority;
  status: "open" | "done";
  completed_at: string | null;
  record_id: string | null;
  record: { id: string; object: string; display_name: string } | null;
  recurrence: string | null;
  parent_task_id: string | null;
  depends_on_task_id: string | null;
  depends_on: Brief | null;
  position: number;
  created_at: string;
  updated_at: string;
};
export type TaskInput = Partial<Pick<Task, "title" | "notes" | "due_at" | "all_day" | "assignee_id" | "priority" | "record_id" | "recurrence" | "depends_on_task_id">>;
export type Member = { id: string; name: string; email: string; role: "admin" | "member" };
export type MyDay = {
  date: string;
  timezone: string;
  tasks: { overdue: Task[]; today: Task[]; counts: { overdue: number; today: number; done_today: number } };
};

/** The reader's time zone: it decides what "today" is for the server. */
export const zone = () => Intl.DateTimeFormat().resolvedOptions().timeZone;

const query = (params: Record<string, string | number | undefined>) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined) q.set(k, String(v));
  return q.size ? `?${q}` : "";
};

const PAGE = 200;
const MAX_PAGES = 5; // ponytail: a view holds at most 1000 tasks; narrow it with a filter (or page on scroll) past that

/** Every task matching the filters, in manual order. */
export async function listTasks(params: Record<string, string | undefined> = {}): Promise<Task[]> {
  const all: Task[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < MAX_PAGES; page++) {
    const res = await api.get<{ data: Task[]; next_cursor: string | null }>(`/api/v1/tasks${query({ ...params, tz: zone(), limit: PAGE, cursor })}`);
    all.push(...res.data);
    if (!res.next_cursor) break;
    cursor = res.next_cursor;
  }
  return all;
}

export const getTask = (id: string) => api.get<Task>(`/api/v1/tasks/${id}`);
export const createTask = (body: TaskInput & { title: string }) => api.post<Task>("/api/v1/tasks", body);
export const updateTask = (id: string, body: TaskInput) => api.patch<Task>(`/api/v1/tasks/${id}`, body);
export const deleteTask = (id: string) => api.del(`/api/v1/tasks/${id}`);
export const completeTask = (id: string) => api.post<Task & { next: Task | null }>(`/api/v1/tasks/${id}/complete${query({ tz: zone() })}`);
export const reopenTask = (id: string) => api.post<Task>(`/api/v1/tasks/${id}/reopen`);
export const getMyDay = () => api.get<MyDay>(`/api/v1/my-day${query({ tz: zone() })}`);

/** Bumped after any change to a task, so every open view loads again. */
export const tasksVersion = memory(0);
export const touch = () => tasksVersion.set(tasksVersion.get() + 1);

export type Show = "mine" | "all" | "unassigned";
export type View = "list" | "board" | "calendar";
export const showStore = persisted<Show>("gh:tasks-show", "mine", (v) => (v === "mine" || v === "all" || v === "unassigned" ? v : undefined));
export const viewStore = persisted<View>("gh:tasks-view", "list", (v) => (v === "list" || v === "board" || v === "calendar" ? v : undefined));
export const assigneeParam = (show: Show) => (show === "mine" ? "me" : show === "unassigned" ? "unassigned" : "anyone");

// --- people --------------------------------------------------------------------------------------------------------

const people = new Map<string, Member[]>();
const peopleVersion = memory(0);

/** The people of the current workspace, for assignee pickers and names. Empty until loaded. */
export function useMembers(): Member[] {
  const ws = useStore(workspaceId);
  useStore(peopleVersion);
  const [, retry] = useState(0);
  useEffect(() => {
    if (!ws || people.has(ws)) return;
    let alive = true;
    api
      .get<{ data: Member[] }>("/api/v1/members")
      .then((r) => {
        people.set(ws, r.data);
        peopleVersion.set(peopleVersion.get() + 1);
      })
      .catch(() => alive && setTimeout(() => retry((n) => n + 1), 10_000));
    return () => {
      alive = false;
    };
  }, [ws]);
  return (ws && people.get(ws)) || [];
}

export const personName = (members: Member[], id: string | null) => (id ? (members.find((m) => m.id === id)?.name ?? "Someone") : "Unassigned");

export const PRIORITY_LABEL: Record<Priority, string> = { none: "No priority", low: "Low", medium: "Medium", high: "High" };
export const recordPath = (r: { object: string; id: string }) => `/records/${r.object}/${r.id}`;
