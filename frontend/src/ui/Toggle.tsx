import * as RCheckbox from "@radix-ui/react-checkbox";
import * as RSwitch from "@radix-ui/react-switch";
import { Check, Minus } from "lucide-react";
import { useId } from "react";

type Common = { label?: string; "aria-label"?: string; disabled?: boolean; id?: string };

export function Checkbox({
  label,
  checked,
  onCheckedChange,
  ...rest
}: Common & { checked?: boolean | "indeterminate"; onCheckedChange?: (c: boolean) => void }) {
  const auto = useId();
  const id = rest.id ?? auto;
  return (
    <span className="ui-check-row">
      <RCheckbox.Root
        id={id}
        className="ui-checkbox"
        checked={checked}
        onCheckedChange={(c) => onCheckedChange?.(c === true)}
        disabled={rest.disabled}
        aria-label={rest["aria-label"]}
      >
        <RCheckbox.Indicator>{checked === "indeterminate" ? <Minus size={12} strokeWidth={3} aria-hidden /> : <Check size={12} strokeWidth={3} aria-hidden />}</RCheckbox.Indicator>
      </RCheckbox.Root>
      {label && (
        <label htmlFor={id} className="ui-check-label">
          {label}
        </label>
      )}
    </span>
  );
}

export function Switch({
  label,
  checked,
  onCheckedChange,
  ...rest
}: Common & { checked?: boolean; onCheckedChange?: (c: boolean) => void }) {
  const auto = useId();
  const id = rest.id ?? auto;
  return (
    <span className="ui-check-row">
      <RSwitch.Root id={id} className="ui-switch" checked={checked} onCheckedChange={onCheckedChange} disabled={rest.disabled} aria-label={rest["aria-label"]}>
        <RSwitch.Thumb className="ui-switch-thumb" />
      </RSwitch.Root>
      {label && (
        <label htmlFor={id} className="ui-check-label">
          {label}
        </label>
      )}
    </span>
  );
}
