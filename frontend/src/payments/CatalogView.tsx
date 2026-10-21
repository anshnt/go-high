// Products and prices, coupons and payment links.
import { Archive, Copy, Link2, Package, Plus, TicketPercent, X } from "lucide-react";
import { useEffect, useState } from "react";
import { errorText } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { Badge, Button, Checkbox, Dialog, EmptyState, Input, Select, Switch, Table, Textarea, useToast, type Column } from "../ui";
import { pay } from "./api";
import { CURRENCIES, money, percent, priceText, readAmount, readPercent } from "./money";
import { Confirm, fieldsOf, ListError, More, MoneyInput, PricePicker, useList, usePrices } from "./shared";
import type { Coupon, PaymentLink, Product, TaxRate } from "./types";

// --- products ---------------------------------------------------------------------------------------------------

export function ProductsView() {
  const { can } = useCan();
  const toast = useToast();
  const [archived, setArchived] = useState(false);
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState<Product | "new" | null>(null);
  const [archiving, setArchiving] = useState<Product | null>(null);
  const list = useList((cursor) => pay.products({ active: !archived, q: q || undefined, cursor }), [archived, q]);
  const columns: Column<Product>[] = [
    { key: "name", header: "Product", cell: (p) => <div className="pay-name"><strong>{p.name}</strong>{p.description && <span className="pay-muted">{p.description}</span>}</div> },
    { key: "prices", header: "Prices", cell: (p) => <div className="pay-prices">{p.prices.filter((x) => x.active || archived).map((x) => <span key={x.id}>{priceText(x)}{x.nickname ? ` · ${x.nickname}` : ""}{x.trial_days ? ` · ${x.trial_days}-day trial` : ""}</span>)}</div> },
    { key: "kind", header: "Kind", cell: (p) => <Badge>{p.kind}</Badge> },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (p) =>
        can("payments.write") && p.active ? (
          <span className="pay-row-actions">
            <Button size="sm" onClick={() => setAdding(p)}>
              Add price
            </Button>
            <Button size="icon" variant="ghost" aria-label={`Archive ${p.name}`} onClick={() => setArchiving(p)}>
              <Archive size={16} aria-hidden />
            </Button>
          </span>
        ) : null,
    },
  ];
  return (
    <>
      <div className="pay-toolbar">
        <Input type="search" aria-label="Search products" placeholder="Search products" value={q} onChange={(e) => setQ(e.target.value)} />
        <Switch label="Archived" checked={archived} onCheckedChange={setArchived} />
        <span className="pay-grow" />
        {can("payments.write") && (
          <Button variant="primary" onClick={() => setAdding("new")}>
            <Plus size={16} aria-hidden /> New product
          </Button>
        )}
      </div>
      {list.error ? (
        <ListError error={list.error} onRetry={list.reload} what="products" />
      ) : (
        <>
          <Table caption="Products" columns={columns} rows={list.rows ?? []} rowId={(p) => p.id} loading={list.rows === null} empty={<EmptyState icon={Package} title={archived ? "Nothing archived" : "No products yet"} text="A product has one or more prices: one time, every month or year, or tiered by quantity. The same catalog serves invoices, payment links and subscriptions." action={!archived && can("payments.write") ? <Button variant="primary" onClick={() => setAdding("new")}>New product</Button> : undefined} />} />
          <More cursor={list.cursor} loading={list.loadingMore} onMore={list.loadMore} />
        </>
      )}
      {adding && (
        <PriceDialog
          product={adding === "new" ? null : adding}
          onClose={() => setAdding(null)}
          onDone={() => {
            setAdding(null);
            list.reload();
          }}
        />
      )}
      <Confirm
        open={!!archiving}
        title={`Archive ${archiving?.name ?? ""}?`}
        text="Its prices can no longer be put on new invoices, links or subscriptions. Subscriptions already on them go on as they are."
        action="Archive"
        onClose={() => setArchiving(null)}
        onConfirm={async () => {
          const p = archiving!;
          setArchiving(null);
          try {
            await pay.patchProduct(p.id, { active: false });
            toast({ title: "Archived", description: p.name, tone: "success" });
            list.reload();
          } catch (e) {
            toast({ title: "Could not archive it", description: errorText(e), tone: "danger" });
          }
        }}
      />
    </>
  );
}

type TierDraft = { up_to: string; unit: string; flat: string };

