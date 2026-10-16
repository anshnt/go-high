import type { FieldDef, FieldType, Op, RecordRow } from "./types.ts";

/** The type a value actually has: formula and rollup fields are as typed as their result. */
export const valueType = (f: Pick<FieldDef, "type" | "options">): FieldType =>
  f.type === "formula" || f.type === "rollup" ? (f.options.result ?? "number") : f.type;

export const isComputed = (f: Pick<FieldDef, "type">) => f.type === "formula" || f.type === "rollup";

/** Computed fields and system columns the user cannot type into. */
export const isReadOnly = (f: Pick<FieldDef, "type" | "rules">) => isComputed(f) || !!f.rules.read_only;

const UNSORTABLE: FieldType[] = ["multi_select", "record", "long_text"];
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

export const needsValue = (op: Op) => op !== "is_empty" && op !== "is_not_empty";
