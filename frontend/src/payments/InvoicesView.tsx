import { Copy, ExternalLink, FileText, Plus, Send, Trash2, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router";
import { errorText } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { Button, EmptyState, Input, Select, Sheet, Table, Textarea, useToast, type Column } from "../ui";
import { pay, type InvoiceInput } from "./api";
import { INVOICE_STATUS, invoiceName, METHOD } from "./meta";
import { CURRENCIES, money, percent, readAmount, toInput } from "./money";
import { Confirm, ContactPicker, day, fieldsOf, ListError, More, MoneyInput, PricePicker, Row, Status, useList, usePrices } from "./shared";
import type { Invoice, TaxRate } from "./types";

const STATUSES = [{ value: "all", label: "All invoices" }, ...Object.entries(INVOICE_STATUS).map(([value, m]) => ({ value, label: m.label }))];

export function InvoicesView() {
  const { id } = useParams();
  const navigate = useNavigate();
  const { can } = useCan();
  const [status, setStatus] = useState("all");
  const [q, setQ] = useState("");
  const [editing, setEditing] = useState<Invoice | "new" | null>(null);
  const list = useList((cursor) => pay.invoices({ status: status === "all" ? undefined : status, q: q || undefined, cursor }), [status, q]);

  const columns: Column<Invoice>[] = [
    { key: "number", header: "Invoice", mono: true, cell: (i) => invoiceName(i) },
    { key: "contact", header: "Customer", cell: (i) => i.contact?.display_name ?? <span className="pay-muted">Hidden</span> },
    { key: "status", header: "Status", cell: (i) => <Status meta={INVOICE_STATUS[i.status]} /> },
    { key: "total", header: "Total", align: "right", mono: true, cell: (i) => money(i.total, i.currency) },
    { key: "due", header: "Due", align: "right", mono: true, cell: (i) => (i.status === "open" ? money(i.amount_due, i.currency) : "") },
    { key: "date", header: "Due date", cell: (i) => (i.status === "open" ? day(i.due_at) : i.paid_at ? `Paid ${day(i.paid_at)}` : day(i.issued_at ?? i.created_at)) },
  ];

  return (
    <>
      <div className="pay-toolbar">
        <Input type="search" aria-label="Search by invoice number" placeholder="Search by number" value={q} onChange={(e) => setQ(e.target.value)} />
        <Select aria-label="Status" value={status} onValueChange={setStatus} options={STATUSES} />
        <span className="pay-grow" />
        {can("payments.write") && (
          <Button variant="primary" onClick={() => setEditing("new")}>
            <Plus size={16} aria-hidden /> New invoice
          </Button>
        )}
      </div>
      {list.error ? (
        <ListError error={list.error} onRetry={list.reload} what="invoices" />
      ) : (
        <>
          <Table
            caption="Invoices"
            columns={columns}
            rows={list.rows ?? []}
            rowId={(i) => i.id}
            loading={list.rows === null}
            onRowClick={(i) => navigate(`/payments/invoices/${i.id}`)}
            activeId={id ?? null}
            rowLabel={(i) => `${invoiceName(i)} for ${i.contact?.display_name ?? "a hidden contact"}`}
            empty={
              <EmptyState
                icon={FileText}
                title={status === "all" && !q ? "No invoices yet" : "No invoices match"}
                text={status === "all" && !q ? "Bill a contact for products or custom work. Tax and discounts are worked out for you, and the customer pays on a hosted page." : "Try another status or number."}
                action={status === "all" && !q && can("payments.write") ? <Button variant="primary" onClick={() => setEditing("new")}>New invoice</Button> : undefined}
              />
            }
          />
          <More cursor={list.cursor} loading={list.loadingMore} onMore={list.loadMore} />
        </>
      )}
      {editing && (
        <InvoiceEditor
          initial={editing === "new" ? null : editing}
          onClose={() => setEditing(null)}
          onSaved={(inv) => {
            setEditing(null);
            list.reload();
            navigate(`/payments/invoices/${inv.id}`);
          }}
        />
      )}
      {id && <InvoiceDetail id={id} onClose={() => navigate("/payments/invoices")} onChanged={list.reload} onEdit={(inv) => setEditing(inv)} />}
    </>
  );
}

type LineDraft = { key: number; price_id: string | null; description: string; amount: string; quantity: string; tax_rate_id: string };
let lineKey = 0;
const blank = (): LineDraft => ({ key: ++lineKey, price_id: null, description: "", amount: "", quantity: "1", tax_rate_id: "" });

function InvoiceEditor({ initial, onClose, onSaved }: { initial: Invoice | null; onClose: () => void; onSaved: (i: Invoice) => void }) {
  const toast = useToast();
  const prices = usePrices();
  const [taxes, setTaxes] = useState<TaxRate[]>([]);
  const [contact, setContact] = useState<{ id: string; name: string } | null>(initial?.contact ? { id: initial.contact.id, name: initial.contact.display_name } : null);
  const [currency, setCurrency] = useState(initial?.currency ?? "usd");
  const [lines, setLines] = useState<LineDraft[]>(() =>
    initial?.lines?.length
      ? initial.lines.map((l) => ({ key: ++lineKey, price_id: l.price_id, description: l.description, amount: l.price_id ? "" : toInput(l.unit_amount, initial.currency), quantity: String(l.quantity), tax_rate_id: l.tax_rate_id ?? "" }))
      : [blank()],
  );
  const [coupon, setCoupon] = useState("");
  const [due, setDue] = useState(initial?.due_at ? initial.due_at.slice(0, 10) : "");
  const [memo, setMemo] = useState(initial?.memo ?? "");
  const [preview, setPreview] = useState<Invoice | null>(null);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState<"save" | "send" | null>(null);

  useEffect(() => {
    void pay.taxRates().then((t) => setTaxes(t.filter((x) => x.active))).catch(() => setTaxes([]));
    if (!initial) void pay.settings().then((s) => setCurrency(s.default_currency)).catch(() => {});
  }, [initial]);

  const built = useMemo(() => {
    const errors: Record<string, string> = {};
    const out: InvoiceInput["lines"] = [];
    lines.forEach((l, i) => {
      const quantity = Number(l.quantity);
      if (!Number.isInteger(quantity) || quantity < 1) errors[`lines.${i}.quantity`] = "Enter a whole number";
      if (l.price_id) {
        out.push({ price_id: l.price_id, quantity, description: l.description || undefined, tax_rate_id: l.tax_rate_id || undefined });
      } else if (l.description || l.amount) {
        const a = readAmount(l.amount, currency);
        if ("error" in a) errors[`lines.${i}.unit_amount`] = a.error;
        if (!l.description.trim()) errors[`lines.${i}.description`] = "Describe the line";
        out.push({ description: l.description.trim(), unit_amount: "amount" in a ? a.amount : 0, quantity, tax_rate_id: l.tax_rate_id || undefined });
      }
    });
    const body: InvoiceInput = { contact_id: contact?.id ?? "", currency, lines: out, coupon_code: coupon.trim() || undefined, memo, due_at: due ? new Date(`${due}T23:59:00`).toISOString() : undefined };
    return { body, errors };
  }, [lines, contact, currency, coupon, memo, due]);

  // the server works out every total; ask it again a moment after the last change
  useEffect(() => {
    if (!contact || !built.body.lines.length || Object.keys(built.errors).length) {
      setPreview(null);
      return;
    }
    const t = setTimeout(() => {
      pay
        .preview(built.body)
        .then((p) => {
          setPreview(p);
          setFields({});
        })
        .catch((e) => {
          setPreview(null);
          setFields(fieldsOf(e));
        });
    }, 350);
    return () => clearTimeout(t);
  }, [built, contact]);

  const err = (k: string) => built.errors[k] ?? fields[k];
  const pricesInCurrency = prices?.filter((p) => p.currency === currency) ?? null;

  async function save(send: boolean) {
    if (!contact) return setFields({ contact_id: "Choose who the invoice is for" });
    if (Object.keys(built.errors).length || !built.body.lines.length) return setFields({ lines: "Add at least one complete line" });
    setBusy(send ? "send" : "save");
    try {
      let inv = initial ? await pay.patchInvoice(initial.id, built.body) : await pay.createInvoice(built.body);
      if (send) inv = await pay.sendInvoice(inv.id);
      toast({ title: send ? `Invoice ${inv.number} sent` : "Draft saved", description: send ? "The customer can pay it on its link." : undefined, tone: "success" });
      onSaved(inv);
    } catch (e) {
      setFields(fieldsOf(e));
      toast({ title: "Could not save the invoice", description: errorText(e), tone: "danger" });
      setBusy(null);
    }
  }

  return (
    <Sheet open onOpenChange={(o) => !o && !busy && onClose()} title={initial ? "Edit draft invoice" : "New invoice"} description="Totals, tax and discounts are worked out by the server as you type.">
      <div className="pay-form">
        <ContactPicker label="Bill to" value={contact} onChange={setContact} error={fields.contact_id} />
        <Select label="Currency" value={currency} onValueChange={setCurrency} options={CURRENCIES.map((c) => ({ value: c, label: c.toUpperCase() }))} />
        <fieldset className="pay-lines">
          <legend>Lines</legend>
          {lines.map((l, i) => (
            <div key={l.key} className="pay-line">
              <div className="pay-line-main">
                <PricePicker
                  label={`Line ${i + 1} product`}
                  prices={pricesInCurrency}
                  value={l.price_id}
                  onChange={(price_id) => setLines((ls) => ls.map((x) => (x.key === l.key ? { ...x, price_id, amount: "" } : x)))}
                  error={err(`lines.${i}.price_id`)}
                />
                {l.price_id && (
                  <Button size="sm" variant="ghost" onClick={() => setLines((ls) => ls.map((x) => (x.key === l.key ? { ...x, price_id: null } : x)))}>
                    Use a custom line instead
                  </Button>
                )}
                <Input label="Description" value={l.description} placeholder={l.price_id ? "The product's name" : "What it is for"} onChange={(e) => setLines((ls) => ls.map((x) => (x.key === l.key ? { ...x, description: e.target.value } : x)))} error={err(`lines.${i}.description`)} maxLength={500} />
              </div>
              <div className="pay-line-nums">
                {!l.price_id && <MoneyInput label="Unit price" currency={currency} value={l.amount} onChange={(amount) => setLines((ls) => ls.map((x) => (x.key === l.key ? { ...x, amount } : x)))} error={err(`lines.${i}.unit_amount`)} />}
                <Input label="Qty" inputMode="numeric" value={l.quantity} onChange={(e) => setLines((ls) => ls.map((x) => (x.key === l.key ? { ...x, quantity: e.target.value } : x)))} error={err(`lines.${i}.quantity`)} />
                <Select label="Tax" value={l.tax_rate_id || "none"} onValueChange={(v) => setLines((ls) => ls.map((x) => (x.key === l.key ? { ...x, tax_rate_id: v === "none" ? "" : v } : x)))} options={[{ value: "none", label: l.price_id ? "The price's" : "No tax" }, ...taxes.map((t) => ({ value: t.id, label: `${t.name} ${percent(t.percentage_bp)}${t.inclusive ? " incl." : ""}` }))]} />
                {lines.length > 1 && (
                  <Button variant="ghost" size="icon" aria-label={`Remove line ${i + 1}`} onClick={() => setLines((ls) => ls.filter((x) => x.key !== l.key))}>
                    <X size={16} aria-hidden />
                  </Button>
                )}
              </div>
            </div>
          ))}
          {fields.lines && (
            <p className="ui-hint" data-tone="danger">
              {fields.lines}
            </p>
          )}
          <Button size="sm" onClick={() => setLines((ls) => [...ls, blank()])}>
            <Plus size={14} aria-hidden /> Add line
          </Button>
        </fieldset>
        <div className="pay-grid2">
          <Input label="Discount code" value={coupon} onChange={(e) => setCoupon(e.target.value)} error={fields.coupon_code} placeholder="Optional" />
          <Input label="Due date" type="date" value={due} onChange={(e) => setDue(e.target.value)} hint="Leave empty for the workspace's terms" />
        </div>
        <Textarea label="Note to the customer" value={memo} onChange={(e) => setMemo(e.target.value)} maxLength={2000} rows={3} />
        <Totals invoice={preview} />
        <div className="pay-actions">
          <Button onClick={onClose} disabled={!!busy}>
            Cancel
          </Button>
          <Button onClick={() => void save(false)} loading={busy === "save"} disabled={!!busy}>
            Save draft
          </Button>
          <Button variant="primary" onClick={() => void save(true)} loading={busy === "send"} disabled={!!busy}>
            <Send size={16} aria-hidden /> Save and send
          </Button>
        </div>
      </div>
    </Sheet>
  );
}

function Totals({ invoice }: { invoice: Invoice | null }) {
  if (!invoice) return <p className="pay-muted pay-totals-empty">Choose a contact and add a line to see the totals.</p>;
  const c = invoice.currency;
  return (
    <dl className="pay-totals" aria-live="polite">
      <Row label="Subtotal">{money(invoice.subtotal, c)}</Row>
      {invoice.discount > 0 && <Row label="Discount">{money(-invoice.discount, c)}</Row>}
      {invoice.tax > 0 && <Row label="Tax">{money(invoice.tax, c)}</Row>}
      {invoice.credit_applied > 0 && <Row label="Credit applied">{money(-invoice.credit_applied, c)}</Row>}
      <Row label="Total">
        <strong>{money(invoice.total, c)}</strong>
      </Row>
    </dl>
  );
}

function InvoiceDetail({ id, onClose, onChanged, onEdit }: { id: string; onClose: () => void; onChanged: () => void; onEdit: (i: Invoice) => void }) {
  const toast = useToast();
  const { can } = useCan();
  const [inv, setInv] = useState<Invoice | null>(null);
  const [error, setError] = useState<string>();
  const [confirm, setConfirm] = useState<"void" | "delete" | null>(null);
  const [recording, setRecording] = useState(false);
  const [busy, setBusy] = useState(false);
  const load = () => {
    setError(undefined);
    pay.invoice(id).then(setInv).catch((e) => setError(errorText(e)));
  };
  useEffect(load, [id]);

  async function act(run: () => Promise<Invoice | void>, done: string) {
    setBusy(true);
    try {
      const out = await run();
      if (out) setInv(out);
      toast({ title: done, tone: "success" });
      onChanged();
    } catch (e) {
      toast({ title: "That did not work", description: errorText(e), tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  const c = inv?.currency ?? "usd";
  return (
    <Sheet open onOpenChange={(o) => !o && onClose()} title={inv ? `Invoice ${invoiceName(inv)}` : "Invoice"} description={inv?.contact?.display_name}>
      {error ? (
        <ListError error={error} onRetry={load} what="this invoice" />
      ) : !inv ? (
        <p className="pay-muted">Loading…</p>
      ) : (
        <div className="pay-detail">
          <div className="pay-detail-head">
            <Status meta={INVOICE_STATUS[inv.status]} />
            <strong className="pay-big">{money(inv.total, c)}</strong>
          </div>
          <div className="pay-actions pay-actions-start">
            {inv.status === "draft" && can("payments.write") && (
              <>
                <Button variant="primary" loading={busy} onClick={() => void act(() => pay.sendInvoice(inv.id), "Invoice sent")}>
                  <Send size={16} aria-hidden /> Send
                </Button>
                <Button onClick={() => onEdit(inv)}>Edit</Button>
                <Button variant="ghost" onClick={() => setConfirm("delete")}>
                  <Trash2 size={16} aria-hidden /> Delete
                </Button>
              </>
            )}
            {inv.public_url && (
              <>
                <Button
                  onClick={async () => {
                    await navigator.clipboard?.writeText(inv.public_url!);
                    toast({ title: "Link copied", description: "The customer pays and prints the invoice there.", tone: "success" });
                  }}
                >
                  <Copy size={16} aria-hidden /> Copy link
                </Button>
                <a className="ui-btn" data-variant="secondary" data-size="md" href={inv.public_url} target="_blank" rel="noreferrer">
                  <ExternalLink size={16} aria-hidden /> Open page
                </a>
              </>
            )}
            {inv.status === "open" && can("payments.refund") && (
              <>
                <Button onClick={() => setRecording(true)}>Record payment</Button>
                {inv.amount_paid === 0 && (
                  <Button variant="ghost" onClick={() => setConfirm("void")}>
                    Void
                  </Button>
                )}
              </>
            )}
          </div>
          <dl className="pay-facts">
            <Row label="Customer">{inv.contact?.display_name ?? "Hidden"}</Row>
            <Row label="Issued">{day(inv.issued_at)}</Row>
            <Row label="Due">{day(inv.due_at)}</Row>
            {inv.paid_at && <Row label="Paid">{day(inv.paid_at)}</Row>}
            {inv.status === "open" && <Row label="Amount due">{money(inv.amount_due, c)}</Row>}
            {inv.next_attempt_at && <Row label="Next retry">{day(inv.next_attempt_at)}</Row>}
          </dl>
          <table className="pay-table">
            <caption className="sr-only">Lines</caption>
            <thead>
              <tr>
                <th scope="col">Description</th>
                <th scope="col" className="num">
                  Qty
                </th>
                <th scope="col" className="num">
                  Amount
                </th>
              </tr>
            </thead>
            <tbody>
              {inv.lines?.map((l) => (
                <tr key={l.id}>
                  <td>
                    {l.description}
                    {l.tax_name && (
                      <span className="pay-muted">
                        {" "}
                        · {l.tax_name} {percent(l.tax_bp)}
                        {l.tax_inclusive ? " incl." : ""}
                      </span>
                    )}
                  </td>
                  <td className="num mono">{l.quantity}</td>
                  <td className="num mono">{money(l.amount, c)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <Totals invoice={inv} />
          {inv.memo && <p className="pay-note">{inv.memo}</p>}
          {!!inv.payments?.length && (
            <>
              <h3 className="pay-h3">Payments</h3>
              <ul className="pay-list">
                {inv.payments.map((p) => (
                  <li key={p.id}>
                    <span>{day(p.created_at)}</span>
                    <span>{METHOD[p.method] ?? p.method}</span>
                    <span className="mono">{money(p.amount, c)}</span>
                    <span>{p.status}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
      )}
      <Confirm
        open={confirm === "void"}
        title="Void this invoice?"
        text="Its link stops taking payments and its discount code use is given back. It keeps its number. This cannot be undone: make a new invoice if you need one."
        action="Void invoice"
        onClose={() => setConfirm(null)}
        onConfirm={async () => {
          setConfirm(null);
          await act(() => pay.voidInvoice(inv!.id), "Invoice voided");
        }}
      />
      <Confirm
        open={confirm === "delete"}
        title="Delete this draft?"
        text="A draft has no number yet, so nothing is skipped. This cannot be undone."
        action="Delete draft"
        onClose={() => setConfirm(null)}
        onConfirm={async () => {
          setConfirm(null);
          await act(() => pay.deleteInvoice(inv!.id), "Draft deleted");
          onClose();
        }}
      />
      {recording && inv && (
        <RecordPayment
          invoice={inv}
          onClose={() => setRecording(false)}
          onDone={(next) => {
            setRecording(false);
            setInv(next);
            onChanged();
          }}
        />
      )}
    </Sheet>
  );
}

function RecordPayment({ invoice, onClose, onDone }: { invoice: Invoice; onClose: () => void; onDone: (i: Invoice) => void }) {
  const toast = useToast();
  const [amount, setAmount] = useState(toInput(invoice.amount_due, invoice.currency));
  const [method, setMethod] = useState("cash");
  const [note, setNote] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  async function submit() {
    const a = readAmount(amount, invoice.currency);
    if ("error" in a) return setError(a.error);
    if (a.amount > invoice.amount_due) return setError(`At most ${money(invoice.amount_due, invoice.currency)} is due`);
    setBusy(true);
    try {
      const next = await pay.recordPayment(invoice.id, { amount: a.amount, method, note });
      toast({ title: "Payment recorded", tone: "success" });
      onDone(next);
    } catch (e) {
      setError(fieldsOf(e).amount ?? errorText(e));
      setBusy(false);
    }
  }
  return (
    <Confirm open title="Record a payment" text="For money taken outside go-high: cash, a cheque or a bank transfer. Partial payments add up." action="Record payment" tone="primary" onClose={onClose} onConfirm={submit}>
      <div className="pay-form">
        <MoneyInput label="Amount" currency={invoice.currency} value={amount} onChange={setAmount} error={error} />
        <Select label="Method" value={method} onValueChange={setMethod} options={["cash", "check", "bank_transfer", "other"].map((m) => ({ value: m, label: METHOD[m] }))} />
        <Input label="Note" value={note} onChange={(e) => setNote(e.target.value)} maxLength={500} placeholder="Cheque number, reference" />
        {busy && <span className="sr-only">Saving</span>}
      </div>
    </Confirm>
  );
}
