// The shapes of the inbox API (README "Inbox and channels"). Types only, so node can import everything built on them.

export type ChannelKind = "sms" | "email" | "webchat" | "whatsapp";
export type ConversationStatus = "open" | "snoozed" | "closed";
export type ViewId = "open" | "mine" | "unassigned" | "unread" | "snoozed" | "closed";
export type Direction = "in" | "out";
export type MessageStatus = "queued" | "sent" | "delivered" | "read" | "failed" | "received";
export type MessageKind = "message" | "note" | "call" | "voicemail" | "system";

export type ContactRef = { id: string; display_name: string | null; email: string | null; phone: string | null };

export type Conversation = {
  id: string;
  contact: ContactRef;
  status: ConversationStatus;
  assignee_id: string | null;
  team_id: string | null;
  snooze_until: string | null;
  last_message_at: string;
  last_inbound_at: string | null;
  channel_id: string | null;
  channel_kind: ChannelKind | null;
  preview: string | null;
  last_direction: Direction | null;
  unread: boolean;
  last_seq: number;
  /** A webchat visitor: the chat session is a way to reach them. */
  visitor: boolean;
  created_at: string;
};

export type Attachment = { url: string; name?: string; content_type?: string; size?: number };

export type Message = {
  id: string;
  conversation_id: string;
  seq: number;
  direction: Direction;
  channel_id: string | null;
  kind: MessageKind;
  subject: string | null;
  body: string;
  html: string | null;
  attachments: Attachment[];
  status: MessageStatus;
  error: string | null;
  provider_message_id: string | null;
  thread_ref: string | null;
  sent_by: string | null;
  occurred_at: string;
  created_at: string;
  segments: number | null;
  estimated_cost: string | null;
};

/** A message as the thread holds it: the server's, or one still on its way (or that failed to leave). */
export type ThreadMessage = Message & { local?: { key: string; state: "sending" | "failed"; error?: string; channelKind?: ChannelKind } };

export type MessagePage = { data: Message[]; next_cursor: string | null };
export type ConversationDetail = Conversation & { last_read_seq: number; messages: MessagePage };

export type Counts = Record<ViewId, number> & { channels: Record<string, number> };
export type ConversationPage = { data: Conversation[]; next_cursor: string | null; counts?: Counts };

export type ChannelStatus = "active" | "pending" | "failing" | "disabled";
export type Channel = {
  id: string;
  kind: ChannelKind;
  provider: "twilio" | "telnyx" | "smtp" | "ses" | "mailgun" | "meta" | "internal";
  name: string;
  address: string;
  status: ChannelStatus;
  status_detail: string | null;
  created_at: string;
  updated_at: string;
  widget_key?: string;
  // only for roles with channels.manage
  config?: Record<string, unknown>;
  secrets_set?: boolean;
  webhook_url?: string | null;
  embed?: string;
};

export type ConsentStatus = "opted_out" | "opted_in" | "dnd";
export type Consent = { kind: ChannelKind; status: ConsentStatus; source: string; reason: string | null; changed_at: string };

export type Estimate = { encoding: "gsm7" | "ucs2"; segments: number; chars: number; estimated_cost: string };
export type SentMessage = Message & { estimate: Estimate | null };

export type Team = { id: string; name: string };
