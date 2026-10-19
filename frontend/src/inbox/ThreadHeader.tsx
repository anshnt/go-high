import { AlarmClock, ArchiveRestore, ChevronLeft, CircleCheck, Ellipsis, MailOpen, PanelRight, PanelRightClose, Search, UserPlus, Users } from "lucide-react";
import { useState } from "react";
import { Avatar, Badge, Button, DropdownMenu, Kbd, MenuItem, Tooltip } from "../ui";
import { Combobox } from "../ui/Combobox";
import { Popover } from "../ui/Popover";
import { ChannelIcon } from "./ChannelIcon";
import { contactName } from "./ConversationList";
import { formatPhone } from "../records/format.ts";
import { fromLocalInput, snoozePresets, toLocalInput, whenLabel } from "./time.ts";
import type { Conversation, Team } from "./types.ts";

type Person = { id: string; name: string };

type Props = {
  conv: Conversation;
  me: string | null;
  members: Person[];
  teams: Team[];
  canWrite: boolean;
  /** Phones: a back button to the list. */
  onBack?: () => void;
  cardOpen: boolean;
  onCard: () => void;
  onFind: () => void;
  assignOpen: boolean;
  onAssignOpen: (open: boolean) => void;
  snoozeOpen: boolean;
  onSnoozeOpen: (open: boolean) => void;
  onAssign: (who: { user_id?: string | null; team_id?: string | null }) => void;
  onSnooze: (until: Date) => void;
  onClose: () => void;
  onReopen: () => void;
  onUnread: () => void;
  now: Date;
};

const ME = "me";
const NOBODY = "nobody";
const NO_TEAM = "noteam";

function Assign({ conv, me, members, teams, open, onOpen, onAssign }: Pick<Props, "conv" | "me" | "members" | "teams" | "onAssign"> & { open: boolean; onOpen: (o: boolean) => void }) {
  const person = conv.assignee_id ? members.find((m) => m.id === conv.assignee_id) : null;
  const team = conv.team_id ? teams.find((t) => t.id === conv.team_id) : null;
  const label = conv.assignee_id ? (conv.assignee_id === me ? "You" : (person?.name ?? "Someone")) : team ? team.name : "Unassigned";
  const items = [
    ...(me && conv.assignee_id !== me ? [{ value: ME, label: "Assign to me", group: "Quick" }] : []),
    ...(conv.assignee_id ? [{ value: NOBODY, label: "Unassign", group: "Quick" }] : []),
    ...(conv.team_id ? [{ value: NO_TEAM, label: "Remove team", group: "Quick" }] : []),
    ...members.filter((m) => m.id !== me).map((m) => ({ value: `u:${m.id}`, label: m.name, group: "People", icon: <Avatar name={m.name} size="sm" /> })),
    ...teams.map((t) => ({ value: `t:${t.id}`, label: t.name, group: "Teams", icon: <Users size={14} aria-hidden /> })),
  ];
  const pick = (v: string) => {
    onOpen(false);
    if (v === ME) onAssign({ user_id: me });
    else if (v === NOBODY) onAssign({ user_id: null });
    else if (v === NO_TEAM) onAssign({ team_id: null });
    else if (v.startsWith("u:")) onAssign({ user_id: v.slice(2) });
    else if (v.startsWith("t:")) onAssign({ team_id: v.slice(2) });
  };
  return (
    <Combobox
      label="Assign conversation"
      items={items}
      value={null}
      open={open}
      onOpenChange={onOpen}
      onChange={pick}
      searchPlaceholder="Assign to a person or team"
      emptyText="Nobody matches"
      align="end"
      trigger={
        <Button size="sm" variant="secondary" className="ib-act" aria-label={`Assigned to ${label}. Change`} data-action="assign">
          {conv.assignee_id ? <Avatar name={person?.name ?? label} size="sm" /> : team ? <Users size={14} aria-hidden /> : <UserPlus size={14} aria-hidden />}
          <span className="ib-act-label">{label}</span>
          <Kbd>A</Kbd>
        </Button>
      }
    />
  );
}

function Snooze({ now, open, onOpen, onSnooze }: Pick<Props, "now" | "onSnooze"> & { open: boolean; onOpen: (o: boolean) => void }) {
  const presets = snoozePresets(now);
  const [custom, setCustom] = useState("");
  const when = fromLocalInput(custom);
  const valid = !!when && when.getTime() > now.getTime();
  const go = (at: Date) => {
    onOpen(false);
    onSnooze(at);
  };
  return (
    <Popover
      label="Snooze"
      align="end"
      open={open}
      onOpenChange={onOpen}
      className="ib-snooze"
      trigger={
        <Button size="sm" variant="secondary" className="ib-act" aria-label="Snooze" data-action="snooze">
          <AlarmClock size={14} aria-hidden />
          <span className="ib-act-label">Snooze</span>
          <Kbd>S</Kbd>
        </Button>
      }
    >
      <p className="ib-snooze-title">Snooze until</p>
      <ul>
        {presets.map((p) => (
          <li key={p.id}>
            <button type="button" className="ib-snooze-item" onClick={() => go(p.at)} data-preset={p.id}>
              <span>{p.label}</span>
              <span className="ib-snooze-when">{whenLabel(p.at, now)}</span>
            </button>
          </li>
        ))}
      </ul>
      <form
        className="ib-snooze-custom"
        onSubmit={(e) => {
          e.preventDefault();
          if (valid) go(when!);
        }}
      >
        <label htmlFor="ib-snooze-at">Pick a date and time</label>
        <div>
          <input id="ib-snooze-at" type="datetime-local" className="ui-input" min={toLocalInput(now)} value={custom} onChange={(e) => setCustom(e.target.value)} />
          <Button type="submit" size="sm" variant="primary" disabled={!valid}>
            Snooze
          </Button>
        </div>
      </form>
    </Popover>
  );
}