function PriceDialog({ product, onClose, onDone }: { product: Product | null; onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [currency, setCurrency] = useState("usd");
  const [type, setType] = useState<"one_time" | "recurring">("one_time");
  const [scheme, setScheme] = useState<"fixed" | "tiered">("fixed");
  const [amount, setAmount] = useState("");
  const [interval, setInterval] = useState("month");
  const [trial, setTrial] = useState("0");
  const [mode, setMode] = useState<"graduated" | "volume">("graduated");
  const [tiers, setTiers] = useState<TierDraft[]>([{ up_to: "10", unit: "", flat: "" }, { up_to: "", unit: "", flat: "" }]);
  const [taxes, setTaxes] = useState<TaxRate[]>([]);
  const [tax, setTax] = useState("none");
  const [nickname, setNickname] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    void pay.taxRates().then((t) => setTaxes(t.filter((x) => x.active))).catch(() => {});
    if (product?.prices[0]) setCurrency(product.prices[0].currency);
  }, [product]);

  async function submit() {
    const e: Record<string, string> = {};
    if (!product && !name.trim()) e.name = "Name the product";
    const price: Record<string, unknown> = { currency, type, scheme, nickname, tax_rate_id: tax === "none" ? undefined : tax };
    if (scheme === "fixed") {
      const a = readAmount(amount, currency);
      if ("error" in a) e.amount = a.error;
      else price.unit_amount = a.amount;
    } else {
      price.tiers_mode = mode;
      price.tiers = tiers.map((t, i) => {
        const unit = readAmount(t.unit || "0", currency);
        const flat = readAmount(t.flat || "0", currency);
        const last = i === tiers.length - 1;
        if ("error" in unit) e[`tier.${i}`] = unit.error;
        if ("error" in flat) e[`tier.${i}`] = flat.error;
        if (!last && !/^\d+$/.test(t.up_to)) e[`tier.${i}`] = "Give each tier but the last an upper limit";
        return { up_to: last ? null : Number(t.up_to), unit_amount: "amount" in unit ? unit.amount : 0, flat_amount: "amount" in flat ? flat.amount : 0 };
      });
    }
    if (type === "recurring") {
      price.interval = interval;
      if (!/^\d+$/.test(trial)) e.trial = "Enter a number of days";
      else price.trial_days = Number(trial);
    }
    if (Object.keys(e).length) return setErrors(e);
    setBusy(true);
    try {
      if (product) await pay.addPrice(product.id, price);
      else await pay.createProduct({ name: name.trim(), description, prices: [price] });
      toast({ title: product ? "Price added" : "Product created", tone: "success" });
      onDone();
    } catch (err) {
      const f = fieldsOf(err);
      setErrors(Object.fromEntries(Object.entries(f).map(([k, v]) => [k.replace(/^(prices\.0|price)\./, ""), v])));
      toast({ title: "Could not save it", description: errorText(err), tone: "danger" });
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && !busy && onClose()}
      title={product ? `Add a price to ${product.name}` : "New product"}
      description="Amounts never change once saved: to charge something else, add a new price and archive the old one."
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" loading={busy} onClick={() => void submit()}>
            {product ? "Add price" : "Create product"}
          </Button>
        </>
      }
    >
      <div className="pay-form">
        {!product && (
          <>
            <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} error={errors.name} maxLength={200} autoFocus />
            <Textarea label="Description" value={description} onChange={(e) => setDescription(e.target.value)} rows={2} maxLength={2000} />
          </>
        )}
        <div className="pay-grid2">
          <Select label="Billing" value={type} onValueChange={(v) => setType(v as typeof type)} options={[{ value: "one_time", label: "One time" }, { value: "recurring", label: "Recurring" }]} />
          <Select label="Currency" value={currency} onValueChange={setCurrency} options={CURRENCIES.map((c) => ({ value: c, label: c.toUpperCase() }))} />
        </div>
        {type === "recurring" && (
          <div className="pay-grid2">
            <Select label="Every" value={interval} onValueChange={setInterval} options={["day", "week", "month", "year"].map((i) => ({ value: i, label: i }))} />
            <Input label="Trial days" inputMode="numeric" value={trial} onChange={(e) => setTrial(e.target.value)} error={errors.trial ?? errors.trial_days} />
          </div>
        )}
        <Select label="Pricing" value={scheme} onValueChange={(v) => setScheme(v as typeof scheme)} options={[{ value: "fixed", label: "A price per unit" }, { value: "tiered", label: "Tiered by quantity" }]} />
        {scheme === "fixed" ? (
          <MoneyInput label="Price" currency={currency} value={amount} onChange={setAmount} error={errors.amount ?? errors.unit_amount} />
        ) : (
          <fieldset className="pay-lines">
            <legend>Tiers</legend>
            <Select label="How tiers count" value={mode} onValueChange={(v) => setMode(v as typeof mode)} options={[{ value: "graduated", label: "Graduated: each unit at its tier's rate" }, { value: "volume", label: "Volume: every unit at the rate the total reaches" }]} />
            {tiers.map((t, i) => (
              <div key={i} className="pay-tier">
                <Input label={i === tiers.length - 1 ? "And above" : "Up to (units)"} value={i === tiers.length - 1 ? "∞" : t.up_to} disabled={i === tiers.length - 1} inputMode="numeric" onChange={(e) => setTiers((ts) => ts.map((x, j) => (j === i ? { ...x, up_to: e.target.value } : x)))} />
                <MoneyInput label="Per unit" currency={currency} value={t.unit} onChange={(unit) => setTiers((ts) => ts.map((x, j) => (j === i ? { ...x, unit } : x)))} />
                <MoneyInput label="Flat fee" currency={currency} value={t.flat} onChange={(flat) => setTiers((ts) => ts.map((x, j) => (j === i ? { ...x, flat } : x)))} />
                {tiers.length > 1 && i < tiers.length - 1 && (
                  <Button variant="ghost" size="icon" aria-label={`Remove tier ${i + 1}`} onClick={() => setTiers((ts) => ts.filter((_, j) => j !== i))}>
                    <X size={16} aria-hidden />
                  </Button>
                )}
                {errors[`tier.${i}`] && (
                  <p className="ui-hint" data-tone="danger">
                    {errors[`tier.${i}`]}
                  </p>
                )}
              </div>
            ))}
            {errors.tiers && (
              <p className="ui-hint" data-tone="danger">
                {errors.tiers}
              </p>
            )}
            <Button size="sm" onClick={() => setTiers((ts) => [...ts.slice(0, -1), { up_to: "", unit: "", flat: "" }, ts[ts.length - 1]])}>
              <Plus size={14} aria-hidden /> Add tier
            </Button>
          </fieldset>
        )}
        <div className="pay-grid2">
          <Select label="Tax" value={tax} onValueChange={setTax} options={[{ value: "none", label: "No tax" }, ...taxes.map((t) => ({ value: t.id, label: `${t.name} ${percent(t.percentage_bp)}${t.inclusive ? " incl." : ""}` }))]} />
          <Input label="Nickname" value={nickname} onChange={(e) => setNickname(e.target.value)} placeholder="Optional, e.g. Annual" maxLength={100} />
        </div>
      </div>
    </Dialog>
  );
}

