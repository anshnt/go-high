// The event types an endpoint subscribes to: every event, or a searchable list grouped by what the events are about,
// with a box per group. The list is the server's catalog (GET /api/v1/webhooks/event-types).
import { ChevronDown, Search } from "lucide-react";
import { useId, useMemo, useState } from "react";
import { Checkbox, Switch } from "../ui";
import type { EventType } from "./api";
import { families, familyLabel } from "./logic.ts";

export function EventPicker({ types, value, onChange, error, disabled }: { types: EventType[]; value: string[]; onChange: (v: string[]) => void; error?: string; disabled?: boolean }) {
  const [query, setQuery] = useState("");
  const errId = useId();
  const every = value.includes("*");
  const chosen = new Set(value);
  const groups = useMemo(() => families(types.map((t) => t.type)), [types]);
  const about = useMemo(() => new Map(types.map((t) => [t.type, t.description])), [types]);
  const q = query.trim();
  const shown = groups
    .map((g) => ({ ...g, types: q ? g.types.filter((t) => `${t} ${about.get(t) ?? ""}`.toLowerCase().includes(q.toLowerCase())) : g.types }))
    .filter((g) => g.types.length > 0);

  return (
    <fieldset className="adm-picker" aria-describedby={error ? errId : undefined} disabled={disabled}>
      <legend className="ui-label">Events to send</legend>
      <Switch label="Every event, including types added later" checked={every} onCheckedChange={(on) => onChange(on ? ["*"] : [])} disabled={disabled} />
      {!every && (
        <>
          <div className="adm-picker-search">
            <Search size={14} aria-hidden />
            <input type="search" aria-label="Search event types" placeholder="Search event types" value={query} onChange={(e) => setQuery(e.target.value)} />
            <span className="adm-muted" aria-live="polite">
              {value.length} selected
            </span>
          </div>
          <div className="adm-picker-list">
            {shown.length === 0 && <p className="adm-muted">No event type matches "{query}".</p>}
            {shown.map((g) => {
              const on = g.types.filter((t) => chosen.has(t)).length;
              return (
                <details key={g.family} className="adm-picker-group" open={!!q || on > 0}>
                  <summary>
                    <ChevronDown size={14} aria-hidden className="adm-chevron" />
                    <span>{familyLabel(g.family)}</span>
                    <span className="adm-muted">
                      {on ? `${on} of ${g.types.length}` : g.types.length}
                    </span>
                  </summary>
                  <div className="adm-picker-items">
                    <Checkbox
                      label={`All ${familyLabel(g.family).toLowerCase()} events`}
                      checked={on === g.types.length ? true : on ? "indeterminate" : false}
                      onCheckedChange={(c) => onChange(c ? [...new Set([...value, ...g.types])] : value.filter((t) => !g.types.includes(t)))}
                      disabled={disabled}
                    />
                    {g.types.map((t) => (
                      <div key={t} className="adm-picker-item">
                        <Checkbox label={t} checked={chosen.has(t)} onCheckedChange={(c) => onChange(c ? [...value, t] : value.filter((x) => x !== t))} disabled={disabled} />
                        {about.get(t) && <p className="adm-muted">{about.get(t)}</p>}
                      </div>
                    ))}
                  </div>
                </details>
              );
            })}
          </div>
        </>
      )}
      {error && (
        <p id={errId} className="ui-hint" data-tone="danger" role="alert">
          {error}
        </p>
      )}
    </fieldset>
  );
}
