import { queryTerms } from "../inbox/text.ts";
import { smsSegments } from "../inbox/segments.ts";
import type { StreamEvent } from "../inbox/stream.ts";
import type { Channel, ChannelKind, Consent, Conversation, Message, MessageStatus } from "../inbox/types.ts";
import { seedDataset, USERS } from "../records/seed.ts";
import type { RecordRow } from "../records/types.ts";
import { SCENARIOS, type Scenario } from "./demoInboxData";
import { DemoMiss } from "./demoTasks";

// The inbox of the public demo (VITE_DEMO=1): about 40 fictional conversations across SMS, email, WhatsApp and web chat,
// tied to contacts of the demo CRM, answered from memory in the shapes of the real API. Sending works end to end: the
// message goes queued, sent, delivered a moment later, and the contact may answer. Notes, assign, snooze, close and reopen
// work, an opted-out contact refuses an SMS, and a new conversation arrives while you watch. Nothing leaves the browser.
// ponytail: state lives for the page load; the stream is a local event bus, not a server; search is a prefix match.

type Json = Record<string, unknown>;
type Mine = { id: string; name: string; email: string };
const WS = "demo-ws-1";
const MIN = 60_000;

type Conv = Conversation & { seqLast: number; mark: number; lastInboundSeq: number };

// ---- the event bus the stream client listens to ----
const listeners = new Set<(e: StreamEvent) => void>();
let eventId = 0;
let ambient: ReturnType<typeof setInterval> | undefined;
let arrivalTimer: ReturnType<typeof setTimeout> | undefined;
let arrived = false;

function emit(type: string, ids: NonNullable<StreamEvent["ids"]>) {
  const e: StreamEvent = { id: ++eventId, type, workspace_id: WS, ids };
  listeners.forEach((fn) => fn(e));
}

export const demoEvents = {
  /** Starts the demo's own live activity (snoozes waking, a new conversation arriving) while someone listens. */
  listen(fn: (e: StreamEvent) => void): () => void {
    const first = listeners.size === 0;
    listeners.add(fn);
    if (first) {
      ambient = setInterval(wakeDue, 10_000);
      if (!arrived) arrivalTimer = setTimeout(arrive, 14_000);
    }
    return () => {
      listeners.delete(fn);
      if (!listeners.size) {
        clearInterval(ambient);
        clearTimeout(arrivalTimer);
      }
    };
  },
};

// ---- the world ----
const KINDS: ChannelKind[] = ["sms", "email", "whatsapp", "webchat"];
const TEAMS = [
  { id: "demo-team-support", name: "Support", parent_team_id: null, member_count: 3 },
  { id: "demo-team-sales", name: "Sales", parent_team_id: null, member_count: 2 },
];
const COLLEAGUES: Record<string, string> = Object.fromEntries(USERS.map((u) => [u.name.split(" ")[0]!.toLowerCase(), u.id]));
const REPLIES: Record<ChannelKind, string[]> = {
  sms: ["Thanks, that works for me.", "Perfect, see you then!", "Got it, thank you.", "Can you send that by email as well?"],
  email: ["Thank you, that is very helpful. We will come back to you tomorrow.", "Great, thanks for the quick answer.", "Perfect. Could you also send the revised timeline?"],
  whatsapp: ["Thanks! Sounds good.", "Perfect, talk soon.", "Great, thank you so much!"],
  webchat: ["Thanks, that answers my question.", "Okay, I will book a call then.", "Great, thank you!"],
};

let me: Mine = { id: "demo-user", name: "Alex Rivera", email: "alex@acme.example" };
let contacts: RecordRow[] = [];
const channels: Channel[] = [];
const convs = new Map<string, Conv>();
const messages = new Map<string, Message[]>();
const consents = new Map<string, Consent[]>();
const quiet = new Set<string>();
const keys = new Map<string, unknown>();
let reserved: RecordRow | null = null;
let booted = false;

const iso = (t: number) => new Date(t).toISOString();
const e164 = (phone: unknown) => (typeof phone === "string" ? `+${phone.replace(/\D/g, "")}` : null);
const first = (c: RecordRow) => c.display_name.split(" ")[0]!;
const plain = (html: string) => html.replace(/<(br|\/p|\/li)\s*\/?>/gi, "\n").replace(/<[^>]+>/g, "").replace(/\n{3,}/g, "\n\n").trim();
const logo = () => `${location.origin}${import.meta.env.BASE_URL}demo-logo.svg`;

