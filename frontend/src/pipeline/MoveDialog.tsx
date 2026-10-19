import { useEffect, useId, useMemo, useState, type FormEvent } from "react";
import { FieldEditor } from "../records/fields/FieldEditor";
import { isReadOnly } from "../records/schema.ts";
import type { FieldDef } from "../records/types.ts";
import { isEmptyValue, normalizeText, validateValue } from "../records/validate.ts";
import { Button, Dialog } from "../ui";
import type { BoardStage, Card } from "./types.ts";

export type Ask = {
  card: Card;
  /** the stage the deal is going to, and the one it leaves */
  to: BoardStage;
  from: string;
  /** "lost": ask why before moving. "fix": the server refused and named what is missing. */
  mode: "lost" | "fix";
  /** field key (or the server's path) to what it said */
  errors: Record<string, string>;
};

type Props = {
  ask: Ask | null;
  /** the deal's fields, system columns included */
  fields: FieldDef[];
  /** Saves what was entered and tries the move again. Resolves with what the server still refuses, or null when the deal moved. */
  onSubmit: (values: Record<string, unknown>) => Promise<Record<string, string> | null>;
  onClose: () => void;
};

const LOST_KEYS = ["lost_reason", "lost_note"];

/**
 * The small dialog of a refused or a lost move. For a lost stage it asks the structured reason and an optional note. For a
 * refusal it shows the fields the stage it leaves wants, with the server's words, in the same editors the record uses, and
 * retries the move when they are filled in.
 */
export function MoveDialog({ ask, fields, onSubmit, onClose }: Props) {
  const formId = useId();
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [round, setRound] = useState(0);

  // the fields to ask for, in the order the workspace set them
  const keys = useMemo(() => {
    if (!ask) return [] as FieldDef[];
    const wanted = ask.mode === "lost" ? LOST_KEYS : Object.keys(ask.errors);
    return fields.filter((f) => wanted.includes(f.key) && !isReadOnly(f) && f.key !== "stage");
  }, [ask, fields]);
  const general = useMemo(() => Object.entries(errors).filter(([k]) => !keys.some((f) => f.key === k)).map((e) => e[1]), [errors, keys]);

  useEffect(() => {
    if (!ask) return;
    setValues(Object.fromEntries(keys.map((f) => [f.key, f.key === "owner_id" ? ask.card.owner_id : ask.card.values[f.key]]).filter(([, v]) => v !== undefined && v !== null)));
    setErrors(ask.mode === "fix" ? ask.errors : {});
    setRound((n) => n + 1);
    setBusy(false);
  }, [ask?.card.id, ask?.to.id, ask?.mode]); // eslint-disable-line react-hooks/exhaustive-deps

  if (!ask) return null;
  const lost = ask.mode === "lost";
  const required = (f: FieldDef) => (lost ? f.key === "lost_reason" : true);

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
    const clean: Record<string, unknown> = {};
    for (const f of keys) {
      const raw = values[f.key];
      const v = typeof raw === "string" ? normalizeText(f, raw) : raw;
      if (isEmptyValue(v)) {
        if (required(f)) found[f.key] = `${f.label} is required.`;
        continue;
      }
      const msg = validateValue(f, v);
      if (msg) found[f.key] = msg;
      else clean[f.key] = v;
    }
    if (Object.keys(found).length) {
      setErrors(found);
      return;
    }
    setBusy(true);
    try {
      const refused = await onSubmit(clean);
      if (refused) setErrors(refused);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && !busy && onClose()}
      title={lost ? "Mark as lost" : `Move to ${ask.to.name}`}
      description={lost ? `Why was ${ask.card.display_name || "this deal"} lost? The reason stays on the deal and feeds your reports.` : `${ask.card.display_name || "This deal"} cannot leave ${ask.from} yet. Add what is missing and it moves.`}
      footer={
        <>
          <Button onClick={onClose} disabled={busy}>
            Cancel
          </Button>
          <Button variant="primary" type="submit" form={formId} loading={busy}>
            {lost ? "Mark as lost" : `Save and move to ${ask.to.name}`}
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
        {keys.map((f, i) => (
          <div key={`${f.key}-${round}`} className="ui-field">
            <label htmlFor={`${formId}-${f.key}`} className="ui-label">
              {f.label}
              {required(f) && <span aria-hidden> *</span>}
            </label>
            <FieldEditor id={`${formId}-${f.key}`} field={f} value={values[f.key]} onChange={(v) => set(f.key, v)} autoFocus={i === 0} invalid={!!errors[f.key]} />
            {errors[f.key] && (
              <p className="ui-hint" data-tone="danger" role="alert">
                {errors[f.key]}
              </p>
            )}
          </div>
        ))}
        {keys.length === 0 && general.length === 0 && <p className="ui-hint">Nothing to fill in here. Try the move again.</p>}
      </form>
    </Dialog>
  );
}
