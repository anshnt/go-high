// The admin API calls behind Settings > Team and roles, Audit log, API and webhooks, and Objects and fields (README
// "Roles, permissions and audit", "Events and webhooks", "Records and data model"), typed as the server answers.
import { api, queryString, workspaceId } from "../lib/api";
import { errorFrom } from "../lib/http";
import type { AuditFilters, DeliveryFilters, FieldType, Scope } from "./logic.ts";

export type { Scope } from "./logic.ts";

type List<T> = { data: T[]; next_cursor: string | null };

export const newKey = (): string => (typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `k${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`);
const once = () => ({ "Idempotency-Key": newKey() });

// ---- roles, members, teams ----

export type ObjectRule = { object_key: string; scope: Scope; hidden_fields: string[]; readonly_fields: string[] };
export type Role = {
  id: string;
  key: string;
  name: string;
  description: string;
  is_system: boolean;
  locked: boolean;
  capabilities: string[];
  object_rules: ObjectRule[];
  created_at: string;
};
export type CatalogEntry = { module: string; capability: string; description: string };
export type Catalog = { capabilities: CatalogEntry[]; scopes: Scope[] };
export type RoleRef = { id: string; key: string; name: string };
export type Member = { user_id: string; name: string | null; email: string; role: RoleRef; implicit: boolean; teams: { id: string; name: string }[] };
export type Team = { id: string; name: string; parent_team_id: string | null; created_at: string; member_count: number };
export type TeamDetail = Team & { members: { user_id: string; name: string | null; email: string }[] };

export const listRoles = async () => (await api.get<List<Role>>("/api/v1/roles")).data;
export const getRole = (id: string) => api.get<Role>(`/api/v1/roles/${id}`);
export const createRole = (body: { name: string; description?: string; copy_from: string }) => api.post<Role>("/api/v1/roles", body, once());
export const patchRole = (id: string, body: Partial<Pick<Role, "name" | "description" | "capabilities" | "object_rules">>) => api.patch<Role>(`/api/v1/roles/${id}`, body);
export const deleteRole = (id: string) => api.del(`/api/v1/roles/${id}`);
export const getCatalog = () => api.get<Catalog>("/api/v1/permissions/catalog");

export const listMembers = async () => (await api.get<List<Member>>("/api/v1/members")).data;
export const assignRole = (userId: string, roleId: string) => api.put<{ user_id: string; role: RoleRef }>(`/api/v1/members/${userId}`, { role_id: roleId });

export const listTeams = async () => (await api.get<List<Team>>("/api/v1/teams")).data;
export const getTeam = (id: string) => api.get<TeamDetail>(`/api/v1/teams/${id}`);
export const createTeam = (body: { name: string; parent_team_id: string | null }) => api.post<Team>("/api/v1/teams", body);
export const patchTeam = (id: string, body: { name?: string; parent_team_id?: string | null }) => api.patch<Team>(`/api/v1/teams/${id}`, body);
export const deleteTeam = (id: string) => api.del(`/api/v1/teams/${id}`);
export const addTeamMember = (teamId: string, userId: string) => api.put<{ team_id: string; user_id: string }>(`/api/v1/teams/${teamId}/members/${userId}`, {});
export const removeTeamMember = (teamId: string, userId: string) => api.del(`/api/v1/teams/${teamId}/members/${userId}`);

// ---- the simulator ----

export type Access = {
  scope: Scope;
  rule_scope: Scope;
  hidden_fields: string[];
  readonly_fields: string[];
  can: Record<"read" | "write" | "delete" | "export", boolean>;
};
export type Explanation = {
  user: { id: string; name: string | null; email: string | null };
  role: { id: string; key: string; name: string; source: "organization" | "workspace" } | null;
  capabilities: string[];
  teams: { id: string; name: string; direct: boolean }[];
  objects: Record<string, Access>;
  record?: { id: string; object: string; visible: boolean; in_trash: boolean; reason: string };
};
export const explain = (userId: string, recordId?: string | null) => api.get<Explanation>(`/api/v1/permissions/explain${queryString({ user_id: userId, record_id: recordId })}`);

// ---- records, for pickers ----

export type RecordHit = { id: string; display_name: string; object: string };
export const searchRecords = async (object: string, q: string) =>
  (await api.get<List<RecordHit>>(`/api/v1/objects/${object}/records${queryString({ q: q.trim() || undefined, limit: 20, sort: q.trim() ? undefined : "-updated_at" })}`)).data;
export const getRecord = (object: string, id: string) => api.get<RecordHit>(`/api/v1/objects/${object}/records/${id}`);

// ---- audit log ----

export type AuditEvent = {
  id: number;
  type: string;
  occurred_at: string;
  subject: { type: string; id: string };
  actor: { type: string; id: string | null };
  data: Record<string, unknown>;
};
export type EventType = { type: string; description: string; schema: { properties?: Record<string, unknown>; required?: string[] } };

const auditQuery = (f: AuditFilters) => ({ actor: f.actor, subject: f.subject, type: f.type, from: f.from, to: f.to });
export const listAudit = (f: AuditFilters, cursor?: string | null, limit = 50) => api.get<List<AuditEvent>>(`/api/v1/audit${queryString({ ...auditQuery(f), cursor, limit })}`);
export const auditEventTypes = async () => (await api.get<List<EventType>>("/api/v1/audit/event-types")).data;

/** Fetches a file the API answers (the CSV export) with the workspace header, and hands it to the browser as a download. */
export async function download(path: string, filename: string): Promise<number> {
  const headers: Record<string, string> = { Accept: "text/csv" };
  const ws = workspaceId.get();
  if (ws) headers["X-Workspace-Id"] = ws;
  let res: Response;
  try {
    res = await fetch(path, { headers, credentials: "same-origin" });
  } catch {
    throw new Error("Could not reach the server. Check your connection and try again.");
  }
  if (!res.ok) throw await errorFrom(res);
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return blob.size;
}
export const exportAudit = (f: AuditFilters, filename: string) => download(`/api/v1/audit/export${queryString(auditQuery(f))}`, filename);

