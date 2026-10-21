// The payment provider, invoice terms, dunning and tax rates.
import { CircleCheck, CircleX, Plus, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router";
import { errorText } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { Badge, Button, Checkbox, Input, Select, Switch, Textarea, useToast } from "../ui";
import { pay } from "./api";
import { CURRENCIES, percent, readPercent } from "./money";
import { Confirm, fieldsOf, ListError, Row } from "./shared";
import type { AccountView, Settings, TaxRate } from "./types";

const CAP_LABEL: Record<string, string> = {
  invoices: "Invoices",
  manual_payments: "Payments recorded by hand",
  online_payments: "Card payments",
  payment_links: "Payment links",
  subscriptions: "Subscriptions that charge a card",
  saved_cards: "Cards kept for renewals",
  refunds: "Refunds to cards",
};

export function SettingsView() {
  const { can } = useCan();
  return (
    <div className="pay-settings">
      <Provider manage={can("payments.manage")} />
      <Terms manage={can("payments.manage")} />
      <Taxes manage={can("payments.manage")} />
    </div>
  );
}

function Provider({ manage }: { manage: boolean }) {
  const toast = useToast();
  const [params] = useSearchParams();
  const [view, setView] = useState<AccountView | null>(null);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState<string | null>(null);
  const [disconnecting, setDisconnecting] = useState(false);
  const load = () => {
    setError(undefined);
    pay.account().then(setView).catch((e) => setError(errorText(e)));
  };
  useEffect(load, []);
  useEffect(() => {
    // back from Stripe's onboarding: ask Stripe how far it got
    if (params.get("connected") && manage) void pay.refresh().then(setView).catch(() => {});
  }, [params, manage]);

  async function connect(provider: "stripe" | "fake") {
    setBusy(provider);
    try {
      const next = await pay.connect(provider);
      if (next.url) {
        window.location.assign(next.url); // Stripe's onboarding; it sends the owner back here
        return;
      }
      setView(next);
      toast({ title: "Connected", tone: "success" });
    } catch (e) {
      toast({ title: "Could not connect", description: errorText(e), tone: "danger" });
    } finally {
      setBusy(null);
    }
  }

  if (error) return <ListError error={error} onRetry={load} what="the payment provider" />;
  if (!view) return <section className="pay-card" aria-busy="true"><h2>Payment provider</h2><p className="pay-muted">Loading…</p></section>;
  const a = view.account;
  const live = a && a.status !== "disconnected";
  return (
    <section className="pay-card" aria-labelledby="pay-provider">
      <div className="pay-card-head">
        <h2 id="pay-provider">Payment provider</h2>
        {live && <Badge tone={a.status === "active" ? "success" : "warning"}>{a.status === "active" ? "Taking payments" : "Setup not finished"}</Badge>}
      </div>
      {live ? (
        <dl className="pay-facts">
          <Row label="Provider">{a.provider === "stripe" ? "Stripe" : "Test provider (no real money)"}</Row>
          <Row label="Account">
            <span className="mono">{a.account_id}</span>
            {a.display_name ? ` · ${a.display_name}` : ""}
          </Row>
          <Row label="Mode">{a.livemode ? "Live" : "Test"}</Row>
          <Row label="Payouts">{a.payouts_enabled ? "On" : "Not yet"}</Row>
        </dl>
      ) : (
        <p className="pay-muted">Connect your own Stripe account to take card payments on invoices, payment links and subscriptions. Money goes straight to your account; go-high keeps only Stripe's ids.</p>
      )}
      <ul className="pay-caps" aria-label="What works now">
        {Object.entries(view.capabilities).map(([k, cap]) => (
          <li key={k}>
            {cap.available ? <CircleCheck size={16} className="pay-ok" aria-hidden /> : <CircleX size={16} className="pay-no" aria-hidden />}
            <span>
              <strong>{CAP_LABEL[k] ?? k}</strong>
              {cap.reason && <span className="pay-muted"> · {cap.reason}</span>}
            </span>
          </li>
        ))}
      </ul>
      {manage && (
        <div className="pay-actions pay-actions-start">
          {view.providers.map((p) =>
            live && a.provider === p.key ? null : (
              <span key={p.key} className="pay-provider">
                <Button variant={p.key === "stripe" ? "primary" : "secondary"} disabled={!p.available || !!busy} loading={busy === p.key} onClick={() => void connect(p.key)}>
                  {p.key === "stripe" ? (live ? "Switch to Stripe" : "Connect Stripe") : "Use the test provider"}
                </Button>
                {!p.available && p.reason && <span className="pay-muted">{p.reason}</span>}
              </span>
            ),
          )}
          {live && a.provider === "stripe" && a.status !== "active" && (
            <Button onClick={() => void connect("stripe")} loading={busy === "stripe"}>
              Finish setup with Stripe
            </Button>
          )}
          {live && (
            <>
              <Button
                variant="ghost"
                onClick={async () => {
                  try {
                    setView(await pay.refresh());
                  } catch (e) {
                    toast({ title: "Could not refresh", description: errorText(e), tone: "danger" });
                  }
                }}
              >
                <RefreshCw size={16} aria-hidden /> Refresh
              </Button>
              <Button variant="ghost" onClick={() => setDisconnecting(true)}>
                Disconnect
              </Button>
            </>
          )}
        </div>
      )}
      <Confirm
        open={disconnecting}
        title="Disconnect the provider?"
        text="Invoice pages and payment links stop taking card payments, and subscriptions stop charging cards. Past payments, refunds and their records stay. You can connect again later."
        action="Disconnect"
        onClose={() => setDisconnecting(false)}
        onConfirm={async () => {
          setDisconnecting(false);
          try {
            await pay.disconnect();
            load();
          } catch (e) {
            toast({ title: "Could not disconnect", description: errorText(e), tone: "danger" });
          }
        }}
      />
    </section>
  );
}

function Terms({ manage }: { manage: boolean }) {
  const toast = useToast();
  const [s, setS] = useState<Settings | null>(null);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [retry, setRetry] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    void pay.settings().then((x) => {
      setS(x);
      setDraft(x);
      setRetry(x.retry_days.join(", "));
    });
  }, []);
  if (!draft || !s) return <section className="pay-card" aria-busy="true"><h2>Invoices and retries</h2><p className="pay-muted">Loading…</p></section>;
  const set = (patch: Partial<Settings>) => setDraft({ ...draft, ...patch });
  async function save() {
    const days = retry.split(/[\s,]+/).filter(Boolean).map(Number);
    if (days.some((d) => !Number.isInteger(d) || d < 1 || d > 60)) return setErrors({ retry_days: "Days from 1 to 60, rising, separated by commas" });
    setBusy(true);
    try {
      const { next_invoice_number: _, ...rest } = draft;
      void _;
      const saved = await pay.saveSettings({ ...rest, retry_days: days });
      setS(saved);
      setDraft(saved);
      setErrors({});
      toast({ title: "Settings saved", tone: "success" });
    } catch (e) {
      setErrors(fieldsOf(e));
      toast({ title: "Could not save", description: errorText(e), tone: "danger" });
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="pay-card" aria-labelledby="pay-terms">
      <h2 id="pay-terms">Invoices and retries</h2>
      <fieldset className="pay-form" disabled={!manage}>
        <div className="pay-grid2">
          <Input label="Business name" value={draft.business_name} onChange={(e) => set({ business_name: e.target.value })} maxLength={200} />
          <Select label="Default currency" value={draft.default_currency} onValueChange={(v) => set({ default_currency: v })} options={CURRENCIES.map((c) => ({ value: c, label: c.toUpperCase() }))} disabled={!manage} />
        </div>
        <Textarea label="Business details" value={draft.business_details} onChange={(e) => set({ business_details: e.target.value })} rows={3} hint="Address and tax number, shown on every invoice" maxLength={1000} />
        <div className="pay-grid2">
          <Input label="Number prefix" value={draft.invoice_prefix} onChange={(e) => set({ invoice_prefix: e.target.value })} error={errors.invoice_prefix} hint={`Next: ${draft.invoice_prefix}${String(s.next_invoice_number).padStart(4, "0")}`} />
          <Input label="Days to pay" inputMode="numeric" value={String(draft.invoice_due_days)} onChange={(e) => set({ invoice_due_days: Number(e.target.value) || 0 })} error={errors.invoice_due_days} />
        </div>
        <Textarea label="Footer" value={draft.invoice_footer} onChange={(e) => set({ invoice_footer: e.target.value })} rows={2} maxLength={1000} />
        <div className="pay-grid2">
          <Input label="Retry a failed renewal after (days)" value={retry} onChange={(e) => setRetry(e.target.value)} error={errors.retry_days} hint="Counted from the invoice; up to 8 retries" />
          <Select label="When retries run out" value={draft.after_retries} onValueChange={(v) => set({ after_retries: v as Settings["after_retries"] })} options={[{ value: "cancel", label: "Cancel the subscription" }, { value: "unpaid", label: "Keep it, unpaid" }]} disabled={!manage} />
        </div>
        {manage && (
          <div className="pay-actions pay-actions-start">
            <Button variant="primary" loading={busy} onClick={() => void save()}>
              Save
            </Button>
          </div>
        )}
      </fieldset>
    </section>
  );
}

