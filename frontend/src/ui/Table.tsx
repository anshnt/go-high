import { ArrowDown, ArrowUp, ChevronsUpDown } from "lucide-react";
import { useCallback, useEffect, useLayoutEffect, useRef, useState, type MouseEvent, type ReactNode, type Ref, type RefObject } from "react";
import { density } from "../lib/prefs";
import { cn } from "../lib/cn";
import { Checkbox } from "./Toggle";
import { Skeleton } from "./Display";

export type Column<T> = {
  key: string;
  header: string;
  cell: (row: T) => ReactNode;
  sortable?: boolean;
  align?: "right";
  /** ids, codes, numbers */
  mono?: boolean;
  /** px. Give every column one and the table uses fixed widths (needed for `virtual`, so columns do not jump as rows scroll). */
  width?: number;
};
export type Sort = { key: string; dir: "asc" | "desc" };

type Props<T> = {
  columns: Column<T>[];
  rows: T[];
  rowId: (row: T) => string;
  caption: string;
  sort?: Sort;
  onSortChange?: (s: Sort) => void;
  selected?: Set<string>;
  onSelectedChange?: (s: Set<string>) => void;
  loading?: boolean;
  empty?: ReactNode;
  className?: string;
  /** Only the rows near the viewport are in the DOM; the wrapper scrolls (give it a height). Rows are one `--row-h` tall. */
  virtual?: boolean;
  /** Clicking a row (not a link, button or checkbox inside it). */
  onRowClick?: (row: T) => void;
  /** The keyboard cursor or open row: highlighted, and scrolled into view when it changes. */
  activeId?: string | null;
  /** `virtual` only: the last loaded row is about to scroll into view, so load more. */
  onEndReached?: () => void;
  skeletonRows?: number;
  /** Under the last row, inside the scroll area (for "loading more"). */
  footer?: ReactNode;
  /** "Select Ada Lovelace" instead of "Select row ct_0001". */
  rowLabel?: (row: T) => string;
  wrapRef?: Ref<HTMLDivElement>;
};

const OVERSCAN = 6;
const END_MARGIN = 20;

/** Which rows to render for the scroll position of `wrap`. Row height is read from the DOM, so density and the phone layout just work. */
function useWindow(enabled: boolean, count: number, wrap: RefObject<HTMLDivElement | null>) {
  const [win, setWin] = useState({ start: 0, end: 40, h: 44 });
  const rowH = useRef(44);
  const update = useCallback(() => {
    const el = wrap.current;
    if (!el) return;
    const tr = el.querySelector<HTMLElement>("tbody tr[data-row]");
    const h = tr ? tr.getBoundingClientRect().height : 0;
    if (h > 0) rowH.current = h;
    const head = el.querySelector("thead")?.getBoundingClientRect().height ?? rowH.current;
    const first = Math.floor(Math.max(0, el.scrollTop - head) / rowH.current);
    const visible = Math.ceil(el.clientHeight / rowH.current) + 1;
    const start = Math.max(0, first - OVERSCAN);
    const end = Math.min(count, first + visible + OVERSCAN);
    setWin((w) => (w.start === start && w.end === end && w.h === rowH.current ? w : { start, end, h: rowH.current }));
  }, [count, wrap]);

  useLayoutEffect(() => {
    if (enabled) update();
  });
  useEffect(() => {
    const el = wrap.current;
    if (!enabled || !el) return;
    let raf = 0;
    const tick = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(update);
    };
    el.addEventListener("scroll", tick, { passive: true });
    const ro = new ResizeObserver(tick);
    ro.observe(el);
    const off = density.subscribe(tick);
    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener("scroll", tick);
      ro.disconnect();
      off();
    };
  }, [enabled, update, wrap]);
  return win;
}

