// The pipeline client over /api/v1 (README "Pipelines and deals"). It turns the API's error envelope into the same
// RecordsError the record screens use, and normalizes cards. It talks through `Http`, so node can test it with a fake fetch.
import type { Http } from "../lib/http.ts";
import { queryString } from "../lib/http.ts";
import { asRecordsError } from "../records/apiClient.ts";
import { isMoney } from "../records/format.ts";
import { DEFAULT_CARD_FIELDS, type Board, type BoardStage, type Card, type Forecast, type Layout, type Pipeline, type PipelineClient, type Stage } from "./types.ts";

const enc = encodeURIComponent;
type ApiPage<T> = { data: T[]; next_cursor: string | null };

async function call<T>(run: () => Promise<T>): Promise<T> {
  try {
    return await run();
  } catch (e) {
    throw asRecordsError(e);
  }
}

/** A card as the board shows it: `amount` is the money value or null. */
export const toCard = (c: Card): Card => ({ ...c, amount: isMoney(c.amount) ? c.amount : null, close_date: c.close_date ?? null, owner_id: c.owner_id ?? null, last_activity_at: c.last_activity_at ?? null, values: c.values ?? {} });

type ApiStage = Stage & { count?: number; amount?: Record<string, number>; weighted?: Record<string, number>; deals?: Card[]; next_cursor?: string | null };
const toStage = ({ count: _c, amount: _a, weighted: _w, deals: _d, next_cursor: _n, ...s }: ApiStage): Stage => ({ ...s, exit_rules: s.exit_rules ?? {}, rotting_days: s.rotting_days ?? null, color: s.color ?? null });
const toBoardStage = (s: ApiStage): BoardStage => ({ ...toStage(s), count: s.count ?? 0, amount: s.amount ?? {}, weighted: s.weighted ?? {}, deals: (s.deals ?? []).map(toCard), next_cursor: s.next_cursor ?? null });
const toPipeline = (p: Pipeline): Pipeline => ({ id: p.id, name: p.name, position: p.position, archived_at: p.archived_at ?? null, stages: (p.stages ?? []).map(toStage) });

export function createPipelineApiClient(http: Http): PipelineClient {
  const base = (id: string) => `/api/v1/pipelines/${enc(id)}`;
  const board = (id: string, params: Record<string, unknown>) => call(() => http.get<{ id: string; name: string; stages: ApiStage[] }>(`${base(id)}/board${queryString(params)}`));
  return {
    async list(archived = false) {
      const page = await call(() => http.get<ApiPage<Pipeline>>(`/api/v1/pipelines${queryString({ archived: archived || undefined })}`));
      return page.data.map(toPipeline);
    },
    async board(id, limit = 25): Promise<Board> {
      const b = await board(id, { limit });
      return { id: b.id, name: b.name, stages: b.stages.map(toBoardStage) };
    },
    async column(id, stageId, cursor, limit = 25) {
      const b = await board(id, { limit, stage: stageId, cursor });
      const s = b.stages[0] ? toBoardStage(b.stages[0]) : undefined;
      return { deals: s?.deals ?? [], next_cursor: s?.next_cursor ?? null };
    },
    async move(dealId, input) {
      return toCard(await call(() => http.post<Card>(`/api/v1/deals/${enc(dealId)}/move`, input)));
    },
    async layout(id): Promise<Layout> {
      const l = await call(() => http.get<Layout>(`${base(id)}/layout`));
      return { collapsed: l.collapsed ?? [], card_fields: l.card_fields?.length ? l.card_fields : DEFAULT_CARD_FIELDS };
    },
    async saveLayout(id, layout): Promise<Layout> {
      const l = await call(() => http.put<Layout>(`${base(id)}/layout`, { collapsed: layout.collapsed, card_fields: layout.card_fields }));
      return { collapsed: l.collapsed ?? [], card_fields: l.card_fields ?? layout.card_fields };
    },
    forecast: (id, period) => call(() => http.get<Forecast>(`${base(id)}/forecast${queryString({ period })}`)),
    async createPipeline(name, stages) {
      return toPipeline(await call(() => http.post<Pipeline>("/api/v1/pipelines", { name, ...(stages ? { stages } : {}) })));
    },
    async renamePipeline(id, name) {
      return toPipeline(await call(() => http.patch<Pipeline>(base(id), { name })));
    },
    async archivePipeline(id, archived) {
      return toPipeline(await call(() => http.patch<Pipeline>(base(id), { archived })));
    },
    async createStage(pipelineId, spec) {
      return toStage(await call(() => http.post<ApiStage>(`${base(pipelineId)}/stages`, spec)));
    },
    async updateStage(pipelineId, stageId, patch) {
      return toStage(await call(() => http.patch<ApiStage>(`${base(pipelineId)}/stages/${enc(stageId)}`, patch)));
    },
    deleteStage: (pipelineId, stageId) => call(() => http.del(`${base(pipelineId)}/stages/${enc(stageId)}`)),
    async reorderStages(pipelineId, stageIds) {
      const p = await call(() => http.post<Pipeline>(`${base(pipelineId)}/stages/reorder`, { stage_ids: stageIds }));
      return toPipeline(p).stages;
    },
  };
}
