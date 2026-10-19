import type { FieldDef, LinkType, NewRecord, ObjectDef, Page, QueryParams, RecordRow, SavedView, Tag, TimelineEvent, UserRef } from "./types.ts";
import { createApiClient } from "./apiClient.ts";
import { api } from "../lib/api";
import { session } from "../lib/session";

/**
 * Everything the record screens need from the backend. The screens only ever talk to this interface: the API client
 * (apiClient.ts) is what the app runs on, and the in-memory client (memoryClient.ts) stands in for it in the public
 * demo build. Both return the same shapes and the same errors (RecordsError with `status` and `fields`).
 * Rows are immutable: never edit what a call returns, copy it.
 */
export interface RecordsClient {
  listObjects(): Promise<ObjectDef[]>;
  /** Includes system columns (owner_id, created_at, updated_at) and archived fields; the UI hides archived ones. */
  listFields(object: string): Promise<FieldDef[]>;
  query(object: string, params?: QueryParams): Promise<Page<RecordRow>>;
  get(object: string, id: string): Promise<RecordRow>;
  create(object: string, input: NewRecord): Promise<RecordRow>;
  /** `changes` maps field key to the new value; `owner_id` is accepted too. Resolves with the saved row. */
  update(object: string, id: string, changes: Record<string, unknown>): Promise<RecordRow>;
  /** The same `changes` to many records, all or nothing per call. */
  updateMany(object: string, ids: string[], changes: Record<string, unknown>): Promise<void>;
  /** Soft delete (trash); restore brings them back. Take lists so a bulk action is one call. */
  remove(object: string, ids: string[]): Promise<void>;
  restore(object: string, ids: string[]): Promise<void>;
  /** Newest first. */
  timeline(recordId: string, cursor?: string | null): Promise<Page<TimelineEvent>>;
  listViews(object: string): Promise<SavedView[]>;
  /** No id creates a view owned by the caller; an id updates one the caller owns. */
  saveView(view: Omit<SavedView, "id" | "owner_id"> & { id?: string }): Promise<SavedView>;
  deleteView(id: string): Promise<void>;
  listTags(): Promise<Tag[]>;
  /** Record ids from any object. */
  tag(ids: string[], tagId: string): Promise<void>;
  untag(ids: string[], tagId: string): Promise<void>;
  /** Workspace members, for owner and user fields. */
  listUsers(): Promise<UserRef[]>;
  /** The kinds of link between objects that are not record fields (associations); a record page lists what is linked either way. */
  listLinkTypes(): Promise<LinkType[]>;
}

// The demo build runs on the in-memory client (seeded data, simulated latency, shared by every screen). Normal builds
// fold the condition to false, so the dynamic import goes with it and neither the client nor its seed is bundled.
const me = () => {
  const s = session.get();
  return s.status === "ready" ? { id: s.me.user.id, name: s.me.user.name, email: s.me.user.email } : null;
};
// "demo-user" is the signed-in visitor of lib/demo.ts: it owns a few deals, so the board'"'"'s "My deals" is not empty.
const demo = import.meta.env.VITE_DEMO === "1" ? (await import("./memoryClient.ts")).createMemoryClient({ latency: 60, me, dataset: (await import("./seed.ts")).seedDataset({ anchor: Date.now(), mine: "demo-user" }) }) : undefined;

const live = createApiClient(api);

/** The client every record screen runs on, for code that is not a component (the pipeline demo client builds on it). */
export const recordsClient: RecordsClient = demo ?? live;

export const useRecordsClient = (): RecordsClient => recordsClient;