function boot() {
  if (booted) return;
  booted = true;
  const t = Date.now();
  contacts = seedDataset({ anchor: t }).records.filter((r) => r.object === "contact");
  const mk = (kind: ChannelKind, provider: Channel["provider"], name: string, address: string, config: Json, status: Channel["status"] = "active"): Channel => ({
    id: `demo-ch-${kind}`,
    kind,
    provider,
    name,
    address,
    status,
    status_detail: null,
    created_at: iso(t - 60 * 24 * 60 * MIN),
    updated_at: iso(t - 60 * 24 * 60 * MIN),
    config,
    secrets_set: provider !== "internal",
    webhook_url: provider === "twilio" || provider === "meta" ? `https://app.go-high.example/api/hooks/${provider}/demo-ch-${kind}` : null,
    ...(kind === "webchat" ? { widget_key: address, embed: `<script src="https://app.go-high.example/widget.js" data-key="${address}" async></script>` } : {}),
  });
  channels.push(
    mk("sms", "twilio", "Main line", "+14155550100", { account_sid: "ACdemoaccount", segment_cost: 0.0079, quiet_start: "21:00", quiet_end: "08:00" }),
    mk("email", "smtp", "Support email", "hello@acme.example", { host: "smtp.acme.example", port: 587, security: "starttls", username: "hello@acme.example", reply_to: "support@acme.example" }),
    mk("whatsapp", "meta", "WhatsApp", "+14155550101", { phone_number_id: "100000000000001" }),
    mk("webchat", "internal", "Website chat", "wk_demo_acme", { title: "Chat with Acme", greeting: "Hi! How can we help?", color: "#4f46e5" }),
  );

  // Contacts are taken from the demo CRM in a fixed order, a different one for each conversation.
  const used = new Set<string>();
  let at = 3;
  const pick = (ok: (c: RecordRow) => boolean) => {
    for (let n = 0; n < contacts.length; n++) {
      const c = contacts[at]!;
      at = (at + 7) % contacts.length;
      if (!used.has(c.id) && ok(c)) {
        used.add(c.id);
        return c;
      }
    }
    throw new Error("no contact fits");
  };
  const wants: Record<ChannelKind, (c: RecordRow) => boolean> = {
    sms: (c) => !!c.values.phone,
    whatsapp: (c) => !!c.values.phone,
    email: (c) => !!c.values.email,
    webchat: (c) => !!c.values.email,
  };
  SCENARIOS.forEach((s, i) => build(s, i, pick(wants[s.ch]), t));
  reserved = pick((c) => !!c.values.email);
}

