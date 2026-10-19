// The pipeline contract: what /api/v1 sends for pipelines, boards, layouts and forecasts (README "Pipelines and deals").
// Pure types, so node tests and the memory client import this file for free.
import type { Filter, Money } from "../records/types.ts";

export type StageKind = "open" | "won" | "lost";

/** Money by currency, in minor units: `{ USD: 120000, EUR: 4000 }`. Empty when nothing has an amount. */
export type Sums = Record<string, number>;

export type Stage = {
  id: string;
  pipeline_id: string;
  name: string;
  position: number;
  kind: StageKind;
  /** 0 to 100 (won is 100, lost is 0) */
  probability: number;
  /** a deal is rotting when it has been in the stage longer than this; null: never */
  rotting_days: number | null;
  /** a filter on the deal that must hold before it may leave the stage; {} for none */
  exit_rules: Filter | Record<string, never>;
  /** a color name from the theme (records/types ColorName), free text on the server */
  color: string | null;
};

export type Pipeline = { id: string; name: string; position: number; archived_at: string | null; stages: Stage[] };

export type Card = {
  id: string;
  display_name: string;
  amount: Money | null;
  close_date: string | null;
  owner_id: string | null;
  /** exact decimal as text, lower is higher up */
  board_position: string | null;
  stage_id: string;
  stage_entered_at: string;
  days_in_stage: number;
  rotting: boolean;
  last_activity_at: string | null;
  values: Record<string, unknown>;
};

export type BoardStage = Stage & { count: number; amount: Sums; weighted: Sums; deals: Card[]; next_cursor: string | null };
export type Board = { id: string; name: string; stages: BoardStage[] };

export type Layout = { collapsed: string[]; card_fields: string[] };
export const DEFAULT_CARD_FIELDS = ["amount", "close_date", "owner_id"];

export type MoveInput = {
  stage_id: string;
  /** the card above the drop and the card below it, both ids of other deals of the target stage */
  after_id?: string | null;
  before_id?: string | null;
  lost_reason?: string;
  lost_note?: string;
};

export type Period = "month" | "quarter";
export type Metrics = { pipeline: Sums; best_case: Sums; commit: Sums; weighted: Sums; won: Sums };
export type ForecastPeriod = Metrics & { label: string; start: string; end: string; owners: (Metrics & { owner_id: string | null })[] };
export type Forecast = { period: Period; periods: ForecastPeriod[] };

export type StageSpec = { name: string; kind?: StageKind; probability?: number; rotting_days?: number | null; color?: string | null; exit_rules?: Filter | Record<string, never> };
export type StagePatch = Partial<StageSpec>;

/**
 * Everything the pipeline screens need from the backend. The API client (apiClient.ts) is what the app runs on; the
 * in-memory client (memoryClient.ts) stands in for it in the public demo. Both throw RecordsError (status, fields).
 */
export interface PipelineClient {
  /** Live pipelines in order, or the archived ones. */
  list(archived?: boolean): Promise<Pipeline[]>;
  /** The pipeline's stages with counts, sums and the first `limit` cards of each. */
  board(id: string, limit?: number): Promise<Board>;
  /** The next page of one column. */
  column(id: string, stageId: string, cursor: string, limit?: number): Promise<{ deals: Card[]; next_cursor: string | null }>;
  /** Moves a deal to a stage and a place in it. A 422 carries `fields` (what the stage it leaves wants, or the lost reason). */
  move(dealId: string, input: MoveInput): Promise<Card>;
  layout(id: string): Promise<Layout>;
  saveLayout(id: string, layout: Layout): Promise<Layout>;
  forecast(id: string, period: Period): Promise<Forecast>;
  createPipeline(name: string, stages?: StageSpec[]): Promise<Pipeline>;
  renamePipeline(id: string, name: string): Promise<Pipeline>;
  archivePipeline(id: string, archived: boolean): Promise<Pipeline>;
  createStage(pipelineId: string, spec: StageSpec): Promise<Stage>;
  updateStage(pipelineId: string, stageId: string, patch: StagePatch): Promise<Stage>;
  deleteStage(pipelineId: string, stageId: string): Promise<void>;
  /** The whole order in one call. */
  reorderStages(pipelineId: string, stageIds: string[]): Promise<Stage[]>;
}
