import { useCallback, useEffect, useRef, useState } from "react";
import type { RecordsClient } from "./client.ts";
import { primeRefs } from "./meta.tsx";
import type { Filter, RecordRow, SortSpec } from "./types.ts";

export type ListParams = { filter: Filter | null; sort: SortSpec[]; q: string };

export type ListState = {
  rows: RecordRow[];
  /** rows matching the whole query, when the server says */
  total: number | undefined;
  next: string | null;
  status: "loading" | "ready" | "error";
  error: unknown;
  loadingMore: boolean;
  moreFailed: boolean;
};

const EMPTY: ListState = { rows: [], total: undefined, next: null, status: "loading", error: null, loadingMore: false, moreFailed: false };

/**
 * The rows of a list, loaded a page at a time with the server's cursor. A new query keeps the old rows on screen
 * until the answer arrives (no flash while typing in the search box); an answer for an old query is dropped.
 */
export function useRecordList(client: RecordsClient, object: string, params: ListParams, pageSize = 100) {
  const [state, setState] = useState<ListState>(EMPTY);
  const stateRef = useRef(state);
  stateRef.current = state;
  const paramsRef = useRef(params);
  paramsRef.current = params;
  const gen = useRef(0);
  const key = JSON.stringify([object, params]);

  const load = useCallback(() => {
    const mine = ++gen.current;
    setState((s) => ({ ...s, status: "loading", error: null, loadingMore: false, moreFailed: false }));
    client.query(object, { ...paramsRef.current, limit: pageSize }).then(
      (page) => {
        if (mine !== gen.current) return;
        primeRefs(client, page.data);
        setState({ rows: page.data, total: page.total, next: page.next_cursor, status: "ready", error: null, loadingMore: false, moreFailed: false });
      },
      (error) => mine === gen.current && setState((s) => ({ ...s, status: "error", error, loadingMore: false })),
    );
  }, [client, object, pageSize]);

  // `key` stands for `params`: reload whenever they change
  useEffect(load, [load, key]);

  const loadMore = useCallback(() => {
    const s = stateRef.current;
    if (s.status !== "ready" || !s.next || s.loadingMore || s.moreFailed) return;
    const mine = gen.current;
    setState((x) => ({ ...x, loadingMore: true }));
    client.query(object, { ...paramsRef.current, limit: pageSize, cursor: s.next }).then(
      (page) => {
        if (mine !== gen.current) return;
        primeRefs(client, page.data);
        setState((x) => {
          const have = new Set(x.rows.map((r) => r.id));
          return { ...x, rows: [...x.rows, ...page.data.filter((r) => !have.has(r.id))], next: page.next_cursor, total: page.total ?? x.total, loadingMore: false };
        });
      },
      () => mine === gen.current && setState((x) => ({ ...x, loadingMore: false, moreFailed: true })),
    );
  }, [client, object, pageSize]);

  /** Swap in a row we changed ourselves (an edit, a tag), without asking the server again. */
  const patchRow = useCallback((row: RecordRow) => {
    setState((s) => {
      const i = s.rows.findIndex((r) => r.id === row.id);
      if (i < 0 || s.rows[i] === row) return s;
      const rows = s.rows.slice();
      rows[i] = row;
      return { ...s, rows };
    });
  }, []);

  const removeRows = useCallback((ids: string[]) => {
    const gone = new Set(ids);
    setState((s) => {
      const rows = s.rows.filter((r) => !gone.has(r.id));
      return { ...s, rows, total: s.total === undefined ? undefined : Math.max(0, s.total - (s.rows.length - rows.length)) };
    });
  }, []);

  const retryMore = useCallback(() => {
    setState((x) => ({ ...x, moreFailed: false }));
    setTimeout(loadMore, 0);
  }, [loadMore]);

  return { ...state, reload: load, loadMore, retryMore, patchRow, removeRows };
}
