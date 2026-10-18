import { createContext, useCallback, useContext, useEffect, useMemo, useState, useSyncExternalStore, type ReactNode } from "react";
import type { RecordsClient } from "./client.ts";
import type { FieldDef, LinkType, ObjectDef, RecordRow, Tag, UserRef } from "./types.ts";
import { liveFields } from "./schema.ts";

/** What every record screen needs to know about the workspace: its objects, their fields, people, tags and the kinds of link between objects. */
export type Meta = { objects: ObjectDef[]; fields: Record<string, FieldDef[]>; users: UserRef[]; tags: Tag[]; links: LinkType[] };

const loads = new WeakMap<RecordsClient, Promise<Meta>>();
const loaded = new WeakMap<RecordsClient, Meta>(); // so a screen that opens later renders at once, without a loading flash
function loadMeta(client: RecordsClient): Promise<Meta> {
  let p = loads.get(client);
  if (!p) {
    p = Promise.all([client.listObjects(), client.listUsers(), client.listTags(), client.listLinkTypes()]).then(async ([objects, users, tags, links]) => {
      const pairs = await Promise.all(objects.map(async (o) => [o.key, await client.listFields(o.key)] as const));
      const meta: Meta = { objects, users, tags, links, fields: Object.fromEntries(pairs) };
      loaded.set(client, meta);
      return meta;
    });
    loads.set(client, p);
    p.catch(() => loads.delete(client));
  }
  return p;
}

export function useLoadMeta(client: RecordsClient) {
  const [state, setState] = useState<{ meta: Meta | null; error: unknown }>(() => ({ meta: loaded.get(client) ?? null, error: null }));
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let live = true;
    loadMeta(client).then(
      (meta) => live && setState({ meta, error: null }),
      (error) => live && setState({ meta: null, error }),
    );
    return () => {
      live = false;
    };
  }, [client, attempt]);
  const retry = useCallback(() => {
    setState({ meta: null, error: null });
    setAttempt((n) => n + 1);
  }, []);
  return { ...state, retry };
}

const Ctx = createContext<Meta | null>(null);
export const MetaProvider = ({ meta, children }: { meta: Meta; children: ReactNode }) => <Ctx.Provider value={meta}>{children}</Ctx.Provider>;
export function useMeta(): Meta {
  const m = useContext(Ctx);
  if (!m) throw new Error("useMeta outside MetaProvider");
  return m;
}

export const useObjectDef = (key: string | undefined) => useMeta().objects.find((o) => o.key === key);
/** Fields of an object that are not archived, in workspace order. */
export function useFields(object: string | undefined): FieldDef[] {
  const m = useMeta();
  return object ? liveFields(m.fields[object] ?? []) : [];
}

// ---- the name behind a record link ----
// A link stores an id. Names are fetched in one batched query per object per tick and cached, and every
// row the app has already loaded or saved is put in the cache for free.

type Entry = { row: RecordRow | null } | "loading";
type Cache = { map: Map<string, Entry>; subs: Map<string, Set<() => void>>; all: Set<() => void>; queue: Map<string, Set<string>>; scheduled: boolean };
const caches = new WeakMap<RecordsClient, Cache>();
const cacheOf = (client: RecordsClient): Cache => {
  let c = caches.get(client);
  if (!c) caches.set(client, (c = { map: new Map(), subs: new Map(), all: new Set(), queue: new Map(), scheduled: false }));
  return c;
};
const MAX_IN = 100;
const keyOf = (object: string, id: string) => `${object}/${id}`;
const notify = (c: Cache, k: string) => {
  c.subs.get(k)?.forEach((fn) => fn());
  c.all.forEach((fn) => fn());
};

/** Put rows we already hold in the cache, so their names show without a fetch. */
export function primeRefs(client: RecordsClient, rows: RecordRow[]) {
  const c = cacheOf(client);
  for (const r of rows) {
    const k = keyOf(r.object, r.id);
    const prev = c.map.get(k);
    if (prev && prev !== "loading" && prev.row?.display_name === r.display_name) continue;
    c.map.set(k, { row: r });
    notify(c, k);
  }
}

function flush(client: RecordsClient, c: Cache) {
  const queue = c.queue;
  c.queue = new Map();
  c.scheduled = false;
  for (const [object, ids] of queue) {
    const list = [...ids];
    const settle = (rows: RecordRow[], wanted: string[]) => {
      const found = new Map(rows.map((r) => [r.id, r]));
      for (const id of wanted) {
        c.map.set(keyOf(object, id), { row: found.get(id) ?? null });
        notify(c, keyOf(object, id));
      }
    };
    // The server takes at most 100 ids in one condition.
    for (let i = 0; i < list.length; i += MAX_IN) {
      const part = list.slice(i, i + MAX_IN);
      client.query(object, { filter: { field: "id", op: "in", value: part }, limit: part.length }).then(
        (page) => settle(page.data, part),
        () => settle([], part),
      );
    }
  }
}

function request(client: RecordsClient, object: string, id: string) {
  const c = cacheOf(client);
  const k = keyOf(object, id);
  if (c.map.has(k)) return;
  c.map.set(k, "loading");
  (c.queue.get(object) ?? c.queue.set(object, new Set()).get(object)!).add(id);
  if (!c.scheduled) {
    c.scheduled = true;
    queueMicrotask(() => flush(client, c));
  }
}

/** The linked record: undefined while loading, null if it is gone. */
export function useRecordRef(client: RecordsClient, object: string | undefined, id: unknown): RecordRow | null | undefined {
  const ok = !!object && typeof id === "string" && id !== "";
  const k = ok ? keyOf(object, id) : "";
  const c = cacheOf(client);
  const subscribe = useCallback(
    (fn: () => void) => {
      if (!ok) return () => {};
      const set = c.subs.get(k) ?? c.subs.set(k, new Set()).get(k)!;
      set.add(fn);
      return () => void set.delete(fn);
    },
    [c, k, ok],
  );
  const entry = useSyncExternalStore(subscribe, () => (ok ? c.map.get(k) : undefined));
  useEffect(() => {
    if (ok) request(client, object, id as string);
  }, [client, ok, object, id]);
  return !entry || entry === "loading" ? undefined : entry.row;
}

/** Names for several record ids at once (filter chips). Returns id -> display name for the ones that have arrived. */
export function useRecordNames(client: RecordsClient, pairs: { object: string; id: string }[]): Record<string, string> {
  const c = cacheOf(client);
  const list = pairs.map((p) => keyOf(p.object, p.id)).join(",");
  const read = useCallback(() => {
    const out: Record<string, string> = {};
    for (const p of pairs) {
      const e = c.map.get(keyOf(p.object, p.id));
      if (e && e !== "loading" && e.row) out[p.id] = e.row.display_name;
    }
    return JSON.stringify(out);
    // `list` is the identity of `pairs`
  }, [c, list]);
  const subscribe = useCallback(
    (fn: () => void) => {
      c.all.add(fn);
      return () => void c.all.delete(fn);
    },
    [c],
  );
  const snapshot = useSyncExternalStore(subscribe, read);
  useEffect(() => {
    for (const p of pairs) request(client, p.object, p.id);
  }, [client, list]);
  return useMemo(() => JSON.parse(snapshot) as Record<string, string>, [snapshot]);
}
