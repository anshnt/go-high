// Which channels a contact can be reached on, and which one a reply starts on. Pure: no DOM, no Vite.
import type { Channel, ChannelKind, Conversation } from "./types.ts";

type Who = Pick<Conversation, "contact" | "visitor" | "channel_id">;

/** Whether the contact has a way to be reached on this kind of channel: a phone number, an email address, or an open chat session. */
export function hasAddress(kind: ChannelKind, c: Pick<Who, "contact" | "visitor">): boolean {
  if (kind === "sms" || kind === "whatsapp") return !!c.contact.phone;
  if (kind === "email") return !!c.contact.email;
  return c.visitor; // web chat: only a visitor who started a chat can be answered
}

/** The channels a reply can go out on: not switched off, and the contact can be reached there. */
export const reachable = (channels: Channel[], c: Pick<Who, "contact" | "visitor">): Channel[] => channels.filter((ch) => ch.status !== "disabled" && hasAddress(ch.kind, c));

// Where a first message goes when nothing says otherwise: a text is read soonest, then WhatsApp, then email, then the chat window.
const FIRST: ChannelKind[] = ["sms", "whatsapp", "email", "webchat"];

/** The channel the conversation last used if the contact can still be reached on it, else the quickest one they can be reached on. */
export function defaultChannel(channels: Channel[], c: Who): Channel | null {
  const ok = reachable(channels, c);
  return ok.find((ch) => ch.id === c.channel_id) ?? [...ok].sort((a, b) => FIRST.indexOf(a.kind) - FIRST.indexOf(b.kind))[0] ?? null;
}
