import { Inbox as InboxIcon, Keyboard, ListFilter, LockKeyhole, Plug, Search, SquarePen, X } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router";
import { workspaceId } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { whatWentWrong } from "../lib/errors";
import { useMe } from "../lib/session";
import { persisted, useStore } from "../lib/store";
import { useMembers } from "../lib/tasks";
import { useMediaQuery } from "../lib/useMediaQuery";
import { useDebounced } from "../records/useDebounced";
import { TYPING } from "../shell/useShortcuts";
import { Button, EmptyState, Kbd, Sheet, useToast } from "../ui";
import "./inbox.css";
import { assign as assignApi, close as closeApi, listMessages, markRead as markReadApi, markUnread as markUnreadApi, reopen as reopenApi, snooze as snoozeApi } from "./api";
import { Composer, EMPTY_DRAFT, type ComposerHandle, type Draft } from "./Composer";
import { ContactCard } from "./ContactCard";
import { ConversationList, contactName } from "./ConversationList";
import { useChannels, useConsents, useTeams } from "./hooks";
import { actionFor, moveActive, nextAfterRemoval } from "./keys.ts";
import { defaultChannel } from "./reach.ts";
import { type StreamEvent, planRefetch } from "./stream";
import { subscribe, useStreamStatus } from "./streamClient";
import { Thread } from "./Thread";
import { ThreadHeader } from "./ThreadHeader";
import { NewConversation } from "./NewConversation";
import { whenLabel } from "./time.ts";
import type { Conversation, Message, ViewId } from "./types.ts";
import { useConversationList } from "./useConversationList";
import { useThread } from "./useThread";
import { ViewsPane } from "./ViewsPane";
import { inFilter, isView, VIEWS } from "./views.ts";

const cardPref = persisted<"auto" | "open" | "closed">("gh:inbox-card", "auto", (v) => (v === "open" || v === "closed" || v === "auto" ? v : undefined));
const FLUSH_MS = 150;
const MAX_ROW_REFETCH = 20; // more changed rows than this: read the first page instead
const DOCKED_WIDTH = 1260;

// What the key handler reads: the latest of everything, so it is attached once.
type Keys = {
  open: Conversation | null;
  openId: string | null;
  activeId: string | null;
  ids: string[];
  canWrite: boolean;
  canSend: boolean;
  phone: boolean;
  cardOpen: boolean;
  findOpen: boolean;
  go: (id: string | null, replace?: boolean) => void;
  doClose: () => void;
  toggleUnread: () => void;
};

const EMPTY_TEXT: Record<ViewId, [string, string]> = {
  open: ["You are all caught up", "No open conversations. Messages from SMS, email, WhatsApp and web chat land here the moment they arrive."],
  mine: ["Nothing is assigned to you", "Press A on a conversation to assign it to yourself."],
  unassigned: ["Every open conversation has an owner", "New conversations that nobody has picked up show here."],
  unread: ["Nothing unread", "Conversations with a message you have not read show here."],
  snoozed: ["Nothing is snoozed", "Press S on a conversation to bring it back later."],
  closed: ["No closed conversations", "Press E on a conversation when it is done. It reopens by itself if the contact writes again."],
};