function Taxes({ manage }: { manage: boolean }) {
  const toast = useToast();
  const [rates, setRates] = useState<TaxRate[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [rate, setRate] = useState("");
  const [inclusive, setInclusive] = useState(false);
  const [error, setError] = useState<string>();
  const load = () => void pay.taxRates().then(setRates).catch(() => setRates([]));
  useEffect(load, []);
  return (
    <section className="pay-card" aria-labelledby="pay-taxes">
      <div className="pay-card-head">
        <h2 id="pay-taxes">Tax rates</h2>
        {manage && (
          <Button size="sm" onClick={() => setAdding(true)}>
            <Plus size={14} aria-hidden /> Add tax rate
          </Button>
        )}
      </div>
      <p className="pay-muted">Tax is worked out per line after discounts and rounded half up. An inclusive rate is already inside the price; an exclusive one is added on top.</p>
      {rates?.length ? (
        <ul className="pay-list">
          {rates.map((t) => (
            <li key={t.id}>
              <strong>{t.name}</strong>
              <span className="mono">{percent(t.percentage_bp)}</span>
              <span>{t.inclusive ? "Included in prices" : "Added on top"}</span>
              {t.region && <span className="pay-muted">{t.region}</span>}
              {manage ? (
                <Switch
                  label={t.active ? "On" : "Off"}
                  checked={t.active}
                  onCheckedChange={async (active) => {
                    try {
                      await pay.patchTaxRate(t.id, { active });
                      load();
                    } catch (e) {
                      toast({ title: "Could not change it", description: errorText(e), tone: "danger" });
                    }
                  }}
                />
              ) : (
                <Badge>{t.active ? "On" : "Off"}</Badge>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <p className="pay-muted">{rates ? "No tax rates yet." : "Loading…"}</p>
      )}
      <Confirm
        open={adding}
        title="New tax rate"
        text="A rate's percentage never changes once saved, so issued invoices keep theirs: switch it off and add a new one instead."
        action="Add tax rate"
        tone="primary"
        onClose={() => setAdding(false)}
        onConfirm={async () => {
          const bp = readPercent(rate);
          if (!name.trim() || bp === null) return setError("Give it a name and a percentage from 0 to 100");
          try {
            await pay.createTaxRate({ name: name.trim(), percentage_bp: bp, inclusive, region: "" });
            setAdding(false);
            setName("");
            setRate("");
            load();
          } catch (e) {
            setError(errorText(e));
          }
        }}
      >
        <div className="pay-form">
          <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Sales tax" maxLength={100} error={error} />
          <Input label="Percentage" value={rate} onChange={(e) => setRate(e.target.value)} inputMode="decimal" placeholder="8.25" />
          <Checkbox label="Included in prices (VAT style)" checked={inclusive} onCheckedChange={(v) => setInclusive(v === true)} />
        </div>
      </Confirm>
    </section>
  );
}