/** Who this is, and everything you can do to the conversation: assign, snooze, close or reopen, mark unread, find, the contact card. */
export function ThreadHeader({ conv, me, members, teams, canWrite, onBack, cardOpen, onCard, onFind, assignOpen, onAssignOpen, snoozeOpen, onSnoozeOpen, onAssign, onSnooze, onClose, onReopen, onUnread, now }: Props) {
  const name = contactName(conv.contact);
  const reach = [conv.contact.phone ? formatPhone(conv.contact.phone) : null, conv.contact.email].filter(Boolean).join(" · ");
  return (
    <header className="ib-thread-head">
      {onBack && (
        <Button variant="ghost" size="icon" className="ib-back" aria-label="Back to conversations" onClick={onBack}>
          <ChevronLeft size={20} aria-hidden />
        </Button>
      )}
      <Avatar name={name} />
      <div className="ib-thread-titles">
        <h2>{name}</h2>
        <p>
          <ChannelIcon kind={conv.channel_kind} size={13} /> <span className="ib-ellipsis">{reach || (conv.visitor ? "Web chat visitor" : "No contact details")}</span>
        </p>
      </div>
      {conv.status === "snoozed" && conv.snooze_until && (
        <span className="ib-snoozed">
          <Badge tone="warning">Snoozed until {whenLabel(new Date(conv.snooze_until), now)}</Badge>
          {canWrite && (
            <button type="button" className="ib-wake" onClick={onReopen}>
              Wake now
            </button>
          )}
        </span>
      )}
      {conv.status === "closed" && <Badge>Closed</Badge>}
      <div className="ib-actions">
        {canWrite && (
          <>
            <Assign conv={conv} me={me} members={members} teams={teams} open={assignOpen} onOpen={onAssignOpen} onAssign={onAssign} />
            {conv.status !== "closed" && <Snooze now={now} open={snoozeOpen} onOpen={onSnoozeOpen} onSnooze={onSnooze} />}
            {conv.status !== "closed" ? (
              <Button size="sm" variant="secondary" className="ib-act" onClick={onClose} aria-label="Close conversation" data-action="close">
                <CircleCheck size={14} aria-hidden />
                <span className="ib-act-label">Close</span>
                <Kbd>E</Kbd>
              </Button>
            ) : (
              <Button size="sm" variant="secondary" className="ib-act" onClick={onReopen} aria-label="Reopen conversation" data-action="reopen">
                <ArchiveRestore size={14} aria-hidden />
                <span className="ib-act-label">Reopen</span>
              </Button>
            )}
          </>
        )}
        <Tooltip content="Find in this conversation (F)">
          <Button variant="ghost" size="icon" aria-label="Find in this conversation" onClick={onFind} data-action="find">
            <Search size={16} aria-hidden />
          </Button>
        </Tooltip>
        <Tooltip content={cardOpen ? "Hide the contact card (I)" : "Show the contact card (I)"}>
          <Button variant="ghost" size="icon" aria-label={cardOpen ? "Hide contact card" : "Show contact card"} aria-pressed={cardOpen} onClick={onCard} data-action="card">
            {cardOpen ? <PanelRightClose size={16} aria-hidden /> : <PanelRight size={16} aria-hidden />}
          </Button>
        </Tooltip>
        <DropdownMenu
          label="More actions"
          trigger={
            <Button variant="ghost" size="icon" aria-label="More actions">
              <Ellipsis size={16} aria-hidden />
            </Button>
          }
        >
          <MenuItem icon={<MailOpen size={16} aria-hidden />} onSelect={onUnread}>
            {conv.unread ? "Mark as read" : "Mark as unread"}
          </MenuItem>
          <MenuItem icon={<Search size={16} aria-hidden />} onSelect={onFind}>
            Find in this conversation
          </MenuItem>
          <MenuItem icon={cardOpen ? <PanelRightClose size={16} aria-hidden /> : <PanelRight size={16} aria-hidden />} onSelect={onCard}>
            {cardOpen ? "Hide contact card" : "Show contact card"}
          </MenuItem>
        </DropdownMenu>
      </div>
    </header>
  );
}
