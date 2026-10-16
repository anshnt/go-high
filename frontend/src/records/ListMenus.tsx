import { ArrowDownUp, ArrowDown, ArrowUp, Columns3, Lock, Plus, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Button, Checkbox, Select } from "../ui";
import { Popover } from "../ui/Popover";
import { TAGS_KEY } from "./columns";
import { isSortable, valueType } from "./schema.ts";
import type { FieldDef, FieldType, ObjectDef, SortSpec } from "./types.ts";

const dirLabels = (t: FieldType): [string, string] =>
  t === "date" || t === "datetime" ? ["Oldest first", "Newest first"] : t === "number" || t === "money" ? ["Low to high", "High to low"] : t === "boolean" ? ["No first", "Yes first"] : ["A to Z", "Z to A"];

const MAX_SORTS = 3;

/** Up to three sort levels: "stage, then amount high to low". */
export function SortMenu({ fields, sort, onChange }: { fields: FieldDef[]; sort: SortSpec[]; onChange: (s: SortSpec[]) => void }) {
  const sortable = useMemo(() => fields.filter(isSortable), [fields]);
  const byKey = new Map(sortable.map((f) => [f.key, f]));
  const first = sort[0];
  const firstField = first ? byKey.get(first.field) : undefined;
  const unused = sortable.filter((f) => !sort.some((s) => s.field === f.key));
  const set = (i: number, next: SortSpec) => onChange(sort.map((s, j) => (j === i ? next : s)));
  return (
    <Popover
      label="Sort"
      trigger={
        <Button size="sm" aria-label={firstField ? `Sort: ${firstField.label}, ${first!.dir === "asc" ? "ascending" : "descending"}` : "Sort"}>
          <ArrowDownUp size={14} aria-hidden />
          <span className="rec-btn-text">{firstField ? firstField.label : "Sort"}</span>
          {firstField && (first!.dir === "asc" ? <ArrowUp size={12} aria-hidden /> : <ArrowDown size={12} aria-hidden />)}
        </Button>
      }
    >
      <div className="rec-menu rec-sort">
        {sort.map((s, i) => {
          const f = byKey.get(s.field);
          const [asc, desc] = dirLabels(f ? valueType(f) : "text");
          return (
            <div key={`${s.field}-${i}`} className="rec-sort-row">
              <span className="rec-sort-then">{i === 0 ? "Sort by" : "Then by"}</span>
              <Select
                aria-label={i === 0 ? "Sort field" : "Then sort field"}
                value={s.field}
                onValueChange={(v) => set(i, { field: v, dir: s.dir })}
                options={[...(f ? [] : [{ value: s.field, label: s.field }]), ...sortable.filter((x) => x.key === s.field || unused.includes(x)).map((x) => ({ value: x.key, label: x.label }))]}
              />
              <Select aria-label="Direction" value={s.dir} onValueChange={(v) => set(i, { field: s.field, dir: v as "asc" | "desc" })} options={[{ value: "asc", label: asc }, { value: "desc", label: desc }]} />
              {sort.length > 1 && (
                <Button variant="ghost" size="icon" aria-label="Remove this sort" onClick={() => onChange(sort.filter((_, j) => j !== i))}>
                  <X size={16} aria-hidden />
                </Button>
              )}
            </div>
          );
        })}
        {sort.length < MAX_SORTS && unused.length > 0 && (
          <Button variant="ghost" size="sm" onClick={() => onChange([...sort, { field: unused[0]!.key, dir: "asc" }])}>
            <Plus size={14} aria-hidden /> Add sort
          </Button>
        )}
        <p className="rec-menu-note">Records with no value in a field always come last.</p>
      </div>
    </Popover>
  );
}

/** Show, hide and reorder columns. The name stays first. */
export function ColumnsMenu({ def, fields, columns, onChange }: { def: ObjectDef; fields: FieldDef[]; columns: string[]; onChange: (c: string[]) => void }) {
  const [q, setQ] = useState("");
  const label = (k: string) => (k === TAGS_KEY ? "Tags" : (fields.find((f) => f.key === k)?.label ?? k));
  const all = useMemo(() => [...fields.map((f) => f.key), TAGS_KEY], [fields]);
  const shown = columns.filter((k) => k !== def.primary_field && all.includes(k));
  const hidden = all.filter((k) => k !== def.primary_field && !shown.includes(k));
  const move = (i: number, by: number) => {
    const next = shown.slice();
    [next[i], next[i + by]] = [next[i + by]!, next[i]!];
    onChange([def.primary_field, ...next]);
  };
  const match = (k: string) => label(k).toLowerCase().includes(q.trim().toLowerCase());
  return (
    <Popover
      label="Columns"
      onOpenChange={(o) => o && setQ("")}
      trigger={
        <Button size="sm" aria-label="Columns">
          <Columns3 size={14} aria-hidden />
          <span className="rec-btn-text">Columns</span>
        </Button>
      }
    >
      <div className="rec-menu rec-cols">
        {all.length > 10 && <input className="ui-input" aria-label="Search columns" placeholder="Search columns" value={q} onChange={(e) => setQ(e.target.value)} />}
        <ul className="rec-cols-list" aria-label="Columns">
          <li className="rec-cols-row">
            <Lock size={14} aria-hidden className="rec-cols-lock" />
            <span className="rec-cols-name">{label(def.primary_field)}</span>
            <span className="rec-cols-note">always first</span>
          </li>
          {shown.filter(match).map((k) => {
            const i = shown.indexOf(k);
            return (
              <li key={k} className="rec-cols-row">
                <Checkbox aria-label={`Show ${label(k)}`} checked onCheckedChange={() => onChange([def.primary_field, ...shown.filter((x) => x !== k)])} />
                <span className="rec-cols-name">{label(k)}</span>
                <Button variant="ghost" size="icon" aria-label={`Move ${label(k)} left`} disabled={i === 0} onClick={() => move(i, -1)}>
                  <ArrowUp size={14} aria-hidden />
                </Button>
                <Button variant="ghost" size="icon" aria-label={`Move ${label(k)} right`} disabled={i === shown.length - 1} onClick={() => move(i, 1)}>
                  <ArrowDown size={14} aria-hidden />
                </Button>
              </li>
            );
          })}
        </ul>
        {hidden.some(match) && (
          <>
            <p className="rec-menu-note">Hidden</p>
            <ul className="rec-cols-list" aria-label="Hidden columns">
              {hidden.filter(match).map((k) => (
                <li key={k} className="rec-cols-row">
                  <Checkbox aria-label={`Show ${label(k)}`} checked={false} onCheckedChange={() => onChange([def.primary_field, ...shown, k])} />
                  <span className="rec-cols-name">{label(k)}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </Popover>
  );
}
