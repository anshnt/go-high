import { Plus, Repeat } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { errorText } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { Button, Dialog, EmptyState, Input, Select, Sheet, Switch, Table, useToast, type Column } from "../ui";
import { pay } from "./api";
import { INVOICE_STATUS, invoiceName, subActions, SUB_STATUS } from "./meta";
import { every, money } from "./money";
import { Confirm, ContactPicker, day, fieldsOf, ListError, More, PricePicker, Row, Status, useList, usePrices } from "./shared";
import type { Subscription } from "./types";

const STATUSES = [{ value: "all", label: "All subscriptions" }, ...Object.entries(SUB_STATUS).map(([value, m]) => ({ value, label: m.label }))];
const plan = (s: Subscription) => `${s.product_name ?? "Plan"}${s.price?.nickname ? ` (${s.price.nickname})` : ""}`;

export function SubscriptionsView() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { can } = useCan();
  const [status, setStatus] = useState("all");
  const [creating, setCreating] = useState(false);
  const list = useList((cursor) => pay.subscriptions({ status: status === "all" ? undefined : status, cursor }), [status]);
  const columns: Column<Subscription>[] = [
    { key: "contact", header: "Customer", cell: (s) => s.contact?.display_name ?? <span className="pay-muted">Hidden</span> },
    { key: "plan", header: "Plan", cell: (s) => <Link className="pay-rowlink" to={`/payments/subscriptions/${s.id}`}>{`${plan(s)}${s.quantity > 1 ? ` × ${s.quantity}` : ""}`}</Link> },
    { key: "status", header: "Status", cell: (s) => <span className="pay-badges"><Status meta={SUB_STATUS[s.status]} />{s.cancel_at_period_end && <Status meta={{ label: "Ends at period end", tone: "warning" }} />}</span> },
    { key: "amount", header: "Amount", align: "right", mono: true, cell: (s) => (s.amount === null ? "" : `${money(s.amount, s.currency)} ${every(s.price?.interval ?? null, s.price?.interval_count)}`) },
    { key: "renews", header: "Period ends", cell: (s) => (["canceled", "incomplete_expired"].includes(s.status) ? "" : day(s.current_period_end)) },
  ];
  return (
    <>
      <div className="pay-toolbar">
        <Select aria-label="Status" value={status} onValueChange={setStatus} options={STATUSES} />
        <span className="pay-grow" />
        {can("payments.write") && (
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus size={16} aria-hidden /> New subscription
          </Button>
        )}
      </div>
      {list.error ? (
        <ListError error={list.error} onRetry={list.reload} what="subscriptions" />
      ) : (
        <>
          <Table
            caption="Subscriptions"
            columns={columns}
            rows={list.rows ?? []}
            rowId={(s) => s.id}
            loading={list.rows === null}
            onRowClick={(s) => navigate(`/payments/subscriptions/${s.id}`)}
            activeId={id ?? null}
            rowLabel={(s) => `${plan(s)} for ${s.contact?.display_name ?? "a hidden contact"}`}
            empty={<EmptyState icon={Repeat} title={status === "all" ? "No subscriptions yet" : "None in this state"} text="Bill a contact every week, month or year. Failed payments are retried on your schedule and the customer can pay a missed invoice on its link." />}
          />
          <More cursor={list.cursor} loading={list.loadingMore} onMore={list.loadMore} />
        </>
      )}
      {creating && (
        <NewSubscription
          onClose={() => setCreating(false)}
          onDone={(s) => {
            setCreating(false);
            list.reload();
            navigate(`/payments/subscriptions/${s.id}`);
          }}
        />
      )}
      {id && <SubscriptionDetail id={id} onClose={() => navigate("/payments/subscriptions")} onChanged={list.reload} />}
    </>
  );
}

