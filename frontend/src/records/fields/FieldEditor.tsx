import type { KeyboardEvent, ReactNode } from "react";
import { Switch } from "../../ui";
import { fromLocalInput, toLocalInput } from "../format.ts";
import { valueType } from "../schema.ts";
import type { FieldDef, Money } from "../types.ts";
import { FieldValue } from "./FieldValue";
import { ChoicePicker, MoneyInput, NumberInput, RecordPicker, UserPicker } from "./inputs";

export type EditorProps = {
  field: FieldDef;
  value: unknown;
  onChange: (v: unknown) => void;
  id?: string;
  autoFocus?: boolean;
  invalid?: boolean;
  /** Enter and Escape in the text inputs (inline editing uses them to save and cancel). */
  onKeyDown?: (e: KeyboardEvent) => void;
  /** Pickers only: your own button instead of the default one (inline editing shows the value itself). */
  trigger?: ReactNode;
  /** Pickers only: the list closed. */
  onClose?: () => void;
};

const INPUT_MODE = { email: "email", phone: "tel", url: "url" } as const;

/** The right input for a field's type. Controlled by `value`/`onChange`; number and money keep their own text while you type, so change `key` to reset them. */
export function FieldEditor({ field, value, onChange, id, autoFocus, invalid, onKeyDown, trigger, onClose }: EditorProps) {
  const type = valueType(field);
  const label = field.label;
  switch (type) {
    case "text":
    case "email":
    case "phone":
    case "url":
      return (
        <input
          id={id}
          className="ui-input"
          type="text"
          inputMode={type === "text" ? undefined : INPUT_MODE[type]}
          autoComplete="off"
          spellCheck={type === "text"}
          autoFocus={autoFocus}
          aria-label={label}
          aria-invalid={invalid || undefined}
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
        />
      );
    case "long_text":
      return (
        <textarea
          id={id}
          className="ui-input ui-textarea"
          autoFocus={autoFocus}
          aria-label={label}
          aria-invalid={invalid || undefined}
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={onKeyDown}
        />
      );
    case "number":
      return <NumberInput id={id} label={label} autoFocus={autoFocus} error={invalid} min={field.rules.min} max={field.rules.max} value={typeof value === "number" ? value : undefined} onChange={onChange} onKeyDown={onKeyDown} />;
    case "money":
      return <MoneyInput id={id} label={label} autoFocus={autoFocus} error={invalid} value={value as Money | undefined} currency={field.options.currency ?? "USD"} onChange={onChange} onKeyDown={onKeyDown} />;
    case "date":
      return <input id={id} className="ui-input" type="date" autoFocus={autoFocus} aria-label={label} aria-invalid={invalid || undefined} value={typeof value === "string" ? value : ""} onChange={(e) => onChange(e.target.value || undefined)} onKeyDown={onKeyDown} />;
    case "datetime":
      return (
        <input
          id={id}
          className="ui-input"
          type="datetime-local"
          autoFocus={autoFocus}
          aria-label={label}
          aria-invalid={invalid || undefined}
          value={toLocalInput(value)}
          onChange={(e) => onChange(fromLocalInput(e.target.value))}
          onKeyDown={onKeyDown}
        />
      );
    case "boolean":
      return <Switch id={id} aria-label={label} checked={value === true} onCheckedChange={onChange} />;
    case "select":
    case "stage":
      return (
        <ChoicePicker
          id={id}
          label={label}
          choices={field.options.choices ?? []}
          value={typeof value === "string" ? value : null}
          onChange={(v) => onChange(v ?? undefined)}
          clearable={!field.rules.required}
          trigger={trigger}
          onClose={onClose}
          error={invalid}
        />
      );
    case "multi_select": {
      const ids = Array.isArray(value) ? (value as string[]) : [];
      return <ChoicePicker id={id} multiple label={label} choices={field.options.choices ?? []} value={ids} onChange={(v) => onChange(v.length ? v : undefined)} onClose={onClose} trigger={trigger} error={invalid} />;
    }
    case "user":
      return <UserPicker id={id} label={label} value={typeof value === "string" ? value : null} onChange={(v) => onChange(v ?? undefined)} clearable={!field.rules.required} trigger={trigger} onClose={onClose} error={invalid} />;
    case "record":
      return field.options.object ? (
        <RecordPicker id={id} label={label} object={field.options.object} value={typeof value === "string" ? value : null} onChange={(v) => onChange(v ?? undefined)} clearable={!field.rules.required} trigger={trigger} error={invalid} />
      ) : null;
    default:
      return <FieldValue field={field} value={value} wrap />;
  }
}
