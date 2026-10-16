import type { FieldDef, NewRecord, ObjectDef, Page, QueryParams, RecordRow, SavedView, Tag, TimelineEvent, UserRef } from "./types.ts";
import { createMemoryClient } from "./memoryClient.ts";
import { session } from "../lib/session";

/**
 * Everything the record screens need from the backend. The screens only ever talk to this interface, so the
 * API client (module 07) is a drop-in: same shapes, same errors (RecordsError with `status` and `fields`).
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
}

let demo: RecordsClient | undefined;

// ponytail: the record engine API (module 07) is not built yet, so this returns the in-memory demo client
// (seeded data, simulated latency, shared by every screen). When the backend lands, return an API-backed
// RecordsClient here and the memory client drops out of the bundle.
export function useRecordsClient(): RecordsClient {
  demo ??= createMemoryClient({
    latency: 60,
    me: () => {
      const s = session.get();
      return s.status === "ready" ? { id: s.me.user.id, name: s.me.user.name, email: s.me.user.email } : null;
    },
  });
  return demo;
}