function NewSubscription({ onClose, onDone }: { onClose: () => void; onDone: (s: Subscription) => void }) {
  const toast = useToast();
  const prices = usePrices({ type: "recurring" });
  const [contact, setContact] = useState<{ id: string; name: string } | null>(null);
  const [priceId, setPriceId] = useState<string | null>(null);
  const [quantity, setQuantity] = useState("1");
  const [coupon, setCoupon] = useState("");
  const [trial, setTrial] = useState("");
  const [sendInvoice, setSendInvoice] = useState(false);
  const [fields, setFields] = useState<Record<string, string>>({});
  async function submit() {
    const q = Number(quantity);
    const errors: Record<string, string> = {};
    if (!contact) errors.contact_id = "Choose a contact";
    if (!priceId) errors.price_id = "Choose a recurring price";
    if (!Number.isInteger(q) || q < 1) errors.quantity = "Enter a whole number";
    if (trial && !/^\d+$/.test(trial)) errors.trial_days = "Enter a number of days";
    if (Object.keys(errors).length) return setFields(errors);
    try {
      const s = await pay.createSubscription({ contact_id: contact!.id, price_id: priceId, quantity: q, coupon_code: coupon.trim() || undefined, trial_days: trial ? Number(trial) : undefined, collection: sendInvoice ? "send_invoice" : "charge_automatically" });
      toast({ title: "Subscription started", description: SUB_STATUS[s.status].hint, tone: "success" });
      onDone(s);
    } catch (e) {
      setFields(fieldsOf(e));
      toast({ title: "Could not start it", description: errorText(e), tone: "danger" });
    }
  }
  return (
    <Confirm open title="New subscription" text="Without a trial, the first invoice is sent at once and the subscription starts when it is paid; the card used is kept for renewals." action="Start subscription" tone="primary" onClose={onClose} onConfirm={submit}>
      <div className="pay-form">
        <ContactPicker label="Customer" value={contact} onChange={setContact} error={fields.contact_id} />
        <PricePicker label="Plan" prices={prices} value={priceId} onChange={setPriceId} error={fields.price_id} />
        <div className="pay-grid2">
          <Input label="Quantity" inputMode="numeric" value={quantity} onChange={(e) => setQuantity(e.target.value)} error={fields.quantity} />
          <Input label="Trial days" inputMode="numeric" value={trial} onChange={(e) => setTrial(e.target.value)} error={fields.trial_days} hint="Empty: the price's trial" />
        </div>
        <Input label="Discount code" value={coupon} onChange={(e) => setCoupon(e.target.value)} error={fields.coupon_code} placeholder="Optional" />
        <Switch label="Send each invoice to pay by link instead of charging the card" checked={sendInvoice} onCheckedChange={setSendInvoice} />
      </div>
    </Confirm>
  );
}

