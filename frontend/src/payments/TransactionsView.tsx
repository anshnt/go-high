import { ArrowLeftRight } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { errorText } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { Button, EmptyState, Input, Select, Sheet, Table, useToast, type Column } from "../ui";
import { pay } from "./api";
import { METHOD, PAYMENT_STATUS, paymentState, PROVIDER } from "./meta";
import { money, readAmount, toInput } from "./money";
import { Confirm, day, fieldsOf, ListError, More, MoneyInput, Row, Status, useList } from "./shared";
import type { Payment } from "./types";

const STATUSES = [{ value: "all", label: "All payments" }, ...Object.entries(PAYMENT_STATUS).map(([value, m]) => ({ value, label: m.label }))];
const REASONS = [
  { value: "requested_by_customer", label: "The customer asked" },
  { value: "duplicate", label: "Paid twice" },
  { value: "fraudulent", label: "Fraud" },
];

export function TransactionsView() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [status, setStatus] = useState("all");
  const list = useList((cursor) => pay.transactions({ status: status === "all" ? undefined : status, cursor }), [status]);
  const columns: Column<Payment>[] = [
    { key: "date", header: "Date", cell: (p) => <Link className="pay-rowlink" to={`/payments/transactions/${p.id}`}>{day(p.created_at)}</Link> },
    { key: "contact", header: "Customer", cell: (p) => p.contact?.display_name ?? <span className="pay-muted">Hidden</span> },
    { key: "amount", header: "Amount", align: "right", mono: true, cell: (p) => money(p.amount, p.currency) },
    { key: "status", header: "Status", cell: (p) => <Status meta={paymentState(p)} /> },
    { key: "how", header: "How", cell: (p) => (p.provider === "manual" ? METHOD[p.method] : PROVIDER[p.provider]) },
    { key: "invoice", header: "Invoice", mono: true, cell: (p) => p.invoice_number ?? "" },
  ];
  return (
    <>
      <div className="pay-toolbar">
        <Select aria-label="Status" value={status} onValueChange={setStatus} options={STATUSES} />
      </div>
      {list.error ? (
        <ListError error={list.error} onRetry={list.reload} what="transactions" />
      ) : (
        <>
          <Table
            caption="Transactions"
            columns={columns}
            rows={list.rows ?? []}
            rowId={(p) => p.id}
            loading={list.rows === null}
            onRowClick={(p) => navigate(`/payments/transactions/${p.id}`)}
            activeId={id ?? null}
            rowLabel={(p) => `${money(p.amount, p.currency)} from ${p.contact?.display_name ?? "a hidden contact"}`}
            empty={<EmptyState icon={ArrowLeftRight} title="No payments yet" text="Every payment shows here: card payments through your provider, failed attempts with their reason, and money you record by hand." />}
          />
          <More cursor={list.cursor} loading={list.loadingMore} onMore={list.loadMore} />
        </>
      )}
      {id && <TransactionDetail id={id} onClose={() => navigate("/payments/transactions")} onChanged={list.reload} />}
    </>
  );
}

function TransactionDetail({ id, onClose, onChanged }: { id: string; onClose: () => void; onChanged: () => void }) {
  const toast = useToast();
  const { can } = useCan();
  const [p, setP] = useState<Payment | null>(null);
  const [error, setError] = useState<string>();
  const [refunding, setRefunding] = useState(false);
  const [amount, setAmount] = useState("");
  const [reason, setReason] = useState("requested_by_customer");
  const [note, setNote] = useState("");
  const [fieldError, setFieldError] = useState<string>();
  const load = () => {
    setError(undefined);
    pay
      .transaction(id)
      .then((x) => {
        setP(x);
        setAmount(toInput(x.refundable ?? 0, x.currency));
      })
      .catch((e) => setError(errorText(e)));
  };
  useEffect(load, [id]);
  return (
    <Sheet open onOpenChange={(o) => !o && onClose()} title={p ? `${money(p.amount, p.currency)} payment` : "Payment"} description={p?.contact?.display_name}>
      {error ? (
        <ListError error={error} onRetry={load} what="this payment" />
      ) : !p ? (
        <p className="pay-muted">Loading…</p>
      ) : (
        <div className="pay-detail">
          <div className="pay-detail-head">
            <Status meta={paymentState(p)} />
            <strong className="pay-big">{money(p.amount, p.currency)}</strong>
          </div>
          {can("payments.refund") && (p.refundable ?? 0) > 0 && (
            <div className="pay-actions pay-actions-start">
              <Button onClick={() => setRefunding(true)}>Refund</Button>
            </div>
          )}
          <dl className="pay-facts">
            <Row label="Date">{day(p.created_at)}</Row>
            <Row label="Customer">{p.contact?.display_name ?? "Hidden"}</Row>
            <Row label="Invoice">{p.invoice_number ?? "None"}</Row>
            <Row label="How">{p.provider === "manual" ? `${METHOD[p.method]} (recorded by hand)` : PROVIDER[p.provider]}</Row>
            {p.amount_refunded > 0 && <Row label="Refunded">{money(p.amount_refunded, p.currency)}</Row>}
            {p.failure_message && <Row label="Why it failed">{p.failure_message}</Row>}
            {p.note && <Row label="Note">{p.note}</Row>}
          </dl>
          {!!p.refunds?.length && (
            <>
              <h3 className="pay-h3">Refunds</h3>
              <ul className="pay-list">
                {p.refunds.map((r) => (
                  <li key={r.id}>
                    <span>{day(r.created_at)}</span>
                    <span className="mono">{money(r.amount, p.currency)}</span>
                    <Status meta={{ label: r.status === "pending" ? "On its way" : r.status === "succeeded" ? "Refunded" : "Failed", tone: r.status === "failed" ? "danger" : r.status === "succeeded" ? "success" : "neutral" }} />
                    {r.failure_message && <span className="pay-muted">{r.failure_message}</span>}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
      {p && (
        <Confirm
          open={refunding}
          title="Refund this payment?"
          text={`Up to ${money(p.refundable ?? 0, p.currency)} can go back. ${p.provider === "manual" ? "Give the money back yourself; this records it." : "The provider sends it to the customer's card; it shows as on its way until the provider confirms."}`}
          action="Refund"
          onClose={() => setRefunding(false)}
          onConfirm={async () => {
            const a = readAmount(amount, p.currency);
            if ("error" in a) return setFieldError(a.error);
            if (a.amount === 0 || a.amount > (p.refundable ?? 0)) return setFieldError(`Enter up to ${money(p.refundable ?? 0, p.currency)}`);
            try {
              setP(await pay.refund(p.id, { amount: a.amount, reason, note }));
              setRefunding(false);
              toast({ title: "Refund on its way", tone: "success" });
              onChanged();
            } catch (e) {
              setFieldError(fieldsOf(e).amount ?? errorText(e));
            }
          }}
        >
          <div className="pay-form">
            <MoneyInput label="Amount" currency={p.currency} value={amount} onChange={setAmount} error={fieldError} />
            <Select label="Reason" value={reason} onValueChange={setReason} options={REASONS} />
            <Input label="Note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} placeholder="Only your team sees it" />
          </div>
        </Confirm>
      )}
    </Sheet>
  );
}
