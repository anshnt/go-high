// The workflows API (backend/app/workflows/routes.py, README "Workflows") as typed calls.
import { api, queryString } from "../lib/api";
import type { Graph } from "./graph.ts";

export type Status = "draft" | "published" | "paused" | "archived";
export type RunStatus = "running" | "waiting" | "completed" | "failed" | "exited" | "cancelled";
export type Settings = { reentry: boolean };

export type WorkflowRow = {
  id: string;
  name: string;
  folder: string | null;
  status: Status;
  settings: Settings;
  owner_id: string | null;
  trigger_event: string | null;
  published_version_id: string | null;
  published_version: number | null;
  latest_version: number | null;
  has_draft_changes: boolean;
  /** live runs (test runs left out) by status */
  runs: Partial<Record<RunStatus, number>>;
  created_by: string | null;
  created_at: string;
  updated_at: string;
};
export type WorkflowDetail = WorkflowRow & { graph: Graph | null };

export type Version = {
  id: string;
  workflow_id: string;
  number: number;
  note: string | null;
  created_by: string | null;
  created_at: string;
  published_at: string | null;
  published: boolean;
  nodes: number;
  graph?: Graph;
};

export type Glance = { id: string; object: string; display_name: string };
export type RunRow = {
  id: string;
  workflow_id: string;
  workflow: string | null;
  version: number | null;
  record: Glance | null;
  status: RunStatus;
  node_id: string | null;
  step_count: number;
  wake_at: string | null;
  error: string | null;
  test: boolean;
  trigger_event_id: number | null;
  started_at: string;
  ended_at: string | null;
};
export type StepStatus = "completed" | "waiting" | "failed" | "migrated" | "cancelled";
export type Step = {
  id: string | null;
  seq: number;
  node_id: string;
  status: StepStatus;
  /** null for a role that hides fields */
  input: Record<string, unknown> | null;
  output: Record<string, unknown> | null;
  error: string | null;
  started_at: string;
  finished_at: string | null;
};
export type RunDetail = RunRow & {
  context: Record<string, unknown>;
  steps: Step[];
  waiting_for: { event_type: string; match: Record<string, unknown> }[];
  deliveries: { id: string; node_id: string; host: string | null; status: string; attempts: number; response_status: number | null; error: string | null; created_at: string }[];
};
export type TestResult = { run: RunRow; version: number; steps: Step[]; skipped_seconds: number };

export type NodeDiff = { id: string; node: Record<string, unknown> };
export type Diff = {
  from: number;
  to: number;
  trigger: { changed: boolean; before: Graph["trigger"]; after: Graph["trigger"] };
  start: { changed: boolean; before: string | null; after: string | null };
  nodes: { added: NodeDiff[]; removed: NodeDiff[]; changed: { id: string; keys: string[]; before: Record<string, unknown>; after: Record<string, unknown> }[] };
};

export type PublishPlan = {
  in_flight: number;
  same_node: number;
  removed_nodes: { node_id: string; runs: number; to: string | null }[];
  dry_run: boolean;
  moved?: number;
  exited?: number;
};

export type CheckOutcome = "entered" | "filter" | "object" | "data" | "reentry" | "running" | "self" | "no_record" | "error";
export type Explanation = {
  record_id: string;
  workflow_id: string;
  workflow_status: Status;
  in_workflow: boolean;
  answer: string;
  checks: { event_id: number; event_type: string; matched: boolean; outcome: CheckOutcome; reason: string | null; run_id: string | null; version_id: string | null; at: string }[];
  evaluation: { outcome: string; reason: string | null; matched: boolean; evaluated: "now" } | null;
  runs: { id: string; status: RunStatus; node_id: string | null; started_at: string; ended_at: string | null }[];
};

// ---- the catalog ----

export type JsonSchema = {
  type?: string | string[];
  title?: string;
  description?: string;
  default?: unknown;
  enum?: unknown[];
  format?: string;
  pattern?: string;
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  minItems?: number;
  maxItems?: number;
  minProperties?: number;
  maxProperties?: number;
  properties?: Record<string, JsonSchema>;
  patternProperties?: Record<string, JsonSchema>;
  additionalProperties?: boolean | JsonSchema;
  propertyNames?: JsonSchema;
  items?: JsonSchema;
  anyOf?: JsonSchema[];
  required?: string[];
  $ref?: string;
  $defs?: Record<string, JsonSchema>;
};
export type TriggerSpec = { event: string; description: string; record: "subject" | "contact_id" | "record_id"; data_schema: JsonSchema };
export type NodeSpec = { type: string; description: string; config_schema: JsonSchema | null; published: boolean };
export type ActionSpec = { key: string; label: string; description: string; outbound: boolean; config_schema: JsonSchema };
export type Catalog = {
  triggers: TriggerSpec[];
  trigger_schema: JsonSchema;
  nodes: NodeSpec[];
  actions: ActionSpec[];
  settings_schema: JsonSchema;
  limits: { max_nodes: number; max_steps_per_run: number };
  merge_fields: string;
};

export type Page<T> = { data: T[]; next_cursor: string | null };

const root = "/api/v1/workflows";
const enc = encodeURIComponent;

