import { Link, useLocation } from "react-router";
import type { Column } from "../ui";
import { useRecordsClient } from "./client.ts";
import { FieldValue, TagBadge } from "./fields/FieldValue";
import { subtitle, valueText } from "./format.ts";
import { useMeta, useRecordRef } from "./meta.tsx";
import { recordPath } from "./paths.ts";
import { phoneLines } from "./phoneRow.ts";
import { COLUMN_KEYS, DISPLAY_NAME, isSortable, liveFields, nameKey, readValue, valueType } from "./schema.ts";
import type { FieldDef, FieldType, ObjectDef, RecordRow, SortSpec } from "./types.ts";

/** Tags are not a field, but a list can show them as a column. */
export const TAGS_KEY = "tags";

export const DEFAULT_SORT: SortSpec[] = [{ field: "updated_at", dir: "desc" }];

/** The columns a list starts with when no view says otherwise: the name, four more fields, owner and created. */
export function defaultColumns(def: ObjectDef, fields: FieldDef[]): string[] {
  const own = liveFields(fields)
    .filter((f) => !def.primary_fields.includes(f.key) && f.key !== DISPLAY_NAME && !COLUMN_KEYS.includes(f.key) && f.type !== "long_text")
    .slice(0, 4)
    .map((f) => f.key);
  return [nameKey(def), ...own, "owner_id", "created_at"].filter((k, i, all) => all.indexOf(k) === i);
}

const WIDTH: Partial<Record<FieldType, number>> = {
  number: 110,
  money: 130,
  date: 130,
  datetime: 140,
  boolean: 100,
  select: 140,
  stage: 140,
  multi_select: 200,
  email: 220,
  phone: 160,
  url: 190,
  user: 150,
  record: 180,
  text: 180,
  long_text: 240,
};

/** Name column: a real link, so Tab and Enter work without the list's shortcuts. In the narrow list beside an open record it also shows one more detail. */
function NameCell({ def, row, rail }: { def: ObjectDef; row: RecordRow; rail?: FieldDef[] }) {
  const sub = rail ? subtitle(row.values, rail, def.primary_fields) : "";
  const { search } = useLocation(); // keeps the open view when a record opens
  return (
    <span className="rec-name-cell">
      <Link to={{ pathname: recordPath(def, row.id), search }} className="rec-name">
        {row.display_name || `Untitled ${def.singular.toLowerCase()}`}
      </Link>
      {sub && <span className="rec-name-sub rec-ellipsis">{sub}</span>}
    </span>
  );
}

/** One value of a phone row, as plain text (the row is a link; a link inside it would be a trap for a thumb). */
function PhoneValue({ field, value }: { field: FieldDef; value: unknown }) {
  const client = useRecordsClient();
  const { users } = useMeta();
  const linked = useRecordRef(client, field.type === "record" ? field.options.object : undefined, value);
  if (field.type === "record") return <>{linked ? linked.display_name : "..."}</>;
  return <>{valueText(field, value, { users })}</>;
}

/** The phone list: the name, then the two most useful other values on a second line. */
function PhoneCell({ def, row, fields }: { def: ObjectDef; row: RecordRow; fields: FieldDef[] }) {
  const { search } = useLocation();
  const lines = phoneLines(def, row, fields);
  return (
    <span className="rec-phone-cell">
      <Link to={{ pathname: recordPath(def, row.id), search }} className="rec-name">
        {row.display_name || `Untitled ${def.singular.toLowerCase()}`}
      </Link>
      {lines.length > 0 && (
        <span className="rec-phone-sub rec-ellipsis">
          {lines.map((l, i) => (
            <span key={l.field.key}>
              {i > 0 && " · "}
              <PhoneValue field={l.field} value={l.value} />
            </span>
          ))}
        </span>
      )}
    </span>
  );
}

export function buildColumns(def: ObjectDef, fields: FieldDef[], keys: string[], rail: boolean, phone = false): Column<RecordRow>[] {
  const byKey = new Map(fields.map((f) => [f.key, f]));
  const first = nameKey(def);
  const primary = byKey.get(first);
  const shown = keys.map((k) => byKey.get(k)).filter((f): f is FieldDef => !!f && f.key !== first);
  const name: Column<RecordRow> = {
    key: first,
    header: primary?.label ?? "Name",
    sortable: true,
    width: rail ? 296 : 220,
    cell: (r) => (phone ? <PhoneCell def={def} row={r} fields={fields} /> : <NameCell def={def} row={r} rail={rail ? shown : undefined} />),
  };
  if (rail || phone) return [name];
  const rest = keys.flatMap((k): Column<RecordRow>[] => {
    if (k === first) return [];
    if (k === TAGS_KEY) return [{ key: TAGS_KEY, header: "Tags", width: 200, cell: (r) => <span className="rec-badges">{r.tags.map((t) => <TagBadge key={t.id} tag={t} />)}</span> }];
    const f = byKey.get(k);
    if (!f) return [];
    const type = valueType(f);
    return [
      {
        key: f.key,
        header: f.label,
        sortable: isSortable(f),
        align: type === "number" || type === "money" ? "right" : undefined,
        width: WIDTH[type] ?? 160,
        cell: (r) => <FieldValue field={f} value={readValue(r, f.key)} />,
      },
    ];
  });
  return [name, ...rest];
}
