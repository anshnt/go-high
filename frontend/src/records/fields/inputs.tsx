// Inputs shared by the field editors (forms and inline edits) and the filter builder's value editors.
import { ChevronDown } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { Avatar, Badge } from "../../ui";
import { Combobox, type ComboItem } from "../../ui/Combobox";
import { cn } from "../../lib/cn";
import { useRecordsClient } from "../client.ts";
import { minorDigits, moneyToInput, parseMoney } from "../format.ts";
import { useMeta, useRecordRef } from "../meta.tsx";
import type { Choice, Money } from "../types.ts";
import { toneOf } from "./tone.ts";

export const CURRENCIES = ["USD", "EUR", "GBP", "CAD", "AUD", "INR", "JPY"];

const choiceItems = (choices: Choice[]): ComboItem[] => choices.map((c) => ({ value: c.id, label: c.label }));

/** Pick from a field's choices (select, stage), one or several. Several show as badges in the button. */
export function ChoicePicker(
  p: { choices: Choice[]; label: string; trigger?: ReactNode; onClose?: () => void; autoFocus?: boolean; id?: string; error?: boolean } & (
    | { multiple?: false; value: string | null; onChange: (v: string | null) => void; clearable?: boolean }
    | { multiple: true; value: string[]; onChange: (v: string[]) => void }
  ),
) {
  const items = useMemo(() => choiceItems(p.choices), [p.choices]);
  const common = { items, label: p.label, id: p.id, "aria-invalid": p.error, onOpenChange: (o: boolean) => !o && p.onClose?.() };
  if (p.multiple) {
    const trigger = p.trigger ?? (
      <button type="button" id={p.id} className="ui-input ui-select-trigger rec-multi-trigger" aria-label={p.label} aria-invalid={p.error || undefined} aria-haspopup="listbox">
        <ChoiceBadges choices={p.choices} ids={p.value} placeholder="Choose" />
        <ChevronDown size={16} aria-hidden />
      </button>
    );
    return <Combobox {...common} multiple value={p.value} onChange={p.onChange} trigger={trigger} />;
  }
  return <Combobox {...common} trigger={p.trigger} value={p.value} onChange={p.onChange} onClear={p.clearable ? () => p.onChange(null) : undefined} clearLabel="Clear" placeholder="Choose" />;
}

/** Pick people from the workspace. */
export function UserPicker(
  p: { label: string; trigger?: ReactNode; onClose?: () => void; id?: string; error?: boolean; clearable?: boolean } & (
    | { multiple?: false; value: string | null; onChange: (v: string | null) => void }
    | { multiple: true; value: string[]; onChange: (v: string[]) => void }
  ),
) {
  const { users } = useMeta();
  const items = useMemo<ComboItem[]>(() => users.map((u) => ({ value: u.id, label: u.name, hint: u.email, icon: <Avatar name={u.name} size="sm" /> })), [users]);
  const common = { items, label: p.label, trigger: p.trigger, id: p.id, "aria-invalid": p.error, onOpenChange: (o: boolean) => !o && p.onClose?.(), searchPlaceholder: "Search people" };
  return p.multiple ? (
    <Combobox {...common} multiple value={p.value} onChange={p.onChange} placeholder="Choose people" />
  ) : (
    <Combobox {...common} value={p.value} onChange={p.onChange} onClear={p.clearable ? () => p.onChange(null) : undefined} clearLabel="Unassign" placeholder="Choose a person" />
  );
}

/** Search the records of one object and pick one. Results come from the server as you type. */
export function RecordPicker(p: { object: string; value: string | null; onChange: (id: string | null) => void; label: string; trigger?: ReactNode; id?: string; error?: boolean; clearable?: boolean }) {
  const client = useRecordsClient();
  const meta = useMeta();
  const def = meta.objects.find((o) => o.key === p.object);
  const [items, setItems] = useState<ComboItem[]>([]);
  const [loading, setLoading] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const seq = useRef(0);
  const current = useRecordRef(client, p.object, p.value);

  useEffect(() => () => clearTimeout(timer.current), []);
  const search = (q: string) => {
    clearTimeout(timer.current);
    const mine = ++seq.current;
    setLoading(true);
    timer.current = setTimeout(
      () => {
        client.query(p.object, { q, limit: 20, sort: q ? [{ field: "display_name", dir: "asc" }] : undefined }).then(
          (page) => {
            if (mine !== seq.current) return;
            setItems(page.data.map((r) => ({ value: r.id, label: r.display_name })));
            setLoading(false);
          },
          () => mine === seq.current && setLoading(false),
        );
      },
      q ? 200 : 0,
    );
  };

  return (
    <Combobox
      items={items}
      label={p.label}
      trigger={p.trigger}
      id={p.id}
      aria-invalid={p.error}
      value={p.value}
      valueLabel={current?.display_name}
      onChange={(v) => p.onChange(v)}
      onClear={p.clearable ? () => p.onChange(null) : undefined}
      clearLabel="Remove link"
      onSearch={search}
      loading={loading}
      placeholder={`Choose ${def?.singular.toLowerCase() ?? "a record"}`}
      searchPlaceholder={`Search ${def?.plural.toLowerCase() ?? "records"}`}
      emptyText="No matches"
    />
  );
}

