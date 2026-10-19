import { ExternalLink, ListChecks, Mail, Phone, ShieldCheck, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router";
import { dueLabel } from "../lib/dates";
import { whatWentWrong } from "../lib/errors";
import { listTasks, recordPath, type Task } from "../lib/tasks";
import { useRecordsClient } from "../records/client.ts";
import { formatPhone, valueText } from "../records/format.ts";
import { isEmptyValue } from "../records/validate.ts";
import type { FieldDef, RecordRow } from "../records/types.ts";
import { Avatar, Badge, Skeleton, Switch } from "../ui";
import { ChannelIcon } from "./ChannelIcon";
import { consentLine } from "./refusal.ts";
import type { Channel, ChannelKind, Consent, Conversation } from "./types.ts";
import { CHANNEL_LABEL } from "./views.ts";

// ponytail: the "key fields" are the first few filled-in plain fields of the contact object, in field order. A per-workspace choice
// of which fields to show (and a link to the company) comes with the record layouts of module 07.
const SHOWN = ["text", "select", "number", "date", "url", "stage"];
const MAX_FIELDS = 6;
const KINDS: ChannelKind[] = ["sms", "whatsapp", "email", "webchat"];

type Props = {
  conv: Conversation;
  channels: Channel[];
  consents: Consent[] | null;
  canTasks: boolean;
  canDnd: boolean;
  /** Bumped after a change that the card should read again (a consent, the contact). */
  version: number;
  onDnd: (kind: ChannelKind, on: boolean) => void;
  onClose: () => void;
  users: { id: string; name: string }[];
};

/** The contact beside the thread: how to reach them, the key fields of their record, what they allow us to send, and their open tasks. */
export function ContactCard({ conv, channels, consents, canTasks, canDnd, version, onDnd, onClose, users }: Props) {
  const client = useRecordsClient();
  const id = conv.contact.id;
  const [record, setRecord] = useState<{ row: RecordRow; fields: FieldDef[] } | null | "denied">(null);
  const [tasks, setTasks] = useState<Task[] | null>(null);

  useEffect(() => {
    let live = true;
    setRecord(null);
    Promise.all([client.get("contact", id), client.listFields("contact")]).then(
      ([row, fields]) => live && setRecord({ row, fields }),
      () => live && setRecord("denied"),
    );
    return () => {
      live = false;
    };
  }, [client, id, version]);

  useEffect(() => {
    if (!canTasks) return;
    let live = true;
    listTasks({ record_id: id, status: "open" }).then(
      (t) => live && setTasks(t.slice(0, 4)),
      (e) => live && (console.warn(whatWentWrong(e)), setTasks([])),
    );
    return () => {
      live = false;
    };
  }, [id, canTasks, version]);

  const name = conv.contact.display_name || conv.contact.phone || conv.contact.email || "Unknown contact";
  const loaded = record && record !== "denied" ? record : null;
  const fields = useMemo(() => {
    if (!loaded) return [];
    const skip = new Set(["name", "first_name", "last_name", "email", "phone"]);
    return loaded.fields
      .filter((f) => !f.archived && !f.is_system && !skip.has(f.key) && SHOWN.includes(f.type) && !isEmptyValue(loaded.row.values[f.key]))
      .slice(0, MAX_FIELDS);
  }, [loaded]);
  const kinds = KINDS.filter((k) => channels.some((c) => c.kind === k && c.status !== "disabled") || consents?.some((c) => c.kind === k));
  const owner = loaded?.row.owner_id ? users.find((u) => u.id === loaded.row.owner_id)?.name : null;

  return (
    <aside className="ib-card" aria-label={`About ${name}`}>
      <header className="ib-card-head">
        <Avatar name={name} />
        <div className="ib-card-titles">
          <h2>{name}</h2>
          {loaded?.row.values.job_title ? <p>{String(loaded.row.values.job_title)}</p> : null}
        </div>
        <button type="button" className="ib-card-x" aria-label="Hide contact card" onClick={onClose}>
          <X size={16} aria-hidden />
        </button>
      </header>

      <section aria-label="Contact details" className="ib-card-sec">
        {conv.contact.phone && (
          <a className="ib-card-line" href={`tel:${conv.contact.phone}`}>
            <Phone size={14} aria-hidden /> {formatPhone(conv.contact.phone)}
          </a>
        )}
        {conv.contact.email && (
          <a className="ib-card-line" href={`mailto:${conv.contact.email}`}>
            <Mail size={14} aria-hidden /> <span className="ib-ellipsis">{conv.contact.email}</span>
          </a>
        )}
        {!conv.contact.phone && !conv.contact.email && <p className="ib-card-muted">{conv.visitor ? "A web chat visitor. They have not left a phone number or email yet." : "No phone number or email on this contact."}</p>}
        <Link className="ib-card-link" to={recordPath({ object: "contact", id })}>
          <ExternalLink size={13} aria-hidden /> Open the full record
        </Link>
      </section>

      {record === null ? (
        <div className="ib-card-sec" aria-busy aria-label="Loading contact">
          <Skeleton style={{ width: "70%" }} />
          <Skeleton style={{ width: "55%" }} />
          <Skeleton style={{ width: "62%" }} />
        </div>
      ) : record === "denied" ? (
        <p className="ib-card-muted ib-card-sec">Your role cannot see this contact's record.</p>
      ) : (
        <>
          {(fields.length > 0 || owner) && (
            <dl className="ib-card-sec ib-card-fields" aria-label="Key fields">
              {fields.map((f) => (
                <div key={f.key}>
                  <dt>{f.label}</dt>
                  <dd>{valueText(f, loaded!.row.values[f.key])}</dd>
                </div>
              ))}
              {owner && (
                <div>
                  <dt>Owner</dt>
                  <dd>{owner}</dd>
                </div>
              )}
            </dl>
          )}
          {loaded!.row.tags.length > 0 && (
            <div className="ib-card-sec ib-card-tags" aria-label="Tags">
              {loaded!.row.tags.map((t) => (
                <Badge key={t.id}>{t.name}</Badge>
              ))}
            </div>
          )}
        </>
      )}

      <section className="ib-card-sec" aria-label="Consent">
        <h3>
          <ShieldCheck size={13} aria-hidden /> Consent
        </h3>
        {consents === null ? (
          <Skeleton style={{ width: "80%" }} />
        ) : kinds.length === 0 ? (
          <p className="ib-card-muted">No channels yet.</p>
        ) : (
          <ul className="ib-consents">
            {kinds.map((k) => {
              const c = consents.find((x) => x.kind === k);
              const stop = c?.status === "opted_out";
              return (
                <li key={k} data-status={c?.status ?? "none"}>
                  <span className="ib-consent-kind">
                    <ChannelIcon kind={k} size={14} /> {CHANNEL_LABEL[k]}
                  </span>
                  <span className="ib-consent-line">{consentLine(c)}</span>
                  {canDnd && !stop && k !== "webchat" && (
                    <Switch aria-label={`Do not disturb on ${CHANNEL_LABEL[k]}`} checked={c?.status === "dnd"} onCheckedChange={(on) => onDnd(k, on)} />
                  )}
                </li>
              );
            })}
          </ul>
        )}
        <p className="ib-card-muted">Switch do not disturb on to hold all messages on a channel. Only the contact can undo an opt-out.</p>
      </section>

      {canTasks && (
        <section className="ib-card-sec" aria-label="Open tasks">
          <h3>
            <ListChecks size={13} aria-hidden /> Open tasks
          </h3>
          {tasks === null ? (
            <Skeleton style={{ width: "75%" }} />
          ) : tasks.length === 0 ? (
            <p className="ib-card-muted">Nothing to do for this contact.</p>
          ) : (
            <ul className="ib-card-tasks">
              {tasks.map((t) => (
                <li key={t.id}>
                  <Link to={`/tasks?task=${t.id}`}>{t.title}</Link>
                  <span>{dueLabel(t, new Date())}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
    </aside>
  );
}
