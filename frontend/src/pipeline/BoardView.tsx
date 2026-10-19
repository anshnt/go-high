import { PanelLeftClose, PanelLeftOpen, Plus } from "lucide-react";
import { Fragment, useEffect, useLayoutEffect, useMemo, useRef, useState, type DragEvent, type KeyboardEvent } from "react";
import type { FieldDef } from "../records/types.ts";
import { Button, Tooltip } from "../ui";
import { describeSums, focusTarget, formatSums, isFiltered, passes, slotFromY, summarize, toFullSlot, type Dir, type Quick, type Shown } from "./board.ts";
import { DealCard, dotColor } from "./DealCard";
import type { BoardStage, Card, Layout } from "./types.ts";

const CAP = 500; // ponytail: a filter loads every page of a column to be complete, up to this many cards; past it the count says "+"

export type BoardViewProps = {
  columns: BoardStage[];
  layout: Layout;
  filter: Quick;
  me?: string;
  /** the deal object's fields, by key */
  fields: Map<string, FieldDef>;
  hasAmount: boolean;
  sums: "total" | "weighted";
  canWrite: boolean;
  more: Record<string, "loading" | "failed">;
  openId: string | null;
  refreshing: boolean;
  onOpen: (id: string) => void;
  /** `slot`: the place among the target's loaded cards without this one (see board.ts `neighbours`) */
  onMove: (card: Card, stageId: string, slot: number, how: "drop" | "menu" | "keyboard") => void;
  onToggleCollapsed: (stageId: string) => void;
  onLoadMore: (stageId: string) => void;
  onRetryMore: (stageId: string) => void;
  onNewDeal: (stageId: string) => void;
};

type Drag = { id: string; from: string };
type Over = { stageId: string; slot: number };

