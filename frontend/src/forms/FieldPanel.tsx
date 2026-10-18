import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";
import type { ReactNode } from "react";
import { Button, Checkbox, Input, Select, Switch, Textarea } from "../ui";
import type { Field, Option, Validation } from "../forms-runtime/types";
import type { ContactField, Kind } from "./api";
import { COMPATIBLE, QUIZ_TYPES, TYPE_META, isContent } from "./meta";

const NONE = "__none";
const num = (s: string) => (s === "" || Number.isNaN(Number(s)) ? undefined : Number(s));
const text = (s: string) => (s === "" ? undefined : s);

type Props = { field: Field; kind: Kind; contact: ContactField[]; error?: string; onChange: (patch: Partial<Field>) => void };

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="fm-section">
      <h3>{title}</h3>
      {children}
    </section>
  );
}

/** Settings of the selected question. */
export function FieldPanel({ field: f, kind, contact, error, onChange }: Props) {
  const meta = TYPE_META[f.type];
  const validation = (name: keyof Validation, value: unknown) => {
    const next = { ...f.validation, [name]: value };
    for (const k of Object.keys(next) as (keyof Validation)[]) if (next[k] === undefined || next[k] === false) delete next[k];
    onChange({ validation: Object.keys(next).length ? next : undefined });
  };
  const choices = f.options ?? [];
  const setOptions = (options: Option[]) => onChange({ options });
  const targets = contact.filter((c) => COMPATIBLE[f.type]?.includes(c.type));
  const answer = !isContent(f.type);

  return (
    <div className="fm-panel">
      <p className="fm-panel-type">
        <meta.icon size={16} aria-hidden />
        {meta.label}
        <span className="fm-key mono" title="Used in rules, exports and the API. It does not change.">
          {f.key}
        </span>
      </p>
      {error && (
        <p className="fm-issue" role="alert">
          {error}
        </p>
      )}
      {f.type === "paragraph" ? (
        <Textarea label="Text" value={f.label} onChange={(e) => onChange({ label: e.target.value })} maxLength={2000} />
      ) : (
        <Input label={f.type === "heading" ? "Heading" : f.type === "consent" ? "Consent text" : "Question"} value={f.label} onChange={(e) => onChange({ label: e.target.value })} maxLength={f.type === "consent" ? 1000 : 300} />
      )}
      {answer && f.type !== "hidden" && f.type !== "consent" && <Input label="Help text" hint="Shown under the question." value={f.help ?? ""} onChange={(e) => onChange({ help: text(e.target.value) })} maxLength={500} />}
      {["short_text", "long_text", "email", "phone", "number", "select"].includes(f.type) && <Input label="Placeholder" value={f.placeholder ?? ""} onChange={(e) => onChange({ placeholder: text(e.target.value) })} maxLength={200} />}
      {answer && f.type !== "hidden" && <Switch label="Required" checked={!!f.required} onCheckedChange={(on) => onChange({ required: on || undefined })} />}

      {f.type === "hidden" && (
        <Input label="Link parameter" hint={`Filled from the page address, like ?${f.param ?? f.key}=spring. Never shown.`} value={f.param ?? ""} onChange={(e) => onChange({ param: text(e.target.value) })} maxLength={60} />
      )}

      {(f.type === "select" || f.type === "multi_select") && (
        <Section title="Options">
          <ul className="fm-options">
            {choices.map((o, i) => (
              <li key={o.id}>
                <Input aria-label={`Option ${i + 1}`} value={o.label} onChange={(e) => setOptions(choices.map((x) => (x.id === o.id ? { ...x, label: e.target.value } : x)))} maxLength={100} />
                <Button variant="ghost" size="icon" aria-label={`Move option ${i + 1} up`} disabled={i === 0} onClick={() => { const c = [...choices]; [c[i - 1], c[i]] = [c[i]!, c[i - 1]!]; setOptions(c); }}>
                  <ArrowUp size={16} aria-hidden />
                </Button>
                <Button variant="ghost" size="icon" aria-label={`Move option ${i + 1} down`} disabled={i === choices.length - 1} onClick={() => { const c = [...choices]; [c[i + 1], c[i]] = [c[i]!, c[i + 1]!]; setOptions(c); }}>
                  <ArrowDown size={16} aria-hidden />
                </Button>
                <Button variant="ghost" size="icon" aria-label={`Remove option ${i + 1}`} disabled={choices.length < 2} onClick={() => setOptions(choices.filter((x) => x.id !== o.id))}>
                  <Trash2 size={16} aria-hidden />
                </Button>
              </li>
            ))}
          </ul>
          <Button size="sm" disabled={choices.length >= 50} onClick={() => { let n = choices.length + 1; while (choices.some((x) => x.id === `option_${n}`)) n++; setOptions([...choices, { id: `option_${n}`, label: `Option ${n}` }]); }}>
            <Plus size={16} aria-hidden />
            Add an option
          </Button>
        </Section>
      )}

      {(f.type === "short_text" || f.type === "long_text") && (
        <Section title="Length">
          <div className="fm-pair">
            <Input label="At least" type="number" min={0} value={f.validation?.min_length ?? ""} onChange={(e) => validation("min_length", num(e.target.value))} />
            <Input label="At most" type="number" min={0} value={f.validation?.max_length ?? ""} onChange={(e) => validation("max_length", num(e.target.value))} />
          </div>
        </Section>
      )}
      {f.type === "number" && (
        <Section title="Allowed numbers">
          <div className="fm-pair">
            <Input label="Smallest" type="number" value={f.validation?.min ?? ""} onChange={(e) => validation("min", num(e.target.value))} />
            <Input label="Largest" type="number" value={f.validation?.max ?? ""} onChange={(e) => validation("max", num(e.target.value))} />
          </div>
          <Switch label="Whole numbers only" checked={!!f.validation?.integer} onCheckedChange={(on) => validation("integer", on)} />
        </Section>
      )}
      {f.type === "multi_select" && (
        <Section title="How many choices">
          <div className="fm-pair">
            <Input label="At least" type="number" min={0} value={f.validation?.min_items ?? ""} onChange={(e) => validation("min_items", num(e.target.value))} />
            <Input label="At most" type="number" min={1} value={f.validation?.max_items ?? ""} onChange={(e) => validation("max_items", num(e.target.value))} />
          </div>
        </Section>
      )}

      {answer && f.type !== "heading" && (
        <Section title="Contact">
          <Select
            label="Save the answer to the contact's"
            value={f.maps_to ?? NONE}
            onValueChange={(v) => onChange({ maps_to: v === NONE ? undefined : v })}
            options={[{ value: NONE, label: "Nothing (keep it in the response)" }, ...targets.map((c) => ({ value: c.key, label: c.label })), ...(f.maps_to && !targets.some((c) => c.key === f.maps_to) ? [{ value: f.maps_to, label: `${f.maps_to} (not available)` }] : [])]}
          />
          <p className="ui-hint">An empty answer never clears what the contact already has.</p>
        </Section>
      )}

      {kind === "quiz" && QUIZ_TYPES.includes(f.type) && <QuizAnswer f={f} onChange={onChange} />}
    </div>
  );
}

