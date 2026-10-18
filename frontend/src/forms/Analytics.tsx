import { ChartColumn } from "lucide-react";
import { useEffect, useState } from "react";
import { errorText } from "../lib/api";
import { Button, EmptyState, Input, Skeleton } from "../ui";
import { forms, type Analytics as Data, type FormDetail } from "./api";

const pct = (x: number | null) => (x === null ? "None yet" : `${Math.round(x * 100)}%`);
const share = (n: number, of: number) => (of > 0 ? `${Math.round((n / of) * 100)}%` : "0%");
const duration = (s: number | null) => (s === null ? "None yet" : s < 60 ? `${Math.round(s)} s` : `${Math.floor(s / 60)} min ${Math.round(s % 60)} s`);

function Tile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="fm-tile">
      <span className="fm-tile-label">{label}</span>
      <strong className="fm-tile-value num">{value}</strong>
      {hint && <span className="fm-tile-hint">{hint}</span>}
    </div>
  );
}

/** Views, starts and completions, and where visitors leave: a funnel per step and a table per question. */
export function Analytics({ form }: { form: FormDetail }) {
  const [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState<string>();
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const load = () => {
    setError(undefined);
    forms.analytics(form.id, { from: from || undefined, to: to || undefined }).then(setData).catch((e) => setError(errorText(e)));
  };
  useEffect(load, [form.id, from, to]);

  if (error) return <EmptyState icon={ChartColumn} title="We could not load the numbers" text={error} action={<Button onClick={load}>Try again</Button>} />;
  if (!data) return <Skeleton style={{ height: 160 }} />;
  const top = data.steps[0]?.reached ?? data.starts;
  return (
    <div className="fm-analytics">
      <div className="fm-filters">
        <Input label="From" type="date" value={from} max={to || undefined} onChange={(e) => setFrom(e.target.value)} />
        <Input label="To" type="date" value={to} min={from || undefined} onChange={(e) => setTo(e.target.value)} />
        {(from || to) && (
          <Button variant="ghost" onClick={() => { setFrom(""); setTo(""); }}>
            Clear dates
          </Button>
        )}
      </div>
      <div className="fm-tiles">
        <Tile label="Views" value={data.views.toLocaleString()} />
        <Tile label="Started" value={data.starts.toLocaleString()} hint={data.views ? `${share(data.starts, data.views)} of views` : undefined} />
        <Tile label="Completed" value={data.completions.toLocaleString()} hint={data.conversion_rate === null ? undefined : `${pct(data.conversion_rate)} of views`} />
        <Tile label="Completion rate" value={pct(data.completion_rate)} hint="Of those who started" />
        <Tile label="Average time" value={duration(data.avg_seconds)} hint="Open to sent" />
      </div>

      <section aria-labelledby="funnel-title">
        <h2 id="funnel-title">Where people leave, by step</h2>
        {data.starts === 0 ? (
          <EmptyState icon={ChartColumn} title="Nobody has started this form" text="Once people start filling it in, you see here how many reach each step and where they stop." />
        ) : (
          <table className="fm-table fm-funnel">
            <caption className="sr-only">Responses that reached each step, and where they stopped</caption>
            <thead>
              <tr>
                <th scope="col">Step</th>
                <th scope="col">Reached</th>
                <th scope="col" className="fm-num">Left here</th>
                <th scope="col" className="fm-num">Of those who reached it</th>
              </tr>
            </thead>
            <tbody>
              {data.steps.map((s, i) => (
                <tr key={s.key}>
                  <th scope="row">
                    {i + 1}. {s.title || `Step ${i + 1}`}
                  </th>
                  <td>
                    <span className="fm-bar-row">
                      <span className="fm-bar-track" aria-hidden>
                        <span className="fm-bar" style={{ width: `${top ? Math.round((s.reached / top) * 100) : 0}%` }} />
                      </span>
                      <span className="num">
                        {s.reached.toLocaleString()} <span className="fm-muted">({share(s.reached, top)})</span>
                      </span>
                    </span>
                  </td>
                  <td className="fm-num num">{s.dropped.toLocaleString()}</td>
                  <td className="fm-num num">{share(s.dropped, s.reached)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {data.starts > 0 && (
        <section aria-labelledby="fields-title">
          <h2 id="fields-title">By question</h2>
          <table className="fm-table">
            <caption className="sr-only">How many answered each question, and how many stopped right after it</caption>
            <thead>
              <tr>
                <th scope="col">Question</th>
                <th scope="col" className="fm-num">Answered</th>
                <th scope="col" className="fm-num">Of those who started</th>
                <th scope="col" className="fm-num">Stopped after it</th>
              </tr>
            </thead>
            <tbody>
              {data.fields.map((f) => (
                <tr key={f.key}>
                  <th scope="row">{f.label}</th>
                  <td className="fm-num num">{f.answered.toLocaleString()}</td>
                  <td className="fm-num num">{share(f.answered, data.starts)}</td>
                  <td className="fm-num num">{f.dropped_after.toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </div>
  );
}
