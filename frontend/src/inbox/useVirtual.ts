import { useCallback, useEffect, useLayoutEffect, useState, type RefObject } from "react";

const OVERSCAN = 6;

/**
 * Windowing for a list of rows that are all `rowHeight` tall (the CSS holds them to it): which rows to draw for the scroll
 * position of `scroller`, and a way to scroll one into view. Only about a screenful of rows is ever in the DOM.
 */
export function useVirtual(scroller: RefObject<HTMLElement | null>, count: number, rowHeight: number) {
  const [range, setRange] = useState({ start: 0, end: Math.min(count, 24) });
  const update = useCallback(() => {
    const el = scroller.current;
    if (!el) return;
    const first = Math.floor(el.scrollTop / rowHeight);
    const visible = Math.ceil(el.clientHeight / rowHeight) + 1;
    const start = Math.max(0, first - OVERSCAN);
    const end = Math.min(count, first + visible + OVERSCAN);
    setRange((r) => (r.start === start && r.end === end ? r : { start, end }));
  }, [scroller, count, rowHeight]);

  useLayoutEffect(update);
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    let raf = 0;
    const tick = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(update);
    };
    el.addEventListener("scroll", tick, { passive: true });
    const ro = new ResizeObserver(tick);
    ro.observe(el);
    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener("scroll", tick);
      ro.disconnect();
    };
  }, [scroller, update]);

  /** Scrolls the row at `index` into view, by the least distance. */
  const reveal = useCallback(
    (index: number) => {
      const el = scroller.current;
      if (!el || index < 0) return;
      const top = index * rowHeight;
      if (top < el.scrollTop) el.scrollTop = top;
      else if (top + rowHeight > el.scrollTop + el.clientHeight) el.scrollTop = top + rowHeight - el.clientHeight;
    },
    [scroller, rowHeight],
  );

  return { start: Math.min(range.start, count), end: Math.min(range.end, count), reveal };
}
