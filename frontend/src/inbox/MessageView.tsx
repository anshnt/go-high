import { Check, CheckCheck, CircleAlert, Clock, FileText, Image as ImageIcon, Paperclip, Pencil, Phone, RotateCcw, StickyNote, Voicemail } from "lucide-react";
import { memo, useState, type KeyboardEvent } from "react";
import { Button } from "../ui";
import { ChannelIcon } from "./ChannelIcon";
import { EmailBody } from "./EmailBody";
import { tickOf, type Tick } from "./messages.ts";
import { MessageText } from "./MessageText";
import { clock } from "./time.ts";
import type { Attachment, ChannelKind, ThreadMessage } from "./types.ts";
import { CHANNEL_LABEL } from "./views.ts";

const TICK: Record<Exclude<Tick, "none">, { label: string; Icon: typeof Check }> = {
  sending: { label: "Sending", Icon: Clock },
  sent: { label: "Sent", Icon: Check },
  delivered: { label: "Delivered", Icon: CheckCheck },
  read: { label: "Read", Icon: CheckCheck },
  failed: { label: "Failed", Icon: CircleAlert },
};

function Ticks({ m }: { m: ThreadMessage }) {
  const t = tickOf(m);
  if (t === "none") return null;
  const { label, Icon } = TICK[t];
  return (
    <span className="ib-tick" data-tick={t} title={label}>
      <Icon size={13} aria-hidden />
      <span>{label}</span>
    </span>
  );
}

const fileName = (a: Attachment) => a.name || decodeURIComponent(a.url.split("?")[0]!.split("/").pop() || "Attachment");
const isImage = (a: Attachment) => (a.content_type ?? "").startsWith("image/") || /\.(png|jpe?g|gif|webp|avif)$/i.test(a.url.split("?")[0]!);

function Attachments({ items }: { items: Attachment[] }) {
  if (!items.length) return null;
  return (
    <ul className="ib-files" aria-label="Attachments">
      {items.map((a, i) => (
        <li key={`${a.url}-${i}`}>
          <a href={a.url} target="_blank" rel="noopener noreferrer nofollow" className="ib-file">
            {isImage(a) ? <ImageIcon size={14} aria-hidden /> : <FileText size={14} aria-hidden />}
            <span>{fileName(a)}</span>
          </a>
        </li>
      ))}
    </ul>
  );
}

type Props = {
  m: ThreadMessage;
  /** Who sent it, for a team inbox: "You", or a colleague's name. */
  author: string | null;
  mine: boolean;
  channelName: string | null;
  channelKind: ChannelKind | null;
  contactName: string;
  q: string;
  onRetry: (m: ThreadMessage) => void;
  onSaveNote: (m: ThreadMessage, body: string) => Promise<string | null>;
};

function NoteEditor({ m, onDone, onSave }: { m: ThreadMessage; onDone: () => void; onSave: Props["onSaveNote"] }) {
  const [text, setText] = useState(m.body);
  const [error, setError] = useState<string | null>(null);
  const save = async () => {
    const body = text.trim();
    if (!body) return setError("A note cannot be empty.");
    if (body === m.body) return onDone();
    const failed = await onSave(m, body);
    if (failed) setError(failed);
    else onDone();
  };
  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      onDone();
    } else if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void save();
    }
  };
  return (
    <div className="ib-note-edit">
      <textarea className="ui-input ui-textarea" aria-label="Edit note" autoFocus value={text} onChange={(e) => setText(e.target.value)} onKeyDown={onKey} />
      {error && (
        <p className="ui-hint" data-tone="danger" role="alert">
          {error}
        </p>
      )}
      <div className="ib-note-edit-btns">
        <Button size="sm" variant="primary" onClick={() => void save()}>
          Save
        </Button>
        <Button size="sm" variant="ghost" onClick={onDone}>
          Cancel
        </Button>
      </div>
    </div>
  );
}