function build(s: Scenario, index: number, contact: RecordRow, now: number) {
  const channel = channels.find((c) => c.kind === s.ch)!;
  const id = `demo-conv-${index + 1}`;
  const n = first(contact);
  // timestamps run backwards from the last message
  const times: number[] = [];
  let tt = now - s.ago * MIN;
  for (let k = s.msgs.length - 1; k >= 0; k--) {
    times[k] = tt;
    tt -= s.msgs[k]![1] * MIN;
  }
  const list: Message[] = [];
  const author = s.who ? (s.who === "me" ? me.id : (COLLEAGUES[s.who] ?? me.id)) : null;
  s.msgs.forEach(([dir, , raw, extra], k) => {
    const text = raw.replaceAll("{n}", n);
    const html = extra?.html?.replaceAll("__LOGO__", logo()).replaceAll("{n}", n) ?? null;
    const out = dir === "out";
    const kind = dir === "note" ? "note" : dir === "sys" ? "system" : "message";
    const by = extra?.by ? (COLLEAGUES[extra.by] ?? me.id) : out ? (author ?? me.id) : null;
    const status: MessageStatus = dir === "in" ? "received" : extra?.failed ? "failed" : out ? (k === s.msgs.length - 1 && s.ch === "email" ? "sent" : "delivered") : "sent";
    list.push({
      id: `${id}-m${k + 1}`,
      conversation_id: id,
      seq: k + 1,
      direction: dir === "in" || (dir === "sys" && k > 0 && /replied/.test(text)) ? "in" : "out",
      channel_id: kind === "note" ? null : channel.id,
      kind,
      subject: s.ch === "email" && kind === "message" ? (extra?.subject ?? null) : null,
      body: text || (html ? plain(html) : ""),
      html,
      attachments: (extra?.files ?? []).map(([name, type]) => ({ url: `https://files.acme.example/${encodeURIComponent(name)}`, name, content_type: type })),
      status,
      error: extra?.failed ?? null,
      provider_message_id: kind === "message" ? `demo-${id}-${k + 1}` : null,
      thread_ref: null,
      sent_by: by,
      occurred_at: iso(times[k]!),
      created_at: iso(times[k]!),
      segments: s.ch === "sms" && out ? smsSegments(text).segments : null,
      estimated_cost: s.ch === "sms" && out ? (smsSegments(text).segments * 0.0079).toFixed(6) : null,
    });
  });
  messages.set(id, list);
  const listed = list.filter((m) => m.kind === "message");
  const last = listed[listed.length - 1];
  const lastIn = [...listed].reverse().find((m) => m.direction === "in");
  const until = s.until ? now + s.until * MIN : null;
  const conv: Conv = {
    id,
    contact: { id: contact.id, display_name: contact.display_name, email: (contact.values.email as string) ?? null, phone: e164(contact.values.phone) },
    status: s.status ?? "open",
    assignee_id: author,
    team_id: s.team ? `demo-team-${s.team}` : null,
    snooze_until: s.status === "snoozed" && until ? iso(until) : null,
    last_message_at: last?.created_at ?? iso(now),
    last_inbound_at: lastIn?.created_at ?? null,
    channel_id: channel.id,
    channel_kind: channel.kind,
    preview: (last?.body || last?.subject || "").slice(0, 200) || null,
    last_direction: last?.direction ?? null,
    unread: false,
    last_seq: list.length,
    visitor: s.ch === "webchat",
    created_at: list[0]?.created_at ?? iso(now),
    seqLast: list.length,
    lastInboundSeq: lastIn?.seq ?? 0,
    mark: s.unread ? Math.max(0, (lastIn?.seq ?? 1) - 1) : list.length,
  };
  convs.set(id, conv);
  if (s.consent === "stop") consents.set(contact.id, [{ kind: "sms", status: "opted_out", source: "stop", reason: null, changed_at: iso(times[list.findIndex((m) => m.kind === "system")] ?? now) }]);
  else if (s.consent === "dnd") consents.set(contact.id, [{ kind: "sms", status: "dnd", source: "manual", reason: null, changed_at: iso(now - 500 * MIN) }]);
  else if (s.ch === "sms" || s.ch === "whatsapp") consents.set(contact.id, [{ kind: s.ch, status: "opted_in", source: "start", reason: null, changed_at: iso(now - (s.ago + 600) * MIN) }]);
  if (s.quiet) quiet.add(contact.id);
}

// ---- reading ----
const unreadOf = (c: Conv) => c.lastInboundSeq > c.mark;
const row = (c: Conv): Conversation => {
  const { seqLast: _s, mark: _m, lastInboundSeq: _l, ...rest } = c;
  return { ...rest, unread: unreadOf(c) };
};
const described = (c: Conv) => ({ ...row(c), last_read_seq: c.mark });

function words(c: Conv): string {
  const msgs = (messages.get(c.id) ?? []).map((m) => `${m.subject ?? ""} ${m.body}`).join(" ");
  return `${c.contact.display_name ?? ""} ${c.contact.email ?? ""} ${c.contact.phone ?? ""} ${msgs}`.toLowerCase();
}
const hits = (text: string, q: string) => {
  const terms = queryTerms(q);
  if (!terms.length) return false;
  const bag = text.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? [];
  return terms.every((t) => bag.some((w) => w.startsWith(t)));
};

const VIEWS = ["open", "mine", "unassigned", "unread", "snoozed", "closed"] as const;
function inView(view: string, c: Conv): boolean {
  switch (view) {
    case "open":
      return c.status === "open";
    case "mine":
      return c.status === "open" && c.assignee_id === me.id;
    case "unassigned":
      return c.status === "open" && !c.assignee_id;
    case "snoozed":
      return c.status === "snoozed";
    case "closed":
      return c.status === "closed";
    case "unread":
      return c.status !== "closed" && unreadOf(c);
    default:
      return false;
  }
}
function counts() {
  const all = [...convs.values()];
  const out: Record<string, unknown> = Object.fromEntries(VIEWS.map((v) => [v, all.filter((c) => inView(v, c)).length]));
  const channelsOpen: Record<string, number> = {};
  for (const c of all) if (c.status === "open" && c.channel_id) channelsOpen[c.channel_id] = (channelsOpen[c.channel_id] ?? 0) + 1;
  return { ...out, channels: channelsOpen };
}
const byActivity = (a: Conv, b: Conv) => (a.last_message_at < b.last_message_at ? 1 : a.last_message_at > b.last_message_at ? -1 : a.id < b.id ? 1 : -1);

