import { ChevronLeft, CircleDollarSign, Download, Plus, ReceiptText, RefreshCw, ShieldAlert, Trash2, Wallet as WalletIcon } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { ApiError } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { whatWentWrong } from "../lib/errors";
import { PageHeader } from "../shell/PageHeader";
import { Badge, Button, Dialog, EmptyState, Input, Select, Skeleton, Switch, Tabs, TabsContent, TabsList, TabsTrigger, useToast, type Tone } from "../ui";
import { createCard, createTopup, deleteCard, exportLedger, getUsage, getWallet, listCards, listLedger, listMeters, patchCard, patchWallet, type Entry, type EntryKind, type LedgerFilters, type Meter, type RateCard, type Usage, type Wallet, type WalletPatch } from "./api";
import { CURRENCIES, formatMoney, minorStep, moneyInput, parseMoney, parsePercent, percent } from "./money";
import "./billing.css";

const STATUS: Record<Wallet["status"], { label: string; tone: Tone }> = {
  ok: { label: "Healthy", tone: "success" },
  low: { label: "Running low", tone: "warning" },
  empty: { label: "Empty: paid sends are stopped", tone: "danger" },
  capped: { label: "Monthly cap reached", tone: "danger" },
};
const KINDS: { value: EntryKind | "all"; label: string }[] = [
  { value: "all", label: "Every kind" },
  { value: "usage", label: "Usage" },
  { value: "reversal", label: "Refunds" },
  { value: "topup", label: "Top-ups" },
  { value: "adjustment", label: "Adjustments" },
];
const KIND_BADGE: Record<EntryKind, { label: string; tone: Tone }> = {
  usage: { label: "Usage", tone: "neutral" },
  reversal: { label: "Refund", tone: "info" },
  topup: { label: "Top-up", tone: "success" },
  adjustment: { label: "Adjustment", tone: "accent" },
};
const TABS = ["usage", "history", "settings", "prices"] as const;
type Tab = (typeof TABS)[number];
const newKey = () => (typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`);
const day = (iso: string) => new Date(iso).toLocaleDateString(undefined, { month: "short", day: "numeric" });
const when = (iso: string) => new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

/** Settings > Billing and usage: the wallet, what used it, its alerts and limits, and what each unit costs. */
export function BillingSettings() {
  const { can, ready, data } = useCan();
  const orgAdmin = data?.role?.source === "organization";
  const manage = can("billing.manage");
  const [params, setParams] = useSearchParams();
  const tab: Tab = (TABS as readonly string[]).includes(params.get("tab") ?? "") ? (params.get("tab") as Tab) : "usage";
  const [wallet, setWallet] = useState<Wallet | null>(null);
  const [error, setError] = useState<string>();
  const [topping, setTopping] = useState(false);
  const [version, setVersion] = useState(0); // bumps after a top-up so the lists read again

  const load = useCallback(() => {
    setError(undefined);
    getWallet().then(setWallet, (e) => setError(whatWentWrong(e)));
  }, []);
  const readable = can("usage.read");
  useEffect(() => {
    if (ready && readable) load();
  }, [ready, readable, load]);

  const changed = (w: Wallet) => {
    setWallet(w);
    setVersion((v) => v + 1);
  };

  const header = (
    <>
      <Link to="/settings" className="sh-back">
        <ChevronLeft size={16} aria-hidden />
        Settings
      </Link>
      <PageHeader
        title="Billing and usage"
        description="The wallet pays for SMS, email, WhatsApp, calls and AI. Every charge and refund is in the history."
        actions={
          manage && wallet ? (
            <Button variant="primary" onClick={() => setTopping(true)}>
              <Plus size={16} aria-hidden /> Top up
            </Button>
          ) : null
        }
      />
    </>
  );

  if (!ready) {
    return (
      <div className="sh-page bl-page">
        {header}
        <Loading />
      </div>
    );
  }
  if (!can("usage.read")) {
    return (
      <div className="sh-page bl-page">
        {header}
        <EmptyState icon={ShieldAlert} title="Your role cannot see billing" text="Ask an owner of this workspace for a role with the capability usage.read." />
      </div>
    );
  }
  return (
    <div className="sh-page bl-page">
      {header}
      {error && !wallet ? (
        <EmptyState icon={WalletIcon} title="Could not load the wallet" text={error} action={<Button onClick={load}><RefreshCw size={14} aria-hidden /> Try again</Button>} />
      ) : !wallet ? (
        <Loading />
      ) : (
        <>
          <Summary wallet={wallet} manage={manage} onTopUp={() => setTopping(true)} />
          <Tabs value={tab} onValueChange={(t) => setParams((p) => { p.set("tab", t); return p; }, { replace: true })}>
            <TabsList aria-label="Billing sections">
              <TabsTrigger value="usage">Usage</TabsTrigger>
              <TabsTrigger value="history">History</TabsTrigger>
              <TabsTrigger value="settings">Alerts and limits</TabsTrigger>
              <TabsTrigger value="prices">Prices</TabsTrigger>
            </TabsList>
            <TabsContent value="usage">
              <UsagePanel key={version} margins={orgAdmin} />
            </TabsContent>
            <TabsContent value="history">
              <HistoryPanel key={version} margins={orgAdmin} />
            </TabsContent>
            <TabsContent value="settings">
              <SettingsPanel wallet={wallet} manage={manage} orgAdmin={orgAdmin} onSaved={changed} />
            </TabsContent>
            <TabsContent value="prices">
              <PricesPanel orgAdmin={orgAdmin && manage} currency={wallet.currency} />
            </TabsContent>
          </Tabs>
          <TopUpDialog open={topping} wallet={wallet} onClose={() => setTopping(false)} onDone={changed} onSetUp={() => { setTopping(false); setParams((p) => { p.set("tab", "settings"); return p; }); }} />
        </>
      )}
    </div>
  );
}

function Loading() {
  return (
    <div className="bl-tiles" aria-busy aria-label="Loading billing">
      <Skeleton style={{ height: 112 }} />
      <Skeleton style={{ height: 112 }} />
      <Skeleton style={{ height: 112 }} />
    </div>
  );
}

function Summary({ wallet: w, manage, onTopUp }: { wallet: Wallet; manage: boolean; onTopUp: () => void }) {
  const status = STATUS[w.status];
  const share = w.monthly_cap ? Math.min(100, Math.round((w.month_spent / Math.max(1, w.monthly_cap)) * 100)) : null;
  const money = (m: number) => formatMoney(m, w.currency);
  return (
    <section className="bl-tiles" aria-label="Wallet">
      <div className="bl-tile" data-status={w.status}>
        <span className="bl-tile-label">Balance</span>
        <strong className="bl-balance">{formatMoney(w.balance, w.currency, { minor: true })}</strong>
        <Badge tone={status.tone}>{status.label}</Badge>
        <span className="bl-tile-note">
          {w.mode === "prepaid" ? "Prepaid: sends stop at zero" : w.credit_limit === null ? "Postpaid, no credit limit" : `Postpaid, credit up to ${money(w.credit_limit)}`}
        </span>
        {manage && w.status === "empty" && (
          <Button size="sm" variant="primary" onClick={onTopUp}>
            Top up now
          </Button>
        )}
      </div>
      <div className="bl-tile">
        <span className="bl-tile-label">Used this month</span>
        <strong className="bl-figure">{money(w.month_spent)}</strong>
        {share !== null ? (
          <>
            <div className="bl-meter" role="progressbar" aria-label="Share of the monthly cap used" aria-valuenow={share} aria-valuemin={0} aria-valuemax={100} data-tone={share >= 100 ? "danger" : share >= w.cap_alert_pct ? "warning" : "ok"}>
              <span style={{ width: `${share}%` }} />
            </div>
            <span className="bl-tile-note">
              {share} % of the {money(w.monthly_cap!)} cap, since {day(w.month_start)}
            </span>
          </>
        ) : (
          <span className="bl-tile-note">No monthly cap. Since {day(w.month_start)}.</span>
        )}
      </div>
      <div className="bl-tile">
        <span className="bl-tile-label">Auto-recharge</span>
        <strong className="bl-figure">{w.auto_recharge ? "On" : "Off"}</strong>
        <span className="bl-tile-note">
          {w.auto_recharge && w.recharge_amount !== null && w.recharge_below !== null
            ? `Adds ${money(w.recharge_amount)} when the balance falls below ${money(w.recharge_below)}`
            : w.payment_method
              ? `Card ${w.payment_method} on file`
              : "No payment method yet"}
        </span>
        <span className="bl-tile-note">{w.low_balance_at !== null ? `Alert below ${money(w.low_balance_at)}` : "No low balance alert"}</span>
      </div>
    </section>
  );
}

// ---- usage ----

function UsagePanel({ margins }: { margins: boolean }) {
  const [period, setPeriod] = useState<"month" | "last" | "quarter">("month");
  const [usage, setUsage] = useState<Usage | null>(null);
  const [error, setError] = useState<string>();
  useEffect(() => {
    let live = true;
    setUsage(null);
    setError(undefined);
    const now = new Date();
    const iso = (d: Date) => d.toISOString().slice(0, 10);
    const first = new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), 1));
    const range =
      period === "month"
        ? { from: iso(first), group: "day" as const }
        : period === "last"
          ? { from: iso(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 1, 1))), to: iso(new Date(first.getTime() - 86_400_000)), group: "day" as const }
          : { from: iso(new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth() - 2, 1))), group: "month" as const };
    getUsage(range).then(
      (u) => live && setUsage(u),
      (e) => live && setError(whatWentWrong(e)),
    );
    return () => {
      live = false;
    };
  }, [period]);

  const top = usage ? Math.max(1, ...usage.series.map((s) => s.price)) : 1;
  return (
    <div className="bl-panel">
      <div className="bl-toolbar">
        <Select aria-label="Period" value={period} onValueChange={(v) => setPeriod(v as typeof period)} options={[{ value: "month", label: "This month" }, { value: "last", label: "Last month" }, { value: "quarter", label: "Last three months" }]} />
        {usage && (
          <p className="bl-total">
            Charged <strong>{formatMoney(usage.price, usage.currency)}</strong>
            {margins && usage.cost !== undefined && <span className="bl-muted"> (cost {formatMoney(usage.cost, usage.currency)})</span>}
          </p>
        )}
      </div>
      {error ? (
        <p className="bl-error" role="alert">{error}</p>
      ) : !usage ? (
        <Skeleton style={{ height: 160 }} />
      ) : usage.meters.length === 0 ? (
        <EmptyState icon={ReceiptText} title="No usage in this period" text="Sends and other paid actions show here per service as soon as they happen, with what each cost." />
      ) : (
        <>
          <div className="bl-scroll">
          <table className="bl-table">
            <caption className="sr-only">Usage per service</caption>
            <thead>
              <tr>
                <th scope="col">Service</th>
                <th scope="col" className="bl-num">Quantity</th>
                <th scope="col" className="bl-num">Charged</th>
                {margins && <th scope="col" className="bl-num">Cost</th>}
                {margins && <th scope="col" className="bl-num">Margin</th>}
              </tr>
            </thead>
            <tbody>
              {usage.meters.map((m) => (
                <tr key={m.meter}>
                  <th scope="row">{m.label}</th>
                  <td className="bl-num">{m.quantity.toLocaleString()}</td>
                  <td className="bl-num">{formatMoney(m.price, usage.currency)}</td>
                  {margins && <td className="bl-num">{formatMoney(m.cost ?? 0, usage.currency)}</td>}
                  {margins && <td className="bl-num">{formatMoney(m.price - (m.cost ?? 0), usage.currency)}</td>}
                </tr>
              ))}
            </tbody>
          </table>
          </div>
          <figure className="bl-chart">
            <figcaption>Charged per {usage.group}</figcaption>
            <ol className="bl-bars">
              {usage.series.map((s) => (
                <li key={s.period}>
                  <span className="bl-bar-label">{usage.group === "day" ? day(s.period) : new Date(s.period).toLocaleDateString(undefined, { month: "short", year: "numeric", timeZone: "UTC" })}</span>
                  <span className="bl-bar" aria-hidden>
                    <span style={{ width: `${Math.max(2, Math.round((s.price / top) * 100))}%` }} />
                  </span>
                  <span className="bl-bar-value">{formatMoney(s.price, usage.currency)}</span>
                </li>
              ))}
            </ol>
          </figure>
        </>
      )}
    </div>
  );
}

// ---- history ----

function HistoryPanel({ margins }: { margins: boolean }) {
  const toast = useToast();
  const [filters, setFilters] = useState<LedgerFilters>({});
  const [rows, setRows] = useState<Entry[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string>();
  const [more, setMore] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [meters, setMeters] = useState<Meter[]>([]);

  useEffect(() => {
    listMeters().then((m) => setMeters(m.data), () => undefined);
  }, []);
  useEffect(() => {
    let live = true;
    setRows(null);
    setError(undefined);
    listLedger(filters).then(
      (p) => {
        if (!live) return;
        setRows(p.data);
        setCursor(p.next_cursor);
      },
      (e) => live && setError(whatWentWrong(e)),
    );
    return () => {
      live = false;
    };
  }, [filters]);

  const loadMore = async () => {
    if (!cursor) return;
    setMore(true);
    try {
      const p = await listLedger(filters, cursor);
      setRows((r) => [...(r ?? []), ...p.data]);
      setCursor(p.next_cursor);
    } catch (e) {
      toast({ title: "Could not load more", description: whatWentWrong(e), tone: "danger" });
    } finally {
      setMore(false);
    }
  };
  const download = async () => {
    setExporting(true);
    try {
      const { truncated } = await exportLedger(filters);
      toast({ title: "Export ready", description: truncated ? "Only the newest 50 000 rows fit; narrow the dates for the rest." : "The CSV is in your downloads.", tone: "success" });
    } catch (e) {
      toast({ title: "Could not export", description: whatWentWrong(e), tone: "danger" });
    } finally {
      setExporting(false);
    }
  };
  const set = (patch: LedgerFilters) => setFilters((f) => ({ ...f, ...patch }));
  const filtered = !!(filters.kind || filters.meter || filters.from || filters.to);

  return (
    <div className="bl-panel">
      <div className="bl-filters" role="search" aria-label="Filter the history">
        <Select label="Kind" value={filters.kind || "all"} onValueChange={(v) => set({ kind: v === "all" ? "" : (v as EntryKind) })} options={KINDS} />
        <Select label="Service" value={filters.meter || "all"} onValueChange={(v) => set({ meter: v === "all" ? "" : v })} options={[{ value: "all", label: "Every service" }, ...meters.map((m) => ({ value: m.meter, label: m.label }))]} />
        <Input label="From" type="date" value={filters.from ?? ""} max={filters.to || undefined} onChange={(e) => set({ from: e.target.value })} />
        <Input label="To" type="date" value={filters.to ?? ""} min={filters.from || undefined} onChange={(e) => set({ to: e.target.value })} />
        <div className="bl-filter-actions">
          {filtered && (
            <Button variant="ghost" onClick={() => setFilters({})}>
              Clear
            </Button>
          )}
          <Button onClick={() => void download()} loading={exporting} disabled={!rows?.length}>
            <Download size={14} aria-hidden /> Export CSV
          </Button>
        </div>
      </div>
      {error ? (
        <p className="bl-error" role="alert">{error}</p>
      ) : !rows ? (
        <Skeleton style={{ height: 220 }} />
      ) : rows.length === 0 ? (
        <EmptyState icon={CircleDollarSign} title={filtered ? "Nothing matches these filters" : "No charges yet"} text={filtered ? "Try another kind, service or date range." : "Top-ups, sends and refunds are listed here the moment they happen, with the balance after each."} action={filtered ? <Button onClick={() => setFilters({})}>Clear filters</Button> : undefined} />
      ) : (
        <>
          <div className="bl-scroll">
            <table className="bl-table bl-ledger">
              <caption className="sr-only">Wallet history, newest first</caption>
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">What</th>
                  <th scope="col" className="bl-num">Amount</th>
                  <th scope="col" className="bl-num">Balance</th>
                  <th scope="col">Kind</th>
                  {margins && <th scope="col" className="bl-num">Cost</th>}
                </tr>
              </thead>
              <tbody>
                {rows.map((e) => (
                  <tr key={e.id}>
                    <td className="bl-when">
                      <time dateTime={e.created_at}>{when(e.created_at)}</time>
                    </td>
                    <td className="bl-what">{e.description || e.meter || e.kind}</td>
                    <td className="bl-num" data-sign={e.amount > 0 ? "in" : e.amount < 0 ? "out" : "zero"}>
                      {e.amount > 0 ? "+" : ""}
                      {formatMoney(e.amount, e.currency)}
                    </td>
                    <td className="bl-num">{formatMoney(e.balance_after, e.currency)}</td>
                    <td>
                      <Badge tone={KIND_BADGE[e.kind].tone}>{KIND_BADGE[e.kind].label}</Badge>
                    </td>
                    {margins && <td className="bl-num bl-muted">{e.cost !== undefined && e.cost > 0 ? formatMoney(e.cost, e.currency) : ""}</td>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {cursor && (
            <Button className="bl-more" onClick={() => void loadMore()} loading={more}>
              Load older entries
            </Button>
          )}
        </>
      )}
    </div>
  );
}

// ---- top up ----

function TopUpDialog({ open, wallet: w, onClose, onDone, onSetUp }: { open: boolean; wallet: Wallet; onClose: () => void; onDone: (w: Wallet) => void; onSetUp: () => void }) {
  const toast = useToast();
  const presets = [10, 25, 50, 100].map((n) => n * 1_000_000);
  const [text, setText] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [key, setKey] = useState(newKey);
  useEffect(() => {
    if (open) {
      setText(moneyInput(25_000_000, w.currency));
      setError(undefined);
      setKey(newKey()); // a new attempt; a retry of this one (double click, dropped connection) reuses the key
    }
  }, [open, w.currency]);

  const submit = async () => {
    const parsed = parseMoney(text, w.currency);
    if (!parsed.ok) return setError(parsed.error);
    setBusy(true);
    setError(undefined);
    try {
      const t = await createTopup(parsed.micros, key);
      if (t.status === "succeeded") {
        onDone(t.wallet);
        toast({ title: `Added ${formatMoney(t.amount, t.currency)}`, description: `The balance is ${formatMoney(t.wallet.balance, t.currency, { minor: true })}.`, tone: "success" });
        onClose();
      } else if (t.status === "pending") {
        // the provider did not answer: the same key asks about the same top-up again, so the card is charged at most once
        setError("The payment provider has not answered yet. Press Add money again to check; the card is charged at most once.");
      } else {
        setError(t.error ?? "The payment did not go through.");
        setKey(newKey()); // that attempt is over: another try is a new top-up
        onDone(t.wallet);
      }
    } catch (e) {
      setError(e instanceof ApiError && e.fields?.amount ? `The amount ${e.fields.amount}` : whatWentWrong(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && !busy && onClose()}
      title="Top up the wallet"
      description={w.payment_method ? `Charged to the card ${w.payment_method}.` : undefined}
      footer={
        w.payment_method ? (
          <>
            <Button variant="ghost" onClick={onClose} disabled={busy}>
              Cancel
            </Button>
            <Button variant="primary" type="submit" form="bl-topup" loading={busy}>
              Add money
            </Button>
          </>
        ) : null
      }
    >
      {!w.payment_method ? (
        <div className="bl-stack">
          <p>Add a payment method first. It is saved under Alerts and limits, where auto-recharge can use it too.</p>
          <Button variant="primary" onClick={onSetUp}>
            Add a payment method
          </Button>
        </div>
      ) : (
        <form
          id="bl-topup"
          className="bl-stack"
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <div className="bl-presets" role="group" aria-label="Amounts">
            {presets.map((p) => (
              <Button key={p} size="sm" variant={parseMoney(text, w.currency).ok && (parseMoney(text, w.currency) as { micros: number }).micros === p ? "primary" : "secondary"} onClick={() => setText(moneyInput(p, w.currency))}>
                {formatMoney(p, w.currency)}
              </Button>
            ))}
          </div>
          <Input label={`Amount (${w.currency})`} inputMode="decimal" value={text} onChange={(e) => setText(e.target.value)} error={error} autoFocus hint={`Whole ${minorStep(w.currency) === 1_000_000 ? "units" : "cents"}, from ${formatMoney(1_000_000, w.currency)} to ${formatMoney(10_000_000_000, w.currency)}.`} />
          <p className="bl-muted">
            New balance: {(() => {
              const p = parseMoney(text, w.currency);
              return p.ok ? formatMoney(w.balance + p.micros, w.currency) : "-";
            })()}
          </p>
        </form>
      )}
    </Dialog>
  );
}

// ---- alerts and limits ----

type Form = { low: string; cap: string; capPct: string; auto: boolean; below: string; amount: string; method: string; mode: Wallet["mode"]; credit: string; currency: string };

const formOf = (w: Wallet): Form => ({
  low: moneyInput(w.low_balance_at, w.currency),
  cap: moneyInput(w.monthly_cap, w.currency),
  capPct: String(w.cap_alert_pct),
  auto: w.auto_recharge,
  below: moneyInput(w.recharge_below, w.currency),
  amount: moneyInput(w.recharge_amount, w.currency),
  method: "",
  mode: w.mode,
  credit: moneyInput(w.credit_limit, w.currency),
  currency: w.currency,
});

function SettingsPanel({ wallet: w, manage, orgAdmin, onSaved }: { wallet: Wallet; manage: boolean; orgAdmin: boolean; onSaved: (w: Wallet) => void }) {
  const toast = useToast();
  const [f, setF] = useState<Form>(() => formOf(w));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => setF(formOf(w)), [w]);
  const set = (patch: Partial<Form>) => setF((x) => ({ ...x, ...patch }));
  const currency = orgAdmin ? f.currency : w.currency;

  const build = (): { patch: WalletPatch; errors: Record<string, string> } => {
    const errs: Record<string, string> = {};
    const patch: WalletPatch = {};
    const amount = (key: keyof Form, field: keyof WalletPatch, now: number | null) => {
      const text = String(f[key]).trim();
      if (!text) {
        if (now !== null) (patch as Record<string, unknown>)[field] = null;
        return;
      }
      const p = parseMoney(text, currency);
      if (!p.ok) errs[field] = p.error;
      else if (p.micros !== now) (patch as Record<string, unknown>)[field] = p.micros;
    };
    amount("low", "low_balance_at", w.low_balance_at);
    amount("cap", "monthly_cap", w.monthly_cap);
    amount("below", "recharge_below", w.recharge_below);
    amount("amount", "recharge_amount", w.recharge_amount);
    const pct = Number(f.capPct);
    if (!Number.isInteger(pct) || pct < 1 || pct > 100) errs.cap_alert_pct = "A whole percentage from 1 to 100";
    else if (pct !== w.cap_alert_pct) patch.cap_alert_pct = pct;
    if (f.auto !== w.auto_recharge) patch.auto_recharge = f.auto;
    if (f.method.trim()) patch.payment_method = f.method.trim();
    if (orgAdmin) {
      if (f.mode !== w.mode) patch.mode = f.mode;
      if (f.currency !== w.currency) patch.currency = f.currency;
      amount("credit", "credit_limit", w.credit_limit);
    }
    return { patch, errors: errs };
  };
  const dirty = JSON.stringify(f) !== JSON.stringify(formOf(w));

  const save = async (extra: WalletPatch = {}) => {
    const built = build();
    if (Object.keys(built.errors).length) return setErrors(built.errors);
    setBusy(true);
    setErrors({});
    try {
      onSaved(await patchWallet({ ...built.patch, ...extra }));
      toast({ title: "Billing settings saved", tone: "success" });
    } catch (e) {
      if (e instanceof ApiError && e.fields) setErrors(e.fields);
      toast({ title: "Could not save", description: whatWentWrong(e), tone: "danger" });
    } finally {
      setBusy(false);
    }
  };

  const ro = !manage;
  return (
    <form
      className="bl-panel bl-settings"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      {ro && <p className="bl-note">Your role can see these settings; changing them needs the capability billing.manage.</p>}
      <fieldset className="bl-group" disabled={ro}>
        <legend>Alerts</legend>
        <p className="bl-muted">The people who manage billing get a notification once each time the balance falls below this.</p>
        <Input label={`Alert when the balance is below (${currency})`} inputMode="decimal" placeholder="No alert" value={f.low} onChange={(e) => set({ low: e.target.value })} error={errors.low_balance_at} />
      </fieldset>
      <fieldset className="bl-group" disabled={ro}>
        <legend>Monthly cap</legend>
        <p className="bl-muted">A hard stop: once this month's usage reaches the cap, paid sends are refused until next month or until the cap is raised.</p>
        <div className="bl-pair">
          <Input label={`Cap per month (${currency})`} inputMode="decimal" placeholder="No cap" value={f.cap} onChange={(e) => set({ cap: e.target.value })} error={errors.monthly_cap} />
          <Input label="Warn at (% of the cap)" inputMode="numeric" value={f.capPct} onChange={(e) => set({ capPct: e.target.value })} error={errors.cap_alert_pct} />
        </div>
      </fieldset>
      <fieldset className="bl-group" disabled={ro}>
        <legend>Payment method and auto-recharge</legend>
        <p className="bl-muted">
          {w.payment_method ? `A card ending ${w.payment_method.replace("…", "")} is saved.` : "No payment method is saved."} Card entry arrives with the payments module; until then the {w.provider} provider takes a token (one starting with pm_fake_decline is declined).
        </p>
        <div className="bl-pair">
          <Input label={w.payment_method ? "Replace with token" : "Payment method token"} placeholder="pm_..." value={f.method} onChange={(e) => set({ method: e.target.value })} error={errors.payment_method} autoComplete="off" spellCheck={false} />
          {w.payment_method && manage && (
            <Button variant="ghost" className="bl-align-end" onClick={() => void save({ payment_method: null })} disabled={busy}>
              <Trash2 size={14} aria-hidden /> Remove card
            </Button>
          )}
        </div>
        <Switch label="Top up automatically when the balance runs low" checked={f.auto} onCheckedChange={(on) => set({ auto: on })} disabled={ro} />
        {f.auto && (
          <div className="bl-pair">
            <Input label={`When the balance falls below (${currency})`} inputMode="decimal" value={f.below} onChange={(e) => set({ below: e.target.value })} error={errors.recharge_below} />
            <Input label={`Add (${currency})`} inputMode="decimal" value={f.amount} onChange={(e) => set({ amount: e.target.value })} error={errors.recharge_amount} />
          </div>
        )}
      </fieldset>
      <fieldset className="bl-group" disabled={!orgAdmin || ro}>
        <legend>Credit (set by the organization)</legend>
        <p className="bl-muted">{orgAdmin ? "Prepaid wallets stop paid sends at zero. Postpaid ones let the balance go negative, down to the credit limit." : "Only owners of the organization change these."}</p>
        <div className="bl-pair">
          <Select label="Mode" value={f.mode} onValueChange={(v) => set({ mode: v as Wallet["mode"] })} disabled={!orgAdmin || ro} options={[{ value: "prepaid", label: "Prepaid: stop at zero" }, { value: "postpaid", label: "Postpaid: allow a negative balance" }]} />
          <Select label="Currency" value={f.currency} onValueChange={(v) => set({ currency: v })} disabled={!orgAdmin || ro} options={CURRENCIES.map((c) => ({ value: c, label: c }))} />
        </div>
        {f.mode === "postpaid" && <Input label={`Credit limit (${currency})`} inputMode="decimal" placeholder="No limit" value={f.credit} onChange={(e) => set({ credit: e.target.value })} error={errors.credit_limit ?? errors.currency} />}
        {errors.currency && f.mode !== "postpaid" && <p className="bl-error" role="alert">{errors.currency}</p>}
      </fieldset>
      {manage && (
        <div className="bl-actions">
          <Button variant="ghost" onClick={() => { setF(formOf(w)); setErrors({}); }} disabled={!dirty || busy}>
            Discard changes
          </Button>
          <Button variant="primary" type="submit" loading={busy} disabled={!dirty}>
            Save changes
          </Button>
        </div>
      )}
    </form>
  );
}

// ---- prices and rate cards ----

const SCOPE_LABEL: Record<RateCard["scope"], string> = { organization: "Every workspace", brand: "This brand", workspace: "This workspace" };

function PricesPanel({ orgAdmin, currency }: { orgAdmin: boolean; currency: string }) {
  const toast = useToast();
  const [meters, setMeters] = useState<Meter[] | null>(null);
  const [cards, setCards] = useState<RateCard[] | null>(null);
  const [error, setError] = useState<string>();
  const [editing, setEditing] = useState<RateCard | "new" | null>(null);
  const [removing, setRemoving] = useState<RateCard | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setError(undefined);
    listMeters().then((m) => setMeters(m.data), (e) => setError(whatWentWrong(e)));
    if (orgAdmin) listCards().then((c) => setCards(c.data), (e) => setError(whatWentWrong(e)));
  }, [orgAdmin]);
  useEffect(load, [load]);
  const label = (meter: string) => meters?.find((m) => m.meter === meter)?.label ?? meter;

  const remove = async () => {
    if (!removing) return;
    setBusy(true);
    try {
      await deleteCard(removing.id);
      toast({ title: "Rate card removed", description: `${label(removing.meter)} is priced by the next card, or at cost.`, tone: "success" });
      setRemoving(null);
      load();
    } catch (e) {
      toast({ title: "Could not remove", description: whatWentWrong(e), tone: "danger" });
    } finally {
      setBusy(false);
    }
  };

  if (error) return <p className="bl-error" role="alert">{error}</p>;
  if (!meters) return <Skeleton style={{ height: 200 }} />;
  return (
    <div className="bl-panel">
      <section aria-labelledby="bl-prices">
        <h2 id="bl-prices" className="bl-h">What one unit costs this workspace</h2>
        <div className="bl-scroll">
          <table className="bl-table">
            <caption className="sr-only">Price per unit</caption>
            <thead>
              <tr>
                <th scope="col">Service</th>
                <th scope="col">Unit</th>
                <th scope="col" className="bl-num">Price</th>
                {orgAdmin && <th scope="col" className="bl-num">Cost</th>}
                {orgAdmin && <th scope="col">Priced by</th>}
              </tr>
            </thead>
            <tbody>
              {meters.map((m) => (
                <tr key={m.meter}>
                  <th scope="row">{m.label}</th>
                  <td>{m.unit}</td>
                  <td className="bl-num">{formatMoney(m.unit_price, m.currency)}</td>
                  {orgAdmin && <td className="bl-num bl-muted">{formatMoney(m.unit_cost ?? 0, m.currency)}</td>}
                  {orgAdmin && <td>{m.basis === "price" ? "Fixed price" : m.basis === "markup" ? "Markup" : m.basis === "hook" ? "Plan" : "At cost"}</td>}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
      {orgAdmin && (
        <section aria-labelledby="bl-cards" className="bl-cards">
          <div className="bl-toolbar">
            <h2 id="bl-cards" className="bl-h">Rate cards</h2>
            <Button onClick={() => setEditing("new")}>
              <Plus size={14} aria-hidden /> Add rate card
            </Button>
          </div>
          <p className="bl-muted">What your organization charges its workspaces: a fixed price per unit, or a markup over cost. The most specific card wins (this workspace, then its brand, then every workspace). Past charges keep their price.</p>
          {!cards ? (
            <Skeleton style={{ height: 80 }} />
          ) : cards.length === 0 ? (
            <EmptyState icon={ReceiptText} title="No rate cards yet" text="Without a card every unit is charged at cost. Add one to resell usage with a margin." action={<Button onClick={() => setEditing("new")}>Add rate card</Button>} />
          ) : (
            <ul className="bl-card-list">
              {cards.map((c) => (
                <li key={c.id} className="bl-card">
                  <div>
                    <strong>{label(c.meter)}</strong>
                    <span className="bl-muted">
                      {" "}
                      {SCOPE_LABEL[c.scope]} · {c.currency}
                    </span>
                  </div>
                  <span className="bl-card-value">{c.price !== null ? `${formatMoney(c.price, c.currency)} per unit` : `${percent(c.markup_bp ?? 0)} over cost`}</span>
                  <div className="bl-card-actions">
                    <Button size="sm" variant="ghost" onClick={() => setEditing(c)}>
                      Edit
                    </Button>
                    <Button size="sm" variant="ghost" onClick={() => setRemoving(c)} aria-label={`Remove the rate card for ${label(c.meter)}, ${SCOPE_LABEL[c.scope].toLowerCase()}`}>
                      <Trash2 size={14} aria-hidden />
                    </Button>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </section>
      )}
      {editing && <CardDialog card={editing === "new" ? null : editing} meters={meters} currency={currency} onClose={() => setEditing(null)} onSaved={() => { setEditing(null); load(); }} />}
      <Dialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title="Remove this rate card?"
        description={removing ? `${label(removing.meter)} for ${SCOPE_LABEL[removing.scope].toLowerCase()} will be priced by the next more general card, or at cost. Charges already made keep their price.` : undefined}
        footer={
          <>
            <Button variant="ghost" onClick={() => setRemoving(null)}>
              Keep it
            </Button>
            <Button variant="danger" onClick={() => void remove()} loading={busy}>
              Remove
            </Button>
          </>
        }
      />
    </div>
  );
}

function CardDialog({ card, meters, currency, onClose, onSaved }: { card: RateCard | null; meters: Meter[]; currency: string; onClose: () => void; onSaved: () => void }) {
  const [meter, setMeter] = useState(card?.meter ?? meters[0]?.meter ?? "sms.segment");
  const [scope, setScope] = useState<RateCard["scope"]>(card?.scope ?? "organization");
  const [cur, setCur] = useState(card?.currency ?? currency);
  const [how, setHow] = useState<"price" | "markup">(card && card.price === null ? "markup" : "price");
  const [value, setValue] = useState(card ? (card.price !== null ? moneyInput(card.price, card.currency) : String((card.markup_bp ?? 0) / 100)) : "");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [key] = useState(newKey);

  const submit = async () => {
    let body: { price: number | null; markup_bp: number | null };
    if (how === "price") {
      const p = parseMoney(value, cur, { whole: false });
      if (!p.ok) return setError(p.error);
      body = { price: p.micros, markup_bp: null };
    } else {
      const bp = parsePercent(value);
      if (bp === null) return setError("A percentage from -100 to 10000, like 25 or 12.5");
      body = { price: null, markup_bp: bp };
    }
    setBusy(true);
    setError(undefined);
    try {
      if (card) await patchCard(card.id, how === "price" ? { price: body.price } : { markup_bp: body.markup_bp });
      else await createCard({ meter, scope, currency: cur, ...(how === "price" ? { price: body.price } : { markup_bp: body.markup_bp }) }, key);
      onSaved();
    } catch (e) {
      setError(whatWentWrong(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={card ? "Change rate card" : "Add rate card"}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form="bl-card" loading={busy}>
            {card ? "Save" : "Add"}
          </Button>
        </>
      }
    >
      <form
        id="bl-card"
        className="bl-stack"
        onSubmit={(e) => {
          e.preventDefault();
          void submit();
        }}
      >
        <Select label="Service" value={meter} onValueChange={setMeter} disabled={!!card} options={meters.map((m) => ({ value: m.meter, label: `${m.label} (per ${m.unit})` }))} />
        <div className="bl-pair">
          <Select label="Applies to" value={scope} onValueChange={(v) => setScope(v as RateCard["scope"])} disabled={!!card} options={Object.entries(SCOPE_LABEL).map(([value, label]) => ({ value, label }))} />
          <Select label="Currency" value={cur} onValueChange={setCur} disabled={!!card} options={CURRENCIES.map((c) => ({ value: c, label: c }))} />
        </div>
        <Select label="Charge" value={how} onValueChange={(v) => setHow(v as "price" | "markup")} options={[{ value: "price", label: "A fixed price per unit" }, { value: "markup", label: "A markup over cost" }]} />
        <Input label={how === "price" ? `Price per unit (${cur})` : "Markup (%)"} inputMode="decimal" value={value} onChange={(e) => setValue(e.target.value)} error={error} placeholder={how === "price" ? "0.0100" : "25"} hint={how === "price" ? "Up to six decimals, so a fraction of a cent is fine." : "-100 makes it free; 25 adds a quarter to the cost."} autoFocus />
      </form>
    </Dialog>
  );
}
