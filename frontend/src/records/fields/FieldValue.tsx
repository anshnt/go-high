import { Check, Minus } from "lucide-react";
import type { ReactNode } from "react";
import { Link } from "react-router";
import { Avatar, Badge } from "../../ui";
import { useRecordsClient } from "../client.ts";
import { formatDateTime, formatDay, formatMoney, formatNumber, isMoney, relativeDay, relativeTime } from "../format.ts";
import { useMeta, useRecordRef } from "../meta.tsx";
import { recordPath } from "../paths.ts";
import { valueType } from "../schema.ts";
import type { FieldDef, Tag } from "../types.ts";
import { isEmptyValue } from "../validate.ts";
import { toneOf } from "./tone.ts";

export function UserValue({ id }: { id: string }) {
  const user = useMeta().users.find((u) => u.id === id);
  return (
    <span className="rec-user">
      <Avatar name={user?.name ?? "Unknown"} size="sm" />
      <span className="rec-ellipsis">{user?.name ?? "Unknown person"}</span>
    </span>
  );
}

/** A link to another record, by name. Opens that record in its own list. */
export function RecordChip({ object, id }: { object: string; id: string }) {
  const client = useRecordsClient();
  const meta = useMeta();
  const row = useRecordRef(client, object, id);
  const def = meta.objects.find((o) => o.key === object);
  if (row === undefined) return <span className="rec-chip" data-loading aria-busy="true">Loading</span>;
  if (row === null || !def) return <span className="rec-chip" data-gone>Deleted record</span>;
  return (
    <Link to={recordPath(def, id)} className="rec-chip" title={`Open ${def.singular.toLowerCase()} ${row.display_name}`}>
      <span className="rec-ellipsis">{row.display_name}</span>
    </Link>
  );
}

export const TagBadge = ({ tag }: { tag: Tag }) => <Badge tone={toneOf(tag.color)}>{tag.name}</Badge>;

const hostOf = (u: string) => u.replace(/^https?:\/\//i, "").replace(/\/$/, "");

/** The value of a field as it reads on screen. Returns null when there is nothing to show; the caller decides what an empty value looks like. */
export function FieldValue({ field, value, wrap }: { field: FieldDef; value: unknown; /** show long text in full, wrapped */ wrap?: boolean }): ReactNode {
  if (isEmptyValue(value) && valueType(field) !== "boolean") return null;
  const type = valueType(field);
  const choices = field.options.choices ?? [];
  switch (type) {
    case "number":
      return <span className="num">{typeof value === "number" ? formatNumber(value) : String(value)}</span>;
    case "money":
      return isMoney(value) ? <span className="num">{formatMoney(value)}</span> : null;
    case "date": {
      const day = String(value);
      return <time dateTime={day} title={formatDay(day)}>{relativeDay(day, Date.now())}</time>;
    }
    case "datetime": {
      const iso = String(value);
      return <time dateTime={iso} title={formatDateTime(iso)}>{relativeTime(iso, Date.now())}</time>;
    }
    case "boolean":
      return value ? (
        <span className="rec-bool" data-on>
          <Check size={14} aria-hidden /> Yes
        </span>
      ) : (
        <span className="rec-bool">
          <Minus size={14} aria-hidden /> No
        </span>
      );
    case "select":
    case "stage": {
      const c = choices.find((x) => x.id === value);
      return <Badge tone={toneOf(c?.color)}>{c?.label ?? String(value)}</Badge>;
    }
    case "multi_select":
      return (
        <span className="rec-badges">
          {(Array.isArray(value) ? value : [value]).map((id) => {
            const c = choices.find((x) => x.id === id);
            return (
              <Badge key={String(id)} tone={toneOf(c?.color)}>
                {c?.label ?? String(id)}
              </Badge>
            );
          })}
        </span>
      );
    case "email":
      return (
        <a href={`mailto:${value}`} className="rec-link rec-ellipsis">
          {String(value)}
        </a>
      );
    case "phone":
      return (
        <a href={`tel:${String(value).replace(/[^\d+]/g, "")}`} className="rec-link">
          {String(value)}
        </a>
      );
    case "url":
      return /^https?:\/\//i.test(String(value)) ? (
        <a href={String(value)} target="_blank" rel="noopener noreferrer" className="rec-link rec-ellipsis">
          {hostOf(String(value))}
        </a>
      ) : (
        <span className="rec-ellipsis">{String(value)}</span>
      );
    case "user":
      return <UserValue id={String(value)} />;
    case "record":
      return field.options.object ? <RecordChip object={field.options.object} id={String(value)} /> : null;
    case "long_text":
      return <span className={wrap ? "rec-prose" : "rec-ellipsis"}>{String(value)}</span>;
    default:
      return <span className="rec-ellipsis">{String(value)}</span>;
  }
}
