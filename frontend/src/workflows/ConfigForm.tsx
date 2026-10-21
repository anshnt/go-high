// The settings of an action, drawn from its JSON schema in the catalog: a new action in the backend gets a working form
// here with no change, and the keys that name something in the workspace (a channel, a person, a stage, a tag) get a
// picker instead of a text box.
import { Plus, Trash2 } from "lucide-react";
import { createContext, useContext, useMemo, useState } from "react";
import { FieldEditor } from "../records/fields/FieldEditor";
import { UserPicker } from "../records/fields/inputs";
import { useMeta } from "../records/meta.tsx";
import { isReadOnly } from "../records/schema.ts";
import type { FieldDef } from "../records/types.ts";
import { Button, Input, Select, Switch, Textarea } from "../ui";
import { Combobox, type ComboItem } from "../ui/Combobox";
import type { Choice, JsonSchema } from "./api";
import { offsetOf, UNITS, type Unit } from "./graph";
import { choiceLabel, props, type Prop } from "./schema";

export type Lookups = { channels: Choice[] | null; stages: Choice[] | null; forms: Choice[] | null; calendars: Choice[] | null };
export const LookupsCtx = createContext<Lookups>({ channels: null, stages: null, forms: null, calendars: null });
export const useLookups = () => useContext(LookupsCtx);

/** The error for a setting: its own, or the first of its parts ("values.email"). */
export function errorFor(errors: Record<string, string>, key: string): string | undefined {
  if (errors[key]) return errors[key];
  const sub = Object.entries(errors).find(([k]) => k.startsWith(`${key}.`));
  return sub ? `${sub[0].slice(key.length + 1).replace(/_/g, " ")}: ${sub[1]}` : undefined;
}

const UNIT_OPTIONS = UNITS.map((u) => ({ value: u, label: u }));

/** A count and a unit ({"days": 2}). Empty means none, where none is allowed. */
export function OffsetInput({ label, value, onChange, error, hint, signed, required }: { label: string; value: unknown; onChange: (v: Record<string, number> | null) => void; error?: string; hint?: string; signed?: boolean; required?: boolean }) {
  const o = offsetOf(value);
  const [text, setText] = useState(o ? String(Math.abs(o.count)) : "");
  const [unit, setUnit] = useState<Unit>(o?.unit ?? "days");
  const [before, setBefore] = useState(!!o && o.count < 0);
  const emit = (t: string, u: Unit, b: boolean) => {
    const n = Number.parseInt(t, 10);
    onChange(Number.isFinite(n) && n > 0 ? { [u]: b ? -n : n } : null);
  };
  return (
    <fieldset className="wf-offset">
      <legend className="ui-label">
        {label}
        {required ? "" : " (optional)"}
      </legend>
      <div className="wf-offset-row">
        <Input
          aria-label={`${label}: how many`}
          inputMode="numeric"
          value={text}
          error={undefined}
          aria-invalid={error ? true : undefined}
          onChange={(e) => {
            const t = e.target.value.replace(/[^0-9]/g, "").slice(0, 6);
            setText(t);
            emit(t, unit, before);
          }}
          placeholder={required ? "1" : "None"}
        />
        <Select aria-label={`${label}: unit`} value={unit} onValueChange={(u) => (setUnit(u as Unit), emit(text, u as Unit, before))} options={UNIT_OPTIONS} />
        {signed && (
          <Select aria-label={`${label}: before or after`} value={before ? "before" : "after"} onValueChange={(v) => (setBefore(v === "before"), emit(text, unit, v === "before"))} options={[{ value: "before", label: "before" }, { value: "after", label: "after" }]} />
        )}
      </div>
      {error ? (
        <p className="ui-hint" data-tone="danger">
          {error}
        </p>
      ) : hint ? (
        <p className="ui-hint">{hint}</p>
      ) : null}
    </fieldset>
  );
}

