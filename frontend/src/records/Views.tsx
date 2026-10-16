import { Users } from "lucide-react";
import { useEffect, useState, type FormEvent } from "react";
import { Button, Dialog, Input, Switch, Tabs, TabsList, TabsTrigger } from "../ui";
import type { SavedView } from "./types.ts";

export const ALL_VIEW = "all";

/** "All contacts" first, then the views people made. A dot on the open tab means the filter, columns or sort differ from what is saved. */
export function ViewTabs({ views, active, dirty, plural, onSelect }: { views: SavedView[]; active: string; dirty: boolean; plural: string; onSelect: (id: string) => void }) {
  const dot = <span className="rec-dirty-dot" role="img" aria-label="Unsaved changes" title="Unsaved changes" />;
  return (
    <Tabs value={active} onValueChange={onSelect} className="rec-views">
      <TabsList aria-label="Saved views">
        <TabsTrigger value={ALL_VIEW}>
          All {plural.toLowerCase()}
          {active === ALL_VIEW && dirty && dot}
        </TabsTrigger>
        {views.map((v) => (
          <TabsTrigger key={v.id} value={v.id}>
            {v.shared && <Users size={12} aria-label="Shared" role="img" className="rec-shared-icon" />}
            {v.name}
            {active === v.id && dirty && dot}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}

export function SaveViewDialog({ open, onOpenChange, onSave, busy, error }: { open: boolean; onOpenChange: (o: boolean) => void; onSave: (name: string, shared: boolean) => void; busy: boolean; error?: string }) {
  const [name, setName] = useState("");
  const [shared, setShared] = useState(false);
  useEffect(() => {
    if (open) {
      setName("");
      setShared(false);
    }
  }, [open]);
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (name.trim()) onSave(name.trim(), shared);
  };
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Save view"
      description="Keeps the current filters, columns and sort so you can come back to them."
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" type="submit" form="save-view-form" loading={busy} disabled={!name.trim()}>
            Save view
          </Button>
        </>
      }
    >
      <form id="save-view-form" className="rec-form" onSubmit={submit}>
        <Input label="Name" autoFocus value={name} maxLength={60} onChange={(e) => setName(e.target.value)} placeholder="Customers this quarter" error={error} />
        <Switch label="Share with everyone in this workspace" checked={shared} onCheckedChange={setShared} />
      </form>
    </Dialog>
  );
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirm,
  onConfirm,
  busy,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  description: string;
  confirm: string;
  onConfirm: () => void;
  busy?: boolean;
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="danger" onClick={onConfirm} loading={busy} autoFocus>
            {confirm}
          </Button>
        </>
      }
    />
  );
}
