// The records client over /api/v1 (ADR 0002 and the README's "Records and data model"). It turns the API's shapes into the
// ones the screens use (types.ts), the API's error envelope into RecordsError, and day filters on datetime fields into
// instants in the viewer's time zone. It talks through `Http` (lib/http.ts), so node can test it with a fake fetch.
import type { Http } from "../lib/http.ts";
import { queryString } from "../lib/http.ts";
import type { RecordsClient } from "./client.ts";
import { RecordsError } from "./errors.ts";
import { DISPLAY_NAME, valueType } from "./schema.ts";
import type {
  Choice,
  ColorName,
  FieldDef,
  FieldType,
  Filter,
  FilterCondition,
  LinkType,
  NewRecord,
  ObjectDef,
  Op,
  Page,
  QueryParams,
  RecordRow,
  SavedView,
  SortSpec,
  Tag,
  TimelineEvent,
  UserRef,
} from "./types.ts";

const MAX_BULK = 1000; // ids per bulk call, the API's limit
const TIMELINE_PAGE = 25;
const FALLBACK = "Something went wrong. Try again.";

// ---- what the API sends ----

type ApiRow = Omit<RecordRow, "tags"> & { tags?: { id: string; name: string; color: string | null }[] };
type ApiPage<T> = { data: T[]; next_cursor: string | null; total?: number };
type ApiObject = Omit<ObjectDef, "icon"> & { icon: string; archived_at: string | null };
type ApiField = Omit<FieldDef, "archived"> & { archived_at: string | null };
type ApiView = Omit<SavedView, "filter" | "sort"> & { filter: Record<string, unknown>; sort: string[] };
// Contacts, companies and deals always come first, in that order; custom objects follow by name.
const SYSTEM_ORDER = ["contact", "company", "deal"];
const objectOrder = (a: ObjectDef, b: ObjectDef) => {
  const rank = (o: ObjectDef) => (SYSTEM_ORDER.includes(o.key) ? SYSTEM_ORDER.indexOf(o.key) : SYSTEM_ORDER.length);
  return rank(a) - rank(b) || a.plural.localeCompare(b.plural);
};

export type ApiEvent = {
  id: number | string;
  type: string;
  occurred_at: string;
  actor: { type: string; id: string | null };
  data: Record<string, unknown>;
};
type ApiLinkType = { id: string; from_object: string; to_object: string; label: string; inverse_label: string };
type ApiStage = { id: string; name: string; kind: "open" | "won" | "lost"; probability: number; color: string | null };
export type ApiPipeline = { id: string; object: string; name: string; archived_at: string | null; stages: ApiStage[] };
type ApiMember = { user_id: string; name: string; email: string };

// ---- shapes ----

const COLORS = new Set<string>(["gray", "blue", "green", "amber", "orange", "red", "pink", "purple", "indigo", "teal"]);
/** A tag's color is free text on the server; the screens only know the theme's names. */
export const colorName = (c: unknown): ColorName => (typeof c === "string" && COLORS.has(c) ? (c as ColorName) : "gray");

const toTag = (t: { id: string; name: string; color: string | null }): Tag => ({ id: t.id, name: t.name, color: colorName(t.color) });

export const toRow = (r: ApiRow): RecordRow => ({
  id: r.id,
  object: r.object,
  display_name: r.display_name,
  values: r.values,
  owner_id: r.owner_id,
  created_at: r.created_at,
  updated_at: r.updated_at,
  tags: (r.tags ?? []).map(toTag),
});

/** The columns every record has next to its fields. The API lists only an object's own fields; the owner can be changed, the dates cannot. */
const SYSTEM_COLUMNS: Omit<FieldDef, "position">[] = [
  { key: "owner_id", label: "Owner", type: "user", options: {}, rules: {}, is_system: true, archived: false },
  { key: "created_at", label: "Created", type: "datetime", options: {}, rules: { read_only: true }, is_system: true, archived: false },
  { key: "updated_at", label: "Updated", type: "datetime", options: {}, rules: { read_only: true }, is_system: true, archived: false },
];

/** An object's name is derived from several fields (a contact's first and last name): lists sort and filter by that derived column. */
const NAME_COLUMN: Omit<FieldDef, "position"> = { key: DISPLAY_NAME, label: "Name", type: "text", options: {}, rules: { read_only: true }, is_system: true, archived: false };

