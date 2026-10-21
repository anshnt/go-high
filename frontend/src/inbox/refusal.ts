// A send the server refuses (422 with a code, README "Replying"), said plainly, and the same words for a consent that
// already says no. The server's own sentence is always shown ("Opted out by STOP on Oct 3"); this adds a title, what
// the person can do about it and, for quiet hours, when. Pure: no DOM, no Vite.
import { whenLabel } from "./time.ts";
import type { ChannelKind, Consent } from "./types.ts";

export const REFUSAL_CODES = ["opted_out", "dnd", "quiet_hours", "frequency_cap", "no_address", "no_channel", "channel_disabled", "wallet_empty", "credit_limit", "usage_cap"] as const;
/** The refusals the wallet makes (module 06): the fix is on the billing screen. */
export const WALLET_CODES: readonly RefusalCode[] = ["wallet_empty", "credit_limit", "usage_cap"];
export type RefusalCode = (typeof REFUSAL_CODES)[number];
export const isRefusalCode = (code: unknown): code is RefusalCode => typeof code === "string" && (REFUSAL_CODES as readonly string[]).includes(code);

export type Refusal = {
  code: RefusalCode;
  title: string;
  /** The server's sentence. */
  text: string;
  /** What to do next. */
  hint: string;
  /** When waiting helps (quiet hours): "Tue, Oct 20, 8:00 AM". */
  until?: string;
  /** Sending cannot work until something else changes: the Send button says so. */
  blocking: boolean;
};

const TITLE: Record<RefusalCode, string> = {
  opted_out: "Opted out",
  dnd: "Do not disturb is on",
  quiet_hours: "Quiet hours",
  frequency_cap: "Frequency cap reached",
  no_address: "No way to reach this contact here",
  no_channel: "Choose a channel",
  channel_disabled: "This channel is switched off",
  wallet_empty: "The wallet is empty",
  credit_limit: "Credit limit reached",
  usage_cap: "Monthly usage cap reached",
};
const HINT: Record<RefusalCode, string> = {
  opted_out: "Only the contact can opt back in, by replying START. Use another channel they have not opted out of.",
  dnd: "Turn off do not disturb for this channel on the contact card, or use another channel.",
  quiet_hours: "Messages wait for the contact's morning. Your draft is kept.",
  frequency_cap: "Wait a while before the next message, or use another channel. Your draft is kept.",
  no_address: "Add the phone number or email address to the contact, or pick another channel.",
  no_channel: "Pick a channel in the list above the message.",
  channel_disabled: "Ask an admin to switch it on in Settings > Channels, or pick another channel.",
  // the server's sentence already says where to fix it
  wallet_empty: "Your draft is kept: send again once the wallet is topped up.",
  credit_limit: "Your draft is kept: send again once the balance is settled.",
  usage_cap: "Your draft is kept: send again once the cap is raised.",
};
// Whether trying again as it is could ever work.
const BLOCKING = new Set<RefusalCode>(["opted_out", "no_address", "no_channel", "channel_disabled"]);

type ErrorLike = { code?: string; message: string; fields?: Record<string, string> };

/** The banner for a refused send, or null when the error is something else (a network failure, a 500). */
export function describeRefusal(e: ErrorLike, now: Date = new Date()): Refusal | null {
  if (!isRefusalCode(e.code)) return null;
  const retry = e.code === "quiet_hours" && e.fields?.retry_at ? new Date(e.fields.retry_at) : null;
  return {
    code: e.code,
    title: TITLE[e.code],
    text: e.message,
    hint: HINT[e.code],
    // ponytail: the time only; "Schedule for <time>" arrives with scheduled send (module 12), which the API does not have yet.
    until: retry && !Number.isNaN(retry.getTime()) ? whenLabel(retry, now) : undefined,
    blocking: BLOCKING.has(e.code),
  };
}

const SOURCE: Record<string, string> = { stop: "STOP", unsubscribe: "unsubscribe", complaint: "a spam complaint", manual: "staff" };
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const KIND: Record<ChannelKind, string> = { sms: "sms", email: "email", whatsapp: "whatsapp", webchat: "webchat" };

/** The same banner before anyone presses Send, when the cost preview says the wallet would refuse it. */
export function walletRefusal(charge: { allowed: boolean; code: string | null; reason: string | null } | null | undefined): Refusal | null {
  if (!charge || charge.allowed || !isRefusalCode(charge.code)) return null;
  return { ...base(charge.code), text: charge.reason ?? "" };
}

/** The same banner for a consent already on file, before anyone presses Send. */
export function consentRefusal(c: Consent): Refusal | null {
  const when = new Date(c.changed_at);
  const day = Number.isNaN(when.getTime()) ? "" : ` on ${MONTHS[when.getMonth()]} ${when.getDate()}`;
  if (c.status === "opted_out") return { ...base("opted_out"), text: `Opted out by ${SOURCE[c.source] ?? c.source}${day}` };
  if (c.status === "dnd") return { ...base("dnd"), text: `Do not disturb is on for ${KIND[c.kind] ?? c.kind}` };
  return null;
}

function base(code: RefusalCode): Omit<Refusal, "text"> {
  return { code, title: TITLE[code], hint: HINT[code], blocking: BLOCKING.has(code) };
}

/** A line for the contact card: "Opted in", "Opted out by STOP on Oct 3", "Do not disturb", "No record". */
export function consentLine(c: Consent | undefined): string {
  if (!c) return "No record";
  if (c.status === "opted_in") return "Opted in";
  if (c.status === "dnd") return "Do not disturb";
  return consentRefusal(c)?.text ?? "Opted out";
}
