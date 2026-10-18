// Setting one field on many records at once (the list's "Edit fields" bulk action), and the row change the screens show
// before the server answers. Pure, so node can test it.
import { RecordsError, errorMessage } from "./errors.ts";
import { canonical } from "./filter.ts";
import { COLUMN_KEYS, DISPLAY_NAME, isReadOnly, nameOf, valueType } from "./schema.ts";
import type { FieldDef, ObjectDef, RecordRow } from "./types.ts";
import { isEmptyValue, normalizeText, validateValue } from "./validate.ts";

/** A row with one field changed, its name kept in step when the field is part of it. `undefined` removes the value. */
export const withChange = (row: RecordRow, def: Pick<ObjectDef, "primary_fields">, key: string, value: unknown): RecordRow => {
  if (key === "owner_id") return { ...row, owner_id: (value as string | undefined) ?? null };
  const values = { ...row.values };
  if (value === undefined) delete values[key];
  else values[key] = value;
  return { ...row, values, display_name: def.primary_fields.includes(key) ? nameOf(def, values) : row.display_name };
};

/**
 * The fields a bulk edit offers: the object's own, live fields a person can type into. The record's columns (owner,
 * created, updated, the derived name) are left out, so are read-only and calculated fields; the owner has its own action.
 */
export const bulkFields = (fields: FieldDef[]): FieldDef[] =>
  fields.filter((f) => !f.archived && !isReadOnly(f) && f.key !== DISPLAY_NAME && !COLUMN_KEYS.includes(f.key) && (f.type !== "record" || !!f.options.object));

/** What the editor holds to what is sent: text is trimmed (and normalized like inline edits), empty means clear. */
export function bulkValue(field: FieldDef, draft: unknown, clear: boolean): { value: unknown } | { error: string } {
  if (clear) return field.rules.required ? { error: `${field.label} is required, so it cannot be cleared.` } : { value: undefined };
  const v = typeof draft === "string" ? normalizeText(field, draft) : draft;
  const value = valueType(field) === "boolean" ? v === true : isEmptyValue(v) ? undefined : v;
  if (value === undefined) return { error: field.rules.required ? `${field.label} is required.` : `Enter a value, or choose to clear ${field.label}.` };
  const msg = validateValue(field, value);
  return msg ? { error: msg } : { value };
}

/** The message to show for a refused bulk edit: what the server said about the field, or about the records as a whole. */
export function bulkError(e: unknown, key: string): string {
  if (e instanceof RecordsError && e.fields) return e.fields[key] ?? Object.values(e.fields).join(" ");
  return errorMessage(e);
}

/** For undo: the records grouped by the value the field had before, so each group goes back in one call. */
export function undoGroups(rows: RecordRow[], key: string): { value: unknown; ids: string[] }[] {
  const groups = new Map<string, { value: unknown; ids: string[] }>();
  for (const r of rows) {
    const value = r.values[key];
    const k = canonical(value ?? null);
    const g = groups.get(k);
    if (g) g.ids.push(r.id);
    else groups.set(k, { value, ids: [r.id] });
  }
  return [...groups.values()];
}
