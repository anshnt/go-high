import { useCallback, useEffect, useRef, useState } from "react";
import { RecordsError } from "../records/errors.ts";
import type { RecordRow } from "../records/types.ts";
import { appendCards, moveCard, neighbours, patchCard, replaceCard } from "./board.ts";
import { DEFAULT_CARD_FIELDS, type BoardStage, type Card, type Layout, type MoveInput, type PipelineClient } from "./types.ts";

export const PAGE = 25;
const DEFAULT_LAYOUT: Layout = { collapsed: [], card_fields: DEFAULT_CARD_FIELDS };

export type MoveResult = { ok: true; card: Card; to: BoardStage } | { ok: false; error: unknown };
type MoreState = Record<string, "loading" | "failed">;

type State = { status: "loading" | "ready" | "error"; error: unknown; columns: BoardStage[]; layout: Layout; refreshing: boolean };

/**
 * One pipeline's board: its columns with the first page of cards each, the caller's layout, more pages per column, and moves
 * that show at once and go back if the server says no. Moves are sent one at a time, in the order they were made, so the
 * neighbours each one names are the cards the person saw. Whatever happens, a quiet reload follows a failed move.
 */
export function useBoard(client: PipelineClient, pipelineId: string) {
  const [state, setState] = useState<State>({ status: "loading", error: null, columns: [], layout: DEFAULT_LAYOUT, refreshing: false });
  const [more, setMore] = useState<MoreState>({});
  const columnsRef = useRef<BoardStage[]>([]);
  const layoutRef = useRef<Layout>(DEFAULT_LAYOUT);
  const moreRef = useRef<MoreState>({});
  const gen = useRef(0);
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const inflight = useRef(0);
  const stale = useRef(false);

  const commit = useCallback((columns: BoardStage[]) => {
    if (columns === columnsRef.current) return;
    columnsRef.current = columns;
    setState((s) => ({ ...s, columns }));
  }, []);

  const setMoreState = (stageId: string, v: "loading" | "failed" | null) => {
    const next = { ...moreRef.current };
    if (v) next[stageId] = v;
    else delete next[stageId];
    moreRef.current = next;
    setMore(next);
  };

  /** Fetches the board. `keep` keeps what is on screen until the answer comes (a reload after a move or a change elsewhere). */
  const load = useCallback(
    async (keep = false): Promise<boolean> => {
      const mine = ++gen.current;
      setState((s) => (keep && s.status === "ready" ? { ...s, refreshing: true } : { status: "loading", error: null, columns: [], layout: DEFAULT_LAYOUT, refreshing: false }));
      try {
        const [board, layout] = await Promise.all([client.board(pipelineId, PAGE), client.layout(pipelineId).catch(() => DEFAULT_LAYOUT)]);
        if (mine !== gen.current) return true;
        columnsRef.current = board.stages;
        layoutRef.current = layout;
        moreRef.current = {};
        setMore({});
        setState({ status: "ready", error: null, columns: board.stages, layout, refreshing: false });
        return true;
      } catch (error) {
        if (mine !== gen.current) return true;
        setState((s) => (keep && s.columns.length ? { ...s, refreshing: false } : { status: "error", error, columns: [], layout: DEFAULT_LAYOUT, refreshing: false }));
        return false;
      }
    },
    [client, pipelineId],
  );

  useEffect(() => {
    void load();
    return () => void ++gen.current;
  }, [load]);

  const loadMore = useCallback(
    async (stageId: string) => {
      const col = columnsRef.current.find((c) => c.id === stageId);
      if (!col?.next_cursor || moreRef.current[stageId]) return;
      const mine = gen.current;
      setMoreState(stageId, "loading");
      try {
        const page = await client.column(pipelineId, stageId, col.next_cursor);
        if (mine !== gen.current) return;
        commit(appendCards(columnsRef.current, stageId, page.deals, page.next_cursor));
        setMoreState(stageId, null);
      } catch {
        if (mine === gen.current) setMoreState(stageId, "failed");
      }
    },
    [client, pipelineId, commit],
  );

  const retryMore = useCallback(
    (stageId: string) => {
      setMoreState(stageId, null);
      void loadMore(stageId);
    },
    [loadMore],
  );

  /** Moves `card` to `slot` of a stage (see `neighbours`). Resolves when the server has answered; the board has already changed. */
  const move = useCallback(
    (card: Card, toStage: string, slot: number, extra: Pick<MoveInput, "lost_reason" | "lost_note"> = {}): Promise<MoveResult> => {
      const before = columnsRef.current;
      const target = before.find((c) => c.id === toStage);
      const moved = moveCard(before, card.id, toStage, slot);
      if (!target || !moved) return Promise.resolve({ ok: false, error: new RecordsError(404, "That deal is not on the board any more. Reload the board.") });
      const near = neighbours(target.deals, card.id, slot);
      commit(moved.columns);
      inflight.current++;
      const run = async (): Promise<MoveResult> => {
        try {
          const saved = await client.move(card.id, { stage_id: toStage, ...near, ...extra });
          commit(replaceCard(columnsRef.current, saved));
          return { ok: true, card: saved, to: target };
        } catch (error) {
          commit(before); // the board as it was before this move
          stale.current = true;
          return { ok: false, error };
        } finally {
          inflight.current--;
          if (stale.current && inflight.current === 0) {
            stale.current = false;
            void load(true); // the server's word on every card, after the moves that followed the failed one
          }
        }
      };
      const job = chain.current.then(run);
      chain.current = job;
      return job;
    },
    [client, commit, load],
  );

  /** A deal changed beside the board (the record panel): its card follows, and the column's sums by the difference. */
  const patchFromRecord = useCallback(
    (row: RecordRow) => commit(patchCard(columnsRef.current, { id: row.id, display_name: row.display_name, owner_id: row.owner_id, values: row.values })),
    [commit],
  );

  // Layouts are saved whole, one after another, so the last choice is the one that stays.
  const layoutChain = useRef<Promise<unknown>>(Promise.resolve());
  /** Saves the caller's layout: shown at once, put back if the server refuses. Resolves with the error, or null. */
  const saveLayout = useCallback(
    (next: Layout): Promise<unknown> => {
      const before = layoutRef.current;
      layoutRef.current = next;
      setState((s) => ({ ...s, layout: next }));
      const job = layoutChain.current.then(async () => {
        try {
          await client.saveLayout(pipelineId, next);
          return null;
        } catch (error) {
          if (layoutRef.current === next) {
            layoutRef.current = before;
            setState((s) => ({ ...s, layout: before }));
          }
          return error;
        }
      });
      layoutChain.current = job;
      return job;
    },
    [client, pipelineId],
  );

  const reload = useCallback(() => load(true), [load]);
  return { ...state, more, reload, loadMore, retryMore, move, patchFromRecord, saveLayout };
}
