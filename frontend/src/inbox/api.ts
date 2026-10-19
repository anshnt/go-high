// The inbox API calls (README "Inbox and channels"), typed. The demo build answers the same paths from memory
// (lib/demoInbox.ts), so nothing here knows which one it is talking to.
import { api, queryString } from "../lib/api";
import type { Channel, ChannelKind, Consent, Conversation, ConversationDetail, ConversationPage, Estimate, Message, MessagePage, SentMessage, Team, ViewId } from "./types.ts";

const BASE = "/api/v1/conversations";

/** A fresh key for one send; the same key on a retry makes the server answer with the first result instead of sending twice. */
export const newKey = (): string => (typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `k${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`);

export type ListParams = { view: ViewId; channel?: string | null; q?: string; cursor?: string | null; limit?: number };
export const listConversations = (p: ListParams) => api.get<ConversationPage>(`${BASE}${queryString({ view: p.view, channel_id: p.channel, q: p.q, cursor: p.cursor, limit: p.limit ?? 50 })}`);
export const getConversation = (id: string, limit = 50) => api.get<ConversationDetail>(`${BASE}/${id}${queryString({ limit })}`);
export const listMessages = (id: string, p: { q?: string; cursor?: string | null; limit?: number } = {}) => api.get<MessagePage>(`${BASE}/${id}/messages${queryString({ q: p.q, cursor: p.cursor, limit: p.limit ?? 50 })}`);
export const startConversation = (contactId: string) => api.post<Conversation>(BASE, { contact_id: contactId }, { "Idempotency-Key": newKey() });

export const assign = (id: string, who: { user_id?: string | null; team_id?: string | null }) => api.post<Conversation>(`${BASE}/${id}/assign`, who);
export const snooze = (id: string, until: Date) => api.post<Conversation>(`${BASE}/${id}/snooze`, { until: until.toISOString() });
export const close = (id: string) => api.post<Conversation>(`${BASE}/${id}/close`);
export const reopen = (id: string) => api.post<Conversation>(`${BASE}/${id}/reopen`);
export const markRead = (id: string, seq?: number) => api.post<{ last_read_seq: number }>(`${BASE}/${id}/read`, seq === undefined ? undefined : { seq });
export const markUnread = (id: string) => api.post<{ last_read_seq: number }>(`${BASE}/${id}/unread`);

export type Outgoing = { body: string; kind: "message" | "note"; channel_id?: string | null; subject?: string | null; html?: string | null };
/** One send. `key` is the Idempotency-Key. */
export const sendMessage = (id: string, m: Outgoing, key: string) => api.post<SentMessage>(`${BASE}/${id}/messages`, m, { "Idempotency-Key": key });
export const editNote = (id: string, messageId: string, body: string) => api.patch<Message>(`${BASE}/${id}/messages/${messageId}`, { body });

export const listChannels = async (): Promise<Channel[]> => (await api.get<{ data: Channel[] }>(`/api/v1/channels?limit=200`)).data;
export const estimate = (channelId: string, body: string) => api.post<Estimate>(`/api/v1/channels/${channelId}/estimate`, { body });

export const listConsents = async (contactId: string): Promise<Consent[]> => (await api.get<{ data: Consent[] }>(`/api/v1/contacts/${contactId}/consents`)).data;
export const setDnd = (contactId: string, kind: ChannelKind, dnd: boolean) => api.put<{ kind: string; status: string }>(`/api/v1/contacts/${contactId}/consents/${kind}`, { dnd });

export const listTeams = async (): Promise<Team[]> => (await api.get<{ data: Team[] }>(`/api/v1/teams?limit=200`)).data;

// Channel settings (Settings > Channels, needs channels.manage)
export type NewChannel = { kind: ChannelKind; provider: string; name: string; address?: string; config?: Record<string, unknown>; secrets?: Record<string, string | null> };
export type ChannelPatch = { name?: string; address?: string; config?: Record<string, unknown | null>; secrets?: Record<string, string | null>; status?: "active" | "disabled" };
export const createChannel = (c: NewChannel) => api.post<Channel>("/api/v1/channels", c, { "Idempotency-Key": newKey() });
export const patchChannel = (id: string, p: ChannelPatch) => api.patch<Channel>(`/api/v1/channels/${id}`, p);
export const testChannel = (id: string) => api.post<{ ok: boolean; detail: string }>(`/api/v1/channels/${id}/test`);
