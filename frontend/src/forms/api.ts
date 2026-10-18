// The forms admin API (backend/app/forms/admin.py, responses.py, analytics.py) as typed calls.
import { api, workspaceId, ApiError } from "../lib/api";
import type { Definition } from "../forms-runtime/types";

export type Kind = "form" | "survey" | "quiz";
export type Status = "draft" | "published" | "closed";

export type Settings = {
  success_message: string;
  redirect_url: string | null;
  closed_message: string;
  notify_emails: string[];
  contact: { create: boolean; existing: "update" | "fill_empty" };
  double_submission: "allow" | "block";
  close_at: string | null;
  max_responses: number | null;
  spam_protection: boolean;
  rate_limit_per_minute: number;
  max_body_kb: number;
};

export type FormRow = {
  id: string;
  name: string;
  kind: Kind;
  slug: string;
  public_key: string;
  status: Status;
  closed_reason: "manual" | "date" | "limit" | null;
  settings: Settings;
  published_version_id: string | null;
  published_version: number | null;
  latest_version: number;
  has_draft_changes: boolean;
  starts: number;
  responses: number;
  completion_rate: number | null;
  created_at: string;
  updated_at: string;
  deleted_at: string | null;
};
export type FormDetail = FormRow & { definition: Definition };
export type Version = { id: string; number: number; created_at: string; published: boolean; definition: Definition };

export type Submission = {
  id: string;
  status: "partial" | "complete";
  answers: Record<string, unknown>;
  score: number | null;
  max_score: number | null;
  contact_id: string | null;
  contact_error: string | null;
  source_url: string | null;
  referrer: string | null;
  utm: Record<string, string>;
  consent: Record<string, { text: string; at: string; form_id: string; ip_hash: string }>;
  version: number;
  started_at: string;
  created_at: string;
  completed_at: string | null;
  fields?: { key: string; type: string; label: string; options: { id: string; label: string }[] }[];
};

export type Analytics = {
  from: string | null;
  to: string | null;
  views: number;
  starts: number;
  completions: number;
  completion_rate: number | null;
  conversion_rate: number | null;
  avg_seconds: number | null;
  steps: { key: string; title: string; reached: number; dropped: number }[];
  fields: { key: string; label: string; step: string; type: string; answered: number; dropped_after: number }[];
};

export type ContactField = { key: string; label: string; type: string; options: { choices?: { id: string }[] } };
export type Page<T> = { data: T[]; next_cursor: string | null };

const query = (params: Record<string, string | number | boolean | undefined | null>) => {
  const q = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== null && v !== "") q.set(k, String(v));
  const s = q.toString();
  return s ? `?${s}` : "";
};

const root = "/api/v1/forms";
export const forms = {
  list: (p: { status?: string; q?: string; trashed?: boolean; cursor?: string | null; limit?: number }) => api.get<Page<FormRow>>(`${root}${query({ ...p, limit: p.limit ?? 50 })}`),
  create: (body: { name: string; kind: Kind }) => api.post<FormDetail>(root, body),
  get: (id: string) => api.get<FormDetail>(`${root}/${id}`),
  patch: (id: string, body: Partial<{ name: string; slug: string; settings: Settings; status: "draft" | "closed" }>) => api.patch<FormRow>(`${root}/${id}`, body),
  remove: (id: string) => api.del(`${root}/${id}`),
  restore: (id: string) => api.post<FormRow>(`${root}/${id}/restore`),
  duplicate: (id: string) => api.post<FormDetail>(`${root}/${id}/duplicate`),
  save: (id: string, definition: Definition) => api.post<Version>(`${root}/${id}/versions`, { definition }),
  publish: (id: string) => api.post<FormRow>(`${root}/${id}/publish`),
  submissions: (id: string, p: { status?: string; from?: string; to?: string; cursor?: string | null }) => api.get<Page<Submission>>(`${root}/${id}/submissions${query({ ...p, limit: 50 })}`),
  submission: (id: string, sid: string) => api.get<Submission>(`${root}/${id}/submissions/${sid}`),
  analytics: (id: string, p: { from?: string; to?: string }) => api.get<Analytics>(`${root}/${id}/analytics${query(p)}`),
  contactFields: () => api.get<{ data: ContactField[] }>("/api/v1/objects/contact/fields").then((r) => r.data),
};

/** Saves the CSV of the filtered responses as a file. The export needs the workspace header, so a plain link cannot do it. */
export async function downloadCsv(id: string, p: { status?: string; from?: string; to?: string }): Promise<void> {
  const res = await fetch(`${root}/${id}/submissions/export.csv${query(p)}`, { headers: { "X-Workspace-Id": workspaceId.get() ?? "" }, credentials: "same-origin" });
  if (!res.ok) throw new ApiError(res.status, "The export did not work. Try again.");
  const url = URL.createObjectURL(await res.blob());
  const name = /filename="([^"]+)"/.exec(res.headers.get("Content-Disposition") ?? "")?.[1] ?? "responses.csv";
  const a = Object.assign(document.createElement("a"), { href: url, download: name });
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

export const shareLink = (key: string) => `${location.origin}/f/${key}`;
export const embedCode = (key: string) => `<script src="${location.origin}/embed.js" data-form="${key}" async></script>`;
