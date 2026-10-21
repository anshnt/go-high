// The payments API for signed-in people (backend/app/payments/routes_catalog.py and routes_billing.py).
import { api, queryString } from "../lib/api";
import type { AccountView, Coupon, Invoice, Page, Payment, PaymentLink, Price, Product, Settings, Subscription, Summary, TaxRate } from "./types";

const key = () => ({ "Idempotency-Key": crypto.randomUUID() });

export type LineInput = { description?: string; price_id?: string; quantity: number; unit_amount?: number; tax_rate_id?: string };
export type InvoiceInput = { contact_id: string; currency?: string; lines: LineInput[]; coupon_code?: string; due_at?: string; memo?: string; footer?: string };

export const pay = {
  account: () => api.get<AccountView>("/api/v1/payments/account"),
  connect: (provider: "stripe" | "fake") => api.post<AccountView>("/api/v1/payments/account/connect", { provider }),
  refresh: () => api.post<AccountView>("/api/v1/payments/account/refresh"),
  disconnect: () => api.del("/api/v1/payments/account"),
  settings: () => api.get<Settings>("/api/v1/payments/settings"),
  saveSettings: (patch: Partial<Settings>) => api.patch<Settings>("/api/v1/payments/settings", patch),
  summary: () => api.get<Summary>("/api/v1/payments/summary"),

  taxRates: () => api.get<Page<TaxRate>>("/api/v1/tax-rates").then((r) => r.data),
  createTaxRate: (body: { name: string; percentage_bp: number; inclusive: boolean; region: string }) => api.post<TaxRate>("/api/v1/tax-rates", body, key()),
  patchTaxRate: (id: string, body: Partial<TaxRate>) => api.patch<TaxRate>(`/api/v1/tax-rates/${id}`, body),

  products: (params: { active?: boolean; q?: string; cursor?: string | null }) => api.get<Page<Product>>(`/api/v1/products${queryString({ ...params, active: params.active === undefined ? undefined : String(params.active) })}`),
  createProduct: (body: unknown) => api.post<Product>("/api/v1/products", body, key()),
  patchProduct: (id: string, body: Partial<Product>) => api.patch<Product>(`/api/v1/products/${id}`, body),
  addPrice: (productId: string, body: unknown) => api.post<Price>(`/api/v1/products/${productId}/prices`, body, key()),
  patchPrice: (id: string, body: { nickname?: string; active?: boolean }) => api.patch<Price>(`/api/v1/prices/${id}`, body),
  prices: (params: { type?: string; currency?: string } = {}) => api.get<Page<Price>>(`/api/v1/prices${queryString(params)}`).then((r) => r.data),

  coupons: (cursor?: string | null) => api.get<Page<Coupon>>(`/api/v1/coupons${queryString({ cursor })}`),
  createCoupon: (body: unknown) => api.post<Coupon>("/api/v1/coupons", body, key()),
  patchCoupon: (id: string, body: Partial<Coupon>) => api.patch<Coupon>(`/api/v1/coupons/${id}`, body),

  links: (cursor?: string | null) => api.get<Page<PaymentLink>>(`/api/v1/payment-links${queryString({ cursor })}`),
  createLink: (body: unknown) => api.post<PaymentLink>("/api/v1/payment-links", body, key()),
  patchLink: (id: string, body: Partial<PaymentLink>) => api.patch<PaymentLink>(`/api/v1/payment-links/${id}`, body),

  invoices: (params: { status?: string; q?: string; cursor?: string | null }) => api.get<Page<Invoice>>(`/api/v1/invoices${queryString(params)}`),
  invoice: (id: string) => api.get<Invoice>(`/api/v1/invoices/${id}`),
  preview: (body: InvoiceInput) => api.post<Invoice>("/api/v1/invoices/preview", body),
  createInvoice: (body: InvoiceInput) => api.post<Invoice>("/api/v1/invoices", body, key()),
  patchInvoice: (id: string, body: Partial<InvoiceInput>) => api.patch<Invoice>(`/api/v1/invoices/${id}`, body),
  deleteInvoice: (id: string) => api.del(`/api/v1/invoices/${id}`),
  sendInvoice: (id: string) => api.post<Invoice>(`/api/v1/invoices/${id}/send`, undefined, key()),
  voidInvoice: (id: string, reason?: string) => api.post<Invoice>(`/api/v1/invoices/${id}/void`, reason ? { reason } : {}),
  recordPayment: (id: string, body: { amount: number; method: string; note: string }) => api.post<Invoice>(`/api/v1/invoices/${id}/payments`, body, key()),

  subscriptions: (params: { status?: string; cursor?: string | null }) => api.get<Page<Subscription>>(`/api/v1/subscriptions${queryString(params)}`),
  subscription: (id: string) => api.get<Subscription>(`/api/v1/subscriptions/${id}`),
  createSubscription: (body: unknown) => api.post<Subscription>("/api/v1/subscriptions", body, key()),
  changeSubscription: (id: string, body: { price_id?: string; quantity?: number; prorate: boolean }) => api.patch<Subscription>(`/api/v1/subscriptions/${id}`, body),
  cancelSubscription: (id: string, body: { at_period_end: boolean; reason?: string }) => api.post<Subscription>(`/api/v1/subscriptions/${id}/cancel`, body),
  reactivate: (id: string) => api.post<Subscription>(`/api/v1/subscriptions/${id}/reactivate`),

  transactions: (params: { status?: string; cursor?: string | null }) => api.get<Page<Payment>>(`/api/v1/payments/transactions${queryString(params)}`),
  transaction: (id: string) => api.get<Payment>(`/api/v1/payments/transactions/${id}`),
  refund: (id: string, body: { amount?: number; reason?: string; note: string }) => api.post<Payment>(`/api/v1/payments/transactions/${id}/refunds`, body, key()),

  searchContacts: (q: string) =>
    api.get<{ data: { id: string; display_name: string; values: Record<string, unknown> }[] }>(`/api/v1/objects/contact/records${queryString({ q, limit: 20 })}`).then((r) => r.data),
};