function list(query: URLSearchParams) {
  wakeDue();
  const view = query.get("view") ?? "open";
  const channel = query.get("channel_id");
  const q = query.get("q") ?? "";
  const limit = Math.min(200, Number(query.get("limit")) || 50);
  const cursor = query.get("cursor");
  let rows = [...convs.values()].filter((c) => inView(view, c) && (!channel || c.channel_id === channel) && (!q || hits(words(c), q))).sort(byActivity);
  if (cursor) {
    const [at, id] = cursor.split("|");
    rows = rows.filter((c) => c.last_message_at < at! || (c.last_message_at === at && c.id < id!));
  }
  const page = rows.slice(0, limit);
  const next = rows.length > limit ? `${page[page.length - 1]!.last_message_at}|${page[page.length - 1]!.id}` : null;
  return { data: page.map(row), next_cursor: next, ...(cursor ? {} : { counts: counts() }) };
}

function messagePage(c: Conv, limit: number, cursor: string | null, q: string | null) {
  let all = [...(messages.get(c.id) ?? [])].sort((a, b) => b.seq - a.seq);
  if (q) all = all.filter((m) => hits(`${m.subject ?? ""} ${m.body}`, q));
  if (cursor) all = all.filter((m) => m.seq < Number(cursor));
  const page = all.slice(0, limit);
  return { data: structuredClone(page), next_cursor: all.length > limit ? String(page[page.length - 1]!.seq) : null };
}

const need = (id: string) => {
  const c = convs.get(id);
  if (!c) throw new DemoMiss(404, "Conversation not found");
  return c;
};

// ---- changing ----
function setState(c: Conv, patch: Partial<Pick<Conv, "status" | "assignee_id" | "team_id" | "snooze_until">>) {
  const changed = (Object.keys(patch) as (keyof typeof patch)[]).some((k) => c[k] !== patch[k]);
  Object.assign(c, patch);
  if (changed) emit("conversation.updated", { conversation_id: c.id, contact_id: c.contact.id });
}

function wakeDue() {
  const now = Date.now();
  for (const c of convs.values()) if (c.status === "snoozed" && c.snooze_until && Date.parse(c.snooze_until) <= now) setState(c, { status: "open", snooze_until: null });
}

function append(c: Conv, m: Omit<Message, "id" | "conversation_id" | "seq" | "created_at" | "occurred_at"> & { at?: number }): Message {
  const list = messages.get(c.id) ?? [];
  const seq = c.seqLast + 1;
  const at = iso(m.at ?? Date.now());
  const { at: _at, ...rest } = m;
  const msg: Message = { ...rest, id: `${c.id}-m${seq}`, conversation_id: c.id, seq, created_at: at, occurred_at: at };
  list.push(msg);
  messages.set(c.id, list);
  c.seqLast = seq;
  c.last_seq = seq;
  if (msg.kind === "message") {
    c.last_message_at = msg.created_at;
    c.last_direction = msg.direction;
    c.channel_id = msg.channel_id;
    c.channel_kind = channels.find((x) => x.id === msg.channel_id)?.kind ?? c.channel_kind;
    c.preview = (msg.body || msg.subject || "").slice(0, 200);
    if (msg.direction === "in") {
      c.last_inbound_at = msg.created_at;
      c.lastInboundSeq = seq;
    }
  }
  return msg;
}

function advance(c: Conv, id: string, status: MessageStatus, type: string) {
  const m = (messages.get(c.id) ?? []).find((x) => x.id === id);
  if (!m || m.status === "failed") return;
  m.status = status;
  emit(type, { message_id: m.id, conversation_id: c.id, contact_id: c.contact.id });
}

function receive(c: Conv, text: string, subject?: string) {
  const channel = channels.find((x) => x.id === c.channel_id) ?? channels[0]!;
  const m = append(c, { direction: "in", channel_id: channel.id, kind: "message", subject: channel.kind === "email" ? (subject ?? null) : null, body: text, html: null, attachments: [], status: "received", error: null, provider_message_id: `demo-in-${eventId}`, thread_ref: null, sent_by: null, segments: null, estimated_cost: null });
  const reopened = c.status !== "open";
  if (reopened) Object.assign(c, { status: "open", snooze_until: null });
  emit("message.received", { message_id: m.id, conversation_id: c.id, contact_id: c.contact.id });
  if (reopened) emit("conversation.updated", { conversation_id: c.id, contact_id: c.contact.id });
}

