import { useId } from "react";

type Option<T extends string> = { value: T; label: string; /** the whole phrase for screen readers and a tooltip */ title?: string };

/** One of a few choices as a row of buttons (a radio group): arrows move between them, the chosen one is marked. */
export function Segmented<T extends string>({ label, value, options, onChange }: { label: string; value: T; options: Option<T>[]; onChange: (v: T) => void }) {
  const name = useId();
  return (
    <div className="ui-seg" role="radiogroup" aria-label={label}>
      {options.map((o) => (
        <label key={o.value} className="ui-seg-opt" title={o.title} data-on={o.value === value || undefined}>
          <input type="radio" name={name} value={o.value} checked={o.value === value} onChange={() => onChange(o.value)} />
          <span>{o.label}</span>
        </label>
      ))}
    </div>
  );
}
