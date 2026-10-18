import { Check, Copy, ExternalLink } from "lucide-react";
import { useState } from "react";
import { Badge, Button, Dialog, Input, Textarea, useToast } from "../ui";
import { embedCode, shareLink, type FormRow } from "./api";

function CopyRow({ label, value, area }: { label: string; value: string; area?: boolean }) {
  const toast = useToast();
  const [done, setDone] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setDone(true);
      setTimeout(() => setDone(false), 2000);
    } catch {
      toast({ title: "Could not copy", description: "Select the text and copy it.", tone: "danger" });
    }
  }
  return (
    <div className="fm-copy">
      {area ? <Textarea label={label} value={value} readOnly rows={3} spellCheck={false} onFocus={(e) => e.target.select()} /> : <Input label={label} value={value} readOnly onFocus={(e) => e.target.select()} />}
      <Button onClick={() => void copy()} aria-label={`Copy ${label.toLowerCase()}`}>
        {done ? <Check size={16} aria-hidden /> : <Copy size={16} aria-hidden />}
        {done ? "Copied" : "Copy"}
      </Button>
    </div>
  );
}

/** The link and the embed code of a published form. */
export function ShareDialog({ form, open, onOpenChange }: { form: FormRow; open: boolean; onOpenChange: (o: boolean) => void }) {
  const live = form.status === "published";
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={live ? "Your form is live" : "Share this form"}
      description={live ? `Version ${form.published_version} is what visitors see.` : "Visitors cannot open it until it is published."}
      footer={
        <>
          <a className="ui-btn" data-variant="secondary" data-size="md" href={shareLink(form.public_key)} target="_blank" rel="noreferrer">
            <ExternalLink size={16} aria-hidden />
            Open the page
          </a>
          <Button variant="primary" onClick={() => onOpenChange(false)}>
            Done
          </Button>
        </>
      }
    >
      <div className="fm-share">
        <div className="fm-share-status">
          <Badge tone={live ? "success" : "neutral"}>{live ? "Live" : form.status === "closed" ? "Closed" : "Draft"}</Badge>
          {form.has_draft_changes && <Badge tone="accent">Unpublished changes</Badge>}
        </div>
        <CopyRow label="Link to share" value={shareLink(form.public_key)} />
        <CopyRow label="Embed code" value={embedCode(form.public_key)} area />
        <p className="ui-hint">
          Paste the embed code where the form should appear. It draws inside the page without an iframe, so your page's styles and analytics are untouched, and it picks up changes you publish. Add data-theme="dark" to the tag for the dark theme.
        </p>
      </div>
    </Dialog>
  );
}
