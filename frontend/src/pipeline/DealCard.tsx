import { CalendarDays, Clock, Hourglass, MoreHorizontal } from "lucide-react";
import { memo, type DragEvent, type KeyboardEvent } from "react";
import { cn } from "../lib/cn";
import { useRecordsClient } from "../records/client.ts";
import { formatMoney, relativeDay, relativeTime, valueText, formatDay } from "../records/format.ts";
import { useMeta, useRecordRef } from "../records/meta.tsx";
import { valueType } from "../records/schema.ts";
import type { FieldDef } from "../records/types.ts";
import { isEmptyValue } from "../records/validate.ts";
import { Avatar, Button, DropdownMenu, MenuItem, MenuLabel, MenuSeparator } from "../ui";
import { compactAgo, daysText, moneyOf, overdue, shortDay } from "./board.ts";
import type { BoardStage, Card } from "./types.ts";

export const dotColor = (color: string | null) => `var(--pl-${color ?? "gray"}, var(--pl-gray))`;

/** The name behind a record link on a card: plain text (the whole card is the link). */
function RecordName({ object, id }: { object: string; id: string }) {
  const row = useRecordRef(useRecordsClient(), object, id);
  return <>{row === undefined ? "..." : (row?.display_name ?? "Deleted record")}</>;
}

/** One chosen field on a card, as "Label value". */
function FieldBit({ field, value }: { field: FieldDef; value: unknown }) {
  const { users } = useMeta();
  const type = valueType(field);
  return (
    <span className="pl-bit" title={`${field.label}: ${type === "record" ? "" : valueText(field, value, { users })}`}>
      <span className="pl-bit-label">{field.label}</span>
      <span className="pl-bit-value">{type === "record" && field.options.object ? <RecordName object={field.options.object} id={String(value)} /> : valueText(field, value, { users })}</span>
    </span>
  );
}

export type CardProps = {
  card: Card;
  stage: BoardStage;
  /** every stage of the pipeline, for the "Move to stage" menu */
  stages: BoardStage[];
  cardFields: string[];
  fields: Map<string, FieldDef>;
  hasAmount: boolean;
  canMove: boolean;
  dragging: boolean;
  tabStop: boolean;
  menuOpen: boolean;
  open: boolean;
  now: number;
  onOpen: (id: string) => void;
  onMenuOpen: (id: string | null) => void;
  onMoveTo: (card: Card, stageId: string) => void;
  onDragStart: (card: Card, e: DragEvent) => void;
  onDragEnd: () => void;
  onKeyDown: (card: Card, e: KeyboardEvent<HTMLElement>) => void;
  onFocus: (id: string) => void;
  setEl: (id: string, el: HTMLElement | null) => void;
};

