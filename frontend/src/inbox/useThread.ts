import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError } from "../lib/api";
import { whatWentWrong } from "../lib/errors";
import { editNote, getConversation, listMessages, newKey, sendMessage, type Outgoing } from "./api";
import { draftMessage, fail, mergeMessages, retrying, settle } from "./messages.ts";
import { describeRefusal, type Refusal } from "./refusal.ts";
import type { ChannelKind, Conversation, Estimate, Message, ThreadMessage } from "./types.ts";

export type ThreadState = {
  conv: Conversation | null;
  messages: ThreadMessage[];
  /** The cursor for earlier messages; null when the whole thread is loaded. */
  next: string | null;
  status: "loading" | "ready" | "error";
  error?: string;
  loadingEarlier: boolean;
};

const EMPTY: ThreadState = { conv: null, messages: [], next: null, status: "loading", loadingEarlier: false };

// Threads already read, so opening one again (j then k) shows it at once and refreshes behind it.
// ponytail: in memory for this tab only, 40 threads; the API is the truth and every open reads it again.
const CACHE = new Map<string, ThreadState>();
const remember = (key: string, s: ThreadState) => {
  CACHE.delete(key);
  CACHE.set(key, { ...s, loadingEarlier: false });
  if (CACHE.size > 40) CACHE.delete(CACHE.keys().next().value!);
};

export type SendInput = { body: string; kind: "message" | "note"; channelId: string | null; channelKind?: ChannelKind; subject?: string | null; html?: string | null };
/** What a send came to: stored (with the SMS estimate), refused by consent or the channel (the banner), or it did not leave (a failed message to retry). */
export type SendResult = { ok: true; estimate: Estimate | null } | { ok: false; refusal: Refusal } | { ok: false; failed: string };