/** A conversation from a contact who had none, arriving while the inbox is open. */
function arrive() {
  if (arrived || !reserved) return;
  arrived = true;
  const channel = channels.find((c) => c.kind === "webchat")!;
  const id = `demo-conv-${convs.size + 1}`;
  const t = Date.now();
  const conv: Conv = { id, contact: { id: reserved.id, display_name: reserved.display_name, email: (reserved.values.email as string) ?? null, phone: null }, status: "open", assignee_id: null, team_id: null, snooze_until: null, last_message_at: iso(t), last_inbound_at: null, channel_id: channel.id, channel_kind: "webchat", preview: null, last_direction: null, unread: true, last_seq: 0, visitor: true, created_at: iso(t), seqLast: 0, mark: 0, lastInboundSeq: 0 };
  convs.set(id, conv);
  messages.set(id, []);
  emit("conversation.created", { conversation_id: id, contact_id: reserved.id });
  receive(conv, "Hi! Do you have any availability for a website call this week? I run a small studio and need a quote.");
}

function refusal(c: Conv, channel: Channel): never | void {
  const kind = channel.kind;
  const reach = kind === "email" ? c.contact.email : kind === "webchat" ? (c.visitor ? "visitor" : null) : c.contact.phone;
  if (!reach) throw new DemoMiss(422, `The contact has no way to be reached on ${channel.name}`, "no_address");
  const consent = (consents.get(c.contact.id) ?? []).find((x) => x.kind === kind);
  if (consent?.status === "opted_out") {
    const when = new Date(consent.changed_at);
    const month = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][when.getMonth()];
    throw new DemoMiss(422, `Opted out by STOP on ${month} ${when.getDate()}`, "opted_out");
  }
  if (consent?.status === "dnd") throw new DemoMiss(422, `Do not disturb is on for ${kind}`, "dnd");
  const replying = !!c.last_inbound_at && Date.now() - Date.parse(c.last_inbound_at) < 24 * 60 * MIN;
  if ((kind === "sms" || kind === "whatsapp") && quiet.has(c.contact.id) && !replying) {
    const until = nextMorning("Australia/Sydney");
    throw new DemoMiss(422, "Quiet hours for this contact (Australia/Sydney): sending resumes at 08:00", "quiet_hours", { retry_at: until.toISOString() });
  }
  const cap = (messages.get(c.id) ?? []).filter((m) => m.kind === "message" && m.direction === "out" && m.channel_id === channel.id && m.status !== "failed" && Date.now() - Date.parse(m.created_at) < 24 * 60 * MIN).length;
  if ((kind === "sms" || kind === "whatsapp") && cap >= 10) throw new DemoMiss(422, "Frequency cap reached: 10 messages in 24 hours", "frequency_cap");
}

/** The next 08:00 in a time zone (the end of quiet hours). */
function nextMorning(zone: string): Date {
  const fmt = new Intl.DateTimeFormat("en-GB", { timeZone: zone, hour: "2-digit", minute: "2-digit", hour12: false });
  let t = Math.ceil(Date.now() / (30 * MIN)) * 30 * MIN;
  for (let i = 0; i < 100; i++, t += 30 * MIN) if (fmt.format(new Date(t)) === "08:00") return new Date(t);
  return new Date(Date.now() + 12 * 60 * MIN);
}

