import { Plus, Trash2, X } from "lucide-react";
import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { Button, Select } from "../ui";
import { type ComboItem, Combobox } from "../ui/Combobox";
import { cn } from "../lib/cn";
import { MoneyInput, NumberInput, RecordPicker, ChoicePicker, UserPicker } from "./fields/inputs";
import { useRecordsClient } from "./client.ts";
import {
  cleanFilter,
  convertValue,
  defaultValue,
  filterToText,
  groupItems,
  groupKind,
  isCondition,
  isGroup,
  isTagCondition,
  makeGroup,
  opLabel,
  opsFor,
  toRoot,
  valueKind,
  type FieldRef,
} from "./filter.ts";
import { useMeta, useRecordNames } from "./meta.tsx";
import { valueType } from "./schema.ts";
import type { FieldDef, Filter, FilterCondition, FilterGroup, FilterTag, Money, Op, Tag } from "./types.ts";

const TAG = "$tag";
const KEEP_VALUE: string[] = ["text", "long_text", "email", "phone", "url", "number", "money", "date", "datetime", "boolean"];

type Ctx = { byPath: Map<string, FieldRef>; fieldItems: ComboItem[]; tags: Tag[]; first: FieldRef | undefined; gen: number; bump: () => void };
const FbCtx = createContext<Ctx | null>(null);
const useFb = () => useContext(FbCtx)!;

function useCtx(refs: FieldRef[], gen: number, bump: () => void): Ctx {
  const { tags } = useMeta();
  return useMemo(() => {
    const items: ComboItem[] = refs.map((r) => ({ value: r.path, label: r.field.label, group: r.group }));
    items.push({ value: TAG, label: "Tag", group: "Tags" });
    return { byPath: new Map(refs.map((r) => [r.path, r])), fieldItems: items, tags, first: refs[0], gen, bump };
  }, [refs, tags, gen, bump]);
}

const freshCondition = (r: FieldRef | undefined): FilterCondition => {
  if (!r) return { field: "name", op: "contains" };
  const op = opsFor(r.field)[0]!;
  return { field: r.path, op, value: defaultValue(r.field, op) };
};

// ---- value editors ----

type VProps = { field: FieldDef; value: unknown; onChange: (v: unknown) => void; label: string };

/** One value of the field's type. Used once, twice for "between", or as a list of choices. */
function One({ field, value, onChange, label }: VProps) {
  const type = valueType(field);
  const choices = field.options.choices ?? [];
  switch (type) {
    case "number":
      return <NumberInput label={label} value={typeof value === "number" ? value : undefined} onChange={onChange} />;
    case "money":
      return <MoneyInput label={label} value={value as Money | undefined} currency={field.options.currency ?? "USD"} onChange={onChange} />;
    case "date":
    case "datetime":
      return <input type="date" className="ui-input" aria-label={label} value={typeof value === "string" ? value.slice(0, 10) : ""} onChange={(e) => onChange(e.target.value || undefined)} />;
    case "boolean":
      return (
        <Select aria-label={label} value={value === false ? "no" : "yes"} onValueChange={(v) => onChange(v === "yes")} options={[{ value: "yes", label: "Yes" }, { value: "no", label: "No" }]} />
      );
    case "select":
    case "stage":
    case "multi_select":
      return <ChoicePicker label={label} choices={choices} value={typeof value === "string" ? value : null} onChange={(v) => onChange(v ?? undefined)} />;
    case "user":
      return <UserPicker label={label} value={typeof value === "string" ? value : null} onChange={(v) => onChange(v ?? undefined)} />;
    case "record":
      return field.options.object ? <RecordPicker label={label} object={field.options.object} value={typeof value === "string" ? value : null} onChange={(v) => onChange(v ?? undefined)} /> : null;
    default:
      return <input className="ui-input" aria-label={label} placeholder="Type a value" value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value)} />;
  }
}

