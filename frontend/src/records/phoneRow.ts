// What a record shows under its name in the two-line rows of the phone list. No React, so node can test it.
import { COLUMN_KEYS, DISPLAY_NAME, liveFields, readValue, valueType } from "./schema.ts";
import type { FieldDef, FieldType, ObjectDef, RecordRow } from "./types.ts";
import { isEmptyValue } from "./validate.ts";

/** How well a type tells records apart at a glance (lower first): an email, the company, a phone number, then the rest. Types left out never show. */
const RANK: Partial<Record<FieldType, number>> = { email: 0, record: 1, phone: 2, stage: 3, select: 3, money: 4, url: 5, text: 6, number: 7, date: 8 };

export const PHONE_LINES = 2;

export type PhoneLine = { field: FieldDef; value: unknown };

/** The two most useful filled values besides the name, best type first and in field order among equals. */
export function phoneLines(def: Pick<ObjectDef, "primary_fields">, row: RecordRow, fields: FieldDef[]): PhoneLine[] {
  return liveFields(fields)
    .filter((f) => !def.primary_fields.includes(f.key) && f.key !== DISPLAY_NAME && !COLUMN_KEYS.includes(f.key) && RANK[valueType(f)] !== undefined && !isEmptyValue(readValue(row, f.key)))
    .map((field, order) => ({ field, order }))
    .sort((a, b) => RANK[valueType(a.field)]! - RANK[valueType(b.field)]! || a.order - b.order)
    .slice(0, PHONE_LINES)
    .map(({ field }) => ({ field, value: readValue(row, field.key) }));
}
