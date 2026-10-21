import { ChartColumn, LockKeyhole, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { errorMessage, errorStatus } from "../records/errors.ts";
import { formatMoney } from "../records/format.ts";
import { useMeta } from "../records/meta.tsx";
import { Avatar, Button, EmptyState, Select, Skeleton } from "../ui";
import { axisLabel, compactMoney, currencies, LAYERS, niceTicks, ownerRows, rows as buildRows, sumRows, type Layer, type OwnerRow, type Row } from "./forecast.ts";
import { Segmented } from "../ui/Segmented";
import type { Forecast, Period, Pipeline, PipelineClient } from "./types.ts";

type State = { status: "loading" | "ready" | "error"; data: Forecast | null; error: unknown; refreshing: boolean };

/** The forecast of one pipeline: what each month or quarter is worth, as stacked columns and as a table, with the weighted figure and a breakdown by owner. */
export function ForecastView({ client, pipeline, hasAmount }: { client: PipelineClient; pipeline: Pipeline; hasAmount: boolean }) {
  const [period, setPeriod] = useState<Period>("month");
  const [state, setState] = useState<State>({ status: "loading", data: null, error: null, refreshing: false });
  const [pick, setPick] = useState<string | null>(null); // a period the owner table is scoped to
  const [chosenCurrency, setCurrency] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let live = true;
    setState((s) => (s.data ? { ...s, refreshing: true } : s));
    client.forecast(pipeline.id, period).then(
      (data) => live && setState({ status: "ready", data, error: null, refreshing: false }),
      (error) => live && setState({ status: "error", data: null, error, refreshing: false }),
    );
    return () => {
      live = false;
    };
  }, [client, pipeline.id, period, attempt]);
  useEffect(() => setPick(null), [period]);

  const data = state.data;
  const codes = useMemo(() => (data ? currencies(data) : []), [data]);
  const currency = chosenCurrency && codes.includes(chosenCurrency) ? chosenCurrency : (codes[0] ?? "USD");
  const list = useMemo(() => (data ? buildRows(data, currency) : []), [data, currency]);

  if (!hasAmount) return <Denied text="Your role cannot see deal amounts, and the forecast is made of them." />;
  if (state.status === "error") {
    return errorStatus(state.error) === 403 ? (
      <Denied text={errorMessage(state.error)} />
    ) : (
      <div className="pl-forecast">
        <EmptyState icon={TriangleAlert} title="We could not load the forecast" text={errorMessage(state.error)} action={<Button onClick={() => setAttempt((n) => n + 1)}>Try again</Button>} />
      </div>
    );
  }
  if (state.status === "loading" || !data) {
    return (
      <div className="pl-forecast" aria-busy="true" aria-label="Loading">
        <div className="pl-fc-kpis">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} style={{ height: 76, borderRadius: 8 }} />
          ))}
        </div>
        <Skeleton style={{ height: 300, borderRadius: 8, marginTop: 16 }} />
      </div>
    );
  }
  if (data.periods.length === 0) {
    return (
      <div className="pl-forecast">
        <Controls period={period} onPeriod={setPeriod} codes={codes} currency={currency} onCurrency={setCurrency} />
        <EmptyState icon={ChartColumn} title="Nothing to forecast yet" text="The forecast groups deals by close date. Give your open deals an amount and a close date and they show up here, with the weighted figure for each stage's probability." />
      </div>
    );
  }

  const total = sumRows(list);
  const unit = period === "month" ? "month" : "quarter";
  const owners = ownerRows(data, currency, pick);
  const money = (n: number) => formatMoney({ amount: n, currency });

  return (
    <div className="pl-forecast" data-refreshing={state.refreshing || undefined}>
      <Controls period={period} onPeriod={setPeriod} codes={codes} currency={currency} onCurrency={setCurrency} />

      <section className="pl-fc-kpis" aria-label={`Totals for all ${unit}s shown, in ${currency}`}>
        <Tile label="Won" value={money(total.won)} note="Deals in won stages" />
        <Tile label="Commit" value={money(total.commit)} note="Open, stages of 80% or more" />
        <Tile label="Weighted" value={money(total.weighted)} note="Open deals times their stage's probability" />
        <Tile label="Open pipeline" value={money(total.commit + total.best + total.pipeline)} note="Every open deal with a close date" />
      </section>

      <figure className="pl-fc-chart">
        <figcaption>
          <span className="pl-fc-title">
            Forecast by {unit}, {currency}
          </span>
          <ul className="pl-fc-legend" aria-label="Legend">
            {LAYERS.map((l) => (
              <li key={l.key} title={l.note}>
                <span className="pl-fc-swatch" data-layer={l.key} aria-hidden />
                {l.label}
              </li>
            ))}
            <li title="Open deals times their stage's probability">
              <span className="pl-fc-tickkey" aria-hidden />
              Weighted
            </li>
          </ul>
        </figcaption>
        <Columns rows={list} period={period} currency={currency} pick={pick} onPick={setPick} />
        <p className="pl-fc-hint">Select a {unit} to scope the owner breakdown to it. Every figure is in the table below.</p>
      </figure>

      <section className="pl-fc-block" aria-labelledby="pl-fc-table-h">
        <h2 id="pl-fc-table-h" className="rec-section-title">
          By {unit}
        </h2>
        <div className="pl-table-wrap" tabIndex={0} role="region" aria-label={`Forecast by ${unit} as a table`}>
          <table className="pl-table num">
            <thead>
              <tr>
                <th scope="col">{period === "month" ? "Month" : "Quarter"}</th>
                <FigureHeads />
              </tr>
            </thead>
            <tbody>
              {list.map((r) => (
                <tr key={r.label} data-empty={r.total === 0 || undefined} data-selected={pick === r.label || undefined}>
                  <th scope="row">{r.name}</th>
                  <Figures r={r} money={money} />
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row">Total</th>
                <Figures r={total} money={money} />
              </tr>
            </tfoot>
          </table>
        </div>
      </section>

      <section className="pl-fc-block" aria-labelledby="pl-fc-owner-h">
        <div className="pl-fc-owner-head">
          <h2 id="pl-fc-owner-h" className="rec-section-title">
            By owner
          </h2>
          <Select
            aria-label="Owner breakdown for"
            value={pick ?? "all"}
            onValueChange={(v) => setPick(v === "all" ? null : v)}
            options={[{ value: "all", label: `All ${unit}s` }, ...list.filter((r) => r.total > 0 || r.weighted > 0).map((r) => ({ value: r.label, label: r.name }))]}
          />
        </div>
        <OwnerTable owners={owners} money={money} />
      </section>
    </div>
  );
}

function Denied({ text }: { text: string }) {
  return (
    <div className="pl-forecast">
      <EmptyState icon={LockKeyhole} title="You do not have access to the forecast" text={text} />
    </div>
  );
}

function Controls({ period, onPeriod, codes, currency, onCurrency }: { period: Period; onPeriod: (p: Period) => void; codes: string[]; currency: string; onCurrency: (c: string) => void }) {
  return (
    <div className="pl-fc-controls">
      <Segmented label="Group by" value={period} onChange={onPeriod} options={[{ value: "month", label: "Month" }, { value: "quarter", label: "Quarter" }]} />
      {codes.length > 1 && (
        <Segmented
          label="Currency"
          value={currency}
          onChange={onCurrency}
          options={codes.map((c) => ({ value: c, label: c, title: `Show ${c}. Amounts in different currencies are never added together.` }))}
        />
      )}
    </div>
  );
}

function Tile({ label, value, note }: { label: string; value: string; note: string }) {
  return (
    <div className="pl-tile">
      <p className="pl-tile-label">{label}</p>
      <p className="pl-tile-value num">{value}</p>
      <p className="pl-tile-note">{note}</p>
    </div>
  );
}

const FigureHeads = () => (
  <>
    {LAYERS.map((l) => (
      <th key={l.key} scope="col" className="pl-num" title={l.note}>
        <span className="pl-fc-swatch" data-layer={l.key} aria-hidden /> {l.label}
      </th>
    ))}
    <th scope="col" className="pl-num">
      Total
    </th>
    <th scope="col" className="pl-num" title="Open deals times their stage's probability">
      Weighted
    </th>
  </>
);

function Figures({ r, money }: { r: Omit<Row, "label" | "name" | "start">; money: (n: number) => string }) {
  return (
    <>
      {LAYERS.map((l) => (
        <td key={l.key} className="pl-num">
          {r[l.key as Layer] ? money(r[l.key as Layer]) : <span className="pl-zero">0</span>}
        </td>
      ))}
      <td className="pl-num pl-strong">{r.total ? money(r.total) : <span className="pl-zero">0</span>}</td>
      <td className="pl-num">{r.weighted ? money(r.weighted) : <span className="pl-zero">0</span>}</td>
    </>
  );
}

function OwnerTable({ owners, money }: { owners: OwnerRow[]; money: (n: number) => string }) {
  const { users } = useMeta();
  if (owners.length === 0) return <p className="pl-fc-none">Nobody has deals in this selection.</p>;
  return (
    <div className="pl-table-wrap" tabIndex={0} role="region" aria-label="Forecast by owner as a table">
      <table className="pl-table num">
        <thead>
          <tr>
            <th scope="col">Owner</th>
            <FigureHeads />
          </tr>
        </thead>
        <tbody>
          {owners.map((o) => {
            const user = o.owner_id ? users.find((u) => u.id === o.owner_id) : undefined;
            const name = o.owner_id ? (user?.name ?? "Unknown person") : "Unassigned";
            return (
              <tr key={o.owner_id ?? "none"}>
                <th scope="row">
                  <span className="rec-user">
                    {o.owner_id && <Avatar name={name} size="sm" />}
                    <span className="rec-ellipsis">{name}</span>
                  </span>
                </th>
                <Figures r={o} money={money} />
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---- the chart: stacked columns in plain HTML, the table is its twin ----

function Columns({ rows, period, currency, pick, onPick }: { rows: Row[]; period: Period; currency: string; pick: string | null; onPick: (label: string | null) => void }) {
  const max = Math.max(...rows.map((r) => Math.max(r.total, r.weighted)), 0);
  const ticks = niceTicks(max);
  const top = ticks[ticks.length - 1]!;
  const pct = (n: number) => `${(n / top) * 100}%`;
  const money = (n: number) => formatMoney({ amount: n, currency });
  const summary = `${rows.length} ${period === "month" ? "months" : "quarters"} from ${rows[0]!.name} to ${rows[rows.length - 1]!.name}, in ${currency}.`;
  return (
    <div className="pl-fc-scroll">
      <div className="pl-fc-plot" role="group" aria-label={summary} style={{ "--n": rows.length } as React.CSSProperties}>
        <div className="pl-fc-area">
          {ticks.map((t) => (
            <div key={t} className="pl-fc-tick" style={{ bottom: pct(t) }} aria-hidden>
              <span>{compactMoney(t, currency)}</span>
            </div>
          ))}
          <div className="pl-fc-cols">
            {rows.map((r, i) => {
              const parts = LAYERS.map((l) => ({ ...l, n: r[l.key as Layer] })).filter((p) => p.n > 0);
              const side = i < 2 && rows.length > 3 ? "start" : i >= rows.length - 2 && rows.length > 3 ? "end" : "mid";
              return (
                <button
                  key={r.label}
                  type="button"
                  className="pl-fc-col"
                  data-selected={pick === r.label || undefined}
                  aria-pressed={pick === r.label}
                  aria-label={`${r.name}: won ${money(r.won)}, commit ${money(r.commit)}, best case ${money(r.best)}, pipeline ${money(r.pipeline)}, weighted ${money(r.weighted)}`}
                  onClick={() => onPick(pick === r.label ? null : r.label)}
                >
                  <span className="pl-fc-bar" aria-hidden>
                    {parts.map((p) => (
                      <span key={p.key} className="pl-fc-seg" data-layer={p.key} style={{ height: pct(p.n) }} />
                    ))}
                    {r.weighted > 0 && <span className="pl-fc-weighted" style={{ bottom: pct(r.weighted) }} />}
                  </span>
                  <span className="pl-fc-tip" data-side={side} aria-hidden>
                    <strong>{r.name}</strong>
                    {LAYERS.map((l) => (
                      <span key={l.key} className="pl-fc-tip-row">
                        <span className="pl-fc-swatch" data-layer={l.key} />
                        <span className="pl-fc-tip-label">{l.label}</span>
                        <span className="pl-fc-tip-value num">{money(r[l.key as Layer])}</span>
                      </span>
                    ))}
                    <span className="pl-fc-tip-row">
                      <span className="pl-fc-tickkey" />
                      <span className="pl-fc-tip-label">Weighted</span>
                      <span className="pl-fc-tip-value num">{money(r.weighted)}</span>
                    </span>
                  </span>
                </button>
              );
            })}
          </div>
        </div>
        <div className="pl-fc-labels" aria-hidden>
          {rows.map((r, i) => (
            <span key={r.label} data-selected={pick === r.label || undefined}>
              {axisLabel(r.start, period, i === 0)}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
