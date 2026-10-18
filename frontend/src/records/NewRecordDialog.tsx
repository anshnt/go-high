import { ChevronDown, ChevronRight } from "lucide-react";
import { useEffect, useId, useMemo, useState, type FormEvent } from "react";
import { Button, Checkbox, Dialog, useToast } from "../ui";
import type { RecordsClient } from "./client.ts";
import { errorMessage, RecordsError } from "./errors.ts";
import { FieldEditor } from "./fields/FieldEditor";
import { isReadOnly } from "./schema.ts";
import type { FieldDef, ObjectDef, RecordRow } from "./types.ts";
import { isEmptyValue, normalizeText, validateValue } from "./validate.ts";

type Props = {
  client: RecordsClient;
  def: ObjectDef;
  fields: FieldDef[];
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** `another`: the dialog stays open for the next one, so do not navigate away. */
  onCreated: (row: RecordRow, another: boolean) => void;
};

const clean = (f: FieldDef, v: unknown) => {
  const x = typeof v === "string" ? normalizeText(f, v) : v;
  return isEmptyValue(x) ? undefined : x;
};

/** Required fields first; everything else is one click away. Uses the same editors and the same validator as inline editing. */
export function NewRecordDialog({ client, def, fields, open, onOpenChange, onCreated }: Props) {
  const toast = useToast();
  const formId = useId();
  const editable = useMemo(() => fields.filter((f) => !isReadOnly(f)), [fields]);
  // what a record needs to exist comes first: required fields and the ones that make up its name (a contact's first and last name)
  const needed = (f: FieldDef) => f.rules.required || def.primary_fields.includes(f.key);
  const required = editable.filter(needed);
  const more = editable.filter((f) => !needed(f));
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [showMore, setShowMore] = useState(false);
  const [another, setAnother] = useState(false);
  const [busy, setBusy] = useState(false);
  const [round, setRound] = useState(0);

  useEffect(() => {
    if (open) {
      setValues({});
      setErrors({});
      setShowMore(false);
      setRound((n) => n + 1);
    }
  }, [open]);

  const set = (key: string, v: unknown) => {
    setValues((s) => ({ ...s, [key]: v }));
    setErrors((s) => {
      if (!s[key]) return s;
      const { [key]: _gone, ...rest } = s;
      return rest;
    });
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const found: Record<string, string> = {};
    for (const f of editable) {
      const msg = validateValue(f, clean(f, values[f.key]));
      if (msg) found[f.key] = msg;
    }
    if (Object.keys(found).length) {
      setErrors(found);
      if (Object.keys(found).some((k) => more.some((f) => f.key === k))) setShowMore(true);
      return;
    }
    setBusy(true);
    try {
      const { owner_id, ...rest } = values;
      const vals: Record<string, unknown> = {};
      for (const f of editable) if (f.key !== "owner_id") {
        const v = clean(f, rest[f.key]);
        if (v !== undefined) vals[f.key] = v;
      }
      const row = await client.create(def.key, { values: vals, ...(typeof owner_id === "string" ? { owner_id } : {}) });
      toast({ title: `${def.singular} created`, description: row.display_name, tone: "success" });
      onCreated(row, another);
      if (another) {
        setValues({});
        setErrors({});
        setRound((n) => n + 1);
      } else onOpenChange(false);
    } catch (err) {
      if (err instanceof RecordsError && err.fields) {
        setErrors(err.fields);
        if (Object.keys(err.fields).some((k) => more.some((f) => f.key === k))) setShowMore(true);
      } else toast({ title: `Could not create the ${def.singular.toLowerCase()}`, description: errorMessage(err), tone: "danger" });
    } finally {
      setBusy(false);
    }
  };

  // what the server says about the record as a whole ("a contact needs a name") belongs to no field
  const general = Object.entries(errors).filter(([k]) => !editable.some((f) => f.key === k)).map((e) => e[1]);

  const row = (f: FieldDef, first: boolean) => (
    <div key={`${f.key}-${round}`} className="ui-field">
      <label htmlFor={`${formId}-${f.key}`} className="ui-label">
        {f.label}
        {f.rules.required && <span aria-hidden> *</span>}
      </label>
      <FieldEditor id={`${formId}-${f.key}`} field={f} value={values[f.key]} onChange={(v) => set(f.key, v)} autoFocus={first} invalid={!!errors[f.key]} />
      {errors[f.key] && (
        <p className="ui-hint" data-tone="danger" role="alert">
          {errors[f.key]}
        </p>
      )}
    </div>
  );

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={`New ${def.singular.toLowerCase()}`}
      description={required.length ? `Fields marked * are required.` : undefined}
      footer={
        <>
          <span className="rec-foot-left">
            <Checkbox label="Create another" checked={another} onCheckedChange={setAnother} />
          </span>
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" type="submit" form={formId} loading={busy}>
            Create {def.singular.toLowerCase()}
          </Button>
        </>
      }
    >
      <form id={formId} className="rec-form" onSubmit={submit} noValidate>
        {general.length > 0 && (
          <p className="ui-hint" data-tone="danger" role="alert">
            {general.join(" ")}
          </p>
        )}
        {required.map((f, i) => row(f, i === 0))}
        {more.length > 0 && (
          <>
            <button type="button" className="rec-more" aria-expanded={showMore} onClick={() => setShowMore((v) => !v)}>
              {showMore ? <ChevronDown size={14} aria-hidden /> : <ChevronRight size={14} aria-hidden />} {showMore ? "Fewer fields" : `More fields (${more.length})`}
            </button>
            {showMore && more.map((f) => row(f, false))}
          </>
        )}
      </form>
    </Dialog>
  );
}