/** A deal on the board: name, the fields the person chose, how long it has been here and whether it is rotting. Drag it, or use its menu or the keyboard. */
export const DealCard = memo(function DealCard(p: CardProps) {
  const { card, stage } = p;
  const { users } = useMeta();
  const now = new Date(p.now);
  const owner = card.owner_id ? users.find((u) => u.id === card.owner_id) : undefined;
  const money = moneyOf(card);
  const closeDay = card.close_date;
  const late = stage.kind === "open" && overdue(closeDay, now);
  const show = (key: string) => p.cardFields.includes(key);
  const others = p.cardFields.filter((k) => !["amount", "close_date", "owner_id"].includes(k) && p.fields.has(k) && !isEmptyValue(card.values[k]));
  const age = daysText(card.days_in_stage);
  const ago = compactAgo(card.last_activity_at, p.now);
  const ageTitle = [card.days_in_stage <= 0 ? `Moved into ${stage.name} today.` : `In ${stage.name} for ${card.days_in_stage} days.`, card.rotting ? "Rotting." : "", stage.rotting_days !== null ? `Deals here rot after ${stage.rotting_days} days.` : ""].filter(Boolean).join(" ");
  const label = [
    card.display_name || "Untitled deal",
    show("amount") && money ? formatMoney(money) : "",
    stage.name,
    show("close_date") && closeDay ? `closes ${formatDay(closeDay)}` : "",
    show("owner_id") && owner ? `owner ${owner.name}` : "",
    card.days_in_stage <= 0 ? "moved here today" : `${card.days_in_stage} days in stage`,
    card.rotting ? "rotting" : "",
  ]
    .filter(Boolean)
    .join(", ");

  return (
    <li className="pl-card-item">
      <div
        ref={(el) => p.setEl(card.id, el)}
        className="pl-card"
        role="group"
        aria-roledescription="deal card"
        aria-label={label}
        aria-describedby="pl-help"
        data-card-id={card.id}
        data-rotting={card.rotting || undefined}
        data-dragging={p.dragging || undefined}
        data-open={p.open || undefined}
        tabIndex={p.tabStop ? 0 : -1}
        draggable={p.canMove}
        onClick={() => p.onOpen(card.id)}
        onDragStart={(e) => p.onDragStart(card, e)}
        onDragEnd={p.onDragEnd}
        onKeyDown={(e) => p.onKeyDown(card, e)}
        onFocus={(e) => e.target === e.currentTarget && p.onFocus(card.id)}
      >
        <div className="pl-card-top">
          <span className="pl-card-name">{card.display_name || "Untitled deal"}</span>
          {/* the menu's events must not reach the card: a click in it would open the deal */}
          <span className="pl-card-menu-wrap" onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
            <DropdownMenu
              label={`Actions for ${card.display_name}`}
              open={p.menuOpen}
              onOpenChange={(o) => p.onMenuOpen(o ? card.id : null)}
              onCloseAutoFocus={(e) => {
                e.preventDefault();
                document.querySelector<HTMLElement>(`[data-card-id="${CSS.escape(card.id)}"]`)?.focus();
              }}
              trigger={
                <Button size="icon" variant="ghost" className="pl-card-menu" aria-label={`Actions for ${card.display_name}`}>
                  <MoreHorizontal size={16} aria-hidden />
                </Button>
              }
            >
              {p.canMove && (
                <>
                  <MenuLabel>Move to stage</MenuLabel>
                  {p.stages.map((s) => (
                    <MenuItem key={s.id} disabled={s.id === card.stage_id} onSelect={() => p.onMoveTo(card, s.id)} icon={<span className="pl-dot" style={{ background: dotColor(s.color) }} aria-hidden />}>
                      {s.name}
                      {s.id === card.stage_id && <span className="pl-menu-note">Current</span>}
                    </MenuItem>
                  ))}
                  <MenuSeparator />
                </>
              )}
              <MenuItem onSelect={() => p.onOpen(card.id)}>Open deal</MenuItem>
            </DropdownMenu>
          </span>
        </div>

        {show("amount") && p.hasAmount && money && <div className="pl-card-amount num">{formatMoney(money)}</div>}

        {((show("close_date") && closeDay) || others.length > 0) && (
          <div className="pl-card-facts">
            {show("close_date") && closeDay && (
              <span className="pl-bit pl-close" data-late={late || undefined} title={`Closes ${formatDay(closeDay)}, ${relativeDay(closeDay, p.now)}${late ? " (overdue)" : ""}`}>
                <CalendarDays size={12} aria-hidden />
                <span>{shortDay(closeDay, now)}</span>
                {late && <span className="sr-only"> overdue</span>}
              </span>
            )}
            {others.map((k) => (
              <FieldBit key={k} field={p.fields.get(k)!} value={card.values[k]} />
            ))}
          </div>
        )}

        <div className="pl-card-foot">
          {show("owner_id") &&
            (owner ? (
              <span className="pl-card-owner" title={owner.name}>
                <Avatar name={owner.name} size="sm" />
              </span>
            ) : (
              <span className="pl-card-owner pl-unowned" title="No owner" aria-label="No owner" role="img" />
            ))}
          <span className={cn("pl-age", card.rotting && "pl-age-rot")} data-rotting={card.rotting || undefined} title={ageTitle}>
            {card.rotting ? <Hourglass size={12} aria-hidden /> : <Clock size={12} aria-hidden />}
            <span>{age}</span>
            {card.rotting && <span className="sr-only"> rotting</span>}
          </span>
          {ago && (
            <span className="pl-ago" title={card.last_activity_at ? `Last activity ${relativeTime(card.last_activity_at, p.now)}` : undefined}>
              {ago === "now" ? "Active now" : `${ago} ago`}
            </span>
          )}
        </div>
      </div>
    </li>
  );
});
