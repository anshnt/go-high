// The pipeline backend of the public demo: pipelines, boards, moves with exit rules, layouts and the forecast, kept in
// memory on top of the demo's records client (the deals are its records, so a move shows in the Deals list and the
// record beside the board). Nothing here touches the network. It does what the server does, in plain TypeScript:
// positions between neighbours, exit rules judged on the stage a deal leaves, a lost reason for a lost stage, and the
// weighted, commit and best case figures by month or quarter, currency and owner.
import { evaluate, type Env } from "../records/engine.ts";
import { RecordsError } from "../records/errors.ts";
import { colorName } from "../records/apiClient.ts";
import type { RecordsClient } from "../records/client.ts";
import { isMoney, parseDay, toDay } from "../records/format.ts";
import { isEmptyValue } from "../records/validate.ts";
import { readValue } from "../records/schema.ts";
import { isGroup, groupItems } from "../records/filter.ts";
import type { FieldDef, Filter, RecordRow } from "../records/types.ts";
import { weigh } from "./board.ts";
import { labelOf } from "./forecast.ts";
import { DEFAULT_CARD_FIELDS, type Board, type BoardStage, type Card, type Forecast, type ForecastPeriod, type Layout, type Metrics, type Period, type Pipeline, type PipelineClient, type Stage, type StageKind, type StagePatch, type StageSpec, type Sums } from "./types.ts";

const DAY = 86_400_000;
const FIXED: Record<string, number> = { won: 100, lost: 0 };
const EMPTY: Filter = { and: [] };
const has = (field: string): Filter => ({ field, op: "is_not_empty" });

// The Sales pipeline of the demo: the stage ids are the ones the demo's deals already carry.
const SALES: { id: string; name: string; kind: StageKind; probability: number; rotting: number | null; color: string; rules: Filter }[] = [
  { id: "new", name: "Lead", kind: "open", probability: 10, rotting: 14, color: "gray", rules: EMPTY },
  { id: "qualified", name: "Qualified", kind: "open", probability: 25, rotting: 14, color: "blue", rules: { and: [has("amount"), has("close_date")] } },
  { id: "proposal", name: "Proposal", kind: "open", probability: 50, rotting: 21, color: "amber", rules: { and: [has("amount"), has("close_date")] } },
  { id: "negotiation", name: "Negotiation", kind: "open", probability: 80, rotting: 21, color: "orange", rules: { and: [has("amount"), has("close_date")] } },
  { id: "won", name: "Won", kind: "won", probability: 100, rotting: null, color: "green", rules: EMPTY },
  { id: "lost", name: "Lost", kind: "lost", probability: 0, rotting: null, color: "red", rules: EMPTY },
];

const hash = (s: string) => {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) h = Math.imul(h ^ s.charCodeAt(i), 16777619);
  // ids that differ in their last digits share the high bits of an FNV hash: mix them in
  h ^= h >>> 16;
  h = Math.imul(h, 0x85ebca6b);
  h ^= h >>> 13;
  h = Math.imul(h, 0xc2b2ae35);
  return (h ^ (h >>> 16)) >>> 0;
};

export type MemoryPipelineOptions = { now?: () => number; latency?: number };

