// The Payments area (module 21): a summary, then invoices, subscriptions, transactions, the catalog (products,
// coupons, payment links) and settings, one tab each at /payments/<tab>/<id>.
import { useEffect, useState } from "react";
import { Link, Navigate, useParams } from "react-router";
import { useCan } from "../lib/capabilities";
import { PageHeader } from "../shell/PageHeader";
import { CouponsView, LinksView, ProductsView } from "./CatalogView";
import { InvoicesView } from "./InvoicesView";
import { pay } from "./api";
import { money } from "./money";
import { NoAccess } from "./shared";
import { SettingsView } from "./SettingsView";
import { SubscriptionsView } from "./SubscriptionsView";
import { TransactionsView } from "./TransactionsView";
import type { AccountView, Summary } from "./types";
import "./payments.css";

const TABS = [
  { id: "invoices", label: "Invoices", view: InvoicesView },
  { id: "subscriptions", label: "Subscriptions", view: SubscriptionsView },
  { id: "transactions", label: "Transactions", view: TransactionsView },
  { id: "products", label: "Products", view: ProductsView },
  { id: "coupons", label: "Coupons", view: CouponsView },
  { id: "links", label: "Payment links", view: LinksView },
  { id: "settings", label: "Settings", view: SettingsView },
] as const;

export function PaymentsPage() {
  const { tab } = useParams();
  const { can, ready } = useCan();
  const current = TABS.find((t) => t.id === tab);
  if (!current) return <Navigate to="/payments/invoices" replace />;
  const View = current.view;
  return (
    <div className="sh-page pay-page">
      <PageHeader
        title="Payments"
        description="Invoices, subscriptions and payment links, paid through your own Stripe account."
        views={
          <nav className="ui-tabs pay-tabs" aria-label="Payments">
            {TABS.map((t) => (
              <Link key={t.id} to={`/payments/${t.id}`} className="ui-tab" data-state={t.id === current.id ? "active" : "inactive"} aria-current={t.id === current.id ? "page" : undefined}>
                {t.label}
              </Link>
            ))}
          </nav>
        }
      />
      {ready && !can("payments.read") ? (
        <NoAccess what="payments" />
      ) : (
        <>
          {current.id !== "settings" && <Overview />}
          <View />
        </>
      )}
    </div>
  );
}

/** Money in, money owed, recurring revenue, and a nudge when nothing can take card payments yet. */
function Overview() {
  const [summary, setSummary] = useState<Summary | null>(null);
  const [account, setAccount] = useState<AccountView | null>(null);
  useEffect(() => {
    void pay.summary().then(setSummary).catch(() => {});
    void pay.account().then(setAccount).catch(() => {});
  }, []);
  const rows = summary?.currencies.length ? summary.currencies : [{ currency: "usd", net_volume: 0, gross_volume: 0, refunded: 0, outstanding: 0, mrr: 0 }];
  const sum = (k: "net_volume" | "outstanding" | "mrr") => rows.map((r) => money(r[k], r.currency)).join(" + ");
  return (
    <>
      {account && !account.capabilities.online_payments.available && (
        <div className="pay-banner" role="status">
          <span>{account.capabilities.online_payments.reason}</span>
          <Link to="/payments/settings">Set up payments</Link>
        </div>
      )}
      <dl className="pay-stats" aria-busy={summary === null}>
        <div>
          <dt>Net volume, 30 days</dt>
          <dd className="mono">{summary ? sum("net_volume") : "…"}</dd>
        </div>
        <div>
          <dt>Outstanding</dt>
          <dd className="mono">{summary ? sum("outstanding") : "…"}</dd>
        </div>
        <div>
          <dt>Recurring per month</dt>
          <dd className="mono">{summary ? sum("mrr") : "…"}</dd>
        </div>
        <div>
          <dt>Live subscriptions</dt>
          <dd className="mono">{summary ? summary.live_subscriptions.toLocaleString("en-US") : "…"}</dd>
        </div>
      </dl>
    </>
  );
}
