// Pieces the payments screens share: a cursor-paged list, pickers for contacts and prices, an amount field, a
// confirm dialog and the little layout helpers. Design-system components only.
import { CircleAlert, Lock } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { errorText } from "../lib/api";
import { Badge, Button, Dialog, EmptyState, Input, type Tone } from "../ui";
import { Combobox } from "../ui/Combobox";
import { pay } from "./api";
import { minorDigits, money, priceText, readAmount, toInput } from "./money";
import type { Page, Price } from "./types";

export const day = (iso: string | null | undefined) => (iso ? new Date(iso).toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" }) : "None");

export const Status = ({ meta }: { meta: { label: string; tone: Tone } }) => <Badge tone={meta.tone}>{meta.label}</Badge>;

/** A list read page by page with a cursor; `reload` starts over (after a change or a new filter). */
export function useList<T>(load: (cursor: string | null) => Promise<Page<T>>, deps: unknown[]) {
  const [rows, setRows] = useState<T[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<string>();
  const [more, setMore] = useState(false);
  const loader = useRef(load);
  loader.current = load;
  const fetchPage = useCallback((after: string | null) => {
    setError(undefined);
    if (after) setMore(true);
    loader
      .current(after)
      .then((page) => {
        setRows((old) => (after ? [...(old ?? []), ...page.data] : page.data));
        setCursor(page.next_cursor);
      })
      .catch((e) => setError(errorText(e)))
      .finally(() => setMore(false));
  }, deps);
  useEffect(() => fetchPage(null), [fetchPage]);
  return { rows, error, cursor, loadingMore: more, reload: () => fetchPage(null), loadMore: () => cursor && fetchPage(cursor), setRows };
}

export function ListError({ error, onRetry, what }: { error: string; onRetry: () => void; what: string }) {
  return <EmptyState icon={CircleAlert} title={`We could not load ${what}`} text={error} action={<Button onClick={onRetry}>Try again</Button>} />;
}

export function NoAccess({ what }: { what: string }) {
  return <EmptyState icon={Lock} title="Your role cannot see this" text={`Ask a workspace admin for access to ${what}.`} />;
}

export function More({ cursor, loading, onMore }: { cursor: string | null; loading: boolean; onMore: () => void }) {
  if (!cursor) return null;
  return (
    <div className="pay-more">
      <Button onClick={onMore} loading={loading}>
        Load more
      </Button>
    </div>
  );
}

/** Picks a contact by name, email or phone (searched on the server, so the role's scope applies). */
export function ContactPicker({ value, label, onChange, error }: { value: { id: string; name: string } | null; label: string; onChange: (c: { id: string; name: string }) => void; error?: string }) {
  const [items, setItems] = useState<{ value: string; label: string; hint?: string }[]>([]);
  const [loading, setLoading] = useState(false);
  const search = useCallback((q: string) => {
    setLoading(true);
    pay
      .searchContacts(q)
      .then((rows) => setItems(rows.map((r) => ({ value: r.id, label: r.display_name, hint: typeof r.values.email === "string" ? r.values.email : undefined }))))
      .catch(() => setItems([]))
      .finally(() => setLoading(false));
  }, []);
  useEffect(() => search(""), [search]);
  return (
    <div className="ui-field">
      <span className="ui-label">{label}</span>
      <Combobox
        label={label}
        items={items}
        value={value?.id ?? null}
        valueLabel={value?.name}
        onChange={(id) => onChange({ id, name: items.find((i) => i.value === id)?.label ?? "" })}
        onSearch={search}
        loading={loading}
        placeholder="Choose a contact"
        searchPlaceholder="Search contacts"
        emptyText="No contact matches"
        aria-invalid={error ? true : undefined}
      />
      {error && (
        <p className="ui-hint" data-tone="danger">
          {error}
        </p>
      )}
    </div>
  );
}

/** Active prices of the workspace, for pickers, loaded once per screen. */
export function usePrices(params: { type?: string; currency?: string } = {}) {
  const [prices, setPrices] = useState<Price[] | null>(null);
  const k = JSON.stringify(params);
  useEffect(() => {
    let alive = true;
    pay
      .prices(JSON.parse(k))
      .then((p) => alive && setPrices(p))
      .catch(() => alive && setPrices([]));
    return () => {
      alive = false;
    };
  }, [k]);
  return prices;
}

export function PricePicker({ prices, value, onChange, label = "Price", error }: { prices: Price[] | null; value: string | null; onChange: (id: string) => void; label?: string; error?: string }) {
  return (
    <div className="ui-field">
      <span className="ui-label">{label}</span>
      <Combobox
        label={label}
        items={(prices ?? []).map((p) => ({ value: p.id, label: `${p.product_name ?? "Product"}${p.nickname ? ` (${p.nickname})` : ""}`, hint: priceText(p) }))}
        value={value}
        onChange={onChange}
        loading={prices === null}
        placeholder="Choose a price"
        searchPlaceholder="Search products"
        emptyText="No prices yet: add a product first"
        aria-invalid={error ? true : undefined}
      />
      {error && (
        <p className="ui-hint" data-tone="danger">
          {error}
        </p>
      )}
    </div>
  );
}

/** An amount in a currency, typed in major units and kept as minor units. */
export function MoneyInput({ label, currency, value, onChange, error, hint }: { label: string; currency: string; value: string; onChange: (text: string) => void; error?: string; hint?: string }) {
  const d = minorDigits(currency.toUpperCase());
  return <Input label={`${label} (${currency.toUpperCase()})`} inputMode={d ? "decimal" : "numeric"} value={value} onChange={(e) => onChange(e.target.value)} error={error} hint={hint} placeholder={d ? "0.00" : "0"} />;
}

export { readAmount, toInput, money };

export function Confirm({ open, title, text, action, tone = "danger", onConfirm, onClose, children }: { open: boolean; title: string; text: string; action: string; tone?: "danger" | "primary"; onConfirm: () => Promise<void> | void; onClose: () => void; children?: ReactNode }) {
  const [busy, setBusy] = useState(false);
  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !o && !busy && onClose()}
      title={title}
      description={text}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            Keep it
          </Button>
          <Button
            variant={tone}
            loading={busy}
            onClick={async () => {
              setBusy(true);
              try {
                await onConfirm();
              } finally {
                setBusy(false);
              }
            }}
          >
            {action}
          </Button>
        </>
      }
    >
      {children}
    </Dialog>
  );
}

export const Row = ({ label, children }: { label: string; children: ReactNode }) => (
  <div className="pay-row">
    <dt>{label}</dt>
    <dd>{children}</dd>
  </div>
);

/** Field errors of a 422, by the server's path ("lines.0.price_id"). */
export function fieldsOf(e: unknown): Record<string, string> {
  return (e as { fields?: Record<string, string> })?.fields ?? {};
}