/** What the forecast makes of deals: the open ones by probability, the won ones, lost and undated or amountless ones left out. */
export function buildForecast(deals: RecordRow[], stages: Stage[], period: Period): Forecast {
  const byId = new Map(stages.map((s) => [s.id, s]));
  const blank = (): Record<keyof Metrics, Sums> => ({ pipeline: {}, best_case: {}, commit: {}, weighted: {}, won: {} });
  const add = (sums: Sums, currency: string, n: number) => void (sums[currency] = (sums[currency] ?? 0) + n);
  const periods = new Map<string, { all: Record<keyof Metrics, Sums>; owners: Map<string | null, Record<keyof Metrics, Sums>> }>();
  for (const d of deals) {
    const stage = byId.get(String(d.values.stage));
    const day = typeof d.values.close_date === "string" ? parseDay(d.values.close_date) : null;
    const money = d.values.amount;
    if (!stage || stage.kind === "lost" || !day || !isMoney(money)) continue;
    const first = toDay(period === "month" ? new Date(day.getFullYear(), day.getMonth(), 1) : new Date(day.getFullYear(), day.getMonth() - (day.getMonth() % 3), 1));
    const found = periods.get(first) ?? { all: blank(), owners: new Map() };
    periods.set(first, found);
    const mine = found.owners.get(d.owner_id) ?? blank();
    found.owners.set(d.owner_id, mine);
    for (const bucket of [found.all, mine]) {
      const { currency, amount } = money;
      if (stage.kind === "won") add(bucket.won, currency, amount);
      else {
        add(bucket.pipeline, currency, amount);
        add(bucket.weighted, currency, amount * stage.probability); // divided by 100 below, so rounding happens once per sum
        if (stage.probability >= 50) add(bucket.best_case, currency, amount);
        if (stage.probability >= 80) add(bucket.commit, currency, amount);
      }
    }
  }
  const done = (m: Record<keyof Metrics, Sums>): Metrics => ({ ...m, weighted: Object.fromEntries(Object.entries(m.weighted).map(([c, n]) => [c, Math.floor((n + 50) / 100)])) });
  const out: ForecastPeriod[] = [...periods.entries()]
    .sort((a, b) => a[0].localeCompare(b[0]))
    .map(([start, p]) => {
      const first = parseDay(start)!;
      const end = toDay(new Date(first.getFullYear(), first.getMonth() + (period === "month" ? 1 : 3), 0));
      const owners = [...p.owners.entries()].sort((a, b) => Number(a[0] === null) - Number(b[0] === null) || String(a[0]).localeCompare(String(b[0]))).map(([owner_id, m]) => ({ owner_id, ...done(m) }));
      return { label: labelOf(start, period), start, end, ...done(p.all), owners };
    });
  return { period, periods: out };
}

