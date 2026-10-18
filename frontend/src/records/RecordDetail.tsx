import { Mail, Pencil, Phone, Plus, SearchX, Trash2, X } from "lucide-react";
import { useCallback, useEffect, useId, useMemo, useRef, useState, type KeyboardEvent } from "react";
import { Avatar, Button, EmptyState, Skeleton, Switch, useToast } from "../ui";
import { Combobox } from "../ui/Combobox";
import { Associations } from "./Associations";
import type { RecordsClient } from "./client.ts";
import { errorMessage, errorStatus, RecordsError } from "./errors.ts";
import { FieldEditor } from "./fields/FieldEditor";
import { FieldValue, TagBadge } from "./fields/FieldValue";
import { relativeTime } from "./format.ts";
import { canonical } from "./filter.ts";
import { primeRefs, useMeta } from "./meta.tsx";
import { isComputed, isReadOnly, nameOf, readValue, valueType } from "./schema.ts";
import { Timeline } from "./Timeline";
import type { FieldDef, ObjectDef, RecordRow } from "./types.ts";
import { isEmptyValue, normalizeText, validateValue } from "./validate.ts";

type Save = (key: string, value: unknown) => Promise<string | null>;

const TEXTLIKE = ["text", "long_text", "email", "phone", "url", "number", "money", "date", "datetime"];
const POPOVER = ["select", "stage", "multi_select", "user"];

const withChange = (row: RecordRow, def: ObjectDef, key: string, value: unknown): RecordRow => {
  if (key === "owner_id") return { ...row, owner_id: (value as string | undefined) ?? null };
  const values = { ...row.values };
  if (value === undefined) delete values[key];
  else values[key] = value;
  return { ...row, values, display_name: def.primary_fields.includes(key) ? nameOf(def, values) : row.display_name };
};

