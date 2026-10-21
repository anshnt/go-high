import { useId, type InputHTMLAttributes, type ReactNode, type Ref, type TextareaHTMLAttributes } from "react";
import { cn } from "../lib/cn";

type FieldProps = { label?: string; hint?: string; error?: string };

function Field({ id, label, hint, error, children }: FieldProps & { id: string; children: ReactNode }) {
  return (
    <div className="ui-field">
      {label && (
        <label htmlFor={id} className="ui-label">
          {label}
        </label>
      )}
      {children}
      {error ? (
        <p id={`${id}-msg`} className="ui-hint" data-tone="danger">
          {error}
        </p>
      ) : hint ? (
        <p id={`${id}-msg`} className="ui-hint">
          {hint}
        </p>
      ) : null}
    </div>
  );
}

const describe = (id: string, p: FieldProps) => ({
  "aria-invalid": p.error ? true : undefined,
  "aria-describedby": p.error || p.hint ? `${id}-msg` : undefined,
});

/** `ref` reaches the <input> (React 19 passes it as a prop). */
export function Input({ label, hint, error, className, id, ...rest }: InputHTMLAttributes<HTMLInputElement> & FieldProps & { ref?: Ref<HTMLInputElement> }) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <Field id={fid} label={label} hint={hint} error={error}>
      <input id={fid} className={cn("ui-input", className)} {...describe(fid, { hint, error })} {...rest} />
    </Field>
  );
}

/** `ref` reaches the <textarea>. */
export function Textarea({ label, hint, error, className, id, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement> & FieldProps & { ref?: Ref<HTMLTextAreaElement> }) {
  const auto = useId();
  const fid = id ?? auto;
  return (
    <Field id={fid} label={label} hint={hint} error={error}>
      <textarea id={fid} className={cn("ui-input ui-textarea", className)} {...describe(fid, { hint, error })} {...rest} />
    </Field>
  );
}
