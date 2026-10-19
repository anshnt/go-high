import { Bold, ChevronDown, Italic, Link2, List, Lock, Send, StickyNote } from "lucide-react";
import { useCallback, useEffect, useImperativeHandle, useLayoutEffect, useMemo, useRef, useState, type ClipboardEvent, type KeyboardEvent, type ReactNode, type Ref } from "react";
import { MOD } from "../lib/platform";
import { Button, Kbd } from "../ui";
import { Combobox } from "../ui/Combobox";
import { estimate as fetchEstimate } from "./api";
import { ChannelIcon } from "./ChannelIcon";
import { defaultChannel, reachable } from "./reach.ts";
import { consentRefusal, type Refusal } from "./refusal.ts";
import { RefusalBanner } from "./RefusalBanner";
import { charsLeft, segmentLabel, smsSegments } from "./segments.ts";
import type { Channel, Consent, Conversation } from "./types.ts";
import type { SendInput, SendResult } from "./useThread";
import { useDebounced } from "../records/useDebounced";
import { CHANNEL_LABEL } from "./views.ts";

// ponytail: not here yet, each its own module-12 item: snippets with variables (a `/` menu over the reply box), scheduled send
// (the quiet hours banner then offers "Schedule for <time>", see refusal.ts), pasted images and attachments (the API takes
// URLs, so they wait for the media library), "someone is replying" (the collision guard).
export type Draft = { mode: "reply" | "note"; channelId: string | null; text: string; subject: string; html: string };
export const EMPTY_DRAFT: Draft = { mode: "reply", channelId: null, text: "", subject: "", html: "" };
export type ComposerHandle = { focus: (mode?: "reply" | "note") => void };

type Props = {
  conv: Conversation;
  channels: Channel[];
  consents: Consent[] | null;
  canSend: boolean;
  canNote: boolean;
  canDnd: boolean;
  defaultSubject: string;
  draft: Draft;
  onDraft: (d: Draft) => void;
  onSend: (input: SendInput) => Promise<SendResult>;
  onDndOff: (kind: Channel["kind"]) => void;
  handle?: Ref<ComposerHandle>;
  /** Phones: Esc has nowhere to go back to, so the composer does not take it. */
  onEscape: () => void;
};

const tidyHtml = (html: string) => html.replace(/<div><br><\/div>/g, "<br>").replace(/ /g, " ");

/** A field that takes simple formatting (bold, italic, link, list) and pastes as plain text. Uncontrolled: `initial` is read once. */
function RichInput({ initial, onChange, onKey, innerRef, placeholder, label, head }: { initial: string; onChange: (html: string, text: string) => void; onKey: (e: KeyboardEvent) => void; innerRef: Ref<HTMLDivElement>; placeholder: string; label: string; head?: ReactNode }) {
  const el = useRef<HTMLDivElement | null>(null);
  useLayoutEffect(() => {
    if (el.current) el.current.innerHTML = initial;
  }, []); // the field is uncontrolled: what was typed is the field
  const set = useCallback((node: HTMLDivElement | null) => {
    el.current = node;
    if (typeof innerRef === "function") innerRef(node);
    else if (innerRef) (innerRef as { current: HTMLDivElement | null }).current = node;
  }, [innerRef]);
  const run = (cmd: string, value?: string) => {
    el.current?.focus();
    document.execCommand(cmd, false, value);
    changed();
  };
  const changed = () => el.current && onChange(tidyHtml(el.current.innerHTML), el.current.innerText);
  const link = () => {
    const url = window.prompt("Link address (https://...)");
    if (url && /^(https?:|mailto:)/i.test(url.trim())) run("createLink", url.trim());
  };
  const paste = (e: ClipboardEvent) => {
    e.preventDefault();
    document.execCommand("insertText", false, e.clipboardData.getData("text/plain"));
  };
  return (
    <div className="ib-rich">
      {head}
      <div className="ib-rich-bar" role="toolbar" aria-label="Formatting">
        <button type="button" aria-label="Bold" onMouseDown={(e) => e.preventDefault()} onClick={() => run("bold")}>
          <Bold size={14} aria-hidden />
        </button>
        <button type="button" aria-label="Italic" onMouseDown={(e) => e.preventDefault()} onClick={() => run("italic")}>
          <Italic size={14} aria-hidden />
        </button>
        <button type="button" aria-label="Link" onMouseDown={(e) => e.preventDefault()} onClick={link}>
          <Link2 size={14} aria-hidden />
        </button>
        <button type="button" aria-label="Bulleted list" onMouseDown={(e) => e.preventDefault()} onClick={() => run("insertUnorderedList")}>
          <List size={14} aria-hidden />
        </button>
      </div>
      <div ref={set} className="ib-input ib-rich-input" contentEditable role="textbox" aria-multiline aria-label={label} data-placeholder={placeholder} suppressContentEditableWarning onInput={changed} onKeyDown={onKey} onPaste={paste} />
    </div>
  );
}