let catalogLoad: Promise<Catalog> | null = null;

export const workflows = {
  /** Read once per page load: it only changes with a release. */
  catalog: () => {
    catalogLoad ??= api.get<Catalog>(`${root}/catalog`);
    catalogLoad.catch(() => (catalogLoad = null));
    return catalogLoad;
  },
  list: (p: { status?: Status; q?: string; folder?: string; cursor?: string | null; limit?: number }) => api.get<Page<WorkflowRow>>(`${root}${queryString({ ...p, limit: p.limit ?? 50 })}`),
  create: (body: { name: string; folder?: string; graph?: Graph; note?: string }) => api.post<WorkflowRow & { signing_secret: string; version: Version | null }>(root, body),
  get: (id: string) => api.get<WorkflowDetail>(`${root}/${enc(id)}`),
  patch: (id: string, body: Partial<{ name: string; folder: string | null; settings: Settings }>) => api.patch<WorkflowRow>(`${root}/${enc(id)}`, body),
  archive: (id: string) => api.del(`${root}/${enc(id)}`),
  rotateSecret: (id: string) => api.post<{ signing_secret: string }>(`${root}/${enc(id)}/rotate-secret`),
  versions: (id: string, cursor?: string | null) => api.get<Page<Version>>(`${root}/${enc(id)}/versions${queryString({ cursor, limit: 50 })}`),
  version: (id: string, n: number) => api.get<Version & { graph: Graph }>(`${root}/${enc(id)}/versions/${n}`),
  /** `base`: the newest version number the editor started from; the server answers 409 `version_conflict` when another
   * was saved since. Leave it out to save on top of whatever is newest. */
  save: (id: string, graph: Graph, note?: string, base?: number | null) =>
    api.post<Version & { graph: Graph }>(`${root}/${enc(id)}/versions`, { graph, ...(note ? { note } : {}), ...(base !== undefined ? { base } : {}) }),
  diff: (id: string, from: number, to: number) => api.get<Diff>(`${root}/${enc(id)}/diff${queryString({ from, to })}`),
  publish: (id: string, body: { version?: number; migrate?: Record<string, string>; dry_run?: boolean }) => api.post<WorkflowRow & { publish: PublishPlan }>(`${root}/${enc(id)}/publish`, body),
  pause: (id: string) => api.post<WorkflowRow>(`${root}/${enc(id)}/pause`),
  resume: (id: string) => api.post<WorkflowRow>(`${root}/${enc(id)}/resume`),
  test: (id: string, body: { record_id: string; version?: number; paths?: Record<string, string> }) => api.post<TestResult>(`${root}/${enc(id)}/test`, body),
  explain: (id: string, recordId: string) => api.get<Explanation>(`${root}/${enc(id)}/explain${queryString({ record_id: recordId })}`),
  runs: (p: { workflow_id?: string; status?: RunStatus; record_id?: string; test?: boolean; cursor?: string | null }) => api.get<Page<RunRow>>(`${root}/runs${queryString({ ...p, test: p.test || undefined, limit: 50 })}`),
  run: (runId: string) => api.get<RunDetail>(`${root}/runs/${enc(runId)}`),
  cancelRun: (runId: string) => api.post<RunDetail>(`${root}/runs/${enc(runId)}/cancel`),
  retryRun: (runId: string) => api.post<RunDetail>(`${root}/runs/${enc(runId)}/retry`),
};

// ---- what the config pickers list ----

export type Choice = { id: string; name: string; hint?: string };
const cached = new Map<string, Promise<Choice[]>>();
function once(key: string, load: () => Promise<Choice[]>): Promise<Choice[]> {
  let p = cached.get(key);
  if (!p) {
    p = load();
    cached.set(key, p);
    p.catch(() => cached.delete(key));
  }
  return p;
}

type Stageful = { id: string; name: string; archived_at: string | null; stages: { id: string; name: string }[] };
export const lookups = {
  channels: () => once("channels", () => api.get<Page<{ id: string; name: string; kind: string; address: string }>>("/api/v1/channels").then((p) => p.data.map((c) => ({ id: c.id, name: c.name, hint: `${c.kind}, ${c.address}`, kind: c.kind })))),
  stages: () => once("stages", () => api.get<Page<Stageful>>("/api/v1/pipelines").then((p) => p.data.flatMap((pl) => pl.stages.map((s) => ({ id: s.id, name: s.name, hint: pl.name }))))),
  forms: () => once("forms", () => api.get<Page<{ id: string; name: string; status: string }>>("/api/v1/forms?limit=200").then((p) => p.data.map((f) => ({ id: f.id, name: f.name, hint: f.status })))),
  calendars: () => once("calendars", () => api.get<Page<{ id: string; name: string }>>("/api/v1/calendars").then((p) => p.data.map((c) => ({ id: c.id, name: c.name })))),
};

export async function searchRecords(object: string, q: string): Promise<Glance[]> {
  const page = await api.get<{ data: { id: string; display_name: string }[] }>(`/api/v1/objects/${enc(object)}/records${queryString({ q: q.trim() || undefined, limit: 8 })}`);
  return page.data.map((r) => ({ id: r.id, object, display_name: r.display_name }));
}
