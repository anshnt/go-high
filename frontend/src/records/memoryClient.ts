// An in-memory records backend: seeded demo data, and it really evaluates filters, sorts, searches and pages with
// cursors, validates writes and keeps a timeline, so the screens behave as they will against the API.
// Nothing here touches the network. Rows are copy-on-write: a returned row is never changed afterwards.
import type { RecordsClient } from "./client.ts";
import { RecordsError } from "./errors.ts";
import { compareKeys, decodeCursor, dirsOf, encodeCursor, evaluate, matchesQuery, type Env, type SortKey } from "./engine.ts";
import { canonical } from "./filter.ts";
import { isMoney } from "./format.ts";
import { isComputed, readValue, valueType } from "./schema.ts";
import { mulberry32, seedDataset, type Dataset } from "./seed.ts";
import type { FieldDef, NewRecord, Page, QueryParams, RecordRow, SavedView, Tag, TimelineEvent, UserRef } from "./types.ts";
import { isEmptyValue, validateValue } from "./validate.ts";

export type MemoryOptions = {
  dataset?: Dataset;
  now?: () => number;
  /** Milliseconds every call waits, so loading states are real. 0 in tests. */
  latency?: number;
  /** The signed-in user: owner of new records and views. */
  me?: () => UserRef | null;
};

const PREFIX: Record<string, string> = { contact: "ct", company: "co", deal: "dl" };
const TEXTUAL = ["text", "long_text", "email", "phone", "url"];
const PAGE = 25;

const hash = (s: string) => {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  return h >>> 0;
};

