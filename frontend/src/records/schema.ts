import type { FieldDef, FieldType, ObjectDef, Op, RecordRow } from "./types.ts";

/** The type a value actually has: formula and rollup fields are as typed as their result. */
export const valueType = (f: Pick<FieldDef, "type" | "options">): FieldType =>
  f.type === "formula" || f.type === "rollup" ? (f.options.result ?? "number") : f.type;

export const isComputed = (f: Pick<FieldDef, "type">) => f.type === "formula" || f.type === "rollup";

/** Computed fields and system columns the user cannot type into. */
export const isReadOnly = (f: Pick<FieldDef, "type" | "rules">) => isComputed(f) || !!f.rules.read_only;

/** The derived name of a record (its primary fields joined): a column of the record that lists sort and filter by. */
export const DISPLAY_NAME = "display_name";

/** Columns every record has besides its fields: they are listed with the fields but belong to the record. */
export const COLUMN_KEYS = ["owner_id", "created_at", "updated_at"];

/** The key of the column that names a record in lists: its only primary field, or the derived name when several make it up. */
export const nameKey = (def: Pick<ObjectDef, "primary_fields">): string => (def.primary_fields.length === 1 ? def.primary_fields[0]! : DISPLAY_NAME);

/** A record's name from its values, as the server derives it: the primary fields joined with a space. */
export const nameOf = (def: Pick<ObjectDef, "primary_fields">, values: Record<string, unknown>): string =>
  def.primary_fields
    .map((k) => values[k])
    .filter((v): v is string => typeof v === "string" && v !== "")
    .join(" ");

// A person is not sortable: the server would have to join users, so a list never offers it (the owner column included).
const UNSORTABLE: FieldType[] = ["multi_select", "record", "long_text", "user"];
export const isSortable = (f: Pick<FieldDef, "type" | "options">) => !UNSORTABLE.includes(valueType(f));

/** Raw value of a field on a record, whether it lives in a column or in `values`. */
export function readValue(rec: RecordRow, key: string): unknown {
  switch (key) {
    case "id":
      return rec.id;
    case "display_name":
      return rec.display_name;
    case "owner_id":
      return rec.owner_id;
    case "created_at":
      return rec.created_at;
    case "updated_at":
      return rec.updated_at;
    default:
      return rec.values[key];
  }
}

/** Fields to show: not archived, in the order the workspace set. */
export const liveFields = (fields: FieldDef[]) => fields.filter((f) => !f.archived).sort((a, b) => a.position - b.position);

export const needsValue = (op: Op) => op !== "is_empty" && op !== "is_not_empty";