/** The inbox: views, conversations, the open thread and the contact, all driven from the keyboard, live from the stream. */
export function InboxPage() {
  const { id: routeId } = useParams();
  const openId = routeId ?? null;
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const toast = useToast();
  const me = useMe()?.user.id ?? null;
  const ws = useStore(workspaceId);
  const phone = useMediaQuery("(max-width: 767px)");
  const { can, ready } = useCan();
  const members = useMembers();
  const streamStatus = useStreamStatus();

  const view: ViewId = isView(params.get("view")) ? (params.get("view") as ViewId) : "open";
  const channel = params.get("channel");
  const [qInput, setQInput] = useState("");
  const q = useDebounced(qInput, 250);

  const allowed = can("conversations.read");
  const canWrite = can("conversations.write");
  const canSend = can("messages.send");
  const canDnd = can("consents.manage");
  const canTasks = can("tasks.read");
  const canManageChannels = can("channels.manage");

  const { channels } = useChannels(ws);
  const teams = useTeams(ws, can("members.read"));
  const list = useConversationList(view, channel, q, me, ws);
  const hint = list.rows.find((r) => r.id === openId) ?? null;
  const [now, setNow] = useState(() => new Date());
  const [cardVersion, setCardVersion] = useState(0);
  const openRef = useRef<Conversation | null>(null);

  const thread = useThread(openId, hint, ws, me, (sent) => {
    list.applyChange(openRef.current, sent);
    thread.setConv(sent);
  });
  const open = list.rows.find((r) => r.id === openId) ?? thread.conv ?? null;
  openRef.current = open;
  const { consents, setSwitch: setConsent } = useConsents(open?.contact.id ?? null, cardVersion);

  // --- chrome state ---
  const [activeId, setActiveId] = useState<string | null>(openId);
  const [viewsOpen, setViewsOpen] = useState(false);
  const [newOpen, setNewOpen] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false);
  const [snoozeOpen, setSnoozeOpen] = useState(false);
  const [cardSheet, setCardSheet] = useState(false);
  const [findOpen, setFindOpen] = useState(false);
  const [findQ, setFindQ] = useState("");
  const [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const pref = useStore(cardPref);
  const root = useRef<HTMLDivElement>(null);
  const searchBox = useRef<HTMLInputElement>(null);
  const findBox = useRef<HTMLInputElement>(null);
  const composer = useRef<ComposerHandle>(null);
  const [docked, setDocked] = useState(false);
  const cardOpen = phone ? cardSheet : pref === "open" || (pref === "auto" && docked);

  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const ro = new ResizeObserver(() => setDocked(el.clientWidth >= DOCKED_WIDTH));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 30_000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => setActiveId(openId), [openId]);
  useEffect(() => {
    setFindOpen(false);
    setFindQ("");
  }, [openId]);

  // The tab title carries the unread count.
  useEffect(() => {
    document.title = `${list.counts.unread ? `(${list.counts.unread}) ` : ""}Inbox | go-high`;
  }, [list.counts.unread]);

  // --- navigation ---
  const searchString = params.toString();
  const go = useCallback((id: string | null, replace = false) => navigate({ pathname: id ? `/inbox/${id}` : "/inbox", search: searchString ? `?${searchString}` : "" }, { replace }), [navigate, searchString]);
  const setFilter = (next: { view?: ViewId; channel?: string | null }) => {
    const p = new URLSearchParams(params);
    if (next.channel) {
      p.set("channel", next.channel);
      p.delete("view");
    } else {
      p.delete("channel");
      if (next.view && next.view !== "open") p.set("view", next.view);
      else p.delete("view");
    }
    setParams(p, { replace: true });
    setViewsOpen(false);
  };

  // --- actions: the screen changes at once, the server answers behind it ---
  const rowsRef = useRef(list.rows);
  rowsRef.current = list.rows;
  const filter = useMemo(() => ({ view, channel }), [view, channel]);

  const advance = (c: Conversation, after: Conversation) => {
    // the conversation left this list: take the cursor to the row that took its place
    if (inFilter(filter, after, me) || q.trim()) return;
    const ids = rowsRef.current.map((r) => r.id);
    const next = nextAfterRemoval(ids, c.id);
    setActiveId(next);
    if (openId === c.id) go(phone ? null : next, true);
  };

  const mutate = async (c: Conversation, patch: Partial<Conversation>, call: () => Promise<Conversation>, undo?: { title: string; back: () => Promise<Conversation>; to: Partial<Conversation> }) => {
    const after = { ...c, ...patch };
    list.applyChange(c, after);
    thread.setConv(after);
    advance(c, after);
    try {
      const saved = await call();
      list.applyRow(saved);
      thread.setConv(saved);
      void list.refreshCounts();
      if (undo) {
        toast({
          title: undo.title,
          duration: 7000,
          action: {
            label: "Undo",
            onClick: () => {
              const was = { ...saved, ...undo.to };
              list.applyChange(saved, was);
              thread.setConv(was);
              void undo.back().then((r) => (list.applyRow(r), thread.setConv(r), list.refreshCounts()), (e) => toast({ title: "Could not undo", description: whatWentWrong(e), tone: "danger" }));
            },
          },
        });
      }
    } catch (e) {
      list.applyChange(after, c);
      thread.setConv(c);
      toast({ title: "Could not change the conversation", description: whatWentWrong(e), tone: "danger" });
    }
  };

  const target = open;
  const doClose = () => target && target.status === "open" && void mutate(target, { status: "closed", snooze_until: null }, () => closeApi(target.id), { title: "Conversation closed", back: () => reopenApi(target.id), to: { status: target.status, snooze_until: target.snooze_until } });
  const doReopen = () => target && void mutate(target, { status: "open", snooze_until: null }, () => reopenApi(target.id));
  const doSnooze = (until: Date) => target && void mutate(target, { status: "snoozed", snooze_until: until.toISOString() }, () => snoozeApi(target.id, until), { title: `Snoozed until ${whenLabel(until, new Date())}`, back: () => reopenApi(target.id), to: { status: "open", snooze_until: null } });
  const doAssign = (who: { user_id?: string | null; team_id?: string | null }) => {
    if (!target) return;
    const was = { user_id: target.assignee_id, team_id: target.team_id };
    const patch: Partial<Conversation> = { ...("user_id" in who ? { assignee_id: who.user_id ?? null } : {}), ...("team_id" in who ? { team_id: who.team_id ?? null } : {}) };
    const name = who.user_id ? (who.user_id === me ? "you" : (members.find((m) => m.id === who.user_id)?.name ?? "them")) : who.team_id ? (teams.find((t) => t.id === who.team_id)?.name ?? "the team") : null;
    void mutate(target, patch, () => assignApi(target.id, who), { title: name ? `Assigned to ${name}` : "Unassigned", back: () => assignApi(target.id, was), to: { assignee_id: was.user_id, team_id: was.team_id } });
  };
  const manualUnread = useRef<string | null>(null);
  const setRead = (c: Conversation, read: boolean) => {
    const after = { ...c, unread: !read };
    manualUnread.current = read ? null : `${c.id}:${c.last_seq}`;
    list.applyChange(c, after);
    thread.setConv(after);
    (read ? markReadApi(c.id) : markUnreadApi(c.id)).then(
      () => list.refreshCounts(),
      (e) => {
        list.applyChange(after, c);
        thread.setConv(c);
        toast({ title: "Could not change the read mark", description: whatWentWrong(e), tone: "danger" });
      },
    );
  };
  const toggleUnread = () => target && setRead(target, target.unread);

  // A conversation you have had open for a moment is read (not one you passed on the way down the list).
  const [visible, setVisible] = useState(() => document.visibilityState === "visible");
  useEffect(() => {
    const on = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", on);
    return () => document.removeEventListener("visibilitychange", on);
  }, []);
  useEffect(() => {
    if (!target || !target.unread || thread.status !== "ready" || !visible) return;
    if (manualUnread.current === `${target.id}:${target.last_seq}`) return;
    const t = setTimeout(() => setRead(target, true), 700);
    return () => clearTimeout(t);
  }, [target?.id, target?.unread, target?.last_seq, thread.status, visible]);

  // --- realtime ---
  const showing = useMemo(() => ({ conversationId: openId, contactId: open?.contact.id ?? null, rowsByContact: new Map(list.rows.map((r) => [r.contact.id, r.id])) }), [openId, open?.contact.id, list.rows]);
  const showingRef = useRef(showing);
  showingRef.current = showing;
  const live = useRef({ list, thread });
  live.current = { list, thread };
  useEffect(() => {
    let pending: StreamEvent[] = [];
    let timer: ReturnType<typeof setTimeout> | undefined;
    const flush = () => {
      timer = undefined;
      const batch = pending;
      pending = [];
      const { list: l, thread: t } = live.current;
      const plan = planRefetch(batch, showingRef.current);
      const openNow = showingRef.current.conversationId;
      if (plan.everything || plan.rows.length > MAX_ROW_REFETCH) {
        void l.refresh();
        if (openNow) void t.refresh();
        setCardVersion((n) => n + 1);
        return;
      }
      for (const id of plan.rows) if (id !== openNow) void l.refreshRow(id);
      if (openNow && (plan.thread || plan.rows.includes(openNow))) void t.refresh().then((c) => c && l.applyRow(c));
      if (plan.counts) void l.refreshCounts();
      if (plan.contact) setCardVersion((n) => n + 1);
    };
    const unsubscribe = subscribe((e) => {
      pending.push(e);
      timer ??= setTimeout(flush, FLUSH_MS);
    });
    return () => {
      unsubscribe();
      clearTimeout(timer);
    };
  }, [ws]);

  // --- the keyboard ---
  const latest = useRef<Keys>(null!);
  latest.current = { open, openId, activeId, ids: list.rows.map((r) => r.id), canWrite, canSend, phone, cardOpen, findOpen, go, doClose, toggleUnread };
  useEffect(() => {
    let gAt = 0;
    const onKey = (e: KeyboardEvent) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const el = e.target as HTMLElement;
      if (el.closest(TYPING) || document.querySelector('[role="dialog"]')) return;
      if (e.key === "g") return void (gAt = Date.now());
      if (gAt && Date.now() - gAt < 1000) return void (gAt = 0); // the second key of "g i": the shell takes it
      const action = actionFor(e);
      if (!action || (e.repeat && action !== "next" && action !== "prev")) return;
      if (action === "open" && el.closest("button, a")) return; // Enter on a focused button presses it
      const k = latest.current;
      e.preventDefault();
      switch (action) {
        case "next":
        case "prev": {
          // with a conversation open, j and k open the next one (the thread follows the cursor); on a phone they only move it
          const to = moveActive(k.ids, k.open?.id ?? k.activeId, action === "next" ? 1 : -1);
          setActiveId(to);
          if (to && !k.phone) k.go(to, true);
          break;
        }
        case "open": {
          const to = k.activeId ?? k.ids[0] ?? null;
          if (to && to !== k.openId) k.go(to);
          else composer.current?.focus("reply");
          break;
        }
        case "close":
          if (k.canWrite) k.doClose();
          break;
        case "snooze":
          if (k.canWrite && k.open) setSnoozeOpen(true);
          break;
        case "assign":
          if (k.canWrite && k.open) setAssignOpen(true);
          break;
        case "reply":
          if (k.open && (k.canSend || k.canWrite)) composer.current?.focus("reply");
          break;
        case "note":
          if (k.open && k.canWrite) composer.current?.focus("note");
          break;
        case "unread":
          k.toggleUnread();
          break;
        case "search":
          if (k.phone && k.openId) k.go(null);
          setTimeout(() => searchBox.current?.focus(), 0);
          break;
        case "find":
          if (k.open) {
            setFindOpen(true);
            setTimeout(() => findBox.current?.focus(), 0);
          }
          break;
        case "card":
          if (k.open) k.phone ? setCardSheet((v) => !v) : cardPref.set(k.cardOpen ? "closed" : "open");
          break;
        case "escape":
          if (k.findOpen) setFindOpen(false);
          else if (k.phone && k.openId) k.go(null);
          break;
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  // --- search inside the open conversation ---
  const findTerm = useDebounced(findQ.trim(), 250);
  const [found, setFound] = useState<Message[] | null>(null);
  useEffect(() => {
    if (!openId || !findOpen || !findTerm) return setFound(null);
    let alive = true;
    listMessages(openId, { q: findTerm, limit: 100 }).then(
      (p) => alive && setFound([...p.data].sort((a, b) => a.seq - b.seq)),
      () => alive && setFound([]),
    );
    return () => {
      alive = false;
    };
  }, [openId, findOpen, findTerm]);

  // --- what to draw ---
  const nameOf = useCallback((id: string | null) => (id ? (members.find((m) => m.id === id)?.name ?? null) : null), [members]);
  const draft = (open && drafts[open.id]) || EMPTY_DRAFT;
  const lastSubject = [...thread.messages].reverse().find((m) => m.subject)?.subject ?? null;
  const defaultSubject = lastSubject ? (/^re:/i.test(lastSubject) ? lastSubject : `Re: ${lastSubject}`) : "(no subject)";
  const showingChannel = channel ? channels?.find((c) => c.id === channel) : null;
  const viewTitle = showingChannel ? showingChannel.name : (VIEWS.find((v) => v.id === view)?.label ?? "Open");

  if (ready && !allowed) {
    return (
      <div className="sh-page">
        <EmptyState icon={LockKeyhole} title="Your role cannot see conversations" text="Ask a workspace admin for the capability to read conversations." />
      </div>
    );
  }

  const noChannels = channels !== null && channels.length === 0;
  const [emptyTitle, emptyText] = q.trim() ? ["No conversations match", `Nothing matches "${q.trim()}" in any status. Try other words, or a name, email or phone number.`] : noChannels ? ["Connect your first channel", "Add an SMS number, an email address, WhatsApp or the web chat widget, and conversations appear here."] : showingChannel ? [`No open conversations on ${showingChannel.name}`, "New messages on this channel show here."] : EMPTY_TEXT[view];
  const emptyAction = noChannels && canManageChannels ? (
    <Link to="/settings/channels" className="ui-btn" data-variant="primary" data-size="md">
      <Plug size={16} aria-hidden /> Connect a channel
    </Link>
  ) : canWrite && canSend && !q.trim() && !noChannels ? (
    <Button onClick={() => setNewOpen(true)}>
      <SquarePen size={16} aria-hidden /> New conversation
    </Button>
  ) : undefined;

  const pane = phone ? (openId ? "thread" : "list") : "all";
  const card = open && cardOpen && (
    <ContactCard
      conv={open}
      channels={channels ?? []}
      consents={consents}
      canTasks={canTasks}
      canDnd={canDnd}
      version={cardVersion}
      users={members}
      onDnd={(kind, on) => void setConsent(kind, on).catch((e) => toast({ title: "Could not change do not disturb", description: whatWentWrong(e), tone: "danger" }))}
      onClose={() => (phone ? setCardSheet(false) : cardPref.set("closed"))}
    />
  );

  return (
    <div className="ib" ref={root} data-pane={pane} data-card={cardOpen ? (docked ? "docked" : "overlay") : "closed"}>
      <h1 className="sr-only">Inbox</h1>

      {!phone && <ViewsPane view={view} channel={channel} counts={list.counts} channels={channels ?? []} onView={(v) => setFilter({ view: v })} onChannel={(id) => setFilter({ channel: id })} onCompose={() => setNewOpen(true)} canCompose={canWrite && canSend} />}

      <section className="ib-listpane" aria-label="Conversations">
        <div className="ib-list-head">
          {phone && (
            <Button variant="secondary" size="sm" className="ib-views-btn" onClick={() => setViewsOpen(true)} aria-label={`Views: ${viewTitle}`}>
              <ListFilter size={15} aria-hidden /> {viewTitle}
              {list.counts[view] > 0 && !channel ? <span className="ib-count">{list.counts[view]}</span> : null}
            </Button>
          )}
          {!phone && (
            <h2 className="ib-list-title">
              {viewTitle}
              {!channel && list.counts[view] > 0 && <span className="ib-count">{list.counts[view]}</span>}
            </h2>
          )}
          <label className="ib-search">
            <Search size={15} aria-hidden />
            <input
              ref={searchBox}
              type="search"
              aria-label="Search conversations"
              placeholder="Search"
              value={qInput}
              onChange={(e) => setQInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  e.preventDefault();
                  e.stopPropagation();
                  if (qInput) setQInput("");
                  else (e.target as HTMLElement).blur();
                } else if (e.key === "ArrowDown" || e.key === "Enter") {
                  e.preventDefault();
                  (e.target as HTMLElement).blur();
                  const first = rowsRef.current[0];
                  if (first) {
                    setActiveId(first.id);
                    if (!phone || e.key === "Enter") go(first.id, !phone);
                  }
                }
              }}
            />
            {qInput ? (
              <button type="button" className="ib-search-x" aria-label="Clear search" onClick={() => setQInput("")}>
                <X size={14} aria-hidden />
              </button>
            ) : (
              <Kbd>/</Kbd>
            )}
          </label>
          {phone && canWrite && canSend && (
            <Button variant="ghost" size="icon" aria-label="New conversation" onClick={() => setNewOpen(true)}>
              <SquarePen size={18} aria-hidden />
            </Button>
          )}
        </div>
        {streamStatus === "retrying" && (
          <p className="ib-offline" role="status">
            Live updates paused. Reconnecting...
          </p>
        )}
        <ConversationList
          rows={list.rows}
          activeId={activeId}
          openId={openId}
          nameOf={nameOf}
          now={now}
          status={list.status}
          error={list.error}
          loadingMore={list.loadingMore}
          searching={list.searching}
          onOpen={(id) => {
            setActiveId(id);
            go(id);
          }}
          onEnd={list.loadMore}
          onRetry={() => void list.refresh()}
          empty={<EmptyState icon={InboxIcon} title={emptyTitle} text={emptyText} action={emptyAction} />}
        />
      </section>

      <section className="ib-threadpane" aria-label={open ? `Conversation with ${contactName(open.contact)}` : "Conversation"}>
        {open ? (
          <>
            <ThreadHeader
              conv={open}
              me={me}
              members={members}
              teams={teams}
              canWrite={canWrite}
              onBack={phone ? () => go(null) : undefined}
              cardOpen={cardOpen}
              onCard={() => (phone ? setCardSheet((v) => !v) : cardPref.set(cardOpen ? "closed" : "open"))}
              onFind={() => {
                setFindOpen(true);
                setTimeout(() => findBox.current?.focus(), 0);
              }}
              assignOpen={assignOpen}
              onAssignOpen={setAssignOpen}
              snoozeOpen={snoozeOpen}
              onSnoozeOpen={setSnoozeOpen}
              onAssign={doAssign}
              onSnooze={doSnooze}
              onClose={doClose}
              onReopen={doReopen}
              onUnread={toggleUnread}
              now={now}
            />
            {findOpen && (
              <div className="ib-find" role="search">
                <Search size={14} aria-hidden />
                <input
                  ref={findBox}
                  type="search"
                  aria-label="Find in this conversation"
                  placeholder="Find in this conversation"
                  value={findQ}
                  onChange={(e) => setFindQ(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Escape") {
                      e.preventDefault();
                      e.stopPropagation();
                      setFindOpen(false);
                      setFindQ("");
                    }
                  }}
                />
                {findTerm && found && (
                  <span className="ib-find-count" role="status">
                    {found.length === 0 ? "No messages match" : `${found.length} message${found.length === 1 ? "" : "s"} match`}
                  </span>
                )}
                <Button size="sm" variant="ghost" onClick={() => (setFindOpen(false), setFindQ(""))}>
                  Done
                </Button>
              </div>
            )}
            <Thread
              conversationId={open.id}
              messages={findOpen && findTerm && found ? found : thread.messages}
              status={thread.status}
              error={thread.error}
              hasEarlier={!(findOpen && findTerm) && !!thread.next}
              loadingEarlier={thread.loadingEarlier}
              onEarlier={() => void thread.loadEarlier()}
              onRetryLoad={() => void thread.refresh()}
              channels={channels ?? []}
              contactName={contactName(open.contact)}
              me={me}
              nameOf={nameOf}
              q={findOpen && findTerm ? findTerm : q}
              onRetry={thread.retry}
              onSaveNote={thread.saveNote}
              empty={findOpen && findTerm && found?.length === 0 ? "No messages match" : undefined}
              now={now}
            />
            <Composer
              key={open.id}
              conv={open}
              channels={channels ?? []}
              consents={consents}
              canSend={canSend}
              canNote={canWrite}
              canDnd={canDnd}
              defaultSubject={defaultSubject}
              draft={{ ...draft, channelId: draft.channelId ?? defaultChannel(channels ?? [], open)?.id ?? null }}
              onDraft={(d) => setDrafts((all) => ({ ...all, [open.id]: d }))}
              onSend={thread.submit}
              onDndOff={(kind) => void setConsent(kind, false).catch((e) => toast({ title: "Could not change do not disturb", description: whatWentWrong(e), tone: "danger" }))}
              handle={composer}
              onEscape={() => setActiveId(open.id)}
            />
          </>
        ) : (
          <div className="ib-nothread">
            <EmptyState
              icon={InboxIcon}
              title={list.rows.length ? "Select a conversation" : "Nothing selected"}
              text="Press J and K to move through the list, Enter to open one, E to close it and S to snooze it. Press ? for every shortcut."
              action={
                <span className="ib-hints">
                  <Kbd>J</Kbd>
                  <Kbd>K</Kbd>
                  <Kbd>Enter</Kbd>
                  <Keyboard size={14} aria-hidden />
                </span>
              }
            />
          </div>
        )}
      </section>

      {!phone && card && <div className="ib-cardpane">{card}</div>}
      {phone && (
        <Sheet open={cardSheet && !!open} onOpenChange={setCardSheet} title="Contact">
          {card}
        </Sheet>
      )}
      {phone && (
        <Sheet open={viewsOpen} onOpenChange={setViewsOpen} title="Views">
          <ViewsPane view={view} channel={channel} counts={list.counts} channels={channels ?? []} onView={(v) => setFilter({ view: v })} onChannel={(id) => setFilter({ channel: id })} onCompose={() => (setViewsOpen(false), setNewOpen(true))} canCompose={canWrite && canSend} />
        </Sheet>
      )}
      <NewConversation
        open={newOpen}
        onOpenChange={setNewOpen}
        onOpen={(id) => {
          setActiveId(id);
          void list.refresh();
          go(id);
          setTimeout(() => composer.current?.focus("reply"), 250);
        }}
      />
    </div>
  );
}
