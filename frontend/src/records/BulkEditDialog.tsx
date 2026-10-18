import { useEffect, useId, useMemo, useState, type FormEvent } from "react";
import { Button, Checkbox, Dialog } from "../ui";
import { Combobox } from "../ui/Combobox";
import { bulkFields, bulkValue } from "./bulkEdit.ts";
import { FieldEditor } from "./fields/FieldEditor";
import { valueType } from "./schema.ts";
import type { FieldDef, ObjectDef } from "./types.ts";

type Props = {
  def: ObjectDef;
  fields: FieldDef[];
  /** how many records the change goes to */
  count: number;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Applies the value (undefined clears it) to the selected records. Resolves with null when done, or the message to show. */
  onApply: (field: FieldDef, value: unknown) => Promise<string | null>;
};

/** Pick one field, give it a value or clear it, and set it on every selected record. Uses the same editors and validator as inline editing. */
export function BulkEditDialog({ def, fields, count, open, onOpenChange, onApply }: Props) {
  const formId = useId();
  const editable = useMemo(() => bulkFields(fields), [fields]);
  const [key, setKey] = useState<string | null>(null);
  const [draft, setDraft] = useState<unknown>(undefined);
  const [clear, setClear] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [round, setRound] = useState(0);
  const field = editable.find((f) => f.key === key);
  const noun = count === 1 ? def.singular.toLowerCase() : def.plural.toLowerCase();

  const pick = (k: string | null) => {
    const f = editable.find((x) => x.key === k);
    setKey(k);
    setDraft(f && valueType(f) === "boolean" ? false : undefined);
    setClear(false);
    setError(null);
    setRound((n) => n + 1); // number and money inputs keep their own text: start them afresh
  };

  useEffect(() => {
    if (open) {
      pick(null);
      setBusy(false);
    }
  }, [open]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!field) return setError("Choose a field to change.");
    const next = bulkValue(field, draft, clear);
    if ("error" in next) return setError(next.error);
    setBusy(true);
    setError(null);
    const failed = await onApply(field, next.value);
    setBusy(false);
    if (failed) setError(failed);
    else onOpenChange(false);
  };

  const fieldId = `${formId}-field`;
  const valueId = `${formId}-value`;

  return (
    <Dialog
      open={open}
      onOpenChange={(o) => !busy && onOpenChange(o)}
      title={`Edit ${count.toLocaleString("en-US")} ${noun}`}
      description="The value you set replaces what each of them has now."
      footer={
        <>
          <Button onClick={() => onOpenChange(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form={formId} loading={busy} disabled={!field}>
            {clear ? "Clear" : "Update"} {count.toLocaleString("en-US")} {noun}
          </Button>
        </>
      }
    >
      <form id={formId} className="rec-form" onSubmit={submit} noValidate>
        {editable.length === 0 ? (
          <p className="ui-hint">{def.plural} have no fields that can be edited in bulk.</p>
        ) : (
          <div className="ui-field">
            <label htmlFor={fieldId} className="ui-label">
              Field
            </label>
            <Combobox
              id={fieldId}
              label="Field to change"
              items={editable.map((f) => ({ value: f.key, label: f.label }))}
              value={key}
              onChange={pick}
              placeholder="Choose a field"
              searchPlaceholder="Search fields"
              emptyText="No matching fields"
              aria-invalid={!field && !!error}
            />
          </div>
        )}
        {field && (
          <div key={`${field.key}-${round}`} className="ui-field">
            {!clear && (
              <>
                <label htmlFor={valueId} className="ui-label">
                  New {field.label.toLowerCase()}
                  {field.rules.required && <span aria-hidden> *</span>}
                </label>
                <FieldEditor
                  id={valueId}
                  field={field}
                  value={draft}
                  onChange={(v) => {
                    setDraft(v);
                    setError(null);
                  }}
                  autoFocus
                  invalid={!!error}
                />
              </>
            )}
            {!field.rules.required && (
              <Checkbox
                label={`Clear ${field.label.toLowerCase()} on all of them`}
                checked={clear}
                onCheckedChange={(c) => {
                  setClear(c);
                  setError(null);
                }}
              />
            )}
          </div>
        )}
        {error && (
          <p className="ui-hint" data-tone="danger" role="alert">
            {error}
          </p>
        )}
      </form>
    </Dialog>
  );
}