export function createMemoryPipelineClient(records: RecordsClient, opts: MemoryPipelineOptions = {}): PipelineClient {
  const now = opts.now ?? Date.now;
  const began = now();
  const wait = () => (opts.latency ? new Promise<void>((r) => setTimeout(r, opts.latency)) : Promise.resolve());
  let serial = 0;
  const fail = (status: number, message: string, fields?: Record<string, string>): never => {
    throw new RecordsError(status, message, fields);
  };

  const pipelines: Pipeline[] = [
    {
      id: "pl_sales",
      name: "Sales",
      position: 0,
      archived_at: null,
      stages: SALES.map((s, i) => ({ id: s.id, pipeline_id: "pl_sales", name: s.name, position: i, kind: s.kind, probability: s.probability, rotting_days: s.rotting, exit_rules: s.rules, color: s.color })),
    },
  ];
  const layouts = new Map<string, Layout>();
  const positions = new Map<string, number>(); // board position of every deal that has been on a board: lower is higher up
  const entered = new Map<string, number>(); // when a deal moved into its stage in this session
  let seeded = false;
  let top = 0;

  const pipeline = (id: string) => pipelines.find((p) => p.id === id) ?? fail(404, "Pipeline not found");
  const allStages = () => pipelines.flatMap((p) => p.stages);
  const stageById = (id: string) => allStages().find((s) => s.id === id);
  const live = () => pipelines.filter((p) => p.archived_at === null);

  async function deals(): Promise<RecordRow[]> {
    const out: RecordRow[] = [];
    let cursor: string | null = null;
    do {
      const page: Awaited<ReturnType<RecordsClient["query"]>> = await records.query("deal", { limit: 200, cursor });
      out.push(...page.data);
      cursor = page.next_cursor;
    } while (cursor);
    if (!seeded) {
      // the first board: biggest deals on top; deals made later land on top
      [...out].sort((a, b) => (isMoney(b.values.amount) ? b.values.amount.amount : 0) - (isMoney(a.values.amount) ? a.values.amount.amount : 0) || a.id.localeCompare(b.id)).forEach((d, i) => positions.set(d.id, i + 1));
      seeded = true;
    }
    for (const d of out) if (!positions.has(d.id)) positions.set(d.id, --top);
    return out;
  }
  const pos = (id: string) => positions.get(id) ?? 0;
  const inStage = (all: RecordRow[], stageId: string) => all.filter((d) => d.values.stage === stageId).sort((a, b) => pos(a.id) - pos(b.id) || a.id.localeCompare(b.id));

  // Days in the stage and the last activity are made up from the deal's id until the deal moves here: a few rotting, most fresh.
  function cardOf(d: RecordRow, stage: Stage): Card {
    const closed = stage.kind !== "open";
    const h = hash(d.id);
    const seededDays = closed ? 2 + (h % 58) : Math.floor(26 * (h / 4294967296) ** 2);
    const since = entered.get(d.id) ?? began - seededDays * DAY - (hash(`${d.id}h`) % 20) * 3_600_000;
    const t = now();
    const days = Math.max(0, Math.floor((t - since) / DAY));
    const last = since + ((hash(`${d.id}a`) % 1000) / 1000) * (t - since);
    const money = isMoney(d.values.amount) ? d.values.amount : null;
    return {
      id: d.id,
      display_name: d.display_name,
      amount: money,
      close_date: typeof d.values.close_date === "string" ? d.values.close_date : null,
      owner_id: d.owner_id,
      board_position: String(pos(d.id)),
      stage_id: stage.id,
      stage_entered_at: new Date(since).toISOString(),
      days_in_stage: days,
      rotting: stage.rotting_days !== null && days > stage.rotting_days,
      last_activity_at: new Date(last).toISOString(),
      values: d.values,
    };
  }

  const sumsOf = (list: RecordRow[]): Sums => {
    const out: Sums = {};
    for (const d of list) if (isMoney(d.values.amount)) out[d.values.amount.currency] = (out[d.values.amount.currency] ?? 0) + d.values.amount.amount;
    return out;
  };

  const encode = (d: RecordRow) => `${pos(d.id)}|${d.id}`;
  const after = (cursor: string) => {
    const [p, id] = cursor.split("|") as [string, string];
    return (d: RecordRow) => pos(d.id) > Number(p) || (pos(d.id) === Number(p) && d.id > id);
  };
  const page = (all: RecordRow[], limit: number, cursor?: string | null) => {
    const rest = cursor ? all.filter(after(cursor)) : all;
    const shown = rest.slice(0, limit);
    return { shown, next: rest.length > limit ? encode(shown[shown.length - 1]!) : null };
  };

  // ---- the stage field of a deal lists the stages of every pipeline, so a deal can be moved into a stage made here ----
  async function syncChoices() {
    const field = (await records.listFields("deal")).find((f: FieldDef) => f.type === "stage");
    if (!field) return;
    const several = live().length > 1;
    // the memory client hands out its own field objects, so this is what its validator and every open screen read next
    field.options = {
      ...field.options,
      choices: pipelines.flatMap((p) => p.stages.map((s) => ({ id: s.id, label: several || p.archived_at ? `${p.name}${p.archived_at ? " (archived)" : ""}: ${s.name}` : s.name, color: colorName(s.color), probability: s.probability / 100 }))),
    };
  }

  // ---- exit rules, judged on the stage a deal leaves ----
  async function refusal(row: RecordRow, from: Stage | undefined, to: Stage, input: { lost_reason?: string }): Promise<Record<string, string>> {
    const fields = await records.listFields("deal");
    const label = (key: string) => fields.find((f) => f.key === key)?.label ?? key;
    const errors: Record<string, string> = {};
    const rules = from?.exit_rules as Filter | undefined;
    if (from && from.id !== to.id && rules && (!isGroup(rules) || groupItems(rules).length)) {
      const env: Env = { now: now(), field: (_o, k) => fields.find((f) => f.key === k), value: (r, k) => readValue(r, k), linked: () => [] };
      const parts = isGroup(rules) && "and" in rules ? rules.and : [rules];
      for (const part of parts) {
        if (evaluate(part, row, env)) continue;
        if ("field" in part) errors[part.field] = `${label(part.field)} ${part.op === "is_empty" ? "must be empty" : part.op === "is_not_empty" ? "is required" : `must satisfy ${part.op}`} to leave ${from.name}`;
        else errors.exit_rules = `${from.name} needs this to hold before a deal leaves`;
      }
    }
    if (to.kind === "won" && from?.id !== to.id) {
      // the demo's one built-in rule: a won deal has an amount and a close date
      for (const key of ["amount", "close_date"]) if (isEmptyValue(row.values[key])) errors[key] ??= `${label(key)} is required to move a deal to ${to.name}`;
    }
    if (to.kind === "lost" && !input.lost_reason && !row.values.lost_reason) errors.lost_reason = `${label("lost_reason")} is required to move a deal to ${to.name}`;
    return errors;
  }

  const spec = (s: StageSpec, i: number, pipelineId: string): Stage => {
    const kind = s.kind ?? "open";
    if (FIXED[kind] !== undefined && s.probability !== undefined && s.probability !== FIXED[kind]) fail(422, `Probability is ${FIXED[kind]} for a ${kind} stage`, { probability: `is ${FIXED[kind]} for a ${kind} stage` });
    return { id: `st_${++serial}`, pipeline_id: pipelineId, name: s.name.trim(), position: i, kind, probability: FIXED[kind] ?? s.probability ?? 10, rotting_days: s.rotting_days ?? null, exit_rules: s.exit_rules ?? {}, color: s.color ?? null };
  };
  const named = (name: string) => name.trim() || fail(422, "Name is required", { name: "is required" });
  const clone = (p: Pipeline): Pipeline => ({ ...p, stages: p.stages.map((s) => ({ ...s })) });

  return {
    async list(archived = false) {
      await wait();
      return pipelines.filter((p) => (p.archived_at !== null) === archived).map(clone);
    },

    async board(id, limit = 25): Promise<Board> {
      await wait();
      const p = pipeline(id);
      const all = await deals();
      const stages: BoardStage[] = p.stages.map((s) => {
        const mine = inStage(all, s.id);
        const amount = sumsOf(mine);
        const { shown, next } = page(mine, limit);
        return { ...s, count: mine.length, amount, weighted: Object.fromEntries(Object.entries(amount).map(([c, n]) => [c, weigh(n, s.probability)])), deals: shown.map((d) => cardOf(d, s)), next_cursor: next };
      });
      return { id: p.id, name: p.name, stages };
    },

    async column(id, stageId, cursor, limit = 25) {
      await wait();
      const s = pipeline(id).stages.find((x) => x.id === stageId) ?? fail(404, "Stage not found");
      const { shown, next } = page(inStage(await deals(), s.id), limit, cursor);
      return { deals: shown.map((d) => cardOf(d, s)), next_cursor: next };
    },

    async move(dealId, input) {
      await wait();
      const row = await records.get("deal", dealId);
      const to = stageById(input.stage_id) ?? fail(404, "Stage not found");
      const from = stageById(String(row.values.stage));
      const errors = await refusal(row, from, to, input);
      if (Object.keys(errors).length) fail(422, Object.values(errors)[0]!, errors);
      const all = await deals();
      const others = inStage(all, to.id).filter((d) => d.id !== dealId);
      const near = (id: string | null | undefined, name: string) => {
        if (!id) return undefined;
        const found = others.find((d) => d.id === id);
        return found ? pos(found.id) : fail(422, "The move is not valid", { [name]: "is not another deal of that stage" });
      };
      const above = near(input.after_id, "after_id");
      const below = near(input.before_id, "before_id");
      if (above !== undefined && below !== undefined && above >= below) fail(409, "The cards are no longer in that order: reload the board");
      const changed = from?.id !== to.id;
      let place: number | undefined;
      if (above !== undefined || below !== undefined) place = below === undefined ? above! + 1 : above === undefined ? below - 1 : (above + below) / 2;
      else if (changed) place = others.length ? Math.min(...others.map((d) => pos(d.id))) - 1 : 0;
      if (place !== undefined) positions.set(dealId, place);
      let saved = row;
      if (changed) {
        const patch: Record<string, unknown> = { stage: to.id };
        if (to.kind === "lost") Object.assign(patch, { lost_reason: input.lost_reason ?? row.values.lost_reason, ...(input.lost_note ? { lost_note: input.lost_note } : {}) });
        else if (from?.kind === "lost") Object.assign(patch, { lost_reason: null, lost_note: null });
        saved = await records.update("deal", dealId, patch);
        entered.set(dealId, now());
      }
      return cardOf(saved, to);
    },

    async layout(id) {
      await wait();
      pipeline(id);
      return { ...(layouts.get(id) ?? { collapsed: [], card_fields: DEFAULT_CARD_FIELDS }) };
    },

    async saveLayout(id, layout) {
      await wait();
      const p = pipeline(id);
      const known = new Set(p.stages.map((s) => s.id));
      const saved = { collapsed: [...new Set(layout.collapsed)].filter((s) => known.has(s)), card_fields: [...new Set(layout.card_fields)] };
      layouts.set(id, saved);
      return { ...saved };
    },

    async forecast(id, period) {
      await wait();
      return buildForecast(await deals(), pipeline(id).stages, period);
    },

    async createPipeline(name, stages) {
      await wait();
      const id = `pl_${++serial}`;
      const specs: StageSpec[] = stages ?? SALES.map((s) => ({ name: s.name, kind: s.kind, probability: s.probability, rotting_days: s.rotting, color: s.color }));
      const p: Pipeline = { id, name: named(name), position: pipelines.length, archived_at: null, stages: specs.map((s, i) => spec(s, i, id)) };
      pipelines.push(p);
      await syncChoices();
      return clone(p);
    },

    async renamePipeline(id, name) {
      await wait();
      const p = pipeline(id);
      p.name = named(name);
      await syncChoices();
      return clone(p);
    },

    async archivePipeline(id, archived) {
      await wait();
      const p = pipeline(id);
      if (archived && p.archived_at === null && live().length === 1) fail(409, "A workspace needs at least one pipeline that is not archived");
      p.archived_at = archived ? new Date(now()).toISOString() : null;
      await syncChoices();
      return clone(p);
    },

    async createStage(pipelineId, s) {
      await wait();
      const p = pipeline(pipelineId);
      if (p.stages.length >= 30) fail(409, "A pipeline has at most 30 stages");
      const stage = spec({ ...s, name: named(s.name) }, p.stages.length, pipelineId);
      p.stages.push(stage);
      await syncChoices();
      return { ...stage };
    },

    async updateStage(pipelineId, stageId, patch: StagePatch) {
      await wait();
      const stage = pipeline(pipelineId).stages.find((s) => s.id === stageId) ?? fail(404, "Stage not found");
      const kind = patch.kind ?? stage.kind;
      let probability = patch.probability ?? (patch.kind && patch.kind !== stage.kind ? 10 : stage.probability);
      if (FIXED[kind] !== undefined) {
        if (patch.probability !== undefined && patch.probability !== FIXED[kind]) fail(422, `Probability is ${FIXED[kind]} for a ${kind} stage`, { probability: `is ${FIXED[kind]} for a ${kind} stage` });
        probability = FIXED[kind]!;
      }
      Object.assign(stage, { ...patch, name: patch.name === undefined ? stage.name : named(patch.name), kind, probability });
      await syncChoices();
      return { ...stage };
    },

    async deleteStage(pipelineId, stageId) {
      await wait();
      const p = pipeline(pipelineId);
      const stage = p.stages.find((s) => s.id === stageId) ?? fail(404, "Stage not found");
      const n = inStage(await deals(), stageId).length;
      if (n) fail(409, `Move the ${n} deal${n === 1 ? "" : "s"} in ${stage.name} to another stage first`);
      p.stages = p.stages.filter((s) => s.id !== stageId).map((s, i) => ({ ...s, position: i }));
      await syncChoices();
    },

    async reorderStages(pipelineId, ids) {
      await wait();
      const p = pipeline(pipelineId);
      if ([...ids].sort().join() !== p.stages.map((s) => s.id).sort().join()) fail(422, "stage_ids must list every stage of the pipeline exactly once", { stage_ids: "must list every stage of the pipeline exactly once" });
      p.stages = ids.map((id, i) => ({ ...p.stages.find((s) => s.id === id)!, position: i }));
      return p.stages.map((s) => ({ ...s }));
    },
  };
}