function SubscriptionDetail({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const { can } = useCan();
  const navigate = useNavigate();
  const [s, setS] = useState<Subscription | null>(null);
  const [error, setError] = useState<string>();
  const [cancelling, setCancelling] = useState<"end" | "now" | null>(null);
  const [changing, setChanging] = useState(false);
  const load = () => {
    setError(undefined);
    pay.subscription(id).then(setS).catch((e) => setError(errorText(e)));
  };
  useEffect(load, [id]);
  async function act(run: () => Promise<Subscription>, done: string) {
    try {
      setS(await run());
      toast({ title: done, tone: "success" });
      onChanged();
    } catch (e) {
      toast({ title: "That did not work", description: errorText(e), tone: "danger" });
    }
  }
  const actions = s ? subActions(s) : null;
  const write = can("payments.write");
  return (
    <Sheet open onOpenChange={(o) => !o && onClose()} title={s ? plan(s) : "Subscription"} description={s?.contact?.display_name}>
      {error ? (
        <ListError error={error} onRetry={load} what="this subscription" />
      ) : !s || !actions ? (
        <p className="pay-muted">Loading…</p>
      ) : (
        <div className="pay-detail">
          <div className="pay-detail-head">
            <span className="pay-badges">
              <Status meta={SUB_STATUS[s.status]} />
              {s.cancel_at_period_end && <Status meta={{ label: "Ends at period end", tone: "warning" }} />}
            </span>
            <strong className="pay-big">{s.amount === null ? "" : money(s.amount, s.currency)}</strong>
          </div>
          <p className="pay-muted">{SUB_STATUS[s.status].hint}</p>
          {write && (
            <div className="pay-actions pay-actions-start">
              {actions.change && <Button onClick={() => setChanging(true)}>Change plan</Button>}
              {actions.reactivate && <Button onClick={() => void act(() => pay.reactivate(s.id), s.cancel_at_period_end ? "It will renew again" : "The card will be tried again")}>{s.cancel_at_period_end ? "Keep it" : "Retry payment"}</Button>}
              {actions.cancelAtEnd && <Button onClick={() => setCancelling("end")}>Cancel at period end</Button>}
              {actions.cancelNow && (
                <Button variant="ghost" onClick={() => setCancelling("now")}>
                  Cancel now
                </Button>
              )}
            </div>
          )}
          <dl className="pay-facts">
            <Row label="Customer">{s.contact?.display_name ?? "Hidden"}</Row>
            <Row label="Billing">{`${s.amount === null ? "" : money(s.amount, s.currency)} ${every(s.price?.interval ?? null, s.price?.interval_count)}${s.quantity > 1 ? ` (${s.quantity} × ${money(s.price?.unit_amount ?? 0, s.currency)})` : ""}`}</Row>
            {s.trial_end && <Row label="Trial ends">{day(s.trial_end)}</Row>}
            <Row label="Current period">{s.current_period_start ? `${day(s.current_period_start)} to ${day(s.current_period_end)}` : "Not started"}</Row>
            <Row label="Collection">{s.collection === "charge_automatically" ? "Charges the kept card" : "Sends each invoice"}</Row>
            <Row label="Card">{s.card ? `${s.card.brand ?? "Card"} ending ${s.card.last4 ?? "····"}` : "None kept yet"}</Row>
            {s.credit_balance > 0 && <Row label="Credit">{money(s.credit_balance, s.currency)}</Row>}
            {s.canceled_at && <Row label="Ended">{day(s.canceled_at)}</Row>}
          </dl>
          <h3 className="pay-h3">Invoices</h3>
          <ul className="pay-list">
            {s.invoices?.map((i) => (
              <li key={i.id}>
                <button type="button" className="pay-link" onClick={() => navigate(`/payments/invoices/${i.id}`)}>
                  {invoiceName(i)}
                </button>
                <span>{day(i.issued_at ?? i.created_at)}</span>
                <span className="mono">{money(i.total, i.currency)}</span>
                <Status meta={INVOICE_STATUS[i.status]} />
              </li>
            ))}
          </ul>
        </div>
      )}
      <Confirm
        open={cancelling === "end"}
        title="Cancel at the end of the period?"
        text={`It stays active until ${day(s?.current_period_end)} and is not billed again. You can undo this until then.`}
        action="Cancel at period end"
        onClose={() => setCancelling(null)}
        onConfirm={async () => {
          setCancelling(null);
          await act(() => pay.cancelSubscription(s!.id, { at_period_end: true }), "It will end at the end of the period");
        }}
      />
      <Confirm
        open={cancelling === "now"}
        title="Cancel now?"
        text="It ends today and its unpaid invoices are voided. Nothing is refunded automatically: refund a payment from Transactions if you need to. This cannot be undone."
        action="Cancel now"
        onClose={() => setCancelling(null)}
        onConfirm={async () => {
          setCancelling(null);
          await act(() => pay.cancelSubscription(s!.id, { at_period_end: false }), "Subscription cancelled");
        }}
      />
      {changing && s && (
        <ChangePlan
          sub={s}
          onClose={() => setChanging(false)}
          onDone={(next) => {
            setChanging(false);
            setS(next);
            onChanged();
          }}
        />
      )}
    </Sheet>
  );
}

function ChangePlan({ sub, onClose, onDone }: { sub: Subscription; onClose: () => void; onDone: (s: Subscription) => void }) {
  const toast = useToast();
  const prices = usePrices({ type: "recurring", currency: sub.currency });
  const [priceId, setPriceId] = useState<string | null>(sub.price_id);
  const [quantity, setQuantity] = useState(String(sub.quantity));
  const [prorate, setProrate] = useState(true);
  const [busy, setBusy] = useState(false);
  const same = prices?.filter((p) => p.interval === sub.price?.interval && p.interval_count === sub.price?.interval_count) ?? null;
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && !busy && onClose()}
      title="Change plan"
      description="With proration, an invoice now charges the new plan for the rest of the period and credits the unused time of the old one; a downgrade's credit comes off the next invoice."
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button
            variant="primary"
            loading={busy}
            onClick={async () => {
              const q = Number(quantity);
              if (!Number.isInteger(q) || q < 1) return;
              setBusy(true);
              try {
                const next = await pay.changeSubscription(sub.id, { price_id: priceId ?? undefined, quantity: q, prorate });
                toast({ title: "Plan changed", tone: "success" });
                onDone(next);
              } catch (e) {
                toast({ title: "Could not change it", description: errorText(e), tone: "danger" });
                setBusy(false);
              }
            }}
          >
            Change plan
          </Button>
        </>
      }
    >
      <div className="pay-form">
        <PricePicker label="Plan" prices={same} value={priceId} onChange={setPriceId} />
        <Input label="Quantity" inputMode="numeric" value={quantity} onChange={(e) => setQuantity(e.target.value)} />
        <Switch label="Prorate the rest of this period" checked={prorate} onCheckedChange={setProrate} />
      </div>
    </Dialog>
  );
}