export const MessageView = memo(function MessageView({ m, author, mine, channelName, channelKind, contactName, q, onRetry, onSaveNote }: Props) {
  const [editing, setEditing] = useState(false);
  const out = m.direction === "out";
  const time = (
    <time dateTime={m.occurred_at} className="ib-time">
      {clock(m.occurred_at)}
    </time>
  );

  if (m.kind === "system") {
    return (
      <li className="ib-msg" data-kind="system" data-seq={m.seq}>
        <p className="ib-system">
          {m.body} {time}
        </p>
      </li>
    );
  }

  if (m.kind === "note") {
    return (
      <li className="ib-msg" data-kind="note" data-seq={m.seq} data-message-id={m.id}>
        <div className="ib-note">
          <div className="ib-note-head">
            <StickyNote size={13} aria-hidden />
            <strong>Internal note</strong>
            <span className="ib-note-by">{mine ? "You" : (author ?? "A colleague")}</span>
            <span className="ib-note-private">Only your team sees this</span>
            {time}
            {mine && !editing && !m.local && (
              <button type="button" className="ib-note-edit-btn" onClick={() => setEditing(true)} aria-label="Edit note">
                <Pencil size={13} aria-hidden />
              </button>
            )}
          </div>
          {editing ? <NoteEditor m={m} onDone={() => setEditing(false)} onSave={onSaveNote} /> : <MessageText text={m.body} q={q} className="ib-text" />}
        </div>
      </li>
    );
  }

  if (m.kind === "call" || m.kind === "voicemail") {
    const Icon = m.kind === "call" ? Phone : Voicemail;
    return (
      <li className="ib-msg" data-kind="system" data-seq={m.seq}>
        <p className="ib-system">
          <Icon size={13} aria-hidden /> {m.body || (m.kind === "call" ? "Call" : "Voicemail")} {time}
        </p>
      </li>
    );
  }

  const failed = m.status === "failed" || m.local?.state === "failed";
  const email = channelKind === "email" || !!m.subject || !!m.html;
  const sender = out ? (mine ? "You" : (author ?? "Team")) : contactName;
  const meta = (
    <div className="ib-meta">
      <ChannelIcon kind={channelKind} size={12} />
      <span>{channelName ?? (channelKind ? CHANNEL_LABEL[channelKind] : "")}</span>
      <span aria-hidden>{"·"}</span>
      {time}
      {out && (
        <>
          <span aria-hidden>{"·"}</span>
          <Ticks m={m} />
        </>
      )}
    </div>
  );
  const retry = failed && (
    <div className="ib-failed" role="alert">
      <CircleAlert size={14} aria-hidden />
      <span>{m.error || "This message was not sent."}</span>
      <Button size="sm" variant="secondary" onClick={() => onRetry(m)}>
        <RotateCcw size={13} aria-hidden /> Retry
      </Button>
    </div>
  );

  if (email) {
    return (
      <li className="ib-msg" data-kind="email" data-dir={m.direction} data-seq={m.seq} data-failed={failed || undefined} data-message-id={m.id}>
        <article className="ib-email">
          <header className="ib-email-head">
            <span className="ib-email-from">{sender}</span>
            {m.subject && <h3 className="ib-email-subject">{m.subject}</h3>}
          </header>
          <EmailBody html={m.html} body={m.body} q={q} />
          <Attachments items={m.attachments} />
          {retry}
        </article>
        {meta}
      </li>
    );
  }

  return (
    <li className="ib-msg" data-kind="message" data-dir={m.direction} data-seq={m.seq} data-failed={failed || undefined} data-sending={m.local?.state === "sending" || undefined} data-message-id={m.id}>
      <div className="ib-bubble">
        {m.body ? <MessageText text={m.body} q={q} className="ib-text" /> : null}
        {m.attachments.length > 0 && (
          <span className="ib-attach-icon">
            <Paperclip size={12} aria-hidden />
          </span>
        )}
        <Attachments items={m.attachments} />
      </div>
      {retry}
      {meta}
    </li>
  );
});
