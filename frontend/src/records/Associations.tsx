import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { Avatar, Button, Skeleton } from "../ui";
import type { RecordsClient } from "./client.ts";
import { subtitle } from "./format.ts";
import { primeRefs, useMeta, useRecordRef } from "./meta.tsx";
import { recordPath } from "./paths.ts";
import { liveFields } from "./schema.ts";
import type { FieldDef, ObjectDef, RecordRow } from "./types.ts";

const SHOWN = 4;
const FETCH = 25;

function Item({ def, fields, row }: { def: ObjectDef; fields: FieldDef[]; row: RecordRow }) {
  const sub = subtitle(row.values, fields, def.primary_field);
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

/** The company a contact works at: a field that links out. */
function Forward({ client, field, id }: { client: RecordsClient; field: FieldDef; id: string }) {
  const meta = useMeta();
  const target = field.options.object!;
  const row = useRecordRef(client, target, id);
  const def = meta.objects.find((o) => o.key === target);
  if (!def) return null;
  return (
    <section className="rec-assoc" aria-label={field.label}>
      <h3 className="rec-section-title">{field.label}</h3>
      {row === undefined ? <Skeleton style={{ width: "70%" }} /> : row === null ? <p className="rec-assoc-none">Deleted record</p> : <ul className="rec-assoc-list"><Item def={def} fields={liveFields(meta.fields[target] ?? [])} row={row} /></ul>}
    </section>
  );
}

/** Contacts of a company, deals of a contact: records elsewhere that link here. */
function Reverse({ client, from, field, id }: { client: RecordsClient; from: ObjectDef; field: FieldDef; id: string }) {
  const meta = useMeta();
  const [state, setState] = useState<{ rows: RecordRow[]; total: number; status: "loading" | "ready" | "error" }>({ rows: [], total: 0, status: "loading" });
  const [all, setAll] = useState(false);
  useEffect(() => {
    let live = true;
    setState((s) => ({ ...s, status: "loading" }));
    client.query(from.key, { filter: { field: field.key, op: "is", value: id }, limit: FETCH, sort: [{ field: "updated_at", dir: "desc" }] }).then(
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
  }, [client, from.key, field.key, id]);
  const fields = useMemo(() => liveFields(meta.fields[from.key] ?? []), [meta.fields, from.key]);
  const shown = all ? state.rows : state.rows.slice(0, SHOWN);
  return (
    <section className="rec-assoc" aria-label={from.plural}>
      <h3 className="rec-section-title">
        {from.plural} {state.status === "ready" && <span className="rec-count-pill">{state.total}</span>}
      </h3>
      {state.status === "loading" && state.rows.length === 0 && <Skeleton style={{ width: "70%" }} />}
      {state.status === "error" && <p className="rec-assoc-none">Could not load {from.plural.toLowerCase()}.</p>}
      {state.status === "ready" && state.rows.length === 0 && <p className="rec-assoc-none">No {from.plural.toLowerCase()} linked yet.</p>}
      {shown.length > 0 && (
        <ul className="rec-assoc-list">
          {shown.map((r) => (
            <Item key={r.id} def={from} fields={fields} row={r} />
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

export function Associations({ client, def, record }: { client: RecordsClient; def: ObjectDef; record: RecordRow }) {
  const meta = useMeta();
  const forward = liveFields(meta.fields[def.key] ?? []).filter((f) => f.type === "record" && f.options.object);
  const reverse = meta.objects.flatMap((o) =>
    o.key === def.key ? [] : liveFields(meta.fields[o.key] ?? []).filter((f) => f.type === "record" && f.options.object === def.key).map((f) => ({ from: o, field: f })),
  );
  return (
    <div className="rec-assocs">
      {forward.map((f) => {
        const id = record.values[f.key];
        return typeof id === "string" ? (
          <Forward key={f.key} client={client} field={f} id={id} />
        ) : (
          <section key={f.key} className="rec-assoc" aria-label={f.label}>
            <h3 className="rec-section-title">{f.label}</h3>
            <p className="rec-assoc-none">No {f.label.toLowerCase()} linked yet.</p>
          </section>
        );
      })}
      {reverse.map(({ from, field }) => (
        <Reverse key={`${from.key}.${field.key}`} client={client} from={from} field={field} id={record.id} />
      ))}
    </div>
  );
}
