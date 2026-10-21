// Adding or editing one field: the type (fixed once made), the settings of that type (choices, currency, country,
// linked object, formula) and its validation rules, checked here the way the server checks them.
import { ArrowDown, ArrowUp, Plus, X } from "lucide-react";
import { useState, type FormEvent } from "react";
import { ApiError } from "../lib/api";
import { whatWentWrong } from "../lib/errors";
import { Button, Checkbox, Dialog, Input, Select, Textarea } from "../ui";
import { createField, listObjects, patchField, type FieldDef, type ObjectDef } from "./api";
import { useLoad } from "./common";
import { COLORS, draftOf, emptyField, fieldBody, fieldErrors, keyFrom, move, placeServerErrors, RULES, TYPES, typeLabel, type FieldDraft, type FieldType } from "./logic.ts";

export function FieldDialog({ object, field, taken, onClose, onSaved }: { object: ObjectDef; field?: FieldDef; taken: string[]; onClose: () => void; onSaved: (f: FieldDef, created: boolean) => void }) {
  const creating = !field;
  const [d, setD] = useState<FieldDraft>(() => (field ? draftOf(field) : emptyField()));
  const [keyTouched, setKeyTouched] = useState(!creating);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const objects = useLoad(() => listObjects(), [], d.type === "record");
  const set = <K extends keyof FieldDraft>(k: K, v: FieldDraft[K]) => setD((x) => ({ ...x, [k]: v }));
  const rules = RULES[d.type] ?? [];
  const locked = !!field?.is_system;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const found = fieldErrors(d, { creating, taken });
    setErrors(found);
    if (Object.keys(found).length) {
      requestAnimationFrame(() => document.querySelector<HTMLElement>("#field-form [aria-invalid='true']")?.focus());
      return;
    }
    setBusy(true);
    try {
      const body = fieldBody(d);
      const saved = creating ? await createField(object.key, { key: d.key, label: d.label.trim(), type: d.type, ...body }) : await patchField(object.key, field.key, { label: d.label.trim(), ...body });
      onSaved(saved, creating);
    } catch (err) {
      if (err instanceof ApiError && err.status === 409) setErrors({ key: `${err.message}.` });
      else if (err instanceof ApiError && err.fields) setErrors(placeServerErrors(err.fields));
      else setErrors({ form: whatWentWrong(err) });
    } finally {
      setBusy(false);
    }
  };

  const typeInfo = TYPES.find((t) => t.value === d.type)!;
  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={creating ? `Add a field to ${object.plural}` : `Edit ${field.label}`}
      description={creating ? "The key and the type cannot change later, because records keep values of that type." : `${typeLabel(field.type)} field. Its key and type stay as they are.`}
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="field-form" loading={busy}>
            {creating ? "Add field" : "Save field"}
          </Button>
        </>
      }
    >
      <form id="field-form" className="adm-form" onSubmit={submit} noValidate>
        <Input
          label="Label"
          value={d.label}
          maxLength={100}
          autoFocus
          error={errors.label}
          onChange={(e) => {
            const label = e.target.value;
            setD((x) => ({ ...x, label, key: keyTouched ? x.key : keyFrom(label) }));
          }}
        />
        <Input label="Key" className="mono" value={d.key} disabled={!creating} maxLength={63} error={errors.key} hint={creating ? "Used in the API, filters and imports." : undefined} spellCheck={false} onChange={(e) => (set("key", e.target.value), setKeyTouched(true))} />
        {creating ? (
          <Select
            label="Type"
            value={d.type}
            onValueChange={(v) => setD((x) => ({ ...emptyField(v as FieldType), label: x.label, key: x.key, required: x.required }))}
            options={TYPES.map((t) => ({ value: t.value, label: `${t.label} (${t.group.toLowerCase()})` }))}
          />
        ) : (
          <Input label="Type" value={typeLabel(d.type)} disabled />
        )}
        <p className="ui-hint adm-type-help">{typeInfo.help}</p>

        {(d.type === "select" || d.type === "multi_select") && <ChoicesEditor choices={d.choices} onChange={(c) => set("choices", c)} error={errors.choices} editing={!creating} />}
        {d.type === "money" && <Input label="Currency" value={d.currency} maxLength={3} onChange={(e) => set("currency", e.target.value.toUpperCase())} error={errors.currency} hint="The default for new amounts, like USD." className="mono" />}
        {d.type === "phone" && <Input label="Default country (optional)" value={d.region} maxLength={2} onChange={(e) => set("region", e.target.value.toUpperCase())} error={errors.region} hint="For numbers typed without + and a country code, like US or GB. Empty uses the workspace default." className="mono" />}
        {d.type === "record" &&
          (creating ? (
            <Select label="Links to" value={d.object || undefined} placeholder={objects.data ? "Pick an object" : "Loading objects"} onValueChange={(v) => set("object", v)} options={(objects.data ?? []).map((o) => ({ value: o.key, label: o.plural }))} disabled={!objects.data} />
          ) : (
            <Input label="Links to" value={d.object} disabled className="mono" />
          ))}
        {errors.object && (
          <p className="ui-hint" data-tone="danger" role="alert">
            {errors.object}
          </p>
        )}
        {d.type === "formula" && <Textarea label="Expression (stored, not computed yet)" className="mono" rows={2} value={d.expression} onChange={(e) => set("expression", e.target.value)} />}
        {d.type === "rollup" && (
          <div className="adm-grid-3">
            <Input label="Association" value={d.association} onChange={(e) => set("association", e.target.value)} className="mono" />
            <Input label="Field" value={d.rollupField} onChange={(e) => set("rollupField", e.target.value)} className="mono" />
            <Select label="Function" value={d.rollupFunction} onValueChange={(v) => set("rollupFunction", v)} options={["count", "sum", "min", "max", "avg"].map((v) => ({ value: v, label: v }))} />
          </div>
        )}

        <fieldset className="adm-fieldset">
          <legend className="ui-label">Validation</legend>
          <Checkbox label="Required: a record cannot be saved without it" checked={d.required} onCheckedChange={(c) => set("required", c)} disabled={locked && d.required} />
          {(rules.includes("min_length") || rules.includes("max_length")) && (
            <div className="adm-grid-2">
              <Input label="Shortest (characters)" type="number" inputMode="numeric" min={0} value={d.min_length} onChange={(e) => set("min_length", e.target.value)} error={errors.min_length} />
              <Input label="Longest (characters)" type="number" inputMode="numeric" min={0} value={d.max_length} onChange={(e) => set("max_length", e.target.value)} error={errors.max_length} />
            </div>
          )}
          {(rules.includes("min") || rules.includes("max")) && (
            <div className="adm-grid-2">
              <Input label={d.type === "money" ? "Lowest amount (cents)" : "Lowest"} type="number" value={d.min} onChange={(e) => set("min", e.target.value)} error={errors.min} />
              <Input label={d.type === "money" ? "Highest amount (cents)" : "Highest"} type="number" value={d.max} onChange={(e) => set("max", e.target.value)} error={errors.max} />
            </div>
          )}
          {rules.includes("integer") && <Checkbox label="Whole numbers only" checked={d.integer} onCheckedChange={(c) => set("integer", c)} />}
          {rules.includes("timezone") && <Checkbox label="A time zone (an IANA name like America/New_York); workflows read the contact's zone from it" checked={d.timezone} onCheckedChange={(c) => set("timezone", c)} />}
          {rules.includes("max_items") && <Input label="Most choices at once" type="number" inputMode="numeric" min={0} value={d.max_items} onChange={(e) => set("max_items", e.target.value)} error={errors.max_items} />}
          {(errors.rules || errors.options) && (
            <p className="ui-hint" data-tone="danger" role="alert">
              {errors.rules ?? errors.options}
            </p>
          )}
        </fieldset>
        {errors.form && (
          <p className="ui-hint" data-tone="danger" role="alert">
            {errors.form}
          </p>
        )}
      </form>
    </Dialog>
  );
}

