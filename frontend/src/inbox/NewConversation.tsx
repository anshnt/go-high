import { Search, UserRound } from "lucide-react";
import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { whatWentWrong } from "../lib/errors";
import { useRecordsClient } from "../records/client.ts";
import { formatPhone } from "../records/format.ts";
import type { RecordRow } from "../records/types.ts";
import { useDebounced } from "../records/useDebounced";
import { Dialog, Skeleton } from "../ui";
import { startConversation } from "./api";

const text = (v: unknown) => (typeof v === "string" ? v : "");

/** Start a conversation with a contact who has never written: search for them, and the thread opens ready for the first message. */
export function NewConversation({ open, onOpenChange, onOpen }: { open: boolean; onOpenChange: (o: boolean) => void; onOpen: (conversationId: string) => void }) {
  const client = useRecordsClient();
  const [q, setQ] = useState("");
  const [found, setFound] = useState<RecordRow[] | null>(null);
  const [active, setActive] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const term = useDebounced(q.trim(), 200);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) return;
    setQ("");
    setFound(null);
    setError(null);
    setActive(0);
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let live = true;
    setFound(null);
    client.query("contact", { q: term || undefined, limit: 8, sort: term ? undefined : [{ field: "updated_at", dir: "desc" }] }).then(
      (page) => live && (setFound(page.data), setActive(0)),
      (e) => live && (setFound([]), setError(whatWentWrong(e))),
    );
    return () => {
      live = false;
    };
  }, [client, term, open]);

  const pick = async (row: RecordRow | undefined) => {
    if (!row || busy) return;
    setBusy(true);
    setError(null);
    try {
      const conv = await startConversation(row.id);
      onOpenChange(false);
      onOpen(conv.id);
    } catch (e) {
      setError(whatWentWrong(e));
    } finally {
      setBusy(false);
    }
  };

  const onKey = (e: KeyboardEvent) => {
    if (!found?.length) return;
    if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => (a + (e.key === "ArrowDown" ? 1 : -1) + found.length) % found.length);
    } else if (e.key === "Enter") {
      e.preventDefault();
      void pick(found[active]);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="New conversation" description="Pick the contact to message. Their conversation opens, ready for the first message.">
      <div className="ib-new">
        <div className="ib-new-search">
          <Search size={16} aria-hidden />
          <input ref={input} autoFocus type="search" role="combobox" aria-expanded aria-controls="ib-new-list" aria-label="Search contacts" placeholder="Search contacts by name, email or phone" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={onKey} autoComplete="off" />
        </div>
        {error && (
          <p className="ui-hint" data-tone="danger" role="alert">
            {error}
          </p>
        )}
        <ul id="ib-new-list" role="listbox" aria-label="Contacts" className="ib-new-list">
          {found === null &&
            Array.from({ length: 4 }, (_, i) => (
              <li key={i} role="presentation" className="ib-new-skel">
                <Skeleton style={{ width: `${40 + i * 12}%` }} />
              </li>
            ))}
          {found?.map((r, i) => (
            <li key={r.id} role="presentation">
              <button type="button" role="option" aria-selected={i === active} data-active={i === active || undefined} className="ib-new-item" onMouseMove={() => setActive(i)} onClick={() => void pick(r)} disabled={busy}>
                <UserRound size={16} aria-hidden />
                <span className="ib-new-name">{r.display_name || "Unnamed contact"}</span>
                <span className="ib-new-sub">{[text(r.values.phone) ? formatPhone(text(r.values.phone)) : "", text(r.values.email)].filter(Boolean).join(" · ")}</span>
              </button>
            </li>
          ))}
          {found?.length === 0 && <li className="ib-new-empty">{term ? `No contact matches "${term}".` : "No contacts yet. Add one on the Contacts page."}</li>}
        </ul>
      </div>
    </Dialog>
  );
}