// --- coupons ----------------------------------------------------------------------------------------------------

const off = (c: Coupon) => (c.percent_off_bp ? `${percent(c.percent_off_bp)} off` : `${money(c.amount_off ?? 0, c.currency ?? "usd")} off`);
const lasts = (c: Coupon) => (c.duration === "once" ? "once" : c.duration === "forever" ? "forever" : `for ${c.duration_months} months`);

export function CouponsView() {
  const { can } = useCan();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const list = useList((cursor) => pay.coupons(cursor), []);
  const columns: Column<Coupon>[] = [
    { key: "code", header: "Code", mono: true, cell: (c) => c.code },
    { key: "name", header: "Name", cell: (c) => c.name },
    { key: "off", header: "Discount", cell: (c) => `${off(c)}, ${lasts(c)}` },
    { key: "used", header: "Used", align: "right", mono: true, cell: (c) => `${c.times_redeemed}${c.max_redemptions ? ` of ${c.max_redemptions}` : ""}` },
    { key: "state", header: "State", cell: (c) => <Badge tone={c.active ? "success" : "neutral"}>{c.active ? "Active" : "Off"}</Badge> },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (c) =>
        can("payments.write") ? (
          <Switch
            label={c.active ? "On" : "Off"}
            checked={c.active}
            onCheckedChange={async (active) => {
              try {
                await pay.patchCoupon(c.id, { active });
                list.reload();
              } catch (e) {
                toast({ title: "Could not change it", description: errorText(e), tone: "danger" });
              }
            }}
          />
        ) : null,
    },
  ];
  return (
    <>
      <div className="pay-toolbar">
        <span className="pay-grow" />
        {can("payments.write") && (
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus size={16} aria-hidden /> New coupon
          </Button>
        )}
      </div>
      {list.error ? (
        <ListError error={list.error} onRetry={list.reload} what="coupons" />
      ) : (
        <>
          <Table caption="Coupons" columns={columns} rows={list.rows ?? []} rowId={(c) => c.id} loading={list.rows === null} empty={<EmptyState icon={TicketPercent} title="No coupons yet" text="A code for a percentage or an amount off. It works on invoices, payment links and subscriptions alike, with limits and an end date if you want them." />} />
          <More cursor={list.cursor} loading={list.loadingMore} onMore={list.loadMore} />
        </>
      )}
      {creating && (
        <NewCoupon
          onClose={() => setCreating(false)}
          onDone={() => {
            setCreating(false);
            list.reload();
          }}
        />
      )}
    </>
  );
}