export function Table<T>({
  columns,
  rows,
  rowId,
  caption,
  sort,
  onSortChange,
  selected,
  onSelectedChange,
  loading,
  empty,
  className,
  virtual,
  onRowClick,
  activeId,
  onEndReached,
  skeletonRows = 4,
  footer,
  rowLabel,
  wrapRef,
}: Props<T>) {
  const selectable = !!selected && !!onSelectedChange;
  const ids = rows.map(rowId);
  const all = selectable && ids.length > 0 && ids.every((id) => selected.has(id));
  const some = selectable && ids.some((id) => selected.has(id));
  const toggle = (id: string, on: boolean) => {
    const next = new Set(selected);
    if (on) next.add(id);
    else next.delete(id);
    onSelectedChange?.(next);
  };
  const nextSort = (key: string): Sort => ({ key, dir: sort?.key === key && sort.dir === "asc" ? "desc" : "asc" });

  const wrap = useRef<HTMLDivElement | null>(null);
  const setWrap = useCallback(
    (node: HTMLDivElement | null) => {
      wrap.current = node;
      if (typeof wrapRef === "function") wrapRef(node);
      else if (wrapRef) (wrapRef as { current: HTMLDivElement | null }).current = node;
    },
    [wrapRef],
  );
  const win = useWindow(!!virtual && !loading, rows.length, wrap);
  const windowed = !!virtual && !loading;
  const start = windowed ? Math.min(win.start, rows.length) : 0;
  const end = windowed ? Math.min(win.end, rows.length) : rows.length;

  // Ask for more when the last loaded row is within a screenful.
  useEffect(() => {
    if (windowed && onEndReached && rows.length > 0 && end >= rows.length - END_MARGIN) onEndReached();
  }, [windowed, onEndReached, end, rows.length]);

  // Keep the active row in view (keyboard moves, or opening a row).
  const activeIndex = activeId ? ids.indexOf(activeId) : -1;
  useLayoutEffect(() => {
    const el = wrap.current;
    if (!el || !windowed || activeIndex < 0) return;
    const head = el.querySelector("thead")?.getBoundingClientRect().height ?? win.h;
    const top = head + activeIndex * win.h;
    if (top - head < el.scrollTop) el.scrollTop = top - head;
    else if (top + win.h > el.scrollTop + el.clientHeight) el.scrollTop = top + win.h - el.clientHeight;
    // only when the active row changes, not on every scroll
  }, [activeIndex, windowed]);

  const fixed = columns.length > 0 && columns.every((c) => c.width);
  const minWidth = fixed ? columns.reduce((n, c) => n + c.width!, 0) + (selectable ? 44 : 0) : undefined;
  const span = columns.length + (selectable ? 1 : 0);

  const click = (row: T) => (e: MouseEvent) => {
    // a click in a menu or dialog opened from the row reaches the row through React's tree, not the DOM's: not a row click
    if (!(e.currentTarget as Node).contains(e.target as Node)) return;
    if ((e.target as HTMLElement).closest("a, button, input, label, [role='checkbox'], [role='button']")) return;
    onRowClick?.(row);
  };

  return (
    <div className={cn("ui-table-wrap", className)} ref={setWrap}>
      <table className="ui-table" data-fixed={fixed || undefined} aria-rowcount={windowed ? rows.length + 1 : undefined} style={fixed ? { minWidth } : undefined}>
        <caption className="sr-only">{caption}</caption>
        {fixed && (
          <colgroup>
            {selectable && <col style={{ width: 44 }} />}
            {columns.map((c) => (
              <col key={c.key} style={{ width: c.width }} />
            ))}
          </colgroup>
        )}
        <thead>
          <tr>
            {selectable && (
              <th className="ui-th-check">
                <Checkbox
                  aria-label="Select all rows"
                  checked={all ? true : some ? "indeterminate" : false}
                  onCheckedChange={(on) => onSelectedChange?.(on ? new Set(ids) : new Set())}
                />
              </th>
            )}
            {columns.map((c) => (
              <th
                key={c.key}
                data-align={c.align}
                aria-sort={sort?.key === c.key ? (sort.dir === "asc" ? "ascending" : "descending") : c.sortable ? "none" : undefined}
              >
                {c.sortable ? (
                  <button type="button" className="ui-sort" onClick={() => onSortChange?.(nextSort(c.key))}>
                    {c.header}
                    {sort?.key === c.key ? sort.dir === "asc" ? <ArrowUp size={14} aria-hidden /> : <ArrowDown size={14} aria-hidden /> : <ChevronsUpDown size={14} aria-hidden />}
                  </button>
                ) : (
                  c.header
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody aria-busy={loading || undefined}>
          {loading ? (
            Array.from({ length: skeletonRows }, (_, i) => (
              <tr key={i}>
                {selectable && <td />}
                {columns.map((c) => (
                  <td key={c.key}>
                    <Skeleton style={{ width: `${55 + ((i + c.key.length) % 4) * 10}%` }} />
                  </td>
                ))}
              </tr>
            ))
          ) : (
            <>
              {windowed && start > 0 && (
                <tr className="ui-spacer" aria-hidden style={{ height: start * win.h }}>
                  <td colSpan={span} />
                </tr>
              )}
              {rows.slice(start, end).map((r, k) => {
                const id = rowId(r);
                return (
                  <tr
                    key={id}
                    data-row
                    data-selected={selected?.has(id) || undefined}
                    data-active={id === activeId || undefined}
                    data-clickable={onRowClick ? true : undefined}
                    aria-rowindex={windowed ? start + k + 2 : undefined}
                    onClick={onRowClick ? click(r) : undefined}
                  >
                    {selectable && (
                      <td className="ui-th-check">
                        <Checkbox aria-label={`Select ${rowLabel ? rowLabel(r) : `row ${id}`}`} checked={selected.has(id)} onCheckedChange={(on) => toggle(id, on)} />
                      </td>
                    )}
                    {columns.map((c) => (
                      <td key={c.key} data-align={c.align} className={c.mono ? "mono" : undefined}>
                        {c.cell(r)}
                      </td>
                    ))}
                  </tr>
                );
              })}
              {windowed && end < rows.length && (
                <tr className="ui-spacer" aria-hidden style={{ height: (rows.length - end) * win.h }}>
                  <td colSpan={span} />
                </tr>
              )}
            </>
          )}
        </tbody>
      </table>
      {!loading && rows.length === 0 && empty}
      {footer}
    </div>
  );
}