export function Composer({ conv, channels, consents, canSend, canNote, canDnd, defaultSubject, draft, onDraft, onSend, onDndOff, handle, onEscape }: Props) {
  const text = useRef<HTMLTextAreaElement>(null);
  const rich = useRef<HTMLDivElement>(null);
  const [refusal, setRefusal] = useState<Refusal | null>(null);
  const options = useMemo(() => reachable(channels, conv), [channels, conv]);
  const mode = draft.mode === "reply" && !canSend && canNote ? "note" : draft.mode;
  const channel = (draft.channelId && options.find((c) => c.id === draft.channelId)) || defaultChannel(channels, conv);
  const email = mode === "reply" && channel?.kind === "email";
  const sms = mode === "reply" && channel?.kind === "sms";
  const set = (patch: Partial<Draft>) => onDraft({ ...draft, ...patch });

  useImperativeHandle(handle, () => ({
    focus: (m) => {
      if (m && m !== draft.mode) onDraft({ ...draft, mode: m });
      // after the mode (and so the field) has rendered
      setTimeout(() => (email && (m ?? draft.mode) === "reply" ? rich.current : text.current)?.focus(), 0);
    },
  }));

  // The refusal belongs to the message that was refused: another channel or another conversation starts clean.
  useEffect(() => setRefusal(null), [conv.id, channel?.id, mode]);

  const known = useMemo(() => {
    const c = channel && consents?.find((x) => x.kind === channel.kind);
    return mode === "reply" && c ? consentRefusal(c) : null;
  }, [channel, consents, mode]);
  const shown = refusal ?? known;
  const blocked = mode === "reply" && (!channel || !!known?.blocking);

  // The estimate under an SMS: the count is instant (same rules as the server), the price comes from the channel's own call.
  const local = useMemo(() => smsSegments(draft.text), [draft.text]);
  const typed = useDebounced(draft.text, 350);
  const [perSegment, setPerSegment] = useState<{ channel: string; price: number } | null>(null);
  useEffect(() => {
    if (!sms || !channel || !typed.trim()) return;
    let live = true;
    fetchEstimate(channel.id, typed).then(
      (e) => live && setPerSegment({ channel: channel.id, price: e.segments > 0 ? Number(e.estimated_cost) / e.segments : 0 }),
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, [sms, channel, typed]);
  const price = perSegment && channel && perSegment.channel === channel.id ? perSegment.price : 0;

  const empty = !draft.text.trim();
  const send = async () => {
    if (empty || blocked) return;
    const sent = { ...draft };
    const input: SendInput =
      mode === "note"
        ? { body: sent.text.trim(), kind: "note", channelId: null }
        : { body: sent.text.trim(), kind: "message", channelId: channel?.id ?? null, channelKind: channel?.kind, ...(email ? { subject: sent.subject.trim() || null, html: sent.html || null } : {}) };
    onDraft({ ...draft, text: "", html: "", subject: email ? "" : draft.subject });
    if (rich.current) rich.current.innerHTML = "";
    setRefusal(null);
    const result = await onSend(input);
    if (!result.ok && "refusal" in result) {
      onDraft(sent); // nothing left: the words come back
      if (rich.current) rich.current.innerHTML = sent.html;
      setRefusal(result.refusal);
    }
  };

  const onKey = (e: KeyboardEvent) => {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      void send();
    } else if (e.key === "Escape") {
      e.preventDefault();
      e.stopPropagation();
      (document.activeElement as HTMLElement | null)?.blur();
      onEscape();
    }
  };

  // Grow with the text, up to a limit; then scroll.
  useLayoutEffect(() => {
    const t = text.current;
    if (!t) return;
    t.style.height = "auto";
    t.style.height = `${Math.min(t.scrollHeight + 2, 220)}px`;
  }, [draft.text, mode, email]);

  if (!canSend && !canNote) {
    return (
      <div className="ib-composer" data-readonly>
        <p className="ib-composer-note">
          <Lock size={14} aria-hidden /> Your role can read conversations but not reply to them.
        </p>
      </div>
    );
  }

  const placeholder = mode === "note" ? "Write a note for your team. The contact never sees it." : channel ? `Message ${conv.contact.display_name ?? "the contact"} by ${CHANNEL_LABEL[channel.kind]}` : "No channel can reach this contact";
  const to = channel?.kind === "email" ? conv.contact.email : channel?.kind === "webchat" ? "web chat visitor" : conv.contact.phone;

  return (
    <div className="ib-composer" data-mode={mode} data-kind={mode === "note" ? "note" : channel?.kind}>
      {shown && (
        <RefusalBanner
          refusal={shown}
          onDismiss={refusal ? () => setRefusal(null) : undefined}
          action={
            shown.code === "dnd" && canDnd && channel ? (
              <button type="button" className="ib-refusal-action" onClick={() => onDndOff(channel.kind)}>
                Turn off do not disturb for {CHANNEL_LABEL[channel.kind]}
              </button>
            ) : undefined
          }
        />
      )}
      <div className="ib-composer-bar">
        <div className="ib-seg" role="group" aria-label="Reply or internal note">
          <button type="button" aria-pressed={mode === "reply"} disabled={!canSend} onClick={() => set({ mode: "reply" })}>
            Reply
            <Kbd>R</Kbd>
          </button>
          <button type="button" aria-pressed={mode === "note"} disabled={!canNote} onClick={() => set({ mode: "note" })}>
            <StickyNote size={13} aria-hidden /> Note
            <Kbd>N</Kbd>
          </button>
        </div>
        {mode === "reply" && (
          <div className="ib-channel-pick">
            {options.length > 1 ? (
              <Combobox
                label="Send on"
                items={options.map((c) => ({ value: c.id, label: c.name, hint: CHANNEL_LABEL[c.kind], icon: <ChannelIcon kind={c.kind} size={14} /> }))}
                value={channel?.id ?? null}
                onChange={(id) => set({ channelId: id })}
                searchPlaceholder="Search channels"
                trigger={
                  <button type="button" className="ib-pick" aria-label={`Send on: ${channel?.name ?? "choose a channel"}`}>
                    <ChannelIcon kind={channel?.kind} size={14} />
                    <span>{channel?.name ?? "Choose channel"}</span>
                    <ChevronDown size={14} aria-hidden />
                  </button>
                }
              />
            ) : channel ? (
              <span className="ib-pick" data-static>
                <ChannelIcon kind={channel.kind} size={14} />
                <span>{channel.name}</span>
              </span>
            ) : (
              <span className="ib-pick" data-static>
                No way to reach this contact
              </span>
            )}
            {to && <span className="ib-to">to {to}</span>}
          </div>
        )}
        {mode === "note" && <span className="ib-to">Only your team sees notes</span>}
      </div>
      {email ? (
        <RichInput
          key={conv.id}
          initial={draft.html}
          innerRef={rich}
          placeholder={placeholder}
          label="Message"
          onChange={(html, t) => onDraft({ ...draft, html, text: t })}
          onKey={onKey}
          head={<input className="ib-subject" aria-label="Subject" placeholder={defaultSubject} value={draft.subject} onChange={(e) => set({ subject: e.target.value })} onKeyDown={onKey} />}
        />
      ) : (
        <textarea ref={text} className="ib-input" rows={2} aria-label={mode === "note" ? "Internal note" : "Message"} placeholder={placeholder} value={draft.text} onChange={(e) => set({ text: e.target.value })} onKeyDown={onKey} />
      )}
      <div className="ib-composer-foot">
        <span className="ib-estimate" aria-live="polite">
          {sms && local.segments > 0 ? (
            <>
              {segmentLabel({ ...local, estimated_cost: price ? String(price * local.segments) : null })}
              <span className="ib-left"> {"·"} {charsLeft(local)} left</span>
            </>
          ) : null}
        </span>
        <Button variant="primary" className="ib-send" disabled={empty || blocked} onClick={() => void send()} aria-keyshortcuts="Control+Enter Meta+Enter">
          <Send size={15} aria-hidden />
          {mode === "note" ? "Add note" : "Send"}
          <span className="ib-send-keys" aria-hidden>
            <Kbd>{MOD}</Kbd>
            <Kbd>{"↵"}</Kbd>
          </span>
        </Button>
      </div>
    </div>
  );
}