function NewCoupon({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const [name, setName] = useState("");
  const [code, setCode] = useState("");
  const [kind, setKind] = useState<"percent" | "amount">("percent");
  const [value, setValue] = useState("");
  const [currency, setCurrency] = useState("usd");
  const [duration, setDuration] = useState("once");
  const [months, setMonths] = useState("3");
  const [limit, setLimit] = useState("");
  const [oncePer, setOncePer] = useState(false);
  const [errors, setErrors] = useState<Record<string, string>>({});
  async function submit() {
    const e: Record<string, string> = {};
    const body: Record<string, unknown> = { name: name.trim(), code: code.trim(), duration, once_per_contact: oncePer };
    if (!name.trim()) e.name = "Name it";
    if (!/^[A-Za-z0-9_-]{2,40}$/.test(code.trim())) e.code = "2 to 40 letters, digits, - or _";
    if (kind === "percent") {
      const bp = readPercent(value);
      if (!bp) e.value = "Enter a percentage from 0.01 to 100";
      else body.percent_off_bp = bp;
    } else {
      const a = readAmount(value, currency);
      if ("error" in a || a.amount === 0) e.value = "error" in a ? a.error : "Enter an amount";
      else Object.assign(body, { amount_off: a.amount, currency });
    }
    if (duration === "repeating") body.duration_months = Number(months);
    if (limit) body.max_redemptions = Number(limit);
    if (Object.keys(e).length) return setErrors(e);
    try {
      await pay.createCoupon(body);
      toast({ title: "Coupon created", description: code, tone: "success" });
      onDone();
    } catch (err) {
      setErrors(fieldsOf(err));
      toast({ title: "Could not create it", description: errorText(err), tone: "danger" });
    }
  }
  return (
    <Confirm open title="New coupon" text="Codes match whatever the case typed." action="Create coupon" tone="primary" onClose={onClose} onConfirm={submit}>
      <div className="pay-form">
        <div className="pay-grid2">
          <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} error={errors.name} maxLength={100} />
          <Input label="Code" value={code} onChange={(e) => setCode(e.target.value)} error={errors.code} className="mono" />
        </div>
        <div className="pay-grid2">
          <Select label="Takes off" value={kind} onValueChange={(v) => setKind(v as typeof kind)} options={[{ value: "percent", label: "A percentage" }, { value: "amount", label: "An amount" }]} />
          {kind === "percent" ? <Input label="Percent off" value={value} onChange={(e) => setValue(e.target.value)} error={errors.value ?? errors.percent_off_bp} inputMode="decimal" /> : <MoneyInput label="Amount off" currency={currency} value={value} onChange={setValue} error={errors.value ?? errors.amount_off} />}
        </div>
        {kind === "amount" && <Select label="Currency" value={currency} onValueChange={setCurrency} options={CURRENCIES.map((c) => ({ value: c, label: c.toUpperCase() }))} />}
        <div className="pay-grid2">
          <Select label="On subscriptions" value={duration} onValueChange={setDuration} options={[{ value: "once", label: "The first invoice" }, { value: "repeating", label: "For some months" }, { value: "forever", label: "Every invoice" }]} />
          {duration === "repeating" ? <Input label="Months" inputMode="numeric" value={months} onChange={(e) => setMonths(e.target.value)} error={errors.duration_months} /> : <Input label="Total uses" inputMode="numeric" value={limit} onChange={(e) => setLimit(e.target.value)} placeholder="No limit" error={errors.max_redemptions} />}
        </div>
        <Checkbox label="Once per customer" checked={oncePer} onCheckedChange={(v) => setOncePer(v === true)} />
      </div>
    </Confirm>
  );
}

// --- payment links ----------------------------------------------------------------------------------------------

