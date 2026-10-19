// What belongs in each view, so the list and the counts can follow a change without asking the server again.
// The server stays the judge (a refetch corrects any drift); this is what makes an action show up at once. Pure.
import type { ChannelKind, Conversation, Counts, ViewId } from "./types.ts";

export const VIEWS: { id: ViewId; label: string }[] = [
  { id: "open", label: "Open" },
  { id: "mine", label: "Mine" },
  { id: "unassigned", label: "Unassigned" },
  { id: "unread", label: "Unread" },
  { id: "snoozed", label: "Snoozed" },
  { id: "closed", label: "Closed" },
];
export const VIEW_IDS = VIEWS.map((v) => v.id);
export const isView = (v: unknown): v is ViewId => typeof v === "string" && VIEW_IDS.includes(v as ViewId);

export const CHANNEL_LABEL: Record<ChannelKind, string> = { sms: "SMS", email: "Email", whatsapp: "WhatsApp", webchat: "Web chat" };

/** The server's rule for each view (backend/app/inbox/conversations.py `view_condition`). */
export function matchesView(view: ViewId, c: Conversation, me: string | null): boolean {
  switch (view) {
    case "open":
      return c.status === "open";
    case "mine":
      return c.status === "open" && !!me && c.assignee_id === me;
    case "unassigned":
      return c.status === "open" && !c.assignee_id;
    case "snoozed":
      return c.status === "snoozed";
    case "closed":
      return c.status === "closed";
    case "unread":
      return c.status !== "closed" && c.unread;
  }
}

/** The view and channel filter a list is showing. */
export type Filter = { view: ViewId; channel: string | null };
export const inFilter = (f: Filter, c: Conversation, me: string | null) => matchesView(f.view, c, me) && (!f.channel || c.channel_id === f.channel);

/** Most recent activity first, the order the server pages in (ties by id, so the order is stable). */
export const byActivity = (a: Conversation, b: Conversation) => (a.last_message_at < b.last_message_at ? 1 : a.last_message_at > b.last_message_at ? -1 : a.id < b.id ? 1 : -1);

/**
 * The list after `next` replaced the conversation of the same id: in place when it still belongs, gone when it no
 * longer does, inserted in order when it just started to. `search` lists cannot tell (the server decides what matches
 * a query), so a conversation that is not there stays out of them.
 */
export function withRow(rows: Conversation[], next: Conversation, filter: Filter, me: string | null, search = false, more = false): Conversation[] {
  const at = rows.findIndex((r) => r.id === next.id);
  const belongs = inFilter(filter, next, me);
  if (at >= 0) {
    if (!belongs && !search) return rows.filter((r) => r.id !== next.id);
    const copy = rows.slice();
    copy[at] = next;
    return next.last_message_at === rows[at]!.last_message_at ? copy : copy.sort(byActivity);
  }
  if (!belongs || search) return rows;
  // with more pages to come, one older than the last row loaded belongs to a later page, not here
  if (more && rows.length && byActivity(next, rows[rows.length - 1]!) > 0) return rows;
  return [...rows, next].sort(byActivity);
}

/** The counts after a conversation went from `before` to `after` (null: it did not exist, or is gone). */
export function withCounts(counts: Counts, before: Conversation | null, after: Conversation | null, me: string | null): Counts {
  const out: Counts = { ...counts, channels: { ...counts.channels } };
  for (const v of VIEW_IDS) {
    out[v] = Math.max(0, out[v] + (after && matchesView(v, after, me) ? 1 : 0) - (before && matchesView(v, before, me) ? 1 : 0));
  }
  const open = (c: Conversation | null) => (c && c.status === "open" && c.channel_id ? c.channel_id : null);
  const was = open(before);
  const now = open(after);
  if (was !== now) {
    if (was) out.channels[was] = Math.max(0, (out.channels[was] ?? 0) - 1);
    if (now) out.channels[now] = (out.channels[now] ?? 0) + 1;
  }
  return out;
}

export const EMPTY_COUNTS: Counts = { open: 0, mine: 0, unassigned: 0, unread: 0, snoozed: 0, closed: 0, channels: {} };