/**
 * The stages a stage field offers: the stages of the object's pipelines, in order, live pipelines first. The API keeps a
 * stage field's options empty (a stage is a row of a pipeline), so the choices come from the pipelines. The pipeline's name
 * is added only where there is a choice of pipelines, and archived ones say so (they hold deals but take no new ones).
 * `first` is where a new record starts: the first open stage of the first live pipeline, as the server decides.
 */
export function stageChoices(pipelines: ApiPipeline[], object: string): { choices: Choice[]; first?: string } {
  const mine = pipelines.filter((p) => p.object === object).sort((a, b) => Number(a.archived_at !== null) - Number(b.archived_at !== null));
  const several = mine.filter((p) => p.archived_at === null).length > 1;
  const choices = mine.flatMap((p) =>
    p.stages.map((st): Choice => ({ id: st.id, label: p.archived_at ? `${p.name} (archived): ${st.name}` : several ? `${p.name}: ${st.name}` : st.name, color: colorName(st.color), probability: st.probability / 100 })),
  );
  const live = mine.find((p) => p.archived_at === null);
  return { choices, first: live?.stages.find((st) => st.kind === "open")?.id };
}

export function toFields(fields: ApiField[], object: ObjectDef, pipelines: ApiPipeline[] = []): FieldDef[] {
  const stages = stageChoices(pipelines, object.key);
  const own: FieldDef[] = fields.map(({ archived_at, ...f }) => ({
    ...f,
    archived: archived_at !== null,
    // a stage is always set (a new deal starts in the first open stage), so it is required and the pickers do not clear it
    ...(f.type === "stage" ? { options: { ...f.options, choices: stages.choices, default: stages.first }, rules: { ...f.rules, required: true } } : {}),
  }));
  const last = own.reduce((n, f) => Math.max(n, f.position), 0);
  // the derived name goes first, so it sorts and filters as the list's name column; the columns come after the fields
  const name = object.primary_fields.length === 1 ? [] : [{ ...NAME_COLUMN, position: -1 }];
  return [...name, ...own, ...SYSTEM_COLUMNS.map((f, i) => ({ ...f, position: last + 1 + i }))];
}

export const sortParam = (s: SortSpec) => `${s.dir === "desc" ? "-" : ""}${s.field}`;
export const parseSort = (s: string): SortSpec => ({ field: s.replace(/^-/, ""), dir: s.startsWith("-") ? "desc" : "asc" });

const toView = (v: ApiView): SavedView => ({
  id: v.id,
  object: v.object,
  name: v.name,
  filter: v.filter && Object.keys(v.filter).length ? (v.filter as Filter) : null,
  columns: v.columns,
  sort: v.sort.map(parseSort),
  shared: v.shared,
  owner_id: v.owner_id,
});

// ---- errors ----

/** The API's field paths are `values.email`; the screens key their inline messages by the field. */
const fieldKey = (path: string) => (path.startsWith("values.") ? path.slice("values.".length) : path);

/** Turns what lib/http throws (an ApiError, matched by name so this file needs no import of it) into a RecordsError. */
export function asRecordsError(e: unknown): unknown {
  const x = e as { name?: unknown; status?: unknown; message?: unknown; fields?: Record<string, string> } | null;
  if (x?.name !== "ApiError") return e;
  const fields = x.fields && Object.keys(x.fields).length ? Object.fromEntries(Object.entries(x.fields).map(([k, v]) => [fieldKey(k), v])) : undefined;
  const message = fields ? Object.values(fields)[0]! : typeof x.message === "string" ? x.message : FALLBACK;
  return new RecordsError(typeof x.status === "number" ? x.status : 0, message, fields);
}

async function call<T>(run: () => Promise<T>): Promise<T> {
  try {
    return await run();
  } catch (e) {
    throw asRecordsError(e);
  }
}

// ---- filters: a day on a datetime field is a day where the viewer is ----

const DAY = /^\d{4}-\d{2}-\d{2}$/;
const isDay = (v: unknown): v is string => typeof v === "string" && DAY.test(v);
/** Midnight of a calendar day (plus `plus` days) in the viewer's time zone, as an instant the API reads. */
const localMidnight = (day: string, plus = 0) => {
  const [y, m, d] = day.split("-").map(Number) as [number, number, number];
  return new Date(y, m - 1, d + plus).toISOString();
};

