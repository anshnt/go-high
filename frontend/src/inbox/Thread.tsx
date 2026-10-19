import { ArrowDown, LoaderCircle, MessageSquareDashed, TriangleAlert } from "lucide-react";
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { Button, EmptyState, Skeleton } from "../ui";
import { MessageView } from "./MessageView";
import { groupByDay } from "./time.ts";
import type { Channel, ThreadMessage } from "./types.ts";

type Props = {
  conversationId: string;
  messages: ThreadMessage[];
  status: "loading" | "ready" | "error";
  error?: string;
  hasEarlier: boolean;
  loadingEarlier: boolean;
  onEarlier: () => void;
  onRetryLoad: () => void;
  channels: Channel[];
  contactName: string;
  me: string | null;
  nameOf: (userId: string | null) => string | null;
  q: string;
  onRetry: (m: ThreadMessage) => void;
  onSaveNote: (m: ThreadMessage, body: string) => Promise<string | null>;
  /** What the empty thread says (a search with no hits, a conversation not started). */
  empty?: string;
  now: Date;
};

const NEAR = 96; // px from the bottom that still counts as "at the bottom"

/** The messages of one conversation by day, oldest at the top, kept at the bottom as new ones arrive. */
export function Thread({ conversationId, messages, status, error, hasEarlier, loadingEarlier, onEarlier, onRetryLoad, channels, contactName, me, nameOf, q, onRetry, onSaveNote, empty, now }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const inner = useRef<HTMLOListElement>(null);
  const stuck = useRef(true); // the reader is at the bottom: new messages scroll into view
  const last = useRef({ id: "", first: "", count: 0, height: 0 });
  const [unseen, setUnseen] = useState(0);
  const groups = useMemo(() => groupByDay(messages, now), [messages, now]);
  const byId = useMemo(() => new Map(channels.map((c) => [c.id, c])), [channels]);

  // Opening a conversation lands on the newest message; earlier messages arriving above keep what you were reading in place.
  useLayoutEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const prev = last.current;
    const first = messages[0]?.id ?? "";
    if (prev.id !== conversationId) {
      el.scrollTop = el.scrollHeight;
      stuck.current = true;
      setUnseen(0);
    } else if (prev.first !== first && prev.first && messages.some((m) => m.id === prev.first)) {
      el.scrollTop += el.scrollHeight - prev.height; // earlier messages were added on top
    } else if (messages.length > prev.count) {
      const mineJustSent = messages[messages.length - 1]?.local !== undefined;
      if (stuck.current || mineJustSent) el.scrollTop = el.scrollHeight;
      else setUnseen((n) => n + (messages.length - prev.count));
    }
    last.current = { id: conversationId, first, count: messages.length, height: el.scrollHeight };
  }, [conversationId, messages]);

  // An email that finishes drawing, or an image that arrives, changes the height: stay at the bottom if that is where we were.
  useEffect(() => {
    const el = scroller.current;
    const list = inner.current;
    if (!el || !list) return;
    const ro = new ResizeObserver(() => {
      if (stuck.current) el.scrollTop = el.scrollHeight;
      last.current.height = el.scrollHeight;
    });
    ro.observe(list);
    return () => ro.disconnect();
  }, [conversationId, status]);

  const onScroll = () => {
    const el = scroller.current!;
    stuck.current = el.scrollHeight - el.scrollTop - el.clientHeight < NEAR;
    if (stuck.current && unseen) setUnseen(0);
    if (el.scrollTop < 80 && hasEarlier && !loadingEarlier) onEarlier();
  };

  if (status === "error" && messages.length === 0) {
    return <EmptyState icon={TriangleAlert} title="Could not load this conversation" text={error ?? "Try again."} action={<Button onClick={onRetryLoad}>Try again</Button>} />;
  }
  if (status === "loading" && messages.length === 0) {
    return (
      <div className="ib-thread-skeleton" aria-busy aria-label="Loading messages">
        {[62, 40, 74, 33, 55].map((w, i) => (
          <Skeleton key={i} style={{ width: `${w}%`, height: 38, alignSelf: i % 2 ? "flex-end" : "flex-start", borderRadius: 14 }} />
        ))}
      </div>
    );
  }
  if (messages.length === 0) return <EmptyState icon={MessageSquareDashed} title={empty ?? "No messages yet"} text={empty ? "Try other words." : "Write the first message below. It goes out on the channel you pick."} />;

  return (
    <div className="ib-thread-wrap">
      <div className="ib-thread-scroll" ref={scroller} onScroll={onScroll} tabIndex={-1} data-conversation-id={conversationId}>
        {hasEarlier && (
          <div className="ib-earlier">
            {loadingEarlier ? (
              <span role="status">
                <LoaderCircle className="ui-spin" size={14} aria-hidden /> Loading earlier messages
              </span>
            ) : (
              <Button size="sm" variant="ghost" onClick={onEarlier}>
                Load earlier messages
              </Button>
            )}
          </div>
        )}
        <ol className="ib-messages" ref={inner} aria-label="Messages">
          {groups.map((g) => (
            <li key={g.key + g.items[0]!.id} className="ib-day-group">
              <div className="ib-day" role="separator" aria-label={g.label}>
                <span>{g.label}</span>
              </div>
              <ol>
                {g.items.map((m) => {
                  const ch = m.channel_id ? byId.get(m.channel_id) : undefined;
                  return (
                    <MessageView
                      key={m.id}
                      m={m}
                      author={nameOf(m.sent_by)}
                      mine={!!me && m.sent_by === me}
                      channelName={ch?.name ?? null}
                      channelKind={ch?.kind ?? m.local?.channelKind ?? null}
                      contactName={contactName}
                      q={q}
                      onRetry={onRetry}
                      onSaveNote={onSaveNote}
                    />
                  );
                })}
              </ol>
            </li>
          ))}
        </ol>
      </div>
      {unseen > 0 && (
        <button
          type="button"
          className="ib-unseen"
          onClick={() => {
            const el = scroller.current!;
            el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
          }}
        >
          <ArrowDown size={14} aria-hidden /> {unseen === 1 ? "New message" : `${unseen} new messages`}
        </button>
      )}
    </div>
  );
}