export function createMemoryClient(opts: MemoryOptions = {}): RecordsClient {
  const now = opts.now ?? Date.now;
  const ds = opts.dataset ?? seedDataset({ anchor: now() });
  const me = opts.me ?? (() => null);
  const wait = () => (opts.latency ? new Promise<void>((r) => setTimeout(r, opts.latency)) : Promise.resolve());

  const rows = new Map<string, Map<string, RecordRow>>(ds.objects.map((o) => [o.key, new Map()]));
  const objectOf = new Map<string, string>();
  const original = new Map<string, RecordRow>();
  const counter = new Map<string, number>();
  for (const r of ds.records) {
    rows.get(r.object)!.set(r.id, r);
    objectOf.set(r.id, r.object);
    original.set(r.id, r);
    counter.set(r.object, Math.max(counter.get(r.object) ?? 0, Number(r.id.split("_")[1]) || 0));
  }
  const trash = new Set<string>();
  const events = new Map<string, TimelineEvent[]>();
  const history = new Map<string, TimelineEvent[]>();
  const views: SavedView[] = ds.views.map((v) => ({ ...v }));
  const users = ds.users;
  let version = 0;
  let seq = 0;

  const fieldsOf = (object: string) => ds.fields[object] ?? [];
  const fieldDef = (object: string, key: string): FieldDef | undefined => fieldsOf(object).find((f) => f.key === key);
  const objectDef = (key: string) => {
    const o = ds.objects.find((x) => x.key === key);
    if (!o) throw new RecordsError(404, `There is no object "${key}".`);
    return o;
  };
  const notFound = () => new RecordsError(404, "That record was not found. It may have been deleted.");
  const rowOf = (object: string, id: string) => {
    const r = rows.get(object)?.get(id);
    if (!r || trash.has(id)) throw notFound();
    return r;
  };
  const locate = (id: string) => {
    const o = objectOf.get(id);
    if (!o) throw notFound();
    return rowOf(o, id);
  };
  const tagById = (id: string): Tag => {
    const t = ds.tags.find((x) => x.id === id);
    if (!t) throw new RecordsError(404, "That tag does not exist.");
    return t;
  };
  const put = (rec: RecordRow) => {
    rows.get(rec.object)!.set(rec.id, rec);
    version++;
  };
  const stamp = () => new Date(now()).toISOString();
  const log = (rec: RecordRow, e: Omit<TimelineEvent, "id" | "record_id" | "at" | "actor_id">) => {
    const list = events.get(rec.id) ?? [];
    list.push({ id: `ev_live_${++seq}`, record_id: rec.id, at: stamp(), actor_id: me()?.id ?? null, ...e });
    events.set(rec.id, list);
  };

  // ---- links and computed values ----

  let linkVersion = -1;
  let links = new Map<string, RecordRow[]>();
  const reverse = (object: string, fieldKey: string, targetId: string) => {
    if (linkVersion !== version) {
      links = new Map();
      for (const o of ds.objects)
        for (const f of fieldsOf(o.key).filter((x) => x.type === "record" && !x.archived))
          for (const r of rows.get(o.key)!.values()) {
            const t = r.values[f.key];
            if (typeof t !== "string" || trash.has(r.id)) continue;
            const k = `${o.key}.${f.key}>${t}`;
            const list = links.get(k);
            if (list) list.push(r);
            else links.set(k, [r]);
          }
      linkVersion = version;
    }
    return links.get(`${object}.${fieldKey}>${targetId}`) ?? [];
  };

  const linked = (rec: RecordRow, segment: string): RecordRow[] => {
    const fwd = fieldDef(rec.object, segment);
    if (fwd?.type === "record") {
      const id = rec.values[segment];
      const t = typeof id === "string" && !trash.has(id) ? rows.get(fwd.options.object ?? "")?.get(id) : undefined;
      return t ? [t] : [];
    }
    if (!rows.has(segment)) throw new RecordsError(400, `There is no association "${segment}".`);
    return fieldsOf(segment)
      .filter((f) => f.type === "record" && f.options.object === rec.object && !f.archived)
      .flatMap((f) => reverse(segment, f.key, rec.id));
  };

  // Formulas and rollups, computed on read as ADR 0002 says. The API computes its own.
  const COMPUTED: Record<string, (rec: RecordRow) => unknown> = {
    "company.contacts": (rec) => reverse("contact", "company", rec.id).length,
    "company.open_value": (rec) => ({
      amount: reverse("deal", "company", rec.id).reduce((n, d) => {
        const m = d.values.amount;
        const open = d.values.stage !== "won" && d.values.stage !== "lost";
        return open && isMoney(m) && m.currency === "USD" ? n + m.amount : n;
      }, 0),
      currency: "USD",
    }),
    "deal.weighted": (rec) => {
      const m = rec.values.amount;
      const p = fieldDef("deal", "stage")?.options.choices?.find((c) => c.id === rec.values.stage)?.probability ?? 0;
      return isMoney(m) ? { amount: Math.round(m.amount * p), currency: m.currency } : undefined;
    },
  };
  const value = (rec: RecordRow, key: string): unknown => {
    const f = fieldDef(rec.object, key);
    return f && isComputed(f) ? COMPUTED[`${rec.object}.${key}`]?.(rec) : readValue(rec, key);
  };
  const toRow = (rec: RecordRow): RecordRow => {
    const extra: Record<string, unknown> = {};
    for (const f of fieldsOf(rec.object)) if (isComputed(f)) extra[f.key] = value(rec, f.key);
    return Object.keys(extra).length ? { ...rec, values: { ...rec.values, ...extra } } : rec;
  };

  // ---- search and order ----

  const blobs = new WeakMap<RecordRow, string>();
  const blob = (rec: RecordRow) => {
    let b = blobs.get(rec);
    if (b === undefined) {
      const parts = [rec.display_name, ...rec.tags.map((t) => t.name)];
      for (const [k, v] of Object.entries(rec.values)) {
        const f = fieldDef(rec.object, k);
        if (f && typeof v === "string" && TEXTUAL.includes(valueType(f))) parts.push(v, v.replace(/\D/g, ""));
      }
      b = parts.join(" ").toLowerCase();
      blobs.set(rec, b);
    }
    return b;
  };

  const sortKey = (rec: RecordRow, key: string): SortKey => {
    const f = fieldDef(rec.object, key) ?? (key === "display_name" || key === "id" ? ({ type: "text", options: {}, label: key } as FieldDef) : undefined);
    if (!f) throw new RecordsError(400, `There is no field "${key}".`);
    const t = valueType(f);
    const v = value(rec, key);
    if (t === "boolean") return v ? 1 : 0;
    if (isEmptyValue(v)) return null;
    switch (t) {
      case "number":
        return typeof v === "number" ? v : null;
      case "money":
        return isMoney(v) ? v.amount : null;
      case "date":
      case "datetime": {
        const p = Date.parse(String(v));
        return Number.isNaN(p) ? null : p;
      }
      case "select":
      case "stage": {
        const i = f.options.choices?.findIndex((c) => c.id === v) ?? -1;
        return i < 0 ? null : i;
      }
      case "user":
        return users.find((u) => u.id === v)?.name ?? null;
      case "multi_select":
      case "record":
      case "long_text":
        throw new RecordsError(400, `${f.label} cannot be sorted.`);
      default:
        return String(v);
    }
  };

  // ---- writes ----

  const fail = (errors: Record<string, string>): never => {
    throw new RecordsError(422, Object.values(errors)[0] ?? "Some details need fixing.", errors);
  };

  /** The one validator for create and update; `partial` skips fields that are not being written. */
  const check = (object: string, values: Record<string, unknown>, partial: boolean) => {
    const errors: Record<string, string> = {};
    const defs = fieldsOf(object).filter((f) => !f.archived && !f.rules.read_only && f.key !== "owner_id");
    for (const key of Object.keys(values)) if (!defs.some((f) => f.key === key)) errors[key] = `There is no field "${key}".`;
    for (const f of defs) {
      if (isComputed(f) ? !(f.key in values) : partial && !(f.key in values)) continue;
      const msg = validateValue(f, values[f.key]);
      if (msg) errors[f.key] = msg;
    }
    if (Object.keys(errors).length) fail(errors);
  };

  // A stage exit rule, enforced here the way the pipeline tables will enforce it.
  const exitRules = (object: string, values: Record<string, unknown>) => {
    if (object === "deal" && values.stage === "won" && !values.close_date) fail({ stage: "A won deal needs a close date. Add one first.", close_date: "Add a close date to mark this deal won." });
  };

  const known = (ownerId: unknown) => {
    if (ownerId !== null && ownerId !== undefined && ![...users, me()].some((u) => u && u.id === ownerId)) fail({ owner_id: "That person is not in this workspace." });
  };

  const ownsView = (v: SavedView) => {
    if (v.owner_id && v.owner_id !== me()?.id) throw new RecordsError(403, "Only the person who made this view can change it.");
  };

  // ---- seeded history for the timeline ----

  const synth = (rec: RecordRow): TimelineEvent[] => {
    const rng = mulberry32(hash(rec.id));
    const created = Date.parse(rec.created_at);
    const updated = Date.parse(rec.updated_at);
    const out: TimelineEvent[] = [{ id: `ev_${rec.id}_0`, record_id: rec.id, at: rec.created_at, actor_id: rec.owner_id, type: "created" }];
    const span = updated - created;
    const at = (n: number, of: number) => new Date(created + (span * (n + 1)) / (of + 1)).toISOString();
    if (span > 3_600_000) {
      const pool = fieldsOf(rec.object).filter((f) => !f.archived && !f.rules.read_only && ["select", "stage", "number", "money"].includes(f.type) && rec.values[f.key] !== undefined);
      const chosen = pool.filter(() => rng() < 0.45).slice(0, 2);
      chosen.forEach((f, i) => {
        const to = rec.values[f.key];
        let from: unknown = null;
        if (f.type === "select" || f.type === "stage") {
          const c = f.options.choices ?? [];
          const idx = c.findIndex((x) => x.id === to);
          from = c[idx > 0 ? idx - 1 : Math.min(c.length - 1, idx + 1)]?.id ?? null;
        } else if (f.type === "number" && typeof to === "number") from = Math.max(0, to - 5 - Math.floor(rng() * 20));
        else if (isMoney(to)) from = { amount: Math.round(to.amount * 0.9), currency: to.currency };
        out.push({ id: `ev_${rec.id}_${i + 1}`, record_id: rec.id, at: at(i, chosen.length + rec.tags.length), actor_id: users[Math.floor(rng() * users.length)]!.id, type: "updated", changes: [{ field: f.key, from, to }] });
      });
      rec.tags.forEach((tag, i) => out.push({ id: `ev_${rec.id}_t${i}`, record_id: rec.id, at: at(chosen.length + i, chosen.length + rec.tags.length), actor_id: users[Math.floor(rng() * users.length)]!.id, type: "tagged", tag }));
    }
    return out;
  };

  const retag = async (ids: string[], tagId: string, add: boolean) => {
    await wait();
    const tag = tagById(tagId);
    const recs = ids.map(locate);
    for (const r of recs) {
      if (r.tags.some((t) => t.id === tagId) === add) continue;
      const next = { ...r, tags: add ? [...r.tags, tag] : r.tags.filter((t) => t.id !== tagId) };
      put(next);
      log(next, { type: add ? "tagged" : "untagged", tag });
    }
  };

  return {
    async listObjects() {
      await wait();
      return ds.objects;
    },

    async listFields(object) {
      await wait();
      objectDef(object);
      return fieldsOf(object);
    },

    async query(object, p: QueryParams = {}): Promise<Page<RecordRow>> {
      await wait();
      objectDef(object);
      const sort = p.sort?.length ? p.sort : [{ field: "updated_at", dir: "desc" as const }];
      const env: Env = { now: now(), field: fieldDef, value, linked };
      const q = p.q?.trim();
      const hits: { r: RecordRow; k: SortKey[] }[] = [];
      for (const r of rows.get(object)!.values()) {
        if (trash.has(r.id) || (q && !matchesQuery(blob(r), q)) || !evaluate(p.filter, r, env)) continue;
        hits.push({ r, k: sort.map((s) => sortKey(r, s.field)) });
      }
      const dirs = dirsOf(sort);
      hits.sort((a, b) => compareKeys(a.k, b.k, dirs, a.r.id, b.r.id));

      // Keyset paging: the cursor is the last row's sort values and id, so rows added or removed between
      // pages never cause repeats or gaps among the rows that come after it.
      let start = 0;
      if (p.cursor) {
        const c = decodeCursor(p.cursor);
        if (c.k.length !== sort.length) throw new RecordsError(400, "That page link does not match this sort. Reload the list.");
        let lo = 0;
        let hi = hits.length;
        while (lo < hi) {
          const mid = (lo + hi) >> 1;
          if (compareKeys(hits[mid]!.k, c.k, dirs, hits[mid]!.r.id, c.id) <= 0) lo = mid + 1;
          else hi = mid;
        }
        start = lo;
      }
      const limit = Math.min(Math.max(p.limit ?? 50, 1), 200);
      const slice = hits.slice(start, start + limit);
      const last = slice[slice.length - 1];
      return {
        data: slice.map((h) => toRow(h.r)),
        next_cursor: last && start + limit < hits.length ? encodeCursor({ k: last.k, id: last.r.id }) : null,
        total: hits.length,
      };
    },

    async get(object, id) {
      await wait();
      objectDef(object);
      return toRow(rowOf(object, id));
    },

    async create(object, input: NewRecord) {
      await wait();
      const def = objectDef(object);
      const values = Object.fromEntries(Object.entries(input.values).filter(([, v]) => !isEmptyValue(v)));
      check(object, values, false);
      exitRules(object, values);
      known(input.owner_id);
      const n = (counter.get(object) ?? 0) + 1;
      counter.set(object, n);
      const t = stamp();
      const rec: RecordRow = {
        id: `${PREFIX[object] ?? "rec"}_${String(n).padStart(4, "0")}`,
        object,
        display_name: String(values[def.primary_field] ?? ""),
        values,
        owner_id: input.owner_id === undefined ? (me()?.id ?? null) : input.owner_id,
        created_at: t,
        updated_at: t,
        tags: (input.tags ?? []).map(tagById),
      };
      objectOf.set(rec.id, object);
      put(rec);
      log(rec, { type: "created" });
      return toRow(rec);
    },

    async update(object, id, changes) {
      await wait();
      const def = objectDef(object);
      const cur = rowOf(object, id);
      const { owner_id, ...vals } = changes;
      check(object, vals, true);
      known(owner_id);
      const next = { ...cur.values };
      const diffs: NonNullable<TimelineEvent["changes"]> = [];
      for (const [k, raw] of Object.entries(vals)) {
        const nv = isEmptyValue(raw) ? undefined : raw;
        if (canonical(cur.values[k] ?? null) === canonical(nv ?? null)) continue;
        diffs.push({ field: k, from: cur.values[k] ?? null, to: nv ?? null });
        if (nv === undefined) delete next[k];
        else next[k] = nv;
      }
      const ownerChanged = owner_id !== undefined && owner_id !== cur.owner_id;
      if (ownerChanged) diffs.push({ field: "owner_id", from: cur.owner_id, to: owner_id ?? null });
      if (!diffs.length) return toRow(cur);
      exitRules(object, next);
      const rec: RecordRow = {
        ...cur,
        values: next,
        owner_id: ownerChanged ? ((owner_id as string | null) ?? null) : cur.owner_id,
        display_name: String(next[def.primary_field] ?? ""),
        updated_at: stamp(),
      };
      put(rec);
      log(rec, { type: "updated", changes: diffs });
      return toRow(rec);
    },

    async remove(object, ids) {
      await wait();
      for (const id of ids) rowOf(object, id);
      for (const id of ids) trash.add(id);
      version++;
    },

    async restore(object, ids) {
      await wait();
      for (const id of ids) if (!rows.get(object)?.has(id)) throw notFound();
      for (const id of ids) trash.delete(id);
      version++;
    },

    async timeline(recordId, cursor) {
      await wait();
      const rec = locate(recordId);
      let base = history.get(recordId);
      if (!base) {
        const orig = original.get(recordId);
        base = orig ? synth(orig) : [];
        history.set(recordId, base);
      }
      const all = [...base, ...(events.get(rec.id) ?? [])].sort((a, b) => (a.at === b.at ? (a.id < b.id ? 1 : -1) : a.at < b.at ? 1 : -1));
      let start = 0;
      if (cursor) {
        const c = decodeCursor(cursor);
        start = all.findIndex((e) => (e.at === c.k[0] ? e.id < c.id : e.at < String(c.k[0])));
        if (start < 0) start = all.length;
      }
      const data = all.slice(start, start + PAGE);
      const last = data[data.length - 1];
      return { data, next_cursor: last && start + PAGE < all.length ? encodeCursor({ k: [last.at], id: last.id }) : null, total: all.length };
    },

    async listViews(object) {
      await wait();
      return views.filter((v) => v.object === object).map((v) => ({ ...v }));
    },

    async saveView(input) {
      await wait();
      objectDef(input.object);
      if (!input.name.trim()) fail({ name: "Give the view a name." });
      const body = { object: input.object, name: input.name.trim(), filter: input.filter, columns: input.columns, sort: input.sort, shared: input.shared };
      if (input.id) {
        const i = views.findIndex((v) => v.id === input.id);
        if (i < 0) throw new RecordsError(404, "That view no longer exists.");
        ownsView(views[i]!);
        views[i] = { ...views[i]!, ...body };
        return { ...views[i]! };
      }
      const v: SavedView = { id: `v_${++seq}`, ...body, owner_id: me()?.id ?? null };
      views.push(v);
      return { ...v };
    },

    async deleteView(id) {
      await wait();
      const i = views.findIndex((v) => v.id === id);
      if (i < 0) throw new RecordsError(404, "That view no longer exists.");
      ownsView(views[i]!);
      views.splice(i, 1);
    },

    async listTags() {
      await wait();
      return ds.tags;
    },

    tag: (ids, tagId) => retag(ids, tagId, true),
    untag: (ids, tagId) => retag(ids, tagId, false),

    async listUsers() {
      await wait();
      const m = me();
      return m && !users.some((u) => u.id === m.id) ? [m, ...users] : users;
    },
  };
}