/** A labelled picker over a list of choices. */
export function ChoiceCombo({ label, items, value, onChange, error, hint, placeholder = "Choose", loading, clearable }: { label: string; items: ComboItem[]; value: string | null; onChange: (v: string | null) => void; error?: string; hint?: string; placeholder?: string; loading?: boolean; clearable?: boolean }) {
  const known = items.find((i) => i.value === value);
  return (
    <div className="ui-field">
      <span className="ui-label">{label}</span>
      <Combobox
        label={label}
        items={items}
        value={value}
        onChange={onChange}
        placeholder={loading ? "Loading" : placeholder}
        valueLabel={value && !known ? (loading ? "Loading" : /^[0-9a-f-]{36}$/i.test(value) ? "Not found any more: choose again" : `${value} (not found)`) : undefined}
        aria-invalid={!!error}
        onClear={clearable ? () => onChange(null) : undefined}
        emptyText={loading ? "Loading" : "Nothing to choose from yet"}
      />
      {error ? (
        <p className="ui-hint" data-tone="danger">
          {error}
        </p>
      ) : hint ? (
        <p className="ui-hint">{hint}</p>
      ) : null}
    </div>
  );
}

/** Inserts `{{field}}` into a text: the fields of the workflow's object, by label. */
function MergeField({ object, onPick }: { object: string; onPick: (key: string) => void }) {
  const meta = useMeta();
  const items = useMemo<ComboItem[]>(() => [{ value: "display_name", label: "Display name" }, ...(meta.fields[object] ?? []).filter((f) => !f.archived && f.key !== "display_name").map((f) => ({ value: f.key, label: f.label, hint: `{{${f.key}}}` }))], [meta, object]);
  return (
    <Combobox
      label="Insert a field"
      items={items}
      value={null}
      onChange={(v) => onPick(v)}
      searchPlaceholder="Search fields"
      trigger={
        <button type="button" className="wf-link wf-merge">
          Insert a field
        </button>
      }
    />
  );
}

const MERGEABLE = new Set(["body", "title", "notes", "subject"]);

type FormProps = { schema: JsonSchema | null | undefined; value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void; errors: Record<string, string>; object: string; disabled?: boolean; skip?: string[] };

/** Every setting of the schema, in order. */
export function ConfigForm({ schema, value, onChange, errors, object, disabled, skip = [] }: FormProps) {
  const list = props(schema).filter((p) => !skip.includes(p.key));
  const set = (key: string, v: unknown) => {
    const next = { ...value };
    if (v === undefined || v === null || v === "") delete next[key];
    else next[key] = v;
    onChange(next);
  };
  return (
    <fieldset className="wf-form" disabled={disabled}>
      {list.map((p) => (
        <Setting key={p.key} prop={p} value={value[p.key]} onChange={(v) => set(p.key, v)} error={errorFor(errors, p.key)} object={object} />
      ))}
    </fieldset>
  );
}