/** Badges for a set of choices, used as the trigger of multi-select pickers. */
export function ChoiceBadges({ choices, ids, placeholder }: { choices: Choice[]; ids: string[]; placeholder: string }) {
  if (ids.length === 0) return <span className="rec-placeholder">{placeholder}</span>;
  return (
    <span className="rec-badges">
      {ids.map((id) => {
        const c = choices.find((x) => x.id === id);
        return (
          <Badge key={id} tone={toneOf(c?.color)}>
            {c?.label ?? id}
          </Badge>
        );
      })}
    </span>
  );
}

type KeyProps = { onKeyDown?: (e: KeyboardEvent) => void; autoFocus?: boolean; id?: string; error?: boolean; label?: string };

/** A decimal amount in a currency. Reports undefined while the text is empty or not an amount. */
export function MoneyInput({
  value,
  currency,
  onChange,
  fixedCurrency,
  ...k
}: KeyProps & { value: Money | undefined; currency: string; fixedCurrency?: boolean; onChange: (m: Money | undefined) => void }) {
  const [text, setText] = useState(moneyToInput(value));
  const [cur, setCur] = useState(value?.currency ?? currency);
  const [bad, setBad] = useState(false);
  const emit = (t: string, c: string) => {
    const n = t.trim() ? parseMoney(t, c) : null;
    setBad(!!t.trim() && n === null);
    onChange(n === null ? undefined : { amount: n, currency: c });
  };
  const digits = minorDigits(cur);
  return (
    <div className="rec-money">
      <input
        id={k.id}
        className="ui-input num"
        inputMode="decimal"
        autoComplete="off"
        autoFocus={k.autoFocus}
        aria-label={k.label}
        aria-invalid={k.error || bad || undefined}
        placeholder={digits === 0 ? "0" : `0.${"0".repeat(digits)}`}
        value={text}
        onKeyDown={k.onKeyDown}
        onChange={(e) => {
          setText(e.target.value);
          emit(e.target.value, cur);
        }}
      />
      {!fixedCurrency && (
        <select
          className="ui-input rec-currency"
          aria-label={`${k.label ?? "Amount"} currency`}
          value={cur}
          onKeyDown={k.onKeyDown}
          onChange={(e) => {
            setCur(e.target.value);
            emit(text, e.target.value);
          }}
        >
          {[...new Set([cur, ...CURRENCIES])].map((c) => (
            <option key={c}>{c}</option>
          ))}
        </select>
      )}
      {bad && <p className="ui-hint rec-money-hint" data-tone="danger">{digits === 0 ? "Whole amounts only." : `Use at most ${digits} decimals.`}</p>}
    </div>
  );
}

/** Number box that reports undefined while empty. Remount (change `key`) to reset it. */
export function NumberInput({ value, onChange, ...k }: KeyProps & { value: number | undefined; onChange: (n: number | undefined) => void; className?: string; min?: number; max?: number }) {
  return (
    <input
      id={k.id}
      type="number"
      step="any"
      inputMode="decimal"
      className={cn("ui-input num", k.className)}
      autoFocus={k.autoFocus}
      aria-label={k.label}
      aria-invalid={k.error || undefined}
      defaultValue={value ?? ""}
      min={k.min}
      max={k.max}
      onKeyDown={k.onKeyDown}
      onChange={(e) => onChange(e.target.value === "" || Number.isNaN(Number(e.target.value)) ? undefined : Number(e.target.value))}
    />
  );
}
