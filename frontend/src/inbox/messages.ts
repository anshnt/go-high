// The messages of one thread: merging what the server sends with what is on screen, and the message that is still
// on its way. The server's `seq` is the order (never the provider's clock). Pure: no DOM, no Vite.
import type { ChannelKind, Message, ThreadMessage } from "./types.ts";

export const LOCAL_SEQ = Number.MAX_SAFE_INTEGER; // a message not yet stored sits after every stored one

export const isLocal = (m: ThreadMessage) => !!m.local;

/** Oldest first, by seq; messages still being sent keep the order they were typed in, after the stored ones. */
export const bySeq = (a: ThreadMessage, b: ThreadMessage) => (a.seq === b.seq ? (a.created_at < b.created_at ? -1 : 1) : a.seq - b.seq);

/**
 * `incoming` (any page, newest or oldest first) merged into `current`: a message the server knows replaces the copy we
 * had (so a status that moved on, or an edited note, shows), and a message that is still on its way stays.
 * Never drops a stored message, so a page fetched while the thread has grown cannot make anything disappear.
 */
export function mergeMessages(current: ThreadMessage[], incoming: Message[]): ThreadMessage[] {
  const byId = new Map<string, ThreadMessage>();
  for (const m of current) byId.set(m.id, m);
  for (const m of incoming) byId.set(m.id, m);
  return [...byId.values()].sort(bySeq);
}

/** A message the person just typed, shown at once as sending. `key` is also the Idempotency-Key of the request. */
export function draftMessage(init: { key: string; conversationId: string; channelId: string | null; channelKind?: ChannelKind; kind: "message" | "note"; body: string; subject: string | null; html: string | null; me: string | null; now: Date }): ThreadMessage {
  const at = init.now.toISOString();
  return {
    id: `local-${init.key}`,
    conversation_id: init.conversationId,
    seq: LOCAL_SEQ,
    direction: "out",
    channel_id: init.kind === "note" ? null : init.channelId,
    kind: init.kind,
    subject: init.subject,
    body: init.body,
    html: init.html,
    attachments: [],
    status: "queued",
    error: null,
    provider_message_id: null,
    thread_ref: null,
    sent_by: init.me,
    occurred_at: at,
    created_at: at,
    segments: null,
    estimated_cost: null,
    local: { key: init.key, state: "sending", channelKind: init.channelKind },
  };
}

/** The stored message in place of the draft it came from. If a refetch already brought it in, the draft just goes. */
export function settle(current: ThreadMessage[], key: string, stored: Message): ThreadMessage[] {
  const rest = current.filter((m) => m.local?.key !== key);
  return mergeMessages(rest, [stored]);
}

/** The draft marked failed (it did not leave, or the server refused it), kept so Retry can send the same thing. */
export function fail(current: ThreadMessage[], key: string, error: string): ThreadMessage[] {
  return current.map((m) => (m.local?.key === key ? { ...m, status: "failed", error, local: { ...m.local, key, state: "failed", error } } : m));
}

/** The draft shown as sending again (Retry). */
export function retrying(current: ThreadMessage[], key: string): ThreadMessage[] {
  return current.map((m) => (m.local?.key === key ? { ...m, status: "queued", error: null, local: { ...m.local, key, state: "sending" } } : m));
}

/** The ticks of a delivery status: "sending", "sent", "delivered", "read" or "failed". */
export type Tick = "sending" | "sent" | "delivered" | "read" | "failed" | "none";
export function tickOf(m: ThreadMessage): Tick {
  if (m.direction !== "out" || m.kind === "note" || m.kind === "system") return "none";
  if (m.local?.state === "sending") return "sending";
  if (m.local?.state === "failed" || m.status === "failed") return "failed";
  switch (m.status) {
    case "queued":
      return "sending";
    case "sent":
      return "sent";
    case "delivered":
      return "delivered";
    case "read":
      return "read";
    default:
      return "none";
  }
}

/** The newest seq the thread holds from the server (what the read mark moves to). */
export const lastStoredSeq = (messages: ThreadMessage[]) => messages.reduce((n, m) => (m.local ? n : Math.max(n, m.seq)), 0);
