// The unread count on the Inbox item of the sidebar and the tab bar. The inbox screen keeps it exact (it has the live
// counts); everywhere else it is read when the app opens, every minute and when the tab comes back, like the bell.
// ponytail: polling every 60 s; the stream (one EventSource per tab) belongs to the inbox screen alone, because browsers
// allow few connections per host and a stream on every page would use them up across tabs.
import { useEffect } from "react";
import { api, workspaceId } from "./api";
import { holds } from "./holds";
import { capabilities } from "./capabilities";
import { memory, useStore } from "./store";

export const inboxUnread = memory(0);
export const useInboxUnread = () => useStore(inboxUnread);

const REFRESH_MS = 60_000;

async function read(ws: string | null) {
  if (!ws) return;
  try {
    const page = await api.get<{ counts?: { unread: number } }>("/api/v1/conversations?limit=1");
    if (page.counts && workspaceId.get() === ws) inboxUnread.set(page.counts.unread);
  } catch {
    /* keep what it showed */
  }
}

/** Mounted once in the shell. */
export function useInboxBadge() {
  const ws = useStore(workspaceId);
  const allowed = holds(useStore(capabilities), "conversations.read");
  useEffect(() => {
    inboxUnread.set(0);
    if (!ws || !allowed) return;
    void read(ws);
    const timer = setInterval(() => void read(ws), REFRESH_MS);
    const visible = () => document.visibilityState === "visible" && void read(ws);
    document.addEventListener("visibilitychange", visible);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", visible);
    };
  }, [ws, allowed]);
}
