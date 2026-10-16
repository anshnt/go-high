import * as RDialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import type { ReactNode } from "react";
import { Button } from "./Button";

type Props = {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: string;
  children?: ReactNode;
  footer?: ReactNode;
};

function Modal({ kind, open, onOpenChange, title, description, children, footer }: Props & { kind: "dialog" | "sheet" }) {
  return (
    <RDialog.Root open={open} onOpenChange={onOpenChange}>
      <RDialog.Portal>
        <RDialog.Overlay className="ui-overlay" />
        {/* Phones: both kinds render as a bottom sheet (see ui.css). */}
        <RDialog.Content className="ui-modal" data-kind={kind} {...(description ? {} : { "aria-describedby": undefined })}>
          <header className="ui-modal-head">
            <div>
              <RDialog.Title className="ui-modal-title">{title}</RDialog.Title>
              {description ? (
                <RDialog.Description className="ui-modal-desc">{description}</RDialog.Description>
              ) : null}
            </div>
            <RDialog.Close asChild>
              <Button variant="ghost" size="icon" aria-label="Close">
                <X size={16} aria-hidden />
              </Button>
            </RDialog.Close>
          </header>
          <div className="ui-modal-body">{children}</div>
          {footer && <footer className="ui-modal-foot">{footer}</footer>}
        </RDialog.Content>
      </RDialog.Portal>
    </RDialog.Root>
  );
}

export const Dialog = (p: Props) => <Modal kind="dialog" {...p} />;
/** Side panel on desktop, bottom sheet on phones. */
export const Sheet = (p: Props) => <Modal kind="sheet" {...p} />;