function Setting({ prop: p, value, onChange, error, object }: { prop: Prop; value: unknown; onChange: (v: unknown) => void; error?: string; object: string }) {
  const meta = useMeta();
  const lookups = useLookups();
  const label = p.label + (p.required || p.kind === "boolean" || p.kind === "choice" ? "" : " (optional)");
  const str = typeof value === "string" ? value : "";
  switch (p.widget) {
    case "channel":
      return <ChoiceCombo label={label} items={(lookups.channels ?? []).map((c) => ({ value: c.id, label: c.name, hint: c.hint }))} value={str || null} onChange={onChange} error={error} loading={!lookups.channels} hint={lookups.channels?.length === 0 ? "Connect an SMS, email or WhatsApp channel in Settings, Channels first." : undefined} />;
    case "stage":
      return <ChoiceCombo label={label} items={(lookups.stages ?? []).map((s) => ({ value: s.id, label: s.name, group: s.hint }))} value={str || null} onChange={onChange} error={error} loading={!lookups.stages} />;
    case "tag":
      return (
        <ChoiceCombo
          label={label}
          items={meta.tags.map((t) => ({ value: t.id, label: t.name }))}
          value={meta.tags.find((t) => t.id === str || t.name.toLowerCase() === str.toLowerCase())?.id ?? (str || null)}
          onChange={onChange}
          error={error}
          hint={meta.tags.length === 0 ? "There are no tags yet: make one on a contact first." : undefined}
        />
      );
    case "user":
      return (
        <div className="ui-field">
          <span className="ui-label">{label}</span>
          <UserPicker label={p.label} value={str || null} onChange={onChange} error={!!error} clearable={p.nullable} />
          {error && (
            <p className="ui-hint" data-tone="danger">
              {error}
            </p>
          )}
        </div>
      );
    case "person":
      return <ChoiceCombo label={label} items={[{ value: "owner", label: "The record's owner" }, ...meta.users.map((u) => ({ value: u.id, label: u.name, hint: u.email }))]} value={str || null} onChange={onChange} error={error} clearable={p.nullable} placeholder={p.nullable ? "Nobody" : "Choose"} />;
    case "users":
      return (
        <div className="ui-field">
          <span className="ui-label">{label}</span>
          <UserPicker label={p.label} multiple value={Array.isArray(value) ? (value as string[]) : []} onChange={(v) => onChange(v.length ? v : null)} error={!!error} />
          {error && (
            <p className="ui-hint" data-tone="danger">
              {error}
            </p>
          )}
        </div>
      );
  }
  switch (p.kind) {
    case "choice":
      return <Select label={label} value={str || String(p.schema.default ?? "")} onValueChange={onChange} options={(p.choices ?? []).map((c) => ({ value: c, label: choiceLabel(c) }))} />;
    case "boolean":
      return <Switch label={p.label} checked={value === true} onCheckedChange={onChange} />;
    case "number":
      return <Input label={label} inputMode="numeric" value={typeof value === "number" ? String(value) : ""} error={error} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />;
    case "offset":
      return <OffsetInput label={p.label} value={value} onChange={onChange} error={error} hint={p.hint} required={p.required} />;
    case "fields":
      return <FieldValues object={object} value={(value as Record<string, unknown>) ?? {}} onChange={(v) => onChange(Object.keys(v).length ? v : null)} error={error} />;
    case "map":
      return <MapInput label={label} value={(value as Record<string, unknown>) ?? {}} onChange={(v) => onChange(Object.keys(v).length ? v : null)} error={error} hint={p.hint} />;
    case "uuid_list":
    case "json":
      return <JsonInput label={label} value={value} onChange={onChange} error={error} />;
    case "long_text":
    case "text": {
      const merge = MERGEABLE.has(p.key) ? <MergeField object={object} onPick={(k) => onChange(`${str}${str && !str.endsWith(" ") ? " " : ""}{{${k}}}`)} /> : null;
      const Control = p.kind === "long_text" ? Textarea : Input;
      return (
        <div className="wf-text">
          <Control label={label} value={str} maxLength={p.max} error={error} hint={p.hint} onChange={(e: { target: { value: string } }) => onChange(e.target.value)} />
          {merge}
        </div>
      );
    }
    default:
      return <Input label={label} value={str} error={error} hint={p.hint} onChange={(e) => onChange(e.target.value)} />;
  }
}

/** Fields to set on the record: a field and its value per row, each value in its field's own input. */
function FieldValues({ object, value, onChange, error }: { object: string; value: Record<string, unknown>; onChange: (v: Record<string, unknown>) => void; error?: string }) {
  const meta = useMeta();
  const fields = (meta.fields[object] ?? []).filter((f) => !f.archived && !isReadOnly(f) && f.key !== "display_name");
  const byKey = new Map(fields.map((f) => [f.key, f]));
  const free = fields.filter((f) => !(f.key in value));
  const keys = Object.keys(value);
  const rename = (from: string, to: string) => onChange(Object.fromEntries(Object.entries(value).map(([k, v]) => (k === from ? [to, null] : [k, v]))));
  return (
    <fieldset className="wf-rows">
      <legend className="ui-label">Fields to set</legend>
      {keys.length === 0 && <p className="wf-muted">Add the fields this step sets. An empty value clears the field.</p>}
      {keys.map((k) => {
        const f: FieldDef | undefined = byKey.get(k);
        return (
          <div key={k} className="wf-row">
            <Select aria-label="Field" value={k} onValueChange={(to) => rename(k, to)} options={[...(f ? [{ value: k, label: f.label }] : [{ value: k, label: `${k} (not a field)` }]), ...free.map((x) => ({ value: x.key, label: x.label }))]} />
            <div className="wf-row-value">{f ? <FieldEditor key={`${k}`} field={f} value={value[k] ?? undefined} onChange={(v) => onChange({ ...value, [k]: v ?? null })} /> : <Input aria-label={`Value of ${k}`} value={String(value[k] ?? "")} onChange={(e) => onChange({ ...value, [k]: e.target.value })} />}</div>
            <Button variant="ghost" size="icon" aria-label={`Stop setting ${f?.label ?? k}`} onClick={() => onChange(Object.fromEntries(Object.entries(value).filter(([x]) => x !== k)))}>
              <Trash2 size={16} aria-hidden />
            </Button>
          </div>
        );
      })}
      {free.length > 0 && (
        <Combobox
          label="Add a field"
          items={free.map((f) => ({ value: f.key, label: f.label }))}
          value={null}
          onChange={(k) => onChange({ ...value, [k]: null })}
          searchPlaceholder="Search fields"
          trigger={
            <Button variant="ghost" size="sm">
              <Plus size={14} aria-hidden /> Add a field
            </Button>
          }
        />
      )}
      {error && (
        <p className="ui-hint" data-tone="danger">
          {error}
        </p>
      )}
    </fieldset>
  );
}