export function LinksView() {
  const { can } = useCan();
  const toast = useToast();
  const [creating, setCreating] = useState(false);
  const list = useList((cursor) => pay.links(cursor), []);
  async function copy(l: PaymentLink) {
    await navigator.clipboard?.writeText(l.public_url);
    toast({ title: "Link copied", description: l.public_url, tone: "success" });
  }
  const columns: Column<PaymentLink>[] = [
    { key: "name", header: "Link", cell: (l) => <div className="pay-name"><strong>{l.name}</strong><span className="pay-muted mono">{l.public_url}</span></div> },
    { key: "items", header: "Items", align: "right", mono: true, cell: (l) => l.items.length },
    { key: "state", header: "State", cell: (l) => <Badge tone={l.active ? "success" : "neutral"}>{l.active ? "Live" : "Off"}</Badge> },
    {
      key: "actions",
      header: "",
      align: "right",
      cell: (l) => (
        <span className="pay-row-actions">
          <Button size="sm" onClick={() => void copy(l)} aria-label={`Copy the link of ${l.name}`}>
            <Copy size={14} aria-hidden /> Copy
          </Button>
          {can("payments.write") && (
            <Switch
              label={l.active ? "On" : "Off"}
              checked={l.active}
              onCheckedChange={async (active) => {
                try {
                  await pay.patchLink(l.id, { active });
                  list.reload();
                } catch (e) {
                  toast({ title: "Could not change it", description: errorText(e), tone: "danger" });
                }
              }}
            />
          )}
        </span>
      ),
    },
  ];
  return (
    <>
      <div className="pay-toolbar">
        <span className="pay-grow" />
        {can("payments.write") && (
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus size={16} aria-hidden /> New payment link
          </Button>
        )}
      </div>
      {list.error ? (
        <ListError error={list.error} onRetry={list.reload} what="payment links" />
      ) : (
        <>
          <Table caption="Payment links" columns={columns} rows={list.rows ?? []} rowId={(l) => l.id} loading={list.rows === null} empty={<EmptyState icon={Link2} title="No payment links yet" text="A hosted checkout to share by SMS, email or on your site. Prices come from your catalog, so a visitor can never change what they pay." />} />
          <More cursor={list.cursor} loading={list.loadingMore} onMore={list.loadMore} />
        </>
      )}
      {creating && (
        <NewLink
          onClose={() => setCreating(false)}
          onDone={() => {
            setCreating(false);
            list.reload();
          }}
        />
      )}
    </>
  );
}

function NewLink({ onClose, onDone }: { onClose: () => void; onDone: () => void }) {
  const toast = useToast();
  const prices = usePrices();
  const [name, setName] = useState("");
  const [priceId, setPriceId] = useState<string | null>(null);
  const [adjustable, setAdjustable] = useState(false);
  const [max, setMax] = useState("10");
  const [coupons, setCoupons] = useState(false);
  const [message, setMessage] = useState("");
  const [errors, setErrors] = useState<Record<string, string>>({});
  async function submit() {
    const e: Record<string, string> = {};
    if (!name.trim()) e.name = "Name it";
    if (!priceId) e.price = "Choose what it sells";
    if (adjustable && !(Number(max) >= 1)) e.max = "Enter a number";
    if (Object.keys(e).length) return setErrors(e);
    try {
      await pay.createLink({ name: name.trim(), items: [{ price_id: priceId, quantity: 1, adjustable, min: 1, max: adjustable ? Number(max) : 1 }], allow_coupons: coupons, success_message: message });
      toast({ title: "Payment link created", tone: "success" });
      onDone();
    } catch (err) {
      const f = fieldsOf(err);
      setErrors({ ...f, price: f["items.0.price_id"] ?? f.items });
      toast({ title: "Could not create it", description: errorText(err), tone: "danger" });
    }
  }
  return (
    <Confirm open title="New payment link" text="Visitors give their name and email, then pay on the provider's page. A recurring price starts a subscription." action="Create link" tone="primary" onClose={onClose} onConfirm={submit}>
      <div className="pay-form">
        <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} error={errors.name} maxLength={200} placeholder="Shown as the page title" />
        <PricePicker label="Sells" prices={prices} value={priceId} onChange={setPriceId} error={errors.price} />
        <Switch label="The customer chooses the quantity" checked={adjustable} onCheckedChange={setAdjustable} />
        {adjustable && <Input label="Most they can buy" inputMode="numeric" value={max} onChange={(e) => setMax(e.target.value)} error={errors.max} />}
        <Switch label="Take discount codes" checked={coupons} onCheckedChange={setCoupons} />
        <Textarea label="Thank you message" value={message} onChange={(e) => setMessage(e.target.value)} rows={2} maxLength={1000} placeholder="Shown after paying" />
      </div>
    </Confirm>
  );
}
