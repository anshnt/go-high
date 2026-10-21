// The email marketing API (backend/app/marketing) as typed calls.
import { api, queryString } from "../lib/api";

export type Align = "left" | "center" | "right";
export type Block =
  | { type: "heading"; id?: string; text: string; level?: 1 | 2 | 3; align?: Align }
  | { type: "text"; id?: string; text: string; align?: Align }
  | { type: "button"; id?: string; label: string; url: string; align?: Align }
  | { type: "image"; id?: string; src: string; alt?: string; href?: string | null; width?: number; align?: Align }
  | { type: "divider"; id?: string }
  | { type: "spacer"; id?: string; height?: number }
  | { type: "columns"; id?: string; columns: { blocks: Block[] }[] };
export type BlockType = Block["type"];

export type Style = {
  background?: string;
  content_background?: string;
  text_color?: string;
  muted_color?: string;
  link_color?: string;
  button_color?: string;
  button_text_color?: string;
  font?: "sans" | "serif";
  dark?: { background?: string; content_background?: string; text_color?: string; muted_color?: string; link_color?: string };
};
export type Doc = { version?: 1; style?: Style; blocks: Block[] };

export type Issue = { level: "error" | "warning" | "info"; code: string; message: string };

export type Template = {
  id: string;
  name: string;
  subject: string;
  preheader: string;
  archived: boolean;
  blocks: number;
  created_at: string;
  updated_at: string;
  document?: Doc;
};

export type CampaignStatus = "draft" | "scheduled" | "sending" | "testing" | "paused" | "sent" | "cancelled" | "failed";
export type Variant = { key: "B" | "C" | "D"; subject?: string | null; preheader?: string | null; document?: Doc | null };
export type AB = { enabled: boolean; metric: "opens" | "clicks"; test_percent: number; wait_hours: number; variants: Variant[] };
export type Audience = { view_id?: string; filter?: Record<string, unknown>; all?: boolean };
export type Campaign = {
  id: string;
  name: string;
  status: CampaignStatus;
  paused_from: CampaignStatus | null;
  channel_id: string | null;
  domain_id: string | null;
  topic_id: string | null;
  template_id: string | null;
  from_name: string;
  from_email: string;
  reply_to: string | null;
  subject: string;
  preheader: string;
  audience: Audience;
  ab: AB;
  winner: string | null;
  scheduled_at: string | null;
  timezone: string;
  started_at: string | null;
  test_ends_at: string | null;
  finished_at: string | null;
  audience_count: number | null;
  error: string | null;
  created_at: string;
  updated_at: string;
  stats: { recipients: number; sent: number; opened: number; clicked: number };
  document?: Doc;
};

export type Preview = {
  matched: number;
  with_email: number;
  duplicates: number;
  excluded: Partial<Record<"suppressed" | "unsubscribed" | "topic_unsubscribed", number>>;
  recipients: number;
  sample: { id: string; display_name: string; email: string }[];
};
export type Check = { ok: boolean; issues: Issue[]; audience: Preview; estimate: { recipients: number; per_1000: string; estimated_cost: string } };

export type Report = {
  totals: Record<
    | "recipients" | "sent" | "delivered" | "opened" | "clicked" | "unsubscribed" | "bounced" | "complained" | "failed" | "skipped"
    | "cancelled" | "uncertain" | "waiting" | "machine_opens" | "machine_clicks" | "privacy_proxy_only",
    number
  >;
  rates: { base: "sent" | "delivered"; open: number | null; click: number | null; click_to_open: number | null; bounce: number | null; complaint: number | null; unsubscribe: number | null };
  variants: { variant: string; subject: string; sent: number; opened: number; clicked: number; open_rate: number | null; click_rate: number | null; winner: boolean }[];
  links: { idx: number; url: string; clicks: number; people: number; machine_clicks: number }[];
  reasons: Record<string, number>;
  timeline: { hour: string; opens: number; clicks: number }[];
};
export type Recipient = {
  id: string;
  contact_id: string;
  display_name: string;
  email: string | null;
  variant: string | null;
  status: string;
  reason: string | null;
  sent_at: string | null;
  opened_at: string | null;
  clicked_at: string | null;
  opens: number;
  clicks: number;
  unsubscribed_at: string | null;
};

export type CheckResult = { status: "pass" | "warn" | "fail" | "error"; message: string; found?: string[]; expected?: string | null; host?: string };
export type Domain = {
  id: string;
  domain: string;
  dkim_mode: "managed" | "provider";
  dkim_selector: string;
  spf_include: string | null;
  status: "pending" | "verified" | "failing";
  checks: Partial<Record<"spf" | "dkim" | "dmarc", CheckResult>> & { verified?: boolean };
  checked_at: string | null;
  verified_at: string | null;
  warmup_started_at: string | null;
  hourly_limit: number | null;
  records: { type: string; host: string; value: string; purpose: string }[];
  limits: { hourly: number; daily: number | null; day: number | null; stage: "not_verified" | "warming" | "warm" | "custom"; schedule: { day: number; daily: number }[] };
  sent: { last_hour: number; last_day: number };
  created_at: string;
};
export type Settings = { company_name: string; postal_address: string; track_opens: boolean; track_clicks: boolean };
export type Topic = { id: string; name: string; description: string; archived: boolean; created_at: string };
export type Suppression = { id: string; email: string; reason: "hard_bounce" | "complaint" | "unsubscribe" | "manual"; detail: string | null; created_at: string; removable: boolean };
export type MergeField = { key: string; label: string; type: string };
export type Rendered = { subject: string; html: string; text: string; size: number; issues: Issue[]; merge_errors: Record<string, string> };
export type Page<T> = { data: T[]; next_cursor: string | null };
export type Channel = { id: string; kind: string; name: string; address: string; status: string; provider: string };
export type View = { id: string; name: string; object: string; shared: boolean; count?: number };

