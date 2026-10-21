// The billing and usage API (README "Usage ledger and wallet"). Every amount is integer micros.
import { api, queryString, workspaceId } from "../lib/api";
import { errorFrom } from "../lib/http";

export type WalletStatus = "ok" | "low" | "empty" | "capped";
export type Wallet = {
  workspace_id: string;
  currency: string;
  balance: number;
  mode: "prepaid" | "postpaid";
  credit_limit: number | null;
  available: number | null;
  low_balance_at: number | null;
  auto_recharge: boolean;
  recharge_below: number | null;
  recharge_amount: number | null;
  payment_method: string | null;
  monthly_cap: number | null;
  cap_alert_pct: number;
  month_spent: number;
  month_start: string;
  status: WalletStatus;
  minor_unit: number;
  provider: string;
  updated_at: string;
};
export type WalletPatch = Partial<Pick<Wallet, "low_balance_at" | "auto_recharge" | "recharge_below" | "recharge_amount" | "monthly_cap" | "cap_alert_pct" | "mode" | "credit_limit" | "currency">> & { payment_method?: string | null };

export type EntryKind = "usage" | "reversal" | "topup" | "adjustment";
export type Entry = {
  id: string;
  kind: EntryKind;
  meter: string | null;
  quantity: number;
  unit_price: number;
  price: number;
  amount: number;
  balance_after: number;
  currency: string;
  source: string;
  subject_type: string | null;
  subject_id: string | null;
  reverses_id: string | null;
  description: string;
  actor_type: string;
  actor_id: string | null;
  created_at: string;
  /** Organization owners and admins only. */
  unit_cost?: number;
  cost?: number;
};
export type Page<T> = { data: T[]; next_cursor: string | null };
export type LedgerFilters = { kind?: EntryKind | ""; meter?: string; from?: string; to?: string };

export type UsageLine = { meter: string; label: string; quantity: number; price: number; cost?: number };
export type Usage = { currency: string; from: string; to: string | null; group: "day" | "month"; price: number; cost?: number; meters: UsageLine[]; series: { period: string; price: number; meters: Record<string, UsageLine> }[] };

export type Topup = { id: string; amount: number; currency: string; status: "pending" | "succeeded" | "failed"; trigger: "manual" | "auto"; provider: string; provider_ref: string | null; error: string | null; created_at: string; completed_at: string | null };
export type Meter = { meter: string; label: string; unit: string; units: string; unit_price: number; currency: string; unit_cost?: number; rate_card_id?: string | null; basis?: string };
export type RateCard = { id: string; meter: string; scope: "organization" | "brand" | "workspace"; org_id: string; brand_id: string | null; workspace_id: string | null; currency: string; price: number | null; markup_bp: number | null; created_at: string; updated_at: string };
export type NewCard = { meter: string; scope: RateCard["scope"]; currency: string; price?: number | null; markup_bp?: number | null; brand_id?: string; workspace_id?: string };

const B = "/api/v1/billing";

export const getWallet = () => api.get<Wallet>(`${B}/wallet`);
export const patchWallet = (patch: WalletPatch) => api.patch<Wallet>(`${B}/wallet`, patch);
export const listLedger = (f: LedgerFilters, cursor?: string | null, limit = 50) => api.get<Page<Entry>>(`${B}/ledger${queryString({ ...f, cursor, limit })}`);
export const getUsage = (f: { from?: string; to?: string; group?: "day" | "month" } = {}) => api.get<Usage>(`${B}/usage${queryString(f)}`);
export const listTopups = () => api.get<Page<Topup>>(`${B}/topups?limit=20`);
/** `key` makes a retry (a double click, a dropped connection) charge the card once. */
export const createTopup = (amount: number, key: string) => api.post<Topup & { wallet: Wallet }>(`${B}/topups`, { amount }, { "Idempotency-Key": key });
export const listMeters = () => api.get<{ data: Meter[] }>(`${B}/meters`);
export const listCards = () => api.get<{ data: RateCard[] }>(`${B}/rate-cards`);
export const createCard = (card: NewCard, key: string) => api.post<RateCard>(`${B}/rate-cards`, card, { "Idempotency-Key": key });
export const patchCard = (id: string, patch: { price?: number | null; markup_bp?: number | null }) => api.patch<RateCard>(`${B}/rate-cards/${id}`, patch);
export const deleteCard = (id: string) => api.del(`${B}/rate-cards/${id}`);

/** The ledger as CSV, fetched with the workspace header and handed to the browser as a download. */
export async function exportLedger(f: LedgerFilters): Promise<{ truncated: boolean }> {
  if (import.meta.env.VITE_DEMO === "1") {
    const { demoExport } = await import("./demoBilling");
    return save(new Blob([demoExport()], { type: "text/csv" }), false);
  }
  const ws = workspaceId.get();
  const res = await fetch(`${B}/ledger/export${queryString(f)}`, { credentials: "same-origin", headers: ws ? { "X-Workspace-Id": ws } : {} });
  if (!res.ok) throw await errorFrom(res);
  return save(await res.blob(), res.headers.get("X-Export-Truncated") === "true");
}

function save(blob: Blob, truncated: boolean) {
  const url = URL.createObjectURL(blob);
  const a = Object.assign(document.createElement("a"), { href: url, download: `usage-${new Date().toISOString().slice(0, 10)}.csv` });
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  return { truncated };
}
