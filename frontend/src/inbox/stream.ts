// The realtime stream, the pure half: which events ask for which refetch, and how long to wait before reconnecting.
// The server sends ids only (README, "Realtime"), so everything here is "what do I ask the API for again".
// The EventSource itself is in streamClient.ts. No DOM and no Vite here, so node tests it.

export type StreamEvent = {
  id?: number | string | null;
  type: string;
  workspace_id?: string | null;
  ids?: { message_id?: string | null; conversation_id?: string | null; contact_id?: string | null; record_id?: string | null; object?: string | null };
};

/** What the screen shows right now, which decides what a change matters for. */
export type Showing = {
  /** The conversation open in the thread pane. */
  conversationId: string | null;
  /** Its contact, for the contact card. */
  contactId: string | null;
  /** The contacts of the rows in the list, by contact id, so a changed contact refreshes its row. */
  rowsByContact: ReadonlyMap<string, string>;
};

export type Refetch = {
  /** Everything on screen: the list's first page, the counts, the open thread and its card. */
  everything: boolean;
  /** Conversations whose list row (and header) to read again. */
  rows: string[];
  counts: boolean;
  /** The open conversation's messages. */
  thread: boolean;
  /** The open contact's record and consents. */
  contact: boolean;
};

export const NOTHING: Refetch = { everything: false, rows: [], counts: false, thread: false, contact: false };
export const isNothing = (r: Refetch) => !r.everything && !r.counts && !r.thread && !r.contact && r.rows.length === 0;

// Events that can change who has unread messages, or which view a conversation belongs to.
const MOVES_COUNTS = new Set(["message.received", "message.queued"]);

/**
 * What a batch of events asks for. A conversation's row is read again whenever it is mentioned (one cheap call each);
 * the counts only when something that moves between views happened; the thread only for the conversation that is open;
 * and `stream.resync` (events were missed) asks for everything. A record event matters for a contact on screen.
 */
export function planRefetch(events: StreamEvent[], showing: Showing): Refetch {
  if (events.some((e) => e.type === "stream.resync")) return { ...NOTHING, everything: true };
  const rows = new Set<string>();
  let counts = false;
  let thread = false;
  let contact = false;
  for (const e of events) {
    const conversation = e.ids?.conversation_id ?? null;
    if (e.type.startsWith("message.") || e.type.startsWith("conversation.")) {
      if (conversation) {
        rows.add(conversation);
        if (conversation === showing.conversationId) thread = true;
      }
      if (e.type.startsWith("conversation.") || MOVES_COUNTS.has(e.type)) counts = true;
    } else if (e.type.startsWith("record.") && e.ids?.object === "contact" && e.ids.record_id) {
      if (e.ids.record_id === showing.contactId) contact = true;
      const row = showing.rowsByContact.get(e.ids.record_id);
      if (row) rows.add(row);
    }
  }
  return { everything: false, rows: [...rows], counts, thread, contact };
}

/** The wait before the n-th reconnect (0 first): 1 s, 2 s, 4 s... up to 30 s, with up to a quarter more so tabs do not move together. */
export function backoff(attempt: number, random: () => number = Math.random): number {
  const base = Math.min(30_000, 1000 * 2 ** Math.max(0, attempt));
  return Math.round(base * (1 + 0.25 * random()));
}

/** `{type, ...}` from an SSE `data:` line, or null for anything that is not one of ours. */
export function parseEvent(data: string): StreamEvent | null {
  try {
    const v = JSON.parse(data) as unknown;
    return v && typeof v === "object" && typeof (v as StreamEvent).type === "string" ? (v as StreamEvent) : null;
  } catch {
    return null;
  }
}