function QuizAnswer({ f, onChange }: { f: Field; onChange: (p: Partial<Field>) => void }) {
  const scored = f.quiz !== undefined;
  const set = (correct: unknown, points = f.quiz?.points ?? 1) => onChange({ quiz: { correct, points } });
  const first = f.type === "yes_no" ? true : f.type === "rating" ? 5 : f.type === "number" ? 0 : f.type === "short_text" ? "" : f.type === "multi_select" ? [f.options?.[0]?.id] : f.options?.[0]?.id;
  const options = f.options ?? [];
  const correct = f.quiz?.correct;
  return (
    <Section title="Scoring">
      <Switch label="This question is scored" checked={scored} onCheckedChange={(on) => onChange({ quiz: on ? { correct: first, points: 1 } : undefined })} />
      {scored && (
        <>
          <Input label="Points" type="number" min={1} max={100} value={f.quiz!.points} onChange={(e) => set(correct, Math.max(1, Math.min(100, num(e.target.value) ?? 1)))} />
          {f.type === "select" && <Select label="Right answer" value={String(correct)} onValueChange={(v) => set(v)} options={options.map((o) => ({ value: o.id, label: o.label }))} />}
          {f.type === "yes_no" && <Select label="Right answer" value={correct === false ? "no" : "yes"} onValueChange={(v) => set(v === "yes")} options={[{ value: "yes", label: "Yes" }, { value: "no", label: "No" }]} />}
          {f.type === "rating" && <Select label="Right answer" value={String(correct)} onValueChange={(v) => set(Number(v))} options={[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: String(n) }))} />}
          {f.type === "number" && <Input label="Right answer" type="number" value={typeof correct === "number" ? correct : ""} onChange={(e) => set(num(e.target.value) ?? 0)} />}
          {f.type === "short_text" && <Input label="Right answers" hint="Separate several accepted answers with commas. Case and spaces do not matter." value={Array.isArray(correct) ? correct.join(", ") : String(correct ?? "")} onChange={(e) => { const list = e.target.value.split(",").map((s) => s.trim()).filter(Boolean); set(list.length > 1 ? list : (list[0] ?? e.target.value)); }} />}
          {f.type === "multi_select" && (
            <fieldset className="fm-checks">
              <legend className="ui-label">Right answers</legend>
              {options.map((o) => (
                <Checkbox key={o.id} label={o.label} checked={Array.isArray(correct) && correct.includes(o.id)} onCheckedChange={(on) => { const now = Array.isArray(correct) ? correct : []; set(on ? [...now, o.id] : now.filter((x) => x !== o.id)); }} />
              ))}
            </fieldset>
          )}
        </>
      )}
    </Section>
  );
}
