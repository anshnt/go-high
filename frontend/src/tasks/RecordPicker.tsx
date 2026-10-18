import { Link2, X } from "lucide-react";
import { useEffect, useId, useState } from "react";
import { Link } from "react-router";
import { api } from "../lib/api";
import { recordPath } from "../lib/tasks";
import { Button, Input } from "../ui";

export type Linked = { id: string; object: string; display_name: string };
type Found = { id: string; display_name: string };

// ponytail: the picker searches contacts, companies and deals; a custom object's records are linked from their own page.
const OBJECTS = ["contact", "company", "deal"];

/** The record a task is about: a chip that opens it, or a search over contacts, companies and deals. */
export function RecordPicker({ value, onChange }: { value: Linked | null; onChange: (record: Linked | null) => void }) {
  const id = useId();
  const [q, setQ] = useState("");
  const [found, setFound] = useState<Linked[]>([]);

  useEffect(() => {
    const term = q.trim();
    if (!term) return setFound([]);
    let alive = true;
    const timer = setTimeout(() => {
      Promise.all(
        OBJECTS.map((object) =>
          api
            .get<{ data: Found[] }>(`/api/v1/objects/${object}/records?q=${encodeURIComponent(term)}&limit=4`)
            .then((r) => r.data.map((rec) => ({ id: rec.id, object, display_name: rec.display_name })))
            .catch(() => [] as Linked[]),
        ),
      ).then((lists) => alive && setFound(lists.flat()));
    }, 250);
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [q]);

  if (value) {
    return (
      <div className="ui-field">
        <span className="ui-label">Linked record</span>
        <div className="tk-linked">
          <Link to={recordPath(value)} className="tk-fact tk-fact-link">
            <Link2 size={13} aria-hidden />
            {value.display_name}
          </Link>
          <span className="tk-linked-kind">{value.object}</span>
          <Button variant="ghost" size="icon" aria-label={`Unlink ${value.display_name}`} onClick={() => onChange(null)}>
            <X size={16} aria-hidden />
          </Button>
        </div>
      </div>
    );
  }
  return (
    <div className="ui-field">
      <Input id={id} label="Linked record" type="search" placeholder="Search contacts, companies and deals" value={q} onChange={(e) => setQ(e.target.value)} autoComplete="off" />
      {found.length > 0 && (
        <ul className="tk-found" aria-label="Matching records">
          {found.map((r) => (
            <li key={r.id}>
              <button
                type="button"
                onClick={() => {
                  onChange(r);
                  setQ("");
                }}
              >
                <span>{r.display_name}</span>
                <span className="tk-linked-kind">{r.object}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
