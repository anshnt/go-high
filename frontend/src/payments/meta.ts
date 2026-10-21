// Words and tones for the states of invoices, subscriptions and payments, and what a role may do with each. No React,
// so node can test it.
import type { InvoiceStatus, Payment, SubStatus, Subscription } from "./types.ts";

type Tone = "neutral" | "accent" | "success" | "warning" | "danger" | "info";

export const INVOICE_STATUS: Record<InvoiceStatus, { label: string; tone: Tone }> = {
  draft: { label: "Draft", tone: "neutral" },
  open: { label: "Open", tone: "warning" },
  paid: { label: "Paid", tone: "success" },
  void: { label: "Void", tone: "neutral" },
  uncollectible: { label: "Uncollectible", tone: "danger" },
};

export const SUB_STATUS: Record<SubStatus, { label: string; tone: Tone; hint: string }> = {
  incomplete: { label: "Incomplete", tone: "warning", hint: "Waiting for the first payment" },
  incomplete_expired: { label: "Expired", tone: "neutral", hint: "The first payment never came" },
  trialing: { label: "Trial", tone: "info", hint: "No charge until the trial ends" },
  active: { label: "Active", tone: "success", hint: "Paid up" },
  past_due: { label: "Past due", tone: "danger", hint: "A payment failed; it will be retried" },
  unpaid: { label: "Unpaid", tone: "danger", hint: "Retries are used up; nothing more is billed until it is paid" },
  canceled: { label: "Cancelled", tone: "neutral", hint: "Ended" },
};

export const PAYMENT_STATUS: Record<Payment["status"], { label: string; tone: Tone }> = {
  pending: { label: "Pending", tone: "neutral" },
  processing: { label: "Processing", tone: "info" },
  succeeded: { label: "Succeeded", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
  canceled: { label: "Cancelled", tone: "neutral" },
};

/** A payment's state with its refunds: "Refunded", "Partly refunded", or its status. */
export function paymentState(p: Pick<Payment, "status" | "amount" | "amount_refunded">): { label: string; tone: Tone } {
  if (p.status === "succeeded" && p.amount_refunded >= p.amount) return { label: "Refunded", tone: "neutral" };
  if (p.status === "succeeded" && p.amount_refunded > 0) return { label: "Partly refunded", tone: "info" };
  return PAYMENT_STATUS[p.status];
}

export const METHOD: Record<string, string> = { card: "Card", cash: "Cash", check: "Cheque", bank_transfer: "Bank transfer", other: "Other" };

export const PROVIDER: Record<Payment["provider"], string> = { stripe: "Stripe", fake: "Test provider", manual: "Recorded by hand" };

/** What can be done with a subscription now (the server has the last word). */
export function subActions(s: Pick<Subscription, "status" | "cancel_at_period_end">) {
  const live = ["trialing", "active", "past_due"].includes(s.status);
  return {
    cancelAtEnd: live && !s.cancel_at_period_end,
    cancelNow: !["canceled", "incomplete_expired"].includes(s.status),
    reactivate: (live && s.cancel_at_period_end) || s.status === "unpaid" || s.status === "past_due",
    change: live,
  };
}

/** "INV-0001", or what an invoice without a number is. */
export const invoiceName = (i: { number: string | null; status: InvoiceStatus; billing_reason: string }) =>
  i.number ?? (i.status === "draft" ? "Draft" : i.billing_reason === "payment_link" ? "Checkout" : "No number");
