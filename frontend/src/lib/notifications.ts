import { useEffect } from "react";
import { api, workspaceId } from "./api";
import { memory, useStore } from "./store";

export type Notification = {
  id: string;
  kind: string;
  title: string;
  body: string;
  link: string | null;
  subject: { type: string; id: string } | null;
  created_at: string;
  read_at: string | null;
};
export type Pref = {
  kind: string;
  label: string;
  channels: ("in_app" | "email")[];
  scope: "all" | "mine";
  quiet_start: string | null;
  quiet_end: string | null;
  tz: string | null;
  digest: "daily" | "off";
};

type State = { loaded: boolean; unread: number; items: Notification[] };
export const inbox = memory<State>({ loaded: false, unread: 0, items: [] });

export async function refreshNotifications(): Promise<void> {
  if (!workspaceId.get()) return;
  try {
    const [list, count] = await Promise.all([
      api.get<{ data: Notification[] }>("/api/v1/notifications?limit=20"),
      api.get<{ count: number }>("/api/v1/notifications/unread-count"),
    ]);
    inbox.set({ loaded: true, unread: count.count, items: list.data });
  } catch {
    /* the bell keeps what it had; the next refresh tries again */
  }
}

export async function markRead(ids: string[] | "all"): Promise<void> {
  const now = new Date().toISOString();
  const s = inbox.get();
  const was = (n: Notification) => ids === "all" || ids.includes(n.id);
  inbox.set({ ...s, unread: ids === "all" ? 0 : Math.max(0, s.unread - s.items.filter((n) => was(n) && !n.read_at).length), items: s.items.map((n) => (was(n) && !n.read_at ? { ...n, read_at: now } : n)) });
  try {
    await api.post("/api/v1/notifications/read", ids === "all" ? { all: true } : { ids });
  } finally {
    void refreshNotifications();
  }
}

const REFRESH_MS = 60_000;

/**
 * Keeps the bell current: loads now, again every minute and when the tab comes back, and again when the workspace changes.
 * ponytail: polling every 60 s; the SSE stream arrives with the inbox (module 12) and replaces the timer.
 */
export function useNotifications(): State {
  const ws = useStore(workspaceId);
  useEffect(() => {
    inbox.set({ loaded: false, unread: 0, items: [] });
    void refreshNotifications();
    const timer = setInterval(() => void refreshNotifications(), REFRESH_MS);
    const visible = () => document.visibilityState === "visible" && void refreshNotifications();
    document.addEventListener("visibilitychange", visible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [ws]);
  return useStore(inbox);
}

export const getPrefs = () => api.get<{ data: Pref[] }>("/api/v1/notifications/prefs").then((r) => r.data);
export const savePrefs = (prefs: Pref[]) =>
  api
    .put<{ data: Pref[] }>("/api/v1/notifications/prefs", {
      prefs: prefs.map(({ kind, channels, scope, quiet_start, quiet_end, tz, digest }) => ({ kind, channels, scope, quiet_start, quiet_end, tz, digest })),
    })
    .then((r) => r.data);