/** "is on Oct 17" means from that day's first instant to the next day's, where the viewer is; null when the operand is not a day. */
function dayCondition(c: FilterCondition): unknown {
  const at = (op: Op, value: string): FilterCondition => ({ field: c.field, op, value });
  const a = c.value;
  switch (c.op) {
    case "is":
    case "is_not": {
      if (!isDay(a)) return null;
      const on = { and: [at("gte", localMidnight(a)), at("lt", localMidnight(a, 1))] };
      return c.op === "is" ? on : { not: on };
    }
    case "gt":
      return isDay(a) ? at("gte", localMidnight(a, 1)) : null;
    case "gte":
      return isDay(a) ? at("gte", localMidnight(a)) : null;
    case "lt":
      return isDay(a) ? at("lt", localMidnight(a)) : null;
    case "lte":
      return isDay(a) ? at("lt", localMidnight(a, 1)) : null;
    case "between":
      return Array.isArray(a) && isDay(a[0]) && isDay(a[1]) ? { and: [at("gte", localMidnight(a[0])), at("lt", localMidnight(a[1], 1))] } : null;
    default:
      return null; // within_last and older_than are spans from now, whatever the zone
  }
}

/** The filter as the API reads it. `typeOf` gives the type of a field path ("created_at", "company.created_at"), undefined when unknown. */
export function convertFilter(f: Filter, typeOf: (path: string) => FieldType | undefined): unknown {
  if ("and" in f) return { and: f.and.map((x) => convertFilter(x, typeOf)) };
  if ("or" in f) return { or: f.or.map((x) => convertFilter(x, typeOf)) };
  if ("tag" in f) return f;
  return (typeOf(f.field) === "datetime" && dayCondition(f)) || f;
}

const conditionsOf = (f: Filter, out: FilterCondition[] = []): FilterCondition[] => {
  if ("and" in f) f.and.forEach((x) => conditionsOf(x, out));
  else if ("or" in f) f.or.forEach((x) => conditionsOf(x, out));
  else if ("field" in f) out.push(f);
  return out;
};

// ---- the timeline: the engine's events as the lines the screen shows ----

/** One engine event as a timeline line; null for events the screen has no line for (a delete, a merge, ...). */
export function toTimelineEvent(e: ApiEvent, recordId: string, links: ApiLinkType[], tags: Map<string, Tag>): TimelineEvent | null {
  const base = { id: String(e.id), record_id: recordId, at: e.occurred_at, actor_id: e.actor?.type === "user" ? e.actor.id : null };
  const d = e.data;
  switch (e.type) {
    case "record.created":
      return { ...base, type: "created" };
    case "record.updated": {
      const changes = Object.entries((d.changes ?? {}) as Record<string, { old?: unknown; new?: unknown }>).map(([field, c]) => ({ field, from: c.old ?? null, to: c.new ?? null }));
      return changes.length ? { ...base, type: "updated", changes } : null;
    }
    case "tag.added":
    case "tag.removed": {
      const id = String(d.tag_id);
      return { ...base, type: e.type === "tag.added" ? "tagged" : "untagged", tag: tags.get(id) ?? { id, name: String(d.name ?? "A tag"), color: "gray" } };
    }
    case "association.created":
    case "association.deleted": {
      const t = links.find((x) => x.id === d.type_id);
      if (!t) return null;
      const out = d.from_record_id === recordId; // this record is the link's from side
      const other = String(out ? d.to_record_id : d.from_record_id);
      const label = String(out ? d.label : d.inverse_label);
      return { ...base, type: e.type === "association.created" ? "linked" : "unlinked", link: { label, object: out ? t.to_object : t.from_object, id: other } };
    }
    default:
      return null;
  }
}

// ---- the client ----

const enc = encodeURIComponent;
const chunks = <T>(list: T[], size: number): T[][] => Array.from({ length: Math.ceil(list.length / size) }, (_, i) => list.slice(i * size, (i + 1) * size));