function send(c: Conv, body: Json): unknown {
  const kind = body.kind === "note" ? "note" : "message";
  const text = typeof body.body === "string" ? body.body : "";
  if (!text.trim()) throw new DemoMiss(422, "The message is empty", "validation_failed", { body: "is required" });
  if (kind === "note") {
    const m = append(c, { direction: "out", channel_id: null, kind: "note", subject: null, body: text, html: null, attachments: [], status: "sent", error: null, provider_message_id: null, thread_ref: null, sent_by: me.id, segments: null, estimated_cost: null });
    c.mark = Math.max(c.mark, m.seq);
    emit("message.note_added", { message_id: m.id, conversation_id: c.id, contact_id: c.contact.id });
    return { ...structuredClone(m), estimate: null };
  }
  const channel = channels.find((x) => x.id === ((body.channel_id as string | null) ?? c.channel_id));
  if (!channel) throw new DemoMiss(422, "Choose a channel to send on", "no_channel");
  if (channel.status === "disabled") throw new DemoMiss(422, `The channel ${channel.name} is disabled`, "channel_disabled");
  refusal(c, channel);
  const sms = channel.kind === "sms";
  const est = sms ? smsSegments(text) : null;
  const cost = est ? (est.segments * Number((channel.config?.segment_cost as number) ?? 0)).toFixed(6) : null;
  const webchat = channel.kind === "webchat";
  const reopened = c.status !== "open";
  const subject = channel.kind === "email" ? ((body.subject as string | null) || replySubject(c)) : null;
  const m = append(c, { direction: "out", channel_id: channel.id, kind: "message", subject, body: text, html: channel.kind === "email" ? ((body.html as string | null) ?? null) : null, attachments: [], status: webchat ? "sent" : "queued", error: null, provider_message_id: null, thread_ref: null, sent_by: me.id, segments: est?.segments ?? null, estimated_cost: cost });
  c.mark = Math.max(c.mark, m.seq);
  if (reopened) Object.assign(c, { status: "open", snooze_until: null });
  emit(webchat ? "message.sent" : "message.queued", { message_id: m.id, conversation_id: c.id, contact_id: c.contact.id });
  if (reopened) emit("conversation.updated", { conversation_id: c.id, contact_id: c.contact.id });
  if (!webchat) {
    setTimeout(() => advance(c, m.id, "sent", "message.sent"), 900);
    setTimeout(() => advance(c, m.id, "delivered", "message.status_changed"), 2300);
    if (channel.kind === "whatsapp") setTimeout(() => advance(c, m.id, "read", "message.status_changed"), 5200);
  } else {
    setTimeout(() => advance(c, m.id, "read", "message.status_changed"), 4000);
  }
  // the contact answers a few seconds later
  const pool = REPLIES[channel.kind];
  setTimeout(() => receive(c, pool[m.seq % pool.length]!, subject ?? undefined), 6500);
  return { ...structuredClone(m), estimate: est ? { ...est, estimated_cost: cost } : null };
}

function replySubject(c: Conv): string {
  const last = [...(messages.get(c.id) ?? [])].reverse().find((m) => m.subject);
  return last?.subject ? (/^re:/i.test(last.subject) ? last.subject : `Re: ${last.subject}`) : "(no subject)";
}

const CAPABILITIES = ["contacts.read", "contacts.write", "contacts.delete", "contacts.export", "companies.read", "companies.write", "companies.delete", "companies.export", "deals.read", "deals.write", "deals.delete", "deals.export", "records.read", "records.write", "records.delete", "records.export", "schema.read", "objects.manage", "fields.manage", "tags.write", "tags.manage", "views.write", "views.manage", "pipelines.manage", "tasks.read", "tasks.write", "tasks.delete", "forms.read", "forms.write", "forms.publish", "forms.delete", "responses.read", "responses.export", "calendars.read", "calendars.write", "calendars.manage", "workflows.publish", "messages.send", "conversations.read", "conversations.write", "consents.manage", "channels.manage", "billing.manage", "webhooks.manage", "members.read", "members.manage", "roles.manage", "audit.read"];
const FULL = { scope: "all", rule_scope: "all", hidden_fields: [], readonly_fields: [], can: { read: true, write: true, delete: true, export: true } };

function channelFrom(body: Json): Channel {
  const kind = body.kind as ChannelKind;
  if (!KINDS.includes(kind)) throw new DemoMiss(422, "The channel is not valid", "validation_failed", { kind: "is not a channel kind" });
  const name = typeof body.name === "string" ? body.name.trim() : "";
  if (!name) throw new DemoMiss(422, "The channel is not valid", "validation_failed", { name: "is required" });
  const provider = body.provider as Channel["provider"];
  const webchat = kind === "webchat";
  const id = `demo-ch-${kind}-${channels.length + 1}`;
  const address = webchat ? `wk_demo_${channels.length + 1}` : String(body.address ?? "");
  if (!webchat && !address) throw new DemoMiss(422, "The channel is not valid", "validation_failed", { address: "is required" });
  const secrets = Object.entries((body.secrets as Json) ?? {}).filter(([, v]) => v);
  const now = iso(Date.now());
  return {
    id, kind, provider, name, address, status: webchat ? "active" : "pending", status_detail: null, created_at: now, updated_at: now,
    config: (body.config as Json) ?? {}, secrets_set: secrets.length > 0,
    webhook_url: ["twilio", "telnyx", "mailgun", "meta"].includes(provider) ? `https://app.go-high.example/api/hooks/${provider}/${id}` : null,
    ...(webchat ? { widget_key: address, embed: `<script src="https://app.go-high.example/widget.js" data-key="${address}" async></script>` } : {}),
  };
}