function ValueEditor({ field, op, value, onChange }: { field: FieldDef; op: Op; value: unknown; onChange: (v: unknown) => void }) {
  const kind = valueKind(op);
  const label = `${field.label} value`;
  if (kind === "none") return <span className="rec-fb-note">No value needed</span>;
  if (kind === "days") {
    const days = (value as { days?: number } | undefined)?.days;
    return (
      <span className="rec-fb-days">
        <NumberInput label={`${field.label} days`} min={1} value={days} onChange={(n) => onChange(n === undefined ? undefined : { days: Math.floor(n) })} />
        <span>days</span>
      </span>
    );
  }
  if (kind === "range") {
    const [a, b] = Array.isArray(value) ? value : [null, null];
    return (
      <span className="rec-fb-range">
        <One field={field} label={`${field.label} from`} value={a ?? undefined} onChange={(v) => onChange([v ?? null, b ?? null])} />
        <span>and</span>
        <One field={field} label={`${field.label} to`} value={b ?? undefined} onChange={(v) => onChange([a ?? null, v ?? null])} />
      </span>
    );
  }
  if (kind === "list") {
    const ids = Array.isArray(value) ? (value as string[]) : [];
    return valueType(field) === "user" ? (
      <UserPicker multiple label={label} value={ids} onChange={onChange} />
    ) : (
      <ChoicePicker multiple label={label} choices={field.options.choices ?? []} value={ids} onChange={onChange} />
    );
  }
  return <One field={field} label={label} value={value} onChange={onChange} />;
}

// ---- one condition ----

function Row({ item, onChange, onRemove }: { item: FilterCondition | FilterTag; onChange: (f: Filter) => void; onRemove: () => void }) {
  const { byPath, fieldItems, tags } = useFb();
  const tagRow = isTagCondition(item);
  const ref = tagRow ? undefined : byPath.get(item.field);
  const field = ref?.field;

  const pickField = (path: string) => {
    if (path === TAG) return onChange({ tag: "" });
    const next = byPath.get(path)!.field;
    const keep = !tagRow && field && valueType(field) === valueType(next) && KEEP_VALUE.includes(valueType(next)) && opsFor(next).includes(item.op);
    onChange(keep ? { ...item, field: path } : freshCondition(byPath.get(path)));
  };

  return (
    <div className="rec-fb-row">
      <Combobox
        label="Field"
        items={fieldItems}
        value={tagRow ? TAG : item.field}
        valueLabel={tagRow ? "Tag" : item.field}
        onChange={pickField}
        searchPlaceholder="Search fields"
        className="rec-fb-field"
      />
      {tagRow ? (
        <>
          <span className="rec-fb-fixed">is</span>
          <div className="rec-fb-value">
            <Combobox
              label="Tag"
              items={tags.map((t) => ({ value: t.id, label: t.name }))}
              value={item.tag || null}
              onChange={(id) => onChange({ tag: id })}
              placeholder="Choose a tag"
              searchPlaceholder="Search tags"
            />
          </div>
        </>
      ) : field ? (
        <>
          <Select
            aria-label="Condition"
            value={item.op}
            onValueChange={(op) => onChange({ field: item.field, op: op as Op, value: convertValue(field, item.op, op as Op, item.value) })}
            options={opsFor(field).map((op) => ({ value: op, label: opLabel(op, valueType(field)) }))}
          />
          <div className="rec-fb-value">
            <ValueEditor key={`${item.field}:${item.op}`} field={field} op={item.op} value={item.value} onChange={(value) => onChange({ field: item.field, op: item.op, value })} />
          </div>
        </>
      ) : (
        <span className="rec-fb-note rec-fb-missing">This field no longer exists</span>
      )}
      <Button variant="ghost" size="icon" aria-label="Remove condition" onClick={onRemove}>
        <X size={16} aria-hidden />
      </Button>
    </div>
  );
}

// ---- a group of conditions ----

function Group({ group, depth, onChange, onRemove }: { group: FilterGroup; depth: number; onChange: (g: FilterGroup) => void; onRemove?: () => void }) {
  const { first, gen, bump } = useFb();
  const kind = groupKind(group);
  const items = groupItems(group);
  const set = (next: Filter[]) => onChange(makeGroup(kind, next));
  return (
    <div className="rec-fb-group" data-depth={depth}>
      <div className="rec-fb-head">
        <span>Match</span>
        <div className="rec-fb-kind">
          <Select
            aria-label="Match all or any"
            value={kind === "and" ? "all" : "any"}
            onValueChange={(v) => onChange(makeGroup(v === "all" ? "and" : "or", items))}
            options={[{ value: "all", label: "all" }, { value: "any", label: "any" }]}
          />
        </div>
        <span>of these</span>
        {onRemove && (
          <Button variant="ghost" size="sm" className="rec-fb-remove-group" onClick={onRemove}>
            <Trash2 size={14} aria-hidden /> Remove group
          </Button>
        )}
      </div>
      {items.length === 0 && <p className="rec-fb-empty">No conditions yet. Add one to narrow the list.</p>}
      {items.map((it, i) => {
        const key = `${i}-${gen}`;
        const replace = (next: Filter) => set(items.map((x, j) => (j === i ? next : x)));
        const remove = () => {
          bump(); // rows hold their own typing state, so after a removal they must all re-read their values
          set(items.filter((_, j) => j !== i));
        };
        return isGroup(it) ? (
          <Group key={key} group={it} depth={depth + 1} onChange={replace} onRemove={remove} />
        ) : isCondition(it) || isTagCondition(it) ? (
          <Row key={key} item={it} onChange={replace} onRemove={remove} />
        ) : null;
      })}
      <div className="rec-fb-actions">
        <Button variant="ghost" size="sm" onClick={() => set([...items, freshCondition(first)])}>
          <Plus size={14} aria-hidden /> Add condition
        </Button>
        {/* One level of nesting is enough for real questions ("lead AND (VIP OR big deal)"); deeper groups from a saved view still open and edit. */}
        {depth === 0 && (
          <Button variant="ghost" size="sm" onClick={() => set([...items, makeGroup(kind === "and" ? "or" : "and", [freshCondition(first)])])}>
            <Plus size={14} aria-hidden /> Add group
          </Button>
        )}
      </div>
    </div>
  );
}

