import { Link, useLocation } from "react-router";
import type { Column } from "../ui";
import { FieldValue, TagBadge } from "./fields/FieldValue";
import { subtitle } from "./format.ts";
import { recordPath } from "./paths.ts";
import { isSortable, liveFields, readValue, valueType } from "./schema.ts";
import type { FieldDef, FieldType, ObjectDef, RecordRow, SortSpec } from "./types.ts";

/** Tags are not a field, but a list can show them as a column. */
export const TAGS_KEY = "tags";

export const DEFAULT_SORT: SortSpec[] = [{ field: "updated_at", dir: "desc" }];

/** The columns a list starts with when no view says otherwise: the name, four more fields, owner and created. */
export function defaultColumns(def: ObjectDef, fields: FieldDef[]): string[] {
  const live = liveFields(fields);
  const own = live.filter((f) => f.key !== def.primary_field && !f.is_system && f.type !== "long_text").slice(0, 4).map((f) => f.key);
  return [def.primary_field, ...own, "owner_id", "created_at"].filter((k, i, all) => all.indexOf(k) === i);
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
  const sub = rail ? subtitle(row.values, rail, def.primary_field) : "";
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

export function buildColumns(def: ObjectDef, fields: FieldDef[], keys: string[], rail: boolean): Column<RecordRow>[] {
  const byKey = new Map(fields.map((f) => [f.key, f]));
  const primary = byKey.get(def.primary_field);
  const shown = keys.map((k) => byKey.get(k)).filter((f): f is FieldDef => !!f && f.key !== def.primary_field);
  const name: Column<RecordRow> = {
    key: def.primary_field,
    header: primary?.label ?? "Name",
    sortable: true,
    width: rail ? 296 : 220,
    cell: (r) => <NameCell def={def} row={r} rail={rail ? shown : undefined} />,
  };
  if (rail) return [name];
  const rest = keys.flatMap((k): Column<RecordRow>[] => {
    if (k === def.primary_field) return [];
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
