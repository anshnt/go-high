import { Archive, CircleUserRound, Clock, Inbox, MailOpen, SquarePen, UserRoundX, type LucideIcon } from "lucide-react";
import { Button } from "../ui";
import { ChannelIcon } from "./ChannelIcon";
import type { Channel, Counts, ViewId } from "./types.ts";
import { VIEWS } from "./views.ts";

const ICON: Record<ViewId, LucideIcon> = { open: Inbox, mine: CircleUserRound, unassigned: UserRoundX, unread: MailOpen, snoozed: Clock, closed: Archive };

type Props = {
  view: ViewId;
  channel: string | null;
  counts: Counts;
  channels: Channel[];
  onView: (v: ViewId) => void;
  onChannel: (id: string) => void;
  onCompose: () => void;
  canCompose: boolean;
};

/** The views (Open, Mine, Unassigned, Unread, Snoozed, Closed) and one entry per channel, each with its live count. */
export function ViewsPane({ view, channel, counts, channels, onView, onChannel, onCompose, canCompose }: Props) {
  const live = channels.filter((c) => c.status !== "disabled");
  return (
    <nav className="ib-views" aria-label="Inbox views">
      {canCompose && (
        <Button variant="primary" className="ib-compose" onClick={onCompose}>
          <SquarePen size={16} aria-hidden /> New conversation
        </Button>
      )}
      <ul>
        {VIEWS.map((v) => {
          const Icon = ICON[v.id];
          const on = !channel && view === v.id;
          const n = counts[v.id];
          return (
            <li key={v.id}>
              <button type="button" className="ib-view" aria-current={on ? "page" : undefined} data-view={v.id} onClick={() => onView(v.id)}>
                <Icon size={16} aria-hidden />
                <span className="ib-view-label">{v.label}</span>
                {n > 0 && (
                  <span className="ib-count" data-strong={v.id === "unread" || undefined}>
                    <span className="sr-only">{n} </span>
                    <span aria-hidden>{n > 999 ? "999+" : n}</span>
                  </span>
                )}
              </button>
            </li>
          );
        })}
      </ul>
      {live.length > 0 && (
        <>
          <h2 className="ib-views-head">Channels</h2>
          <ul>
            {live.map((c) => {
              const n = counts.channels[c.id] ?? 0;
              return (
                <li key={c.id}>
                  <button type="button" className="ib-view" aria-current={channel === c.id ? "page" : undefined} data-channel={c.id} onClick={() => onChannel(c.id)}>
                    <ChannelIcon kind={c.kind} size={16} />
                    <span className="ib-view-label">{c.name}</span>
                    {n > 0 && (
                      <span className="ib-count">
                        <span className="sr-only">{n} open </span>
                        <span aria-hidden>{n}</span>
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        </>
      )}
    </nav>
  );
}