/** One field: its value, and the right way to change it. Saves go through `save`, which is optimistic and reports a message if it had to roll back. */
function PropertyRow({ field, row, save }: { field: FieldDef; row: RecordRow; save: Save }) {
  const type = valueType(field);
  const value = readValue(row, field.key);
  const readOnly = isReadOnly(field);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState<unknown>(undefined);
  const [pending, setPending] = useState<unknown>(undefined); // multi select, until its list closes
  const [error, setError] = useState<string | null>(null);
  const [round, setRound] = useState(0);
  const cancelled = useRef(false);
  const id = useId();
  const label = field.label;
  const empty = isEmptyValue(value) && type !== "boolean";
  const placeholder = <span className="rec-placeholder">{readOnly ? "-" : `Add ${label.charAt(0).toLowerCase()}${label.slice(1)}`}</span>;
  const shown = empty ? placeholder : <FieldValue field={field} value={value} wrap />;

  const commit = async (next: unknown): Promise<boolean> => {
    const v = typeof next === "string" ? normalizeText(field, next) : next;
    const clean = isEmptyValue(v) && type !== "boolean" ? undefined : v;
    const msg = validateValue(field, clean);
    if (msg) {
      setError(msg);
      return false;
    }
    setEditing(false);
    setError(null);
    if (canonical(clean ?? null) === canonical(value ?? null)) return true;
    const failed = await save(field.key, clean);
    setError(failed);
    return failed === null;
  };
  const begin = () => {
    cancelled.current = false;
    setDraft(value);
    setError(null);
    setRound((n) => n + 1);
    setEditing(true);
  };
  const cancel = () => {
    cancelled.current = true;
    setEditing(false);
    setError(null);
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      cancel();
    } else if (e.key === "Enter" && (type !== "long_text" || e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void commit(draft);
    }
  };

  const pencil = (
    <button type="button" className="rec-edit-btn" aria-label={`Edit ${label}`} onClick={begin}>
      <Pencil size={14} aria-hidden />
    </button>
  );

  let body;
  if (readOnly) {
    body = <div className="rec-prop-value" data-readonly>{shown}</div>;
  } else if (type === "boolean") {
    body = (
      <div className="rec-prop-value rec-prop-switch">
        <Switch aria-label={label} checked={value === true} onCheckedChange={(on) => void commit(on)} />
        <span>{value === true ? "Yes" : "No"}</span>
      </div>
    );
  } else if (POPOVER.includes(type)) {
    const trigger = (
      <button type="button" className="rec-prop-value rec-prop-btn" aria-label={`Edit ${label}`}>
        {pending !== undefined && type === "multi_select" ? <FieldValue field={field} value={pending} /> : shown}
      </button>
    );
    body = (
      <FieldEditor
        field={field}
        value={type === "multi_select" && pending !== undefined ? pending : value}
        trigger={trigger}
        onChange={(v) => (type === "multi_select" ? setPending(v ?? []) : void commit(v))}
        onClose={() => {
          if (type === "multi_select" && pending !== undefined) {
            const next = pending;
            setPending(undefined);
            void commit(next);
          }
        }}
      />
    );
  } else if (type === "record") {
    body = (
      <div className="rec-prop-row">
        <div className="rec-prop-value">{shown}</div>
        <FieldEditor field={field} value={value} trigger={pencil} onChange={(v) => void commit(v)} />
      </div>
    );
  } else if (TEXTLIKE.includes(type) && editing) {
    body = (
      <div
        className="rec-prop-edit"
        onBlur={(e) => {
          if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
          if (cancelled.current) return void (cancelled.current = false);
          if (canonical(draft ?? null) === canonical(value ?? null)) cancel();
          else void commit(draft);
        }}
      >
        <FieldEditor key={round} id={id} field={field} value={draft} onChange={setDraft} autoFocus invalid={!!error} onKeyDown={onKey} />
        <div className="rec-prop-btns">
          <Button size="sm" variant="primary" onClick={() => void commit(draft)}>
            Save
          </Button>
          <Button size="sm" variant="ghost" onClick={cancel}>
            Cancel
          </Button>
        </div>
      </div>
    );
  } else {
    body = (
      <div className="rec-prop-row">
        <div className="rec-prop-value" data-editable onClick={(e) => !(e.target as HTMLElement).closest("a") && begin()}>
          {shown}
        </div>
        {pencil}
      </div>
    );
  }

  return (
    <div className="rec-prop" data-error={error ? true : undefined}>
      <label className="rec-prop-label" htmlFor={editing ? id : undefined}>
        {label}
        {field.rules.required && <span aria-hidden> *</span>}
      </label>
      {body}
      {error && (
        <p className="ui-hint" data-tone="danger" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}

function useRecord(client: RecordsClient, def: ObjectDef, id: string, initial: RecordRow | undefined) {
  const [state, setState] = useState<{ row: RecordRow | null; status: "loading" | "ready" | "error"; error?: unknown }>({ row: initial ?? null, status: initial ? "ready" : "loading" });
  useEffect(() => {
    let live = true;
    client.get(def.key, id).then(
      (row) => live && setState({ row, status: "ready" }),
      (error) => live && setState((s) => ({ ...s, status: "error", error })),
    );
    return () => {
      live = false;
    };
  }, [client, def.key, id]);
  return [state, setState] as const;
}

type Props = {
  client: RecordsClient;
  def: ObjectDef;
  id: string;
  /** The row the list already has, shown at once while the full record loads. */
  initial?: RecordRow;
  fields: FieldDef[];
  onClose: () => void;
  /** Called with every change, optimistic ones and roll-backs included, so the list row stays in step. */
  onChanged: (row: RecordRow) => void;
  onDelete: (row: RecordRow) => void;
};

export function RecordDetail({ client, def, id, initial, fields, onClose, onChanged, onDelete }: Props) {
  const toast = useToast();
  const meta = useMeta();
  const [state, setState] = useRecord(client, def, id, initial);
  const [version, setVersion] = useState(0);
  const row = state.row;
  const rowRef = useRef(row);
  rowRef.current = row;
  const onChangedRef = useRef(onChanged);
  onChangedRef.current = onChanged;

  useEffect(() => {
    if (row) {
      primeRefs(client, [row]);
      onChangedRef.current(row);
    }
  }, [client, row]);

  const setRow = useCallback((fn: (r: RecordRow) => RecordRow) => setState((s) => (s.row ? { ...s, row: fn(s.row) } : s)), [setState]);
  const computedKeys = useMemo(() => fields.filter(isComputed).map((f) => f.key), [fields]);

  // Saves run one at a time. The screen changes at once; if the server says no, only that field goes back.
  const chain = useRef<Promise<unknown>>(Promise.resolve());
  const save = useCallback<Save>(
    (key, value) => {
      const before = rowRef.current;
      if (!before) return Promise.resolve("Still loading.");
      const prev = key === "owner_id" ? before.owner_id : before.values[key];
      setRow((r) => withChange(r, def, key, value));
      const run = async (): Promise<string | null> => {
        try {
          const saved = await client.update(def.key, id, { [key]: value ?? null });
          // the server may have normalized what was typed (an email in lower case, a phone number as +14155550101): show its version
          setRow((r) => ({
            ...r,
            updated_at: saved.updated_at,
            display_name: saved.display_name,
            ...(key === "owner_id" ? { owner_id: saved.owner_id } : {}),
            values: { ...r.values, ...(key !== "owner_id" && key in saved.values ? { [key]: saved.values[key] } : {}), ...Object.fromEntries(computedKeys.map((k) => [k, saved.values[k]])) },
          }));
          setVersion((v) => v + 1);
          return null;
        } catch (e) {
          setRow((r) => withChange(r, def, key, prev ?? undefined));
          // a refused move says what is missing on the deal ("Close date is required to leave Proposal"): all of it, under the field being changed
          return e instanceof RecordsError && e.fields ? (e.fields[key] ?? Object.values(e.fields).join(" ")) : errorMessage(e);
        }
      };
      const job = chain.current.then(run);
      chain.current = job;
      return job;
    },
    [client, def, id, setRow, computedKeys],
  );

  const retag = useCallback(
    async (ids: string[]) => {
      const before = rowRef.current;
      if (!before) return;
      const had = new Set(before.tags.map((t) => t.id));
      const next = new Set(ids);
      const add = ids.filter((t) => !had.has(t));
      const drop = [...had].filter((t) => !next.has(t));
      const tagOf = (tid: string) => meta.tags.find((t) => t.id === tid)!;
      setRow((r) => ({ ...r, tags: ids.map(tagOf) }));
      try {
        for (const t of add) await client.tag([id], t);
        for (const t of drop) await client.untag([id], t);
        setVersion((v) => v + 1);
      } catch (e) {
        setRow((r) => ({ ...r, tags: before.tags }));
        toast({ title: "Could not change tags", description: errorMessage(e), tone: "danger" });
      }
    },
    [client, id, meta.tags, setRow, toast],
  );

  if (!row) {
    return (
      <section className="rec-detail" aria-label={`${def.singular} details`} aria-busy={state.status === "loading"}>
        {state.status === "error" ? (
          <EmptyState
            icon={SearchX}
            title={errorStatus(state.error) === 403 ? "You do not have access to this record" : `This ${def.singular.toLowerCase()} was not found`}
            text={errorStatus(state.error) === 403 ? "Ask a workspace admin for access." : "It may have been deleted. You can restore deleted records for 30 days."}
            action={<Button onClick={onClose}>Back to the list</Button>}
          />
        ) : (
          <div className="rec-d-loading">
            <Skeleton style={{ width: "50%", height: 20 }} />
            <Skeleton style={{ width: "80%" }} />
            <Skeleton style={{ width: "65%" }} />
            <Skeleton style={{ width: "75%" }} />
          </div>
        )}
      </section>
    );
  }

  const email = fields.find((f) => valueType(f) === "email" && typeof row.values[f.key] === "string");
  const phone = fields.find((f) => valueType(f) === "phone" && typeof row.values[f.key] === "string");
  const title = row.display_name || `Untitled ${def.singular.toLowerCase()}`;

  return (
    <section className="rec-detail" aria-label={`${def.singular} details: ${title}`}>
      <header className="rec-d-head">
        <div className="rec-d-top">
          <span className="rec-d-avatar">
            <Avatar name={title} />
          </span>
          <div className="rec-d-titles">
            <h2 className="rec-d-title">{title}</h2>
            <p className="rec-d-sub">
              {def.singular} · created {relativeTime(row.created_at, Date.now())}
            </p>
          </div>
          <div className="rec-d-actions">
            {email && (
              <a className="ui-btn" data-variant="secondary" data-size="sm" href={`mailto:${row.values[email.key]}`}>
                <Mail size={14} aria-hidden /> <span className="rec-hide-sm">Email</span>
              </a>
            )}
            {phone && (
              <a className="ui-btn" data-variant="secondary" data-size="sm" href={`tel:${String(row.values[phone.key]).replace(/[^\d+]/g, "")}`}>
                <Phone size={14} aria-hidden /> <span className="rec-hide-sm">Call</span>
              </a>
            )}
            <Button size="sm" variant="ghost" onClick={() => onDelete(row)}>
              <Trash2 size={14} aria-hidden /> <span className="rec-hide-sm">Delete</span>
            </Button>
          </div>
          <Button size="icon" variant="ghost" aria-label={`Close ${def.singular.toLowerCase()}`} onClick={onClose}>
            <X size={16} aria-hidden />
          </Button>
        </div>
        <div className="rec-d-tags">
          {row.tags.map((t) => (
            <span key={t.id} className="rec-tag-pill">
              <TagBadge tag={t} />
              <button type="button" className="rec-tag-x" aria-label={`Remove tag ${t.name}`} onClick={() => void retag(row.tags.filter((x) => x.id !== t.id).map((x) => x.id))}>
                <X size={10} aria-hidden />
              </button>
            </span>
          ))}
          <Combobox
            multiple
            label="Tags"
            items={meta.tags.map((t) => ({ value: t.id, label: t.name }))}
            value={row.tags.map((t) => t.id)}
            onChange={(ids) => void retag(ids)}
            searchPlaceholder="Search tags"
            trigger={
              <Button size="sm" variant="ghost">
                <Plus size={14} aria-hidden /> Tag
              </Button>
            }
          />
        </div>
      </header>

      <div className="rec-d-body">
        <section className="rec-props" aria-label="Properties">
          <h3 className="rec-section-title">Properties</h3>
          {fields.map((f) => (
            <PropertyRow key={f.key} field={f} row={row} save={save} />
          ))}
        </section>
        <div className="rec-d-time">
          <Timeline client={client} recordId={row.id} version={version} fields={fields} />
        </div>
        <aside className="rec-d-assoc" aria-label="Associations">
          <Associations client={client} def={def} record={row} version={version} />
        </aside>
      </div>
    </section>
  );
}
