import { Check, ChevronDown, Search } from "lucide-react";
import { useEffect, useId, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { fuzzy, rank } from "../lib/fuzzy";
import { cn } from "../lib/cn";
import { Popover } from "./Popover";

export type ComboItem = { value: string; label: string; hint?: string; /** items with the same group sit under one heading; order them together */ group?: string; icon?: ReactNode };

type Common = {
  items: ComboItem[];
  /** Names the control for screen readers. */
  label: string;
  placeholder?: string;
  searchPlaceholder?: string;
  emptyText?: string;
  disabled?: boolean;
  align?: "start" | "end";
  /** Your own trigger button; the default looks like a Select. */
  trigger?: ReactNode;
  /** Server-side search: called as the user types, and the items you pass are shown as they are. */
  onSearch?: (q: string) => void;
  loading?: boolean;
  /** Text to show for a value that is not in `items` (for example after a server-side search moved on). */
  valueLabel?: string;
  onOpenChange?: (open: boolean) => void;
  /** Open it from outside (a keyboard shortcut); leave out and it opens itself. */
  open?: boolean;
  className?: string;
  id?: string;
  "aria-invalid"?: boolean;
};
type Single = { multiple?: false; value: string | null; onChange: (v: string) => void; clearLabel?: string; onClear?: () => void };
type Multi = { multiple: true; value: string[]; onChange: (v: string[]) => void };

const MAX = 100;

/** A searchable list in a popover: pick one, or toggle several. Focus stays in the search field; arrows move, Enter picks. */
export function Combobox(p: Common & (Single | Multi)) {
  const [inner, setOpen] = useState(false);
  const open = p.open ?? inner;
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const listId = useId();
  const listRef = useRef<HTMLDivElement>(null);

  const selected = p.multiple ? p.value : p.value ? [p.value] : [];
  const shown = useMemo(() => {
    const q = query.trim();
    const hits = p.onSearch || !q ? p.items : rank(p.items, (i) => fuzzy(q, `${i.label} ${i.group ?? ""}`));
    const cut = hits.slice(0, MAX);
    // keep each group together, in the order the groups first appear
    if (!cut.some((i) => i.group)) return cut;
    const order = [...new Set(cut.map((i) => i.group ?? ""))];
    return order.flatMap((g) => cut.filter((i) => (i.group ?? "") === g));
  }, [p.items, p.onSearch, query]);

  useEffect(() => setActive(0), [query, open]);
  useEffect(() => {
    listRef.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: "nearest" });
  }, [active, shown]);

  const choose = (item: ComboItem) => {
    if (p.multiple) p.onChange(selected.includes(item.value) ? selected.filter((v) => v !== item.value) : [...selected, item.value]);
    else {
      p.onChange(item.value);
      setOpen(false);
    }
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      if (shown.length) setActive((a) => (a + (e.key === "ArrowDown" ? 1 : -1) + shown.length) % shown.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      const item = shown[active];
      if (item) choose(item);
    }
  };

  const labelOf = (v: string) => p.items.find((i) => i.value === v)?.label ?? (selected.length === 1 ? p.valueLabel : undefined) ?? v;
  const text = selected.length === 0 ? null : p.multiple && selected.length > 1 ? `${selected.length} selected` : labelOf(selected[0]!);

  const trigger = p.trigger ?? (
    <button type="button" id={p.id} className={cn("ui-input ui-select-trigger", p.className)} disabled={p.disabled} aria-label={p.label} aria-invalid={p["aria-invalid"] || undefined} aria-haspopup="listbox">
      <span className="ui-combo-value" data-placeholder={text === null || undefined}>
        {text ?? p.placeholder ?? "Select"}
      </span>
      <ChevronDown size={16} aria-hidden />
    </button>
  );

  let lastGroup: string | undefined;
  return (
    <Popover
      label={p.label}
      trigger={trigger}
      align={p.align ?? "start"}
      open={open}
      onOpenChange={(o) => {
        setOpen(o);
        p.onOpenChange?.(o);
        if (o) {
          setQuery("");
          p.onSearch?.("");
        }
      }}
      className="ui-combo"
    >
      <div className="ui-combo-search">
        <Search size={14} aria-hidden />
        <input
          autoFocus
          role="combobox"
          aria-expanded
          aria-controls={listId}
          aria-activedescendant={shown[active] ? `${listId}-${active}` : undefined}
          aria-label={`Search ${p.label.toLowerCase()}`}
          placeholder={p.searchPlaceholder ?? "Search"}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            p.onSearch?.(e.target.value);
          }}
          onKeyDown={onKey}
        />
      </div>
      <div className="ui-combo-list" ref={listRef} id={listId} role="listbox" aria-multiselectable={p.multiple || undefined} aria-label={p.label}>
        {!p.multiple && p.onClear && selected.length > 0 && (
          <button type="button" role="option" aria-selected={false} className="ui-item ui-combo-clear" onClick={() => { p.onClear?.(); setOpen(false); }}>
            {p.clearLabel ?? "Clear"}
          </button>
        )}
        {shown.map((item, i) => {
          const heading = item.group !== lastGroup && item.group ? item.group : null;
          lastGroup = item.group;
          const on = selected.includes(item.value);
          return (
            <div key={item.value} role="presentation">
              {heading && <div className="ui-menu-label">{heading}</div>}
              <div
                id={`${listId}-${i}`}
                role="option"
                aria-selected={on}
                data-active={i === active}
                className="ui-item ui-combo-item"
                onMouseMove={() => i !== active && setActive(i)}
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(item)}
              >
                {p.multiple && <span className="ui-combo-box" data-on={on || undefined}>{on && <Check size={12} strokeWidth={3} aria-hidden />}</span>}
                {item.icon}
                <span className="ui-combo-label">{item.label}</span>
                {item.hint && <span className="ui-combo-hint">{item.hint}</span>}
                {!p.multiple && on && <Check size={14} className="ui-item-end" aria-hidden />}
              </div>
            </div>
          );
        })}
        {shown.length === 0 && <div className="ui-combo-empty">{p.loading ? "Searching..." : (p.emptyText ?? "No matches")}</div>}
      </div>
    </Popover>
  );
}
