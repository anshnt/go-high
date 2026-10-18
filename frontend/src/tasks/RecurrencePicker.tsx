import { Repeat } from "lucide-react";
import { useId } from "react";
import { fromInputDate, toInputDate } from "../lib/dates";
import { ordinal, parseRule, PRESETS, ruleFor, ruleText, summarize, WEEKDAYS, type Freq, type Preset, type Rule } from "../lib/recurrence";
import { Input, Select } from "../ui";

const DAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const UNITS: { value: Freq; label: string }[] = [
  { value: "DAILY", label: "days" },
  { value: "WEEKLY", label: "weeks" },
  { value: "MONTHLY", label: "months" },
];
const FRESH: Rule = { freq: "DAILY", interval: 1, byday: [], bymonthday: null, count: null, until: null };

type Props = {
  /** The stored rule text, or null. */
  value: string | null;
  /** The due date: weekly presets repeat on its weekday and monthly ones on its day of the month. */
  due: Date | null;
  preset: Preset;
  onChange: (preset: Preset, rule: string | null) => void;
};

/** "Every weekday", "Every 2 weeks on Mon", "Monthly on the 1st": a preset, or Custom for the interval, days and an end. */
export function RecurrencePicker({ value, due, preset, onChange }: Props) {
  const id = useId();
  const rule = parseRule(value) ?? FRESH;
  const set = (patch: Partial<Rule>) => onChange("custom", ruleText({ ...rule, ...patch }));
  const toggleDay = (d: string) => set({ byday: rule.byday.includes(d) ? rule.byday.filter((x) => x !== d) : [...rule.byday, d] });
  const ends = rule.count !== null ? "count" : rule.until ? "until" : "never";
  const day = due?.getDate() ?? 1;

  return (
    <div className="tk-repeat">
      <Select
        label="Repeat"
        value={preset}
        onValueChange={(p) => onChange(p as Preset, p === "custom" ? (value ?? ruleText(FRESH)) : ruleFor(p as Preset, due))}
        options={PRESETS.map((p) => ({ value: p.id, label: p.label }))}
      />
      {preset === "custom" && (
        <fieldset className="tk-custom">
          <legend className="sr-only">Custom repeat</legend>
          <div className="tk-custom-row">
            <label htmlFor={`${id}-n`}>Every</label>
            <Input
              id={`${id}-n`}
              className="tk-num"
              type="number"
              min={1}
              max={99}
              value={rule.interval}
              onChange={(e) => set({ interval: Math.min(99, Math.max(1, Number(e.target.value) || 1)) })}
            />
            <Select
              aria-label="Repeat unit"
              value={rule.freq}
              onValueChange={(f) => set({ freq: f as Freq, byday: f === "WEEKLY" ? rule.byday : [], bymonthday: f === "MONTHLY" ? (rule.bymonthday ?? day) : null })}
              options={UNITS}
            />
          </div>
          {rule.freq === "WEEKLY" && (
            <div role="group" aria-label="On these days" className="tk-days">
              {WEEKDAYS.map((d, i) => (
                <button key={d} type="button" className="tk-wd" aria-pressed={rule.byday.includes(d)} onClick={() => toggleDay(d)}>
                  {DAY_LABELS[i]}
                </button>
              ))}
            </div>
          )}
          {rule.freq === "MONTHLY" && (
            <Select
              label="On"
              value={rule.bymonthday === -1 ? "last" : "day"}
              onValueChange={(v) => set({ bymonthday: v === "last" ? -1 : day })}
              options={[
                { value: "day", label: `The ${ordinal(rule.bymonthday && rule.bymonthday > 0 ? rule.bymonthday : day)}` },
                { value: "last", label: "The last day" },
              ]}
            />
          )}
          <div className="tk-custom-row">
            <Select
              label="Ends"
              value={ends}
              onValueChange={(v) => set({ count: v === "count" ? 5 : null, until: v === "until" ? toInputDate(due ?? new Date()).replaceAll("-", "") : null })}
              options={[
                { value: "never", label: "Never" },
                { value: "count", label: "After a number of times" },
                { value: "until", label: "On a date" },
              ]}
            />
            {ends === "count" && (
              <Input label="Times" className="tk-num" type="number" min={1} max={999} value={rule.count ?? 5} onChange={(e) => set({ count: Math.min(999, Math.max(1, Number(e.target.value) || 1)) })} />
            )}
            {ends === "until" && rule.until && (
              <Input
                label="Last day"
                type="date"
                value={`${rule.until.slice(0, 4)}-${rule.until.slice(4, 6)}-${rule.until.slice(6, 8)}`}
                onChange={(e) => {
                  const d = fromInputDate(e.target.value);
                  if (d) set({ until: toInputDate(d).replaceAll("-", "") });
                }}
              />
            )}
          </div>
        </fieldset>
      )}
      {value && (
        <p className="tk-repeat-summary">
          <Repeat size={13} aria-hidden /> {summarize(value)}
        </p>
      )}
    </div>
  );
}