/** One open conversation: its newest messages, earlier ones on demand, and everything the composer does to it. */
export function useThread(openId: string | null, hint: Conversation | null, workspace: string | null, me: string | null, onSent: (conv: Conversation) => void) {
  const [state, setState] = useState<ThreadState>(EMPTY);
  const current = useRef<string | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;
  const onSentRef = useRef(onSent);
  onSentRef.current = onSent;
  const key = (id: string) => `${workspace}:${id}`;

  // Updates the thread on screen, or the remembered copy of one the person has moved on from (a send that settles late).
  const apply = useCallback(
    (id: string, fn: (s: ThreadState) => ThreadState) => {
      if (current.current === id) return void setState(fn);
      const held = CACHE.get(key(id));
      if (held) remember(key(id), fn(held));
    },
    [workspace],
  );

  const load = useCallback(
    async (id: string, fresh: boolean) => {
      try {
        const d = await getConversation(id, 50);
        const { messages: page, last_read_seq: _mark, ...conv } = d;
        apply(id, (s) => ({
          conv,
          messages: fresh ? mergeMessages(s.messages.filter((m) => m.local), page.data) : mergeMessages(s.messages, page.data),
          next: fresh || s.messages.length === 0 ? page.next_cursor : s.next,
          status: "ready",
          loadingEarlier: false,
        }));
        return conv;
      } catch (e) {
        apply(id, (s) => ({ ...s, status: s.conv && s.messages.length ? "ready" : "error", error: whatWentWrong(e) }));
        return null;
      }
    },
    [apply],
  );

  useEffect(() => {
    current.current = openId;
    if (!openId) return void setState(EMPTY);
    const cached = CACHE.get(key(openId));
    setState(cached ?? { ...EMPTY, conv: hint?.id === openId ? hint : null });
    // a pause so that holding j through the list reads one thread, not twenty
    const timer = setTimeout(() => void load(openId, !cached), cached ? 0 : 60);
    return () => clearTimeout(timer);
  }, [openId, workspace, load]);

  // Keep the remembered copy current (a draft that is sending, a status that moved on).
  useEffect(() => {
    if (openId && state.status === "ready" && state.conv?.id === openId) remember(key(openId), state);
  }, [state]);

  /** Reads the newest messages again and merges them in (the stream said something happened here). */
  const refresh = useCallback(async () => (openId ? load(openId, false) : null), [openId, load]);

  const loadEarlier = useCallback(async () => {
    const id = current.current;
    const s = stateRef.current;
    if (!id || !s.next || s.loadingEarlier) return;
    setState((x) => ({ ...x, loadingEarlier: true }));
    try {
      const page = await listMessages(id, { cursor: s.next, limit: 50 });
      apply(id, (x) => ({ ...x, messages: mergeMessages(x.messages, page.data), next: page.next_cursor, loadingEarlier: false }));
    } catch {
      apply(id, (x) => ({ ...x, loadingEarlier: false }));
    }
  }, [apply]);

  const setConv = useCallback((conv: Conversation) => setState((s) => (s.conv && s.conv.id === conv.id ? { ...s, conv } : s)), []);

  const deliver = useCallback(
    async (id: string, input: SendInput, k: string): Promise<SendResult> => {
      const out: Outgoing = { body: input.body, kind: input.kind, ...(input.kind === "message" ? { channel_id: input.channelId, subject: input.subject, html: input.html } : {}) };
      try {
        const sent = await sendMessage(id, out, k);
        const { estimate, ...stored } = sent;
        apply(id, (s) => ({ ...s, messages: settle(s.messages, k, stored as Message) }));
        const conv = stateRef.current.conv;
        if (conv && conv.id === id && input.kind === "message") {
          onSentRef.current({ ...conv, status: "open", snooze_until: null, last_message_at: stored.created_at, last_direction: "out", preview: input.body.slice(0, 200), channel_id: input.channelId ?? conv.channel_id, channel_kind: input.channelKind ?? conv.channel_kind, unread: false, last_seq: stored.seq });
        }
        return { ok: true, estimate: estimate ?? null };
      } catch (e) {
        const refusal = e instanceof ApiError ? describeRefusal({ code: e.code, message: e.message, fields: e.fields }) : null;
        if (refusal) {
          apply(id, (s) => ({ ...s, messages: s.messages.filter((m) => m.local?.key !== k) })); // never left: the banner says why, the draft stays in the box
          return { ok: false, refusal };
        }
        const reason = e instanceof ApiError && e.status === 0 ? "Not sent. Could not reach the server." : `Not sent. ${whatWentWrong(e)}`;
        apply(id, (s) => ({ ...s, messages: fail(s.messages, k, reason) }));
        return { ok: false, failed: reason };
      }
    },
    [apply],
  );

  /** Sends a reply or a note: it shows in the thread at once as sending, and settles when the server answers. */
  const submit = useCallback(
    (input: SendInput): Promise<SendResult> => {
      const id = current.current!;
      const k = newKey();
      const draft = draftMessage({ key: k, conversationId: id, channelId: input.channelId, channelKind: input.channelKind, kind: input.kind, body: input.body, subject: input.subject ?? null, html: input.html ?? null, me, now: new Date() });
      setState((s) => ({ ...s, messages: [...s.messages, draft] }));
      return deliver(id, input, k);
    },
    [deliver, me],
  );

  /** Sends a failed message again: one that never left keeps its key (so it cannot send twice); one the server gave up on goes as a new message. */
  const retry = useCallback(
    (m: ThreadMessage) => {
      const id = current.current;
      if (!id) return;
      const channelKind = m.local?.channelKind;
      const input: SendInput = { body: m.body, kind: m.kind === "note" ? "note" : "message", channelId: m.channel_id, channelKind, subject: m.subject, html: m.html };
      if (m.local) {
        setState((s) => ({ ...s, messages: retrying(s.messages, m.local!.key) }));
        void deliver(id, input, m.local.key);
      } else {
        void submit(input);
      }
    },
    [deliver, submit],
  );

  /** A note's new text, shown at once and put back if the server says no. Returns an error sentence, or null. */
  const saveNote = useCallback(
    async (m: ThreadMessage, body: string): Promise<string | null> => {
      const id = current.current;
      if (!id) return "Open a conversation first.";
      const before = m.body;
      setState((s) => ({ ...s, messages: s.messages.map((x) => (x.id === m.id ? { ...x, body } : x)) }));
      try {
        const saved = await editNote(id, m.id, body);
        apply(id, (s) => ({ ...s, messages: mergeMessages(s.messages, [saved]) }));
        return null;
      } catch (e) {
        apply(id, (s) => ({ ...s, messages: s.messages.map((x) => (x.id === m.id ? { ...x, body: before } : x)) }));
        return whatWentWrong(e);
      }
    },
    [apply],
  );

  return { ...state, refresh, loadEarlier, setConv, submit, retry, saveNote };
}