const root = "/api/v1/email";
export const email = {
  campaigns: (p: { status?: string; q?: string; cursor?: string | null }) => api.get<Page<Campaign>>(`${root}/campaigns${queryString({ ...p, limit: 50 })}`),
  campaign: (id: string) => api.get<Campaign>(`${root}/campaigns/${id}`),
  createCampaign: (body: { name: string; template_id?: string }) => api.post<Campaign>(`${root}/campaigns`, body),
  patchCampaign: (id: string, body: Partial<Omit<Campaign, "ab">> & { ab?: AB }) => api.patch<Campaign>(`${root}/campaigns/${id}`, body),
  deleteCampaign: (id: string) => api.del(`${root}/campaigns/${id}`),
  duplicateCampaign: (id: string) => api.post<Campaign>(`${root}/campaigns/${id}/duplicate`),
  audience: (id: string) => api.get<Preview>(`${root}/campaigns/${id}/audience`),
  check: (id: string) => api.post<Check>(`${root}/campaigns/${id}/check`),
  schedule: (id: string, body: { scheduled_at?: string; timezone: string }) => api.post<Campaign>(`${root}/campaigns/${id}/schedule`, body),
  act: (id: string, action: "unschedule" | "pause" | "resume" | "cancel") => api.post<Campaign>(`${root}/campaigns/${id}/${action}`),
  report: (id: string) => api.get<Report>(`${root}/campaigns/${id}/report`),
  recipients: (id: string, p: { status?: string; cursor?: string | null }) => api.get<Page<Recipient>>(`${root}/campaigns/${id}/recipients${queryString({ ...p, limit: 50 })}`),

  templates: (p: { q?: string; archived?: boolean; cursor?: string | null }) => api.get<Page<Template>>(`${root}/templates${queryString({ ...p, limit: 50 })}`),
  template: (id: string) => api.get<Template>(`${root}/templates/${id}`),
  createTemplate: (body: { name: string; subject?: string; document?: Doc }) => api.post<Template>(`${root}/templates`, body),
  patchTemplate: (id: string, body: Partial<{ name: string; subject: string; preheader: string; document: Doc; archived: boolean }>) => api.patch<Template>(`${root}/templates/${id}`, body),
  duplicateTemplate: (id: string) => api.post<Template>(`${root}/templates/${id}/duplicate`),
  render: (body: { subject: string; preheader: string; document: Doc; contact_id?: string }) => api.post<Rendered>(`${root}/render`, body),
  mergeFields: () => api.get<{ data: MergeField[] }>(`${root}/merge-fields`).then((r) => r.data),

  domains: () => api.get<Page<Domain>>(`${root}/domains?limit=200`).then((r) => r.data),
  domain: (id: string) => api.get<Domain>(`${root}/domains/${id}`),
  createDomain: (body: { domain: string; dkim_mode: "managed" | "provider"; dkim_selector?: string; spf_include?: string }) => api.post<Domain>(`${root}/domains`, body),
  patchDomain: (id: string, body: Partial<{ dkim_selector: string; spf_include: string | null; hourly_limit: number | null }>) => api.patch<Domain>(`${root}/domains/${id}`, body),
  deleteDomain: (id: string) => api.del(`${root}/domains/${id}`),
  checkDomain: (id: string) => api.post<Domain>(`${root}/domains/${id}/check`),

  settings: () => api.get<Settings>(`${root}/settings`),
  saveSettings: (body: Settings) => api.put<Settings>(`${root}/settings`, body),
  topics: (archived = false) => api.get<{ data: Topic[] }>(`${root}/topics${archived ? "?archived=true" : ""}`).then((r) => r.data),
  createTopic: (body: { name: string; description?: string }) => api.post<Topic>(`${root}/topics`, body),
  patchTopic: (id: string, body: Partial<{ name: string; description: string; archived: boolean }>) => api.patch<Topic>(`${root}/topics/${id}`, body),

  suppressions: (p: { q?: string; reason?: string; cursor?: string | null }) =>
    api.get<Page<Suppression> & { counts: Record<string, number> }>(`${root}/suppressions${queryString({ ...p, limit: 50 })}`),
  suppress: (body: { email: string; detail?: string }) => api.post<Suppression>(`${root}/suppressions`, body),
  unsuppress: (id: string) => api.del(`${root}/suppressions/${id}`),

  channels: () => api.get<Page<Channel>>("/api/v1/channels?limit=200").then((r) => r.data.filter((c) => c.kind === "email")),
  views: () => api.get<Page<View>>("/api/v1/views?object=contact&counts=true&limit=200").then((r) => r.data),
};
