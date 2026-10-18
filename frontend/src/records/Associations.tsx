import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { Avatar, Button, Skeleton } from "../ui";
import type { RecordsClient } from "./client.ts";
import { subtitle } from "./format.ts";
import { primeRefs, useMeta, type Meta } from "./meta.tsx";
import { recordPath } from "./paths.ts";
import { liveFields } from "./schema.ts";
import type { FieldDef, Filter, ObjectDef, RecordRow } from "./types.ts";

const SHOWN = 4;
const FETCH = 25;

function Item({ def, fields, row }: { def: ObjectDef; fields: FieldDef[]; row: RecordRow }) {
  const sub = subtitle(row.values, fields, def.primary_fields);
  return (
    <li>
      <Link to={recordPath(def, row.id)} className="rec-assoc-item">
        <Avatar name={row.display_name || def.singular} size="sm" />
        <span className="rec-assoc-text">
          <span className="rec-ellipsis">{row.display_name || "Untitled"}</span>
          {sub && <span className="rec-assoc-sub rec-ellipsis">{sub}</span>}
        </span>
      </Link>
    </li>
  );
}

/**
 * The records of `other` that are linked to this one, whichever way the link was made: a record field (a contact's
 * company), a record field on the other side (the contacts whose company is this one) or an association. One condition
 * per way, joined with "or", so the server finds each record once however many ways link it. Null when nothing can link them.
 */
export function linkedFilter(meta: Meta, def: ObjectDef, record: RecordRow, other: ObjectDef): Filter | null {
  const ways: Filter[] = [];
  if (meta.links.some((t) => (t.from === def.key && t.to === other.key) || (t.to === def.key && t.from === other.key))) {
    ways.push({ field: `${def.key}.id`, op: "is", value: record.id });
  }
  for (const f of liveFields(meta.fields[other.key] ?? [])) {
    if (f.type === "record" && f.options.object === def.key) ways.push({ field: f.key, op: "is", value: record.id });
  }
  for (const f of liveFields(meta.fields[def.key] ?? [])) {
    const id = record.values[f.key];
    if (f.type === "record" && f.options.object === other.key && typeof id === "string") ways.push({ field: "id", op: "is", value: id });
  }
  return ways.length === 0 ? null : ways.length === 1 ? ways[0]! : { or: ways };
}

/** One kind of linked record: contacts of a company, deals of a contact. */
function Linked({ client, other, filter, version }: { client: RecordsClient; other: ObjectDef; filter: Filter; version: number }) {
  const meta = useMeta();
  const [state, setState] = useState<{ rows: RecordRow[]; total: number; status: "loading" | "ready" | "error" }>({ rows: [], total: 0, status: "loading" });
  const [all, setAll] = useState(false);
  const key = JSON.stringify(filter);
  useEffect(() => {
    let live = true;
    setState((s) => ({ ...s, status: "loading" }));
    client.query(other.key, { filter, limit: FETCH, sort: [{ field: "updated_at", dir: "desc" }] }).then(
      (p) => {
        if (!live) return;
        primeRefs(client, p.data);
        setState({ rows: p.data, total: p.total ?? p.data.length, status: "ready" });
      },
      () => live && setState({ rows: [], total: 0, status: "error" }),
    );
    return () => {
      live = false;
    };
    // `key` stands for `filter`; `version` moves on when the record was saved, which may have changed its links
  }, [client, other.key, key, version]);
  const fields = useMemo(() => liveFields(meta.fields[other.key] ?? []), [meta.fields, other.key]);
  const shown = all ? state.rows : state.rows.slice(0, SHOWN);
  return (
    <section className="rec-assoc" aria-label={other.plural}>
      <h3 className="rec-section-title">
        {other.plural} {state.status === "ready" && <span className="rec-count-pill">{state.total}</span>}
      </h3>
      {state.status === "loading" && state.rows.length === 0 && <Skeleton style={{ width: "70%" }} />}
      {state.status === "error" && <p className="rec-assoc-none">Could not load {other.plural.toLowerCase()}.</p>}
      {state.status === "ready" && state.rows.length === 0 && <p className="rec-assoc-none">No {other.plural.toLowerCase()} linked yet.</p>}
      {shown.length > 0 && (
        <ul className="rec-assoc-list">
          {shown.map((r) => (
            <Item key={r.id} def={other} fields={fields} row={r} />
          ))}
        </ul>
      )}
      {state.rows.length > SHOWN && (
        <Button variant="ghost" size="sm" onClick={() => setAll((v) => !v)}>
          {all ? "Show fewer" : `Show ${Math.min(state.rows.length, FETCH) - SHOWN} more`}
        </Button>
      )}
      {state.total > FETCH && all && <p className="rec-assoc-none">And {state.total - FETCH} more.</p>}
    </section>
  );
}

export function Associations({ client, def, record, version }: { client: RecordsClient; def: ObjectDef; record: RecordRow; version: number }) {
  const meta = useMeta();
  const groups = meta.objects.flatMap((other) => {
    const filter = linkedFilter(meta, def, record, other);
    return filter ? [{ other, filter }] : [];
  });
  return (
    <div className="rec-assocs">
      {groups.map(({ other, filter }) => (
        <Linked key={other.key} client={client} other={other} filter={filter} version={version} />
      ))}
    </div>
  );
}
