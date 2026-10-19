import { LoaderCircle, TriangleAlert } from "lucide-react";
import { memo, useEffect, useRef, type ReactNode } from "react";
import { Avatar, Button, EmptyState, Skeleton } from "../ui";
import { ChannelIcon } from "./ChannelIcon";
import { listTime } from "./time.ts";
import type { Conversation } from "./types.ts";
import { useVirtual } from "./useVirtual";

export const ROW_HEIGHT = 72;
const END_MARGIN = 12;

export const contactName = (c: Conversation["contact"]) => c.display_name || c.phone || c.email || "Unknown contact";

const Row = memo(function Row({ conv, active, open, assignee, now, searching, index, size, onOpen }: { conv: Conversation; active: boolean; open: boolean; assignee: string | null; now: Date; searching: boolean; index: number; size: number; onOpen: (id: string) => void }) {
  const name = contactName(conv.contact);
  const who = conv.last_direction === "out" ? "You: " : "";
  return (
    <li style={{ height: ROW_HEIGHT }} aria-posinset={index + 1} aria-setsize={size}>
      <button
        type="button"
        className="ib-row"
        data-active={active || undefined}
        data-open={open || undefined}
        data-unread={conv.unread || undefined}
        aria-current={open ? "true" : undefined}
        data-conversation-id={conv.id}
        onClick={() => onOpen(conv.id)}
      >
        <span className="ib-avatar">
          <Avatar name={name} />
          <span className="ib-avatar-ch">
            <ChannelIcon kind={conv.channel_kind} size={11} />
          </span>
        </span>
        <span className="ib-row-main">
          <span className="ib-row-top">
            <span className="ib-row-name">
              {conv.unread && <span className="ib-dot" aria-label="Unread" role="img" />}
              {name}
            </span>
            <time className="ib-row-time" dateTime={conv.last_message_at}>
              {listTime(conv.last_message_at, now)}
            </time>
          </span>
          <span className="ib-row-bottom">
            <span className="ib-row-preview">
              {who}
              {conv.preview || "No messages yet"}
            </span>
            {searching && conv.status !== "open" && <span className="ib-row-status">{conv.status === "closed" ? "Closed" : "Snoozed"}</span>}
            {assignee && (
              <span className="ib-row-who" title={`Assigned to ${assignee}`}>
                <Avatar name={assignee} size="sm" />
              </span>
            )}
          </span>
        </span>
      </button>
    </li>
  );
});

type Props = {
  rows: Conversation[];
  activeId: string | null;
  openId: string | null;
  nameOf: (userId: string | null) => string | null;
  now: Date;
  status: "loading" | "ready" | "error";
  error?: string;
  loadingMore: boolean;
  searching: boolean;
  onOpen: (id: string) => void;
  onEnd: () => void;
  onRetry: () => void;
  empty: ReactNode;
};

/** The conversations, a screenful of rows at a time (every row is one height), paging in more as the end comes near. */
export function ConversationList({ rows, activeId, openId, nameOf, now, status, error, loadingMore, searching, onOpen, onEnd, onRetry, empty }: Props) {
  const scroller = useRef<HTMLDivElement>(null);
  const { start, end, reveal } = useVirtual(scroller, rows.length, ROW_HEIGHT);

  const activeIndex = activeId ? rows.findIndex((r) => r.id === activeId) : -1;
  useEffect(() => reveal(activeIndex), [activeIndex, reveal]);
  useEffect(() => {
    if (status === "ready" && rows.length > 0 && end >= rows.length - END_MARGIN) onEnd();
  }, [status, rows.length, end, onEnd]);

  if (status === "error" && rows.length === 0) {
    return <EmptyState icon={TriangleAlert} title="Could not load conversations" text={error ?? "Try again."} action={<Button onClick={onRetry}>Try again</Button>} />;
  }
  if (status === "loading") {
    return (
      <div className="ib-skeleton" aria-busy aria-label="Loading conversations">
        {Array.from({ length: 9 }, (_, i) => (
          <div key={i} className="ib-skel-row">
            <Skeleton style={{ width: 36, height: 36, borderRadius: 999 }} />
            <div>
              <Skeleton style={{ width: `${40 + ((i * 17) % 35)}%`, height: 12 }} />
              <Skeleton style={{ width: `${60 + ((i * 11) % 30)}%`, height: 11, marginTop: 8 }} />
            </div>
          </div>
        ))}
      </div>
    );
  }
  if (rows.length === 0) return <div className="ib-list-empty">{empty}</div>;

  return (
    <div className="ib-list-scroll" ref={scroller} tabIndex={-1}>
      <ul className="ib-list" role="list" aria-label="Conversations" style={{ paddingTop: start * ROW_HEIGHT, paddingBottom: (rows.length - end) * ROW_HEIGHT }}>
        {rows.slice(start, end).map((c, i) => (
          <Row key={c.id} conv={c} active={c.id === activeId} open={c.id === openId} assignee={nameOf(c.assignee_id)} now={now} searching={searching} index={start + i} size={rows.length} onOpen={onOpen} />
        ))}
      </ul>
      {loadingMore && (
        <div className="ib-more" role="status">
          <LoaderCircle className="ui-spin" size={14} aria-hidden /> Loading more
        </div>
      )}
    </div>
  );
}