/** Text keys and values ({"plan": "{{plan}}"}). Rows keep their place while a key is typed. */
function MapInput({ label, value, onChange, error, hint, keyLabel = "Key", keys }: { label: string; value: Record<string, unknown>; onChange: (v: Record<string, string>) => void; error?: string; hint?: string; keyLabel?: string; keys?: ComboItem[] }) {
  const [rows, setRows] = useState<[string, string][]>(() => Object.entries(value).map(([k, v]) => [k, v === null || v === undefined ? "" : String(v)]));
  const emit = (next: [string, string][]) => {
    setRows(next);
    onChange(Object.fromEntries(next.filter(([k]) => k.trim()).map(([k, v]) => [k.trim(), v])));
  };
  return (
    <fieldset className="wf-rows">
      <legend className="ui-label">{label}</legend>
      {rows.map(([k, v], i) => (
        <div key={i} className="wf-row">
          {keys ? (
            <Select aria-label={keyLabel} value={k || undefined} placeholder={keyLabel} onValueChange={(nk) => emit(rows.map((r, j) => (j === i ? [nk, r[1]] : r)))} options={keys.map((x) => ({ value: x.value, label: x.label }))} />
          ) : (
            <Input aria-label={`${keyLabel} ${i + 1}`} placeholder={keyLabel} value={k} onChange={(e) => emit(rows.map((r, j) => (j === i ? [e.target.value, r[1]] : r)))} />
          )}
          <Input aria-label={`Value ${i + 1}`} placeholder="Value" value={v} onChange={(e) => emit(rows.map((r, j) => (j === i ? [r[0], e.target.value] : r)))} />
          <Button variant="ghost" size="icon" aria-label={`Remove ${k || `row ${i + 1}`}`} onClick={() => emit(rows.filter((_, j) => j !== i))}>
            <Trash2 size={16} aria-hidden />
          </Button>
        </div>
      ))}
      <Button variant="ghost" size="sm" onClick={() => setRows([...rows, ["", ""]])}>
        <Plus size={14} aria-hidden /> Add
      </Button>
      {error ? (
        <p className="ui-hint" data-tone="danger">
          {error}
        </p>
      ) : hint ? (
        <p className="ui-hint">{hint}</p>
      ) : null}
    </fieldset>
  );
}

/** The last resort for a setting with no control of its own: its JSON, checked as it is typed. */
function JsonInput({ label, value, onChange, error }: { label: string; value: unknown; onChange: (v: unknown) => void; error?: string }) {
  const [text, setText] = useState(() => (value === undefined ? "" : JSON.stringify(value, null, 2)));
  const [bad, setBad] = useState(false);
  return (
    <Textarea
      label={label}
      className="mono"
      value={text}
      error={bad ? "This is not valid JSON yet" : error}
      onChange={(e) => {
        setText(e.target.value);
        if (!e.target.value.trim()) return (setBad(false), onChange(null));
        try {
          onChange(JSON.parse(e.target.value));
          setBad(false);
        } catch {
          setBad(true);
        }
      }}
    />
  );
}

