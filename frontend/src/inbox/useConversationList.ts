import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { whatWentWrong } from "../lib/errors";
import { getConversation, listConversations } from "./api";
import type { Conversation, ConversationPage, Counts, ViewId } from "./types.ts";
import { byActivity, EMPTY_COUNTS, withCounts, withRow, type Filter } from "./views.ts";

// A search looks at every status, so a closed conversation can be found; each view is its own query with its own cursor.
const SEARCH_VIEWS: ViewId[] = ["open", "snoozed", "closed"];
const PAGE = 50;
const SEARCH_PAGE = 30;

export type ListState = {
  rows: Conversation[];
  /** The next page of each view being read; a view with none is read to the end. */
  cursors: Partial<Record<ViewId, string>>;
  counts: Counts;
  status: "loading" | "ready" | "error";
  error?: string;
  loadingMore: boolean;
};

const START: ListState = { rows: [], cursors: {}, counts: EMPTY_COUNTS, status: "loading", loadingMore: false };

function merge(pages: { view: ViewId; page: ConversationPage }[], keep: Conversation[] = []): { rows: Conversation[]; cursors: ListState["cursors"] } {
  const byId = new Map(keep.map((r) => [r.id, r]));
  const cursors: ListState["cursors"] = {};
  for (const { view, page } of pages) {
    for (const r of page.data) byId.set(r.id, r);
    if (page.next_cursor) cursors[view] = page.next_cursor;
  }
  return { rows: [...byId.values()].sort(byActivity), cursors };
}

/**
 * The conversations of one view (or a search), most recent first, paged by cursor, with the counts of every view.
 * Changes arrive two ways: `apply` (an action the person just took: the row and the counts move at once) and
 * `refreshRow` / `refreshCounts` / `refresh` (the stream says something changed: ask the API again for just that).
 */
export function useConversationList(view: ViewId, channel: string | null, q: string, me: string | null, workspace: string | null) {
  const [state, setState] = useState<ListState>(START);
  const generation = useRef(0);
  const filter = useMemo<Filter>(() => ({ view, channel }), [view, channel]);
  const latest = useRef({ filter, q, me, state });
  latest.current = { filter, q, me, state };
  const searching = q.trim().length > 0;

  const first = useCallback(async (): Promise<ListState | null> => {
    const g = ++generation.current;
    const views = q.trim() ? SEARCH_VIEWS : [view];
    try {
      const pages = await Promise.all(views.map(async (v) => ({ view: v, page: await listConversations({ view: v, channel, q: q.trim() || undefined, limit: q.trim() ? SEARCH_PAGE : PAGE }) })));
      if (g !== generation.current) return null;
      const counts = pages[0]!.page.counts ?? EMPTY_COUNTS;
      return { ...merge(pages), counts, status: "ready", loadingMore: false };
    } catch (e) {
      if (g !== generation.current) return null;
      return { ...latest.current.state, status: "error", error: whatWentWrong(e), loadingMore: false };
    }
  }, [view, channel, q]);

  // A new view, channel, search or workspace starts over; the rows of the old one are not shown under the new title.
  useEffect(() => {
    setState(START);
    let live = true;
    void first().then((s) => live && s && setState(s));
    return () => {
      live = false;
    };
  }, [first, workspace]);

  /** Reads the first page again and keeps what is on screen until it arrives (the stream asked, or the connection came back). */
  const refresh = useCallback(async () => {
    const next = await first();
    if (next && next.status === "ready") setState((s) => ({ ...next, rows: mergeKeepingLoaded(s.rows, next) }));
  }, [first]);

  const loadMore = useCallback(async () => {
    const { state: s, filter: f, q: query } = latest.current;
    const open = Object.entries(s.cursors) as [ViewId, string][];
    if (s.loadingMore || s.status !== "ready" || open.length === 0) return;
    setState((x) => ({ ...x, loadingMore: true }));
    const g = generation.current;
    try {
      const pages = await Promise.all(open.map(async ([v, cursor]) => ({ view: v, page: await listConversations({ view: v, channel: f.channel, q: query.trim() || undefined, cursor, limit: query.trim() ? SEARCH_PAGE : PAGE }) })));
      if (g !== generation.current) return;
      setState((x) => {
        const done = Object.fromEntries(open.map(([v]) => [v, undefined]));
        const next = merge(pages, x.rows);
        return { ...x, rows: next.rows, cursors: { ...x.cursors, ...done, ...next.cursors }, loadingMore: false };
      });
    } catch {
      if (g === generation.current) setState((x) => ({ ...x, loadingMore: false }));
    }
  }, []);

  /** A conversation changed (read from the API): its row, in place, in or out of this list as it now belongs. */
  const applyRow = useCallback((next: Conversation) => {
    const { filter: f, q: query, me: who } = latest.current;
    setState((s) => ({ ...s, rows: withRow(s.rows, next, f, who, query.trim().length > 0, Object.keys(s.cursors).length > 0) }));
  }, []);

  /** An action the person took: the row and the counts move at once, before the server has answered. */
  const applyChange = useCallback((before: Conversation | null, after: Conversation) => {
    const { filter: f, q: query, me: who } = latest.current;
    setState((s) => ({ ...s, rows: withRow(s.rows, after, f, who, query.trim().length > 0, Object.keys(s.cursors).length > 0), counts: withCounts(s.counts, before, after, who) }));
  }, []);

  const refreshRow = useCallback(
    async (id: string) => {
      try {
        const { messages: _messages, last_read_seq: _mark, ...row } = await getConversation(id, 1);
        applyRow(row);
        return row;
      } catch {
        return null; // gone, or no longer ours to see: the next full read drops it
      }
    },
    [applyRow],
  );

  const refreshCounts = useCallback(async () => {
    try {
      const page = await listConversations({ view: "open", limit: 1 });
      if (page.counts) setState((s) => ({ ...s, counts: page.counts! }));
    } catch {
      /* the counts keep what they had */
    }
  }, []);

  return { ...state, searching, refresh, loadMore, applyRow, applyChange, refreshRow, refreshCounts };
}

// A refresh reads the first page only; rows from later pages that are already loaded stay, newer data wins.
function mergeKeepingLoaded(current: Conversation[], next: ListState): Conversation[] {
  if (Object.keys(next.cursors).length === 0 && current.length <= next.rows.length) return next.rows;
  const fresh = new Map(next.rows.map((r) => [r.id, r]));
  const oldest = next.rows.length ? next.rows[next.rows.length - 1]!.last_message_at : "";
  const older = current.filter((r) => !fresh.has(r.id) && r.last_message_at < oldest);
  return [...next.rows, ...older].sort(byActivity);
}