/** The answer for an inbox, channels, consents, teams or capabilities call; undefined when the path is none of those. */
export function demoInbox(method: string, path: string, body: unknown, headers: Record<string, string> | undefined, who: Mine): unknown {
  const [url = "", search = ""] = path.split("?");
  const query = new URLSearchParams(search);
  const input = (body ?? {}) as Json;
  if (!/^\/api\/v1\/(conversations|channels|contacts\/[^/]+\/consents|teams|me\/capabilities)/.test(url)) return undefined;
  me = who;
  boot();
  const route = `${method} ${url}`;

  if (route === "GET /api/v1/me/capabilities") return { role: { id: "demo-role", key: "owner", name: "Owner", source: "organization" }, capabilities: CAPABILITIES, teams: [], objects: { contact: FULL, company: FULL, deal: FULL } };
  if (route === "GET /api/v1/teams") return { data: structuredClone(TEAMS), next_cursor: null };

  // channels
  if (route === "GET /api/v1/channels") return { data: structuredClone(channels), next_cursor: null };
  if (route === "POST /api/v1/channels") {
    const key = headers?.["Idempotency-Key"];
    if (key && keys.has(key)) return structuredClone(keys.get(key));
    const ch = channelFrom(input);
    channels.push(ch);
    if (key) keys.set(key, ch);
    return structuredClone(ch);
  }
  const ch = /^\/api\/v1\/channels\/([^/]+)(?:\/(test|estimate))?$/.exec(url);
  if (ch) {
    const channel = channels.find((c) => c.id === ch[1]);
    if (!channel) throw new DemoMiss(404, "Channel not found");
    if (method === "GET" && !ch[2]) return structuredClone(channel);
    if (method === "PATCH") {
      if (typeof input.name === "string" && input.name.trim()) channel.name = input.name.trim();
      if (typeof input.address === "string" && channel.kind !== "webchat") channel.address = input.address.trim();
      for (const [k, v] of Object.entries((input.config as Json) ?? {})) {
        if (v === null) delete (channel.config as Json)[k];
        else (channel.config as Json)[k] = v;
      }
      if (input.secrets) channel.secrets_set = true;
      if (input.status === "disabled") Object.assign(channel, { status: "disabled", status_detail: "Disabled by an admin" });
      else if (input.status === "active" && channel.status === "disabled") Object.assign(channel, { status: channel.kind === "webchat" ? "active" : "pending", status_detail: null });
      channel.updated_at = iso(Date.now());
      return structuredClone(channel);
    }
    if (method === "POST" && ch[2] === "test") {
      if (channel.kind !== "webchat" && !channel.secrets_set) {
        Object.assign(channel, { status: "failing", status_detail: "No credentials saved" });
        return { ok: false, detail: "No credentials are saved for this channel. Add them and test again." };
      }
      if (channel.status !== "disabled") Object.assign(channel, { status: "active", status_detail: null });
      return { ok: true, detail: channel.kind === "webchat" ? "This channel has nothing to connect to" : channel.provider === "smtp" ? "Logged in to the mail server without sending a message" : "The account accepted the saved credentials" };
    }
    if (method === "POST" && ch[2] === "estimate") {
      const est = smsSegments(typeof input.body === "string" ? input.body : "");
      return { ...est, estimated_cost: (est.segments * Number((channel.config?.segment_cost as number) ?? 0)).toFixed(6) };
    }
    return undefined;
  }

  // consents
  const cs = /^\/api\/v1\/contacts\/([^/]+)\/consents(?:\/([^/]+))?$/.exec(url);
  if (cs) {
    const list = consents.get(cs[1]!) ?? [];
    if (method === "GET") return { data: structuredClone(list) };
    if (method === "PUT" && cs[2]) {
      const kind = cs[2] as ChannelKind;
      const current = list.find((c) => c.kind === kind);
      if (current?.status === "opted_out") throw new DemoMiss(409, "The contact opted out; only they can opt back in, by replying START", "opted_out");
      const rest = list.filter((c) => c.kind !== kind);
      consents.set(cs[1]!, input.dnd ? [...rest, { kind, status: "dnd", source: "manual", reason: null, changed_at: iso(Date.now()) }] : rest);
      emit("record.updated", { record_id: cs[1]!, object: "contact" });
      return { kind, status: input.dnd ? "dnd" : "none" };
    }
    return undefined;
  }

  // conversations
  if (route === "GET /api/v1/conversations") return list(query);
  if (route === "POST /api/v1/conversations") {
    const contactId = String(input.contact_id ?? "");
    const found = [...convs.values()].find((c) => c.contact.id === contactId);
    if (found) return row(found);
    const contact = contacts.find((c) => c.id === contactId);
    if (!contact) throw new DemoMiss(404, "Contact not found");
    const t = Date.now();
    const id = `demo-conv-${convs.size + 1}`;
    const c: Conv = { id, contact: { id: contact.id, display_name: contact.display_name, email: (contact.values.email as string) ?? null, phone: e164(contact.values.phone) }, status: "open", assignee_id: null, team_id: null, snooze_until: null, last_message_at: iso(t), last_inbound_at: null, channel_id: null, channel_kind: null, preview: null, last_direction: null, unread: false, last_seq: 0, visitor: false, created_at: iso(t), seqLast: 0, mark: 0, lastInboundSeq: 0 };
    convs.set(id, c);
    messages.set(id, []);
    emit("conversation.created", { conversation_id: id, contact_id: contact.id });
    return row(c);
  }
  const one = /^\/api\/v1\/conversations\/([^/]+)(?:\/([a-z]+)(?:\/([^/]+))?)?$/.exec(url);
  if (!one) return undefined;
  const c = need(one[1]!);
  const action = one[2];
  if (method === "GET" && !action) return { ...described(c), messages: messagePage(c, Number(query.get("limit")) || 50, null, null) };
  if (method === "GET" && action === "messages") return messagePage(c, Number(query.get("limit")) || 50, query.get("cursor"), query.get("q"));
  if (method === "POST" && action === "messages") {
    const key = headers?.["Idempotency-Key"];
    if (key && keys.has(key)) return structuredClone(keys.get(key));
    const out = send(c, input);
    if (key) keys.set(key, out);
    return out;
  }
  if (method === "PATCH" && action === "messages" && one[3]) {
    const m = (messages.get(c.id) ?? []).find((x) => x.id === one[3]);
    if (!m) throw new DemoMiss(404, "Message not found");
    if (m.kind !== "note") throw new DemoMiss(409, "Only internal notes can be edited", "not_a_note");
    if (m.sent_by !== me.id) throw new DemoMiss(403, "Only the author can edit a note", "forbidden");
    m.body = String(input.body ?? "").slice(0, 10000);
    emit("message.updated", { message_id: m.id, conversation_id: c.id, contact_id: c.contact.id });
    return structuredClone(m);
  }
  if (method !== "POST") return undefined;
  switch (action) {
    case "assign": {
      const patch: Partial<Conv> = {};
      if ("user_id" in input) {
        const uid = (input.user_id as string | null) ?? null;
        if (uid && uid !== me.id && !USERS.some((u) => u.id === uid)) throw new DemoMiss(422, "The assignee is not valid", "validation_failed", { user_id: "is not a member of this workspace" });
        patch.assignee_id = uid;
      }
      if ("team_id" in input) patch.team_id = (input.team_id as string | null) ?? null;
      setState(c, patch);
      return described(c);
    }
    case "snooze": {
      const until = Date.parse(String(input.until));
      if (!(until > Date.now() && until <= Date.now() + 365 * 24 * 60 * MIN)) throw new DemoMiss(422, "The time is not valid", "validation_failed", { until: "must be within the next year" });
      setState(c, { status: "snoozed", snooze_until: iso(until) });
      return described(c);
    }
    case "close":
      setState(c, { status: "closed", snooze_until: null });
      return described(c);
    case "reopen":
      setState(c, { status: "open", snooze_until: null });
      return described(c);
    case "read": {
      const seq = typeof input.seq === "number" ? Math.min(input.seq, c.seqLast) : c.seqLast;
      c.mark = Math.max(c.mark, seq);
      return { last_read_seq: c.mark };
    }
    case "unread":
      if (c.lastInboundSeq) c.mark = c.lastInboundSeq - 1;
      return { last_read_seq: c.mark };
  }
  return undefined;
}