export function createApiClient(http: Http): RecordsClient {
  // What rarely changes in a session is read once. A failed read is forgotten, so a retry asks again.
  const once = <T>(load: () => Promise<T>) => {
    let p: Promise<T> | undefined;
    return () => (p ??= load().catch((e) => ((p = undefined), Promise.reject(e))));
  };
  const keyed = <T>(load: (key: string) => Promise<T>) => {
    const m = new Map<string, Promise<T>>();
    return (key: string) => {
      let p = m.get(key);
      if (!p) m.set(key, (p = load(key).catch((e) => (m.delete(key), Promise.reject(e)))));
      return p;
    };
  };

  /** Every page of a list endpoint. */
  async function all<T>(path: string, params: Record<string, unknown> = {}): Promise<T[]> {
    const out: T[] = [];
    let cursor: string | null = null;
    for (let i = 0; i < 100; i++) {
      const page: ApiPage<T> = await http.get(`${path}${queryString({ ...params, limit: 200, cursor })}`);
      out.push(...page.data);
      if (!page.next_cursor) break;
      cursor = page.next_cursor;
    }
    return out;
  }

  const pipelines = once(() =>
    call(async () => {
      const [live, archived] = await Promise.all([http.get<ApiPage<ApiPipeline>>("/api/v1/pipelines"), http.get<ApiPage<ApiPipeline>>("/api/v1/pipelines?archived=true")]);
      return [...live.data, ...archived.data];
    }),
  );
  const objects = once(() => call(async () => (await all<ApiObject>("/api/v1/objects")).map(({ archived_at: _gone, ...o }): ObjectDef => o)));
  const fieldsOf = keyed((object: string) =>
    call(async () => {
      const [def, page] = await Promise.all([objects().then((list) => list.find((o) => o.key === object)), http.get<ApiPage<ApiField>>(`/api/v1/objects/${enc(object)}/fields`)]);
      if (!def) throw new RecordsError(404, "Object not found");
      return toFields(page.data, def, page.data.some((f) => f.type === "stage") ? await pipelines() : []);
    }),
  );
  const tags = once(() => call(async () => (await all<{ id: string; name: string; color: string | null }>("/api/v1/tags")).map(toTag)));
  const linkRows = once(() => call(async () => (await http.get<ApiPage<ApiLinkType>>("/api/v1/association-types")).data));

  /** The filter for the API, with day conditions on datetime fields turned into instants. */
  async function apiFilter(object: string, filter: Filter): Promise<unknown> {
    const heads = new Set([object, ...conditionsOf(filter).flatMap((c) => (c.field.includes(".") ? [c.field.slice(0, c.field.indexOf("."))] : []))]);
    const types = new Map<string, Map<string, FieldType>>();
    for (const head of heads) {
      try {
        types.set(head, new Map((await fieldsOf(head)).map((f) => [f.key, valueType(f)])));
      } catch {
        /* an unknown object: its conditions go as they are, and the API says what is wrong with them */
      }
    }
    return convertFilter(filter, (path) => {
      const dot = path.indexOf(".");
      return dot > 0 ? types.get(path.slice(0, dot))?.get(path.slice(dot + 1)) : types.get(object)?.get(path);
    });
  }

  const row = (object: string, id: string) => `/api/v1/objects/${enc(object)}/records/${enc(id)}`;

  const bulk = async (path: string, ids: string[], body: (part: string[]) => unknown) => {
    // ponytail: more than 1000 ids go in several calls, each all or nothing; a failure in a later one leaves the earlier ones done.
    for (const part of chunks(ids, MAX_BULK)) await call(() => http.post(path, body(part)));
  };

  return {
    listObjects: () => objects().then((list) => [...list].sort(objectOrder).map((o) => ({ ...o }))),
    listFields: (object) => fieldsOf(object).then((list) => list.map((f) => ({ ...f }))),

    async query(object, p: QueryParams = {}): Promise<Page<RecordRow>> {
      const filter = p.filter ? await apiFilter(object, p.filter) : {};
      const body = {
        filter,
        sort: (p.sort ?? []).map(sortParam),
        q: p.q || undefined,
        limit: p.limit ?? 50,
        cursor: p.cursor || undefined,
        include: ["tags"],
        count: !p.cursor, // the total does not change from page to page: ask for it once
      };
      const page = await call(() => http.post<ApiPage<ApiRow>>(`/api/v1/objects/${enc(object)}/records/query`, body));
      return { data: page.data.map(toRow), next_cursor: page.next_cursor, total: page.total };
    },

    async get(object, id) {
      return toRow(await call(() => http.get<ApiRow>(`${row(object, id)}${queryString({ include: "tags" })}`)));
    },

    async create(object, input: NewRecord) {
      // no owner given: the server decides (the creator's, or unassigned when the role sees unassigned records)
      const body = { values: input.values, ...(input.owner_id === undefined ? {} : { owner_id: input.owner_id }) };
      const made = await call(() => http.post<ApiRow>(`/api/v1/objects/${enc(object)}/records${queryString({ include: "tags" })}`, body));
      for (const tag of input.tags ?? []) await call(() => http.post(`/api/v1/records/${enc(made.id)}/tags`, { add: [tag] }));
      return toRow(input.tags?.length ? await call(() => http.get<ApiRow>(`${row(object, made.id)}${queryString({ include: "tags" })}`)) : made);
    },

    async update(object, id, changes) {
      const { owner_id, ...values } = changes;
      const body = { values, ...("owner_id" in changes ? { owner_id: owner_id ?? null } : {}) };
      return toRow(await call(() => http.patch<ApiRow>(`${row(object, id)}${queryString({ include: "tags" })}`, body)));
    },

    updateMany: (object, ids, changes) => {
      const { owner_id, ...values } = changes;
      const extra = "owner_id" in changes ? { owner_id: owner_id ?? null } : {};
      return bulk(`/api/v1/objects/${enc(object)}/records/update`, ids, (part) => ({ ids: part, values, ...extra }));
    },

    remove: (object, ids) => bulk(`/api/v1/objects/${enc(object)}/records/delete`, ids, (part) => ({ ids: part })),
    restore: (object, ids) => bulk(`/api/v1/objects/${enc(object)}/records/restore`, ids, (part) => ({ ids: part })),

    async timeline(recordId, cursor) {
      const [page, links, known] = await Promise.all([
        call(() => http.get<ApiPage<ApiEvent>>(`/api/v1/records/${enc(recordId)}/timeline${queryString({ limit: TIMELINE_PAGE, cursor })}`)),
        linkRows(),
        tags().then((list) => new Map(list.map((t) => [t.id, t]))),
      ]);
      return { data: page.data.flatMap((e) => toTimelineEvent(e, recordId, links, known) ?? []), next_cursor: page.next_cursor };
    },

    async listViews(object) {
      // the API lists the newest first; the tabs read oldest first, so a view you save lands at the end and stays there
      return (await call(() => all<ApiView>("/api/v1/views", { object }))).map(toView).reverse();
    },

    async saveView(view) {
      const body = { name: view.name, filter: view.filter ?? {}, columns: view.columns, sort: view.sort.map(sortParam), shared: view.shared };
      const saved = await call(() => (view.id ? http.patch<ApiView>(`/api/v1/views/${enc(view.id)}`, body) : http.post<ApiView>("/api/v1/views", { object: view.object, ...body })));
      return toView(saved);
    },

    deleteView: (id) => call(() => http.del(`/api/v1/views/${enc(id)}`)),

    listTags: () => tags().then((list) => list.map((t) => ({ ...t }))),
    tag: (ids, tagId) => bulk("/api/v1/records/tags", ids, (part) => ({ record_ids: part, add: [tagId] })),
    untag: (ids, tagId) => bulk("/api/v1/records/tags", ids, (part) => ({ record_ids: part, remove: [tagId] })),

    async listUsers() {
      try {
        const page = await call(() => http.get<ApiPage<ApiMember>>("/api/v1/members"));
        return page.data.map((m): UserRef => ({ id: m.user_id, name: m.name, email: m.email }));
      } catch (e) {
        if (e instanceof RecordsError && e.status === 403) return []; // a role that may not see people still works with records: owners show as unknown
        throw e;
      }
    },

    async listLinkTypes(): Promise<LinkType[]> {
      return (await linkRows()).map((t) => ({ from: t.from_object, to: t.to_object, label: t.label, inverse_label: t.inverse_label }));
    },
  };
}