// ---- webhooks ----

export type Endpoint = {
  id: string;
  url: string;
  event_types: string[];
  filter: Record<string, unknown>;
  active: boolean;
  disabled_reason: string | null;
  failing_since: string | null;
  created_at: string;
};
export type DeliveryStatus = "pending" | "retrying" | "succeeded" | "failed";
export type Delivery = {
  id: string;
  endpoint_id: string;
  event_id: number;
  event_type: string | null;
  status: DeliveryStatus;
  attempts: number;
  next_attempt_at: string | null;
  response_status: number | null;
  response_ms: number | null;
  response_body_excerpt: string | null;
  error: string | null;
  replay_of: string | null;
  created_at: string;
};
export type DeliveryDetail = Delivery & { payload: Record<string, unknown> | null; request_headers: Record<string, string> | null };
export type EndpointInput = { url: string; event_types: string[]; filter: Record<string, unknown> };

export const listEndpoints = async () => (await api.get<List<Endpoint>>("/api/v1/webhooks?limit=200")).data;
export const getEndpoint = (id: string) => api.get<Endpoint>(`/api/v1/webhooks/${id}`);
export const createEndpoint = (body: EndpointInput) => api.post<Endpoint & { secret: string }>("/api/v1/webhooks", body, once());
export const patchEndpoint = (id: string, body: Partial<EndpointInput & { active: boolean }>) => api.patch<Endpoint>(`/api/v1/webhooks/${id}`, body);
export const deleteEndpoint = (id: string) => api.del(`/api/v1/webhooks/${id}`);
export const sendTest = (id: string) => api.post<{ event_id: number }>(`/api/v1/webhooks/${id}/test`, undefined, once());
export const revealSecret = (id: string) => api.post<{ secret: string }>(`/api/v1/webhooks/${id}/reveal-secret`);
export const rotateSecret = (id: string) => api.post<Endpoint & { secret: string }>(`/api/v1/webhooks/${id}/rotate-secret`);
export const webhookEventTypes = async () => (await api.get<List<EventType>>("/api/v1/webhooks/event-types")).data;
export const listDeliveries = (id: string, f: DeliveryFilters, cursor?: string | null, limit = 50) =>
  api.get<List<Delivery>>(`/api/v1/webhooks/${id}/deliveries${queryString({ status: f.status, type: f.type, from: f.from, to: f.to, cursor, limit })}`);
export const getDelivery = (id: string) => api.get<DeliveryDetail>(`/api/v1/webhooks/deliveries/${id}`);
export const replayDelivery = (id: string) => api.post<Delivery>(`/api/v1/webhooks/deliveries/${id}/replay`, undefined, once());

// ---- objects, fields and association types ----

export type ObjectDef = {
  id: string;
  key: string;
  singular: string;
  plural: string;
  icon: string;
  is_system: boolean;
  primary_fields: string[];
  archived_at: string | null;
  created_at: string;
};
export type FieldDef = {
  id: string;
  key: string;
  label: string;
  type: FieldType;
  options: Record<string, unknown>;
  rules: Record<string, unknown>;
  is_system: boolean;
  position: number;
  archived_at: string | null;
  created_at: string;
};
export type AssociationType = {
  id: string;
  from_object: string;
  to_object: string;
  label: string;
  inverse_label: string;
  cardinality: "one_to_one" | "one_to_many" | "many_to_many";
  is_system: boolean;
  created_at: string;
};

/** Built-in objects first, then custom ones by name. */
export const listObjects = async (archived = false) =>
  (await api.get<List<ObjectDef>>(`/api/v1/objects${queryString({ archived: archived || undefined, limit: 200 })}`)).data.sort((a, b) => Number(b.is_system) - Number(a.is_system) || a.plural.localeCompare(b.plural));
export const createObject = (body: { key: string; singular: string; plural: string; icon: string }) => api.post<ObjectDef>("/api/v1/objects", body, once());
export const patchObject = (key: string, body: Partial<{ singular: string; plural: string; icon: string; primary_fields: string[]; archived: boolean }>) =>
  api.patch<ObjectDef>(`/api/v1/objects/${key}`, body);
export const listFields = async (object: string, archived = false) => (await api.get<List<FieldDef>>(`/api/v1/objects/${object}/fields${queryString({ archived: archived || undefined })}`)).data;
export const createField = (object: string, body: { key: string; label: string; type: FieldType; options: Record<string, unknown>; rules: Record<string, unknown> }) =>
  api.post<FieldDef>(`/api/v1/objects/${object}/fields`, body, once());
export const patchField = (object: string, key: string, body: Partial<{ label: string; options: Record<string, unknown>; rules: Record<string, unknown>; archived: boolean }>) =>
  api.patch<FieldDef>(`/api/v1/objects/${object}/fields/${key}`, body);
export const reorderFields = async (object: string, keys: string[]) => (await api.post<List<FieldDef>>(`/api/v1/objects/${object}/fields/reorder`, { keys })).data;
export const listAssociationTypes = async (object?: string) => (await api.get<List<AssociationType>>(`/api/v1/association-types${queryString({ object })}`)).data;
export const createAssociationType = (body: Pick<AssociationType, "from_object" | "to_object" | "label" | "inverse_label" | "cardinality">) =>
  api.post<AssociationType>("/api/v1/association-types", body, once());
export const deleteAssociationType = (id: string) => api.del(`/api/v1/association-types/${id}`);