function ChoicesEditor({ choices, onChange, error, editing }: { choices: FieldDraft["choices"]; onChange: (c: FieldDraft["choices"]) => void; error?: string; editing: boolean }) {
  const update = (i: number, patch: Partial<FieldDraft["choices"][number]>) => onChange(choices.map((c, j) => (j === i ? { ...c, ...patch } : c)));
  return (
    <fieldset className="adm-fieldset" aria-describedby={error ? "choices-error" : undefined}>
      <legend className="ui-label">Choices</legend>
      <ol className="adm-choices">
        {choices.map((c, i) => (
          <li key={c.id ?? `new-${i}`} className="adm-choice">
            <input
              className="ui-input"
              aria-label={`Choice ${i + 1}`}
              value={c.label}
              maxLength={100}
              placeholder={`Choice ${i + 1}`}
              aria-invalid={!!error && !c.label.trim() ? true : undefined}
              onChange={(e) => update(i, { label: e.target.value })}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  e.preventDefault();
                  onChange([...choices.slice(0, i + 1), { label: "" }, ...choices.slice(i + 1)]);
                  requestAnimationFrame(() => document.querySelector<HTMLInputElement>(`[aria-label="Choice ${i + 2}"]`)?.focus());
                }
              }}
            />
            <Select aria-label={`Color of choice ${i + 1}`} value={c.color ?? "gray"} onValueChange={(v) => update(i, { color: v === "gray" ? undefined : v })} options={COLORS.map((x) => ({ value: x, label: x.charAt(0).toUpperCase() + x.slice(1) }))} />
            <Button size="icon" variant="ghost" aria-label={`Move choice ${i + 1} up`} disabled={i === 0} onClick={() => onChange(move(choices, i, i - 1))}>
              <ArrowUp size={14} aria-hidden />
            </Button>
            <Button size="icon" variant="ghost" aria-label={`Move choice ${i + 1} down`} disabled={i === choices.length - 1} onClick={() => onChange(move(choices, i, i + 1))}>
              <ArrowDown size={14} aria-hidden />
            </Button>
            <Button size="icon" variant="ghost" aria-label={`Remove choice ${i + 1}`} onClick={() => onChange(choices.filter((_, j) => j !== i))}>
              <X size={14} aria-hidden />
            </Button>
          </li>
        ))}
      </ol>
      <div>
        <Button size="sm" onClick={() => onChange([...choices, { label: "" }])}>
          <Plus size={14} aria-hidden /> Add choice
        </Button>
      </div>
      {editing && <p className="ui-hint">Records keep a choice by its id, so renaming one keeps it on every record. Removing a choice does not change the records that already have it.</p>}
      {error && (
        <p id="choices-error" className="ui-hint" data-tone="danger" role="alert">
          {error}
        </p>
      )}
    </fieldset>
  );
}
