import * as RSelect from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import { useId } from "react";

export type SelectProps = {
  label?: string;
  value?: string;
  onValueChange?: (v: string) => void;
  options: { value: string; label: string }[];
  placeholder?: string;
  disabled?: boolean;
  /** When there is no visible label. */
  "aria-label"?: string;
};

export function Select({ label, value, onValueChange, options, placeholder = "Select", disabled, ...rest }: SelectProps) {
  const id = useId();
  return (
    <div className="ui-field">
      {label && (
        <label htmlFor={id} className="ui-label">
          {label}
        </label>
      )}
      <RSelect.Root value={value} onValueChange={onValueChange} disabled={disabled}>
        <RSelect.Trigger id={id} className="ui-input ui-select-trigger" aria-label={rest["aria-label"]}>
          <RSelect.Value placeholder={placeholder} />
          <RSelect.Icon>
            <ChevronDown size={16} aria-hidden />
          </RSelect.Icon>
        </RSelect.Trigger>
        <RSelect.Portal>
          <RSelect.Content className="ui-popover" position="popper" sideOffset={4}>
            <RSelect.Viewport className="ui-select-viewport">
              {options.map((o) => (
                <RSelect.Item key={o.value} value={o.value} className="ui-item">
                  <RSelect.ItemText>{o.label}</RSelect.ItemText>
                  <RSelect.ItemIndicator className="ui-item-end">
                    <Check size={14} aria-hidden />
                  </RSelect.ItemIndicator>
                </RSelect.Item>
              ))}
            </RSelect.Viewport>
          </RSelect.Content>
        </RSelect.Portal>
      </RSelect.Root>
    </div>
  );
}