/**
 * Edits a filter as AND/OR groups of conditions and reports the finished part as the filter AST (ADR 0002).
 * Conditions still missing a value stay in the editor but are left out of what it reports. Remount to reload from `value`.
 */
export function FilterBuilder({ value, onChange, refs, total, noun }: { value: Filter | null; onChange: (f: Filter | null) => void; refs: FieldRef[]; total?: number; noun: string }) {
  const [draft, setDraft] = useState<FilterGroup>(() => toRoot(value));
  const [gen, setGen] = useState(0);
  const bump = useCallback(() => setGen((n) => n + 1), []);
  const ctx = useCtx(refs, gen, bump);
  const update = (g: FilterGroup) => {
    setDraft(g);
    onChange(cleanFilter(g));
  };
  return (
    <FbCtx.Provider value={ctx}>
      <div className="rec-fb">
        <Group group={draft} depth={0} onChange={update} />
        <div className="rec-fb-foot">
          <span className="rec-fb-count" aria-live="polite">
            {total === undefined ? "" : `${total.toLocaleString("en-US")} matching ${noun.toLowerCase()}`}
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => {
              bump();
              update({ and: [] });
            }}
            disabled={groupItems(draft).length === 0}
          >
            Clear all
          </Button>
        </div>
      </div>
    </FbCtx.Provider>
  );
}

// ---- the summary chips in the toolbar ----

/** One chip per top-level condition, in plain words, each removable. Click a chip to edit. */
export function FilterChips({ value, refs, onChange, onEdit }: { value: Filter | null; refs: FieldRef[]; onChange: (f: Filter | null) => void; onEdit: () => void }) {
  const client = useRecordsClient();
  const { tags, users } = useMeta();
  const fields = useMemo(() => refs.map((r) => r.field), [refs]);
  const root = toRoot(value);
  const kind = groupKind(root);
  const items = groupItems(root);
  // names behind record ids in the filter, so a chip reads "Company is Alder Labs"
  const pairs = useMemo(() => {
    const out: { object: string; id: string }[] = [];
    const walk = (f: Filter) => {
      if (isGroup(f)) groupItems(f).forEach(walk);
      else if (isCondition(f) && typeof f.value === "string") {
        const o = fields.find((x) => x.key === f.field);
        if (o?.type === "record" && o.options.object) out.push({ object: o.options.object, id: f.value });
      }
    };
    walk(root);
    return out;
  }, [value, fields]);
  const records = useRecordNames(client, pairs);
  if (items.length === 0) return null;

  const chips: ReactNode[] = [];
  items.forEach((it, i) => {
    if (i > 0) chips.push(<span key={`j${i}`} className="rec-chips-join">{kind === "and" ? "and" : "or"}</span>);
    const text = filterToText(it, fields, { tags, users, records });
    chips.push(
      <span key={i} className={cn("rec-filter-chip")}>
        <button type="button" className="rec-filter-chip-text" onClick={onEdit} title="Edit this filter">
          {text}
        </button>
        <button type="button" className="rec-filter-chip-x" aria-label={`Remove filter: ${text}`} onClick={() => onChange(cleanFilter(makeGroup(kind, items.filter((_, j) => j !== i))))}>
          <X size={12} aria-hidden />
        </button>
      </span>,
    );
  });
  return <div className="rec-chips" role="group" aria-label="Active filters">{chips}</div>;
}