/** The board's columns and their cards. Drag and drop, a "Move to stage" menu and the keyboard all end in `onMove`. */
export function BoardView(props: BoardViewProps) {
  const { columns, layout, filter } = props;
  const [drag, setDrag] = useState<Drag | null>(null);
  const [over, setOver] = useState<Over | null>(null);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [tabId, setTabId] = useState<string | null>(null);
  const [refocus, setRefocus] = useState<string | null>(null);
  const els = useRef(new Map<string, HTMLElement>());
  const rootRef = useRef<HTMLDivElement>(null);
  const now = useMemo(() => Date.now(), [columns]); // eslint-disable-line react-hooks/exhaustive-deps -- a card's ages are as of the last change to the board

  const filtering = isFiltered(filter);
  const keep = useMemo(() => (filtering ? (c: Card) => passes(c, filter, props.me, new Date()) : null), [filtering, filter, props.me]);
  const shown: Shown[] = useMemo(() => columns.map((c) => summarize(c, keep)), [columns, keep]);
  const collapsed = useMemo(() => new Set(layout.collapsed), [layout.collapsed]);
  const lists = useMemo(() => columns.map((c, i) => (collapsed.has(c.id) ? [] : shown[i]!.deals.map((d) => d.id))), [columns, shown, collapsed]);
  const tabStop = tabId && lists.some((l) => l.includes(tabId)) ? tabId : (lists.flat()[0] ?? null);

  // A filter is only right when it has seen every card, so while one is on, the rest of each column loads (up to CAP).
  useEffect(() => {
    if (!filtering) return;
    for (const c of columns) if (c.next_cursor && c.deals.length < CAP && !props.more[c.id]) props.onLoadMore(c.id);
  }, [filtering, columns, props.more]); // eslint-disable-line react-hooks/exhaustive-deps

  // After a keyboard move the card may have been drawn again in another column: take focus back to it.
  useLayoutEffect(() => {
    if (!refocus) return;
    const el = els.current.get(refocus);
    const active = document.activeElement;
    if (el && (!active || active === document.body || rootRef.current?.contains(active))) el.focus();
    setRefocus(null);
  }, [refocus, columns]);

  // Everything the handlers need is read from here, so they stay the same functions and a card does not redraw for nothing.
  const latest = useRef({ props, columns, shown, lists, drag, over });
  latest.current = { props, columns, shown, lists, drag, over };

  const act = useMemo(() => {
    const L = () => latest.current;
    const find = (id: string) => {
      for (const c of L().columns) {
        const card = c.deals.find((d) => d.id === id);
        if (card) return { card, col: c };
      }
      return null;
    };
    /** The slot a pointer at `y` means in a column: how many of the other cards are above it. */
    const slotAt = (section: HTMLElement, dragId: string, y: number) => {
      const mids = [...section.querySelectorAll<HTMLElement>(".pl-card")]
        .filter((el) => el.dataset.cardId !== dragId)
        .map((el) => {
          const r = el.getBoundingClientRect();
          return r.top + r.height / 2;
        });
      return slotFromY(mids, y);
    };
    /** Moves a card to a slot among the shown cards of a column, which is a slot among the loaded ones when a filter hides some. */
    const moveTo = (card: Card, col: BoardStage, slot: number, how: "drop" | "menu" | "keyboard") => {
      const { shown: s, columns: cols, props: p } = L();
      p.onMove(card, col.id, toFullSlot(col.deals, s[cols.findIndex((c) => c.id === col.id)]!.deals, card.id, slot), how);
    };
    return {
      open: (id: string) => L().props.onOpen(id),
      menuOpen: (id: string | null) => setMenuFor(id),
      moveToStage: (card: Card, stageId: string) => L().props.onMove(card, stageId, 0, "menu"),
      focus: (id: string) => setTabId(id),
      setEl: (id: string, el: HTMLElement | null) => void (el ? els.current.set(id, el) : els.current.delete(id)),
      dragStart: (card: Card, e: DragEvent) => {
        e.dataTransfer.effectAllowed = "move";
        e.dataTransfer.setData("text/plain", card.id);
        setTimeout(() => setDrag({ id: card.id, from: card.stage_id }), 0); // after the browser has taken its picture of the card
      },
      dragEnd: () => {
        setDrag(null);
        setOver(null);
      },
      dragOver: (col: BoardStage, isCollapsed: boolean, e: DragEvent<HTMLElement>) => {
        const d = L().drag;
        if (!d) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "move";
        const slot = isCollapsed ? 0 : slotAt(e.currentTarget, d.id, e.clientY);
        setOver((o) => (o && o.stageId === col.id && o.slot === slot ? o : { stageId: col.id, slot }));
      },
      dragLeave: (col: BoardStage, e: DragEvent<HTMLElement>) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver((o) => (o && o.stageId === col.id ? null : o));
      },
      drop: (col: BoardStage, e: DragEvent<HTMLElement>) => {
        const { drag: d, over: o, shown: s, columns: cols } = L();
        e.preventDefault();
        setDrag(null);
        setOver(null);
        const hit = d && find(d.id);
        if (!hit || !o || o.stageId !== col.id) return;
        // dropped where it already is: nothing to do
        const here = s[cols.findIndex((c) => c.id === col.id)]!.deals.findIndex((c) => c.id === hit.card.id);
        if (hit.col.id === col.id && here === o.slot) return;
        moveTo(hit.card, col, o.slot, "drop");
      },
      key: (card: Card, e: KeyboardEvent<HTMLElement>) => {
        if (e.target !== e.currentTarget || e.ctrlKey || e.metaKey || e.altKey) return;
        const { columns: cols, lists: ls, props: p } = L();
        const ci = cols.findIndex((c) => c.id === card.stage_id);
        const ri = ls[ci]?.indexOf(card.id) ?? -1;
        if (e.key === "Enter") {
          e.preventDefault();
          p.onOpen(card.id);
        } else if (e.key === "m" || e.key === "M") {
          e.preventDefault();
          setMenuFor(card.id);
        } else if (e.key.startsWith("Arrow") && ci >= 0 && ri >= 0) {
          e.preventDefault();
          const dir = e.key.slice(5).toLowerCase() as Dir;
          if (!e.shiftKey) {
            const id = focusTarget(ls, ci, ri, dir);
            if (id) els.current.get(id)?.focus();
            else if (dir === "down" && cols[ci]!.next_cursor) p.onLoadMore(card.stage_id);
            return;
          }
          if (!p.canWrite) return;
          if (dir === "up" || dir === "down") {
            const to = ri + (dir === "up" ? -1 : 1);
            if (to < 0 || to >= ls[ci]!.length) return;
            setRefocus(card.id);
            moveTo(card, cols[ci]!, to, "keyboard");
          } else {
            const next = cols[ci + (dir === "left" ? -1 : 1)];
            if (!next) return;
            setRefocus(card.id);
            p.onMove(card, next.id, 0, "keyboard");
          }
        }
      },
    };
  }, []);

  return (
    <div className="pl-board" ref={rootRef} data-refreshing={props.refreshing || undefined} data-dragging={drag ? true : undefined}>
      <p id="pl-help" className="sr-only">
        Enter opens the deal. M opens the menu to move it to a stage. Arrow keys move between deals. Shift with an arrow key moves the deal: up and down within the stage, left and right to the next stage.
      </p>
      {columns.map((col, i) => {
        const s = shown[i]!;
        const isCollapsed = collapsed.has(col.id);
        const sumText = props.hasAmount ? formatSums(props.sums === "weighted" ? s.weighted : s.amount) : "";
        const slot = over?.stageId === col.id ? over.slot : -1;
        const countText = `${s.count.toLocaleString("en-US")}${s.partial ? "+" : ""}`;
        const label = `${col.name}, ${s.count} ${s.count === 1 ? "deal" : "deals"}${s.partial ? " or more" : ""}`;
        const loadingMore = props.more[col.id];
        const drops = {
          onDragOver: (e: DragEvent<HTMLElement>) => props.canWrite && act.dragOver(col, isCollapsed, e),
          onDragLeave: (e: DragEvent<HTMLElement>) => act.dragLeave(col, e),
          onDrop: (e: DragEvent<HTMLElement>) => props.canWrite && act.drop(col, e),
        };

        if (isCollapsed) {
          return (
            <section key={col.id} className="pl-col" data-collapsed data-over={slot >= 0 || undefined} aria-label={label} {...drops}>
              <button type="button" className="pl-col-strip" aria-label={`Expand ${label}`} aria-expanded={false} onClick={() => props.onToggleCollapsed(col.id)}>
                <PanelLeftOpen size={14} aria-hidden />
                <span className="pl-dot" style={{ background: dotColor(col.color) }} aria-hidden />
                <span className="pl-col-strip-name">{col.name}</span>
                <span className="pl-count num">{countText}</span>
              </button>
            </section>
          );
        }

        let at = 0; // the place of the next card among those that are not being dragged
        return (
          <section key={col.id} className="pl-col" data-kind={col.kind} data-over={slot >= 0 || undefined} aria-label={label} {...drops}>
            <header className="pl-col-head">
              <div className="pl-col-title">
                <span className="pl-dot" style={{ background: dotColor(col.color) }} aria-hidden />
                <h2>{col.name}</h2>
                <span className="pl-count num" title={filtering ? `${s.count} of ${col.count} deals match` : undefined}>
                  {countText}
                </span>
                <span className="pl-col-actions">
                  {props.canWrite && col.kind === "open" && (
                    <Tooltip content={`New deal in ${col.name}`}>
                      <Button size="icon" variant="ghost" className="pl-col-btn" aria-label={`New deal in ${col.name}`} onClick={() => props.onNewDeal(col.id)}>
                        <Plus size={16} aria-hidden />
                      </Button>
                    </Tooltip>
                  )}
                  <Tooltip content={`Collapse ${col.name}`}>
                    <Button size="icon" variant="ghost" className="pl-col-btn" aria-label={`Collapse ${col.name}`} aria-expanded onClick={() => props.onToggleCollapsed(col.id)}>
                      <PanelLeftClose size={16} aria-hidden />
                    </Button>
                  </Tooltip>
                </span>
              </div>
              {props.hasAmount && (
                <p className="pl-col-sums num" title={sumText ? `${describeSums(s.amount, s.weighted)}. ${col.probability}% probability.` : undefined}>
                  {sumText ? (
                    <>
                      {sumText}
                      {props.sums === "weighted" && <span className="pl-col-sums-note"> weighted</span>}
                    </>
                  ) : (
                    <span className="pl-col-sums-note">{s.count > 0 ? "No amounts" : `${col.probability}% probability`}</span>
                  )}
                </p>
              )}
            </header>
            <ul className="pl-cards" role="list" aria-label={`${col.name} deals`}>
              {s.deals.map((card) => {
                const dragged = drag?.id === card.id;
                const here = dragged ? -1 : at++;
                return (
                  <Fragment key={card.id}>
                    {here === slot && <li className="pl-drop" aria-hidden />}
                    <DealCard
                      card={card}
                      stage={col}
                      stages={columns}
                      cardFields={layout.card_fields}
                      fields={props.fields}
                      hasAmount={props.hasAmount}
                      canMove={props.canWrite}
                      dragging={dragged}
                      tabStop={tabStop === card.id}
                      menuOpen={menuFor === card.id}
                      open={props.openId === card.id}
                      now={now}
                      onOpen={act.open}
                      onMenuOpen={act.menuOpen}
                      onMoveTo={act.moveToStage}
                      onDragStart={act.dragStart}
                      onDragEnd={act.dragEnd}
                      onKeyDown={act.key}
                      onFocus={act.focus}
                      setEl={act.setEl}
                    />
                  </Fragment>
                );
              })}
              {slot >= at && slot >= 0 && <li className="pl-drop" aria-hidden />}
              {s.deals.length === 0 && !loadingMore && <li className="pl-empty">{filtering && col.count > 0 ? "No deals match" : "No deals"}</li>}
              {col.next_cursor && <More id={col.id} count={col.deals.length} state={loadingMore} onVisible={props.onLoadMore} onRetry={props.onRetryMore} />}
            </ul>
          </section>
        );
      })}
    </div>
  );
}

/** The end of a column that has more cards: loads the next page when it scrolls into view. */
function More({ id, count, state, onVisible, onRetry }: { id: string; count: number; state?: "loading" | "failed"; onVisible: (id: string) => void; onRetry: (id: string) => void }) {
  const ref = useRef<HTMLLIElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (!el || state) return;
    const io = new IntersectionObserver((hits) => hits.some((h) => h.isIntersecting) && onVisible(id), { root: el.closest(".pl-cards"), rootMargin: "240px" });
    io.observe(el);
    return () => io.disconnect();
  }, [id, count, state, onVisible]);
  return (
    <li ref={ref} className="pl-more">
      {state === "failed" ? (
        <>
          Could not load more.{" "}
          <Button size="sm" variant="ghost" onClick={() => onRetry(id)}>
            Try again
          </Button>
        </>
      ) : (
        "Loading more"
      )}
    </li>
  );
}
