import { useState, type FormEvent } from "react";
import { errorText } from "../lib/api";
import { creatableOrgs, createWorkspace, type Me } from "../lib/session";
import { Button, Dialog, Input, Select, useToast } from "../ui";

/** Loaded on demand (shell/WorkspaceSwitcher.tsx), so the select and dialog code stay out of the first load. */
export function CreateWorkspace({ me, onClose }: { me: Me; onClose: () => void }) {
  const targets = creatableOrgs(me);
  const toast = useToast();
  const [name, setName] = useState("");
  const [orgId, setOrgId] = useState(targets[0]?.org.id ?? "");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function submit(ev: FormEvent) {
    ev.preventDefault();
    const clean = name.trim();
    const target = targets.find((t) => t.org.id === orgId);
    if (!clean) return setError("Give the workspace a name.");
    if (!target) return setError("You cannot create workspaces here.");
    setError(undefined);
    setBusy(true);
    try {
      const ws = await createWorkspace(clean, target.brandId);
      toast({ title: `${ws.name} created`, description: "You are now working in it.", tone: "success" });
      onClose();
    } catch (e) {
      setError(errorText(e));
      setBusy(false);
    }
  }

  return (
    <Dialog
      open
      onOpenChange={(open) => !open && onClose()}
      title="Create workspace"
      description="A separate space with its own data and settings."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="create-workspace" variant="primary" loading={busy}>
            Create workspace
          </Button>
        </>
      }
    >
      <form id="create-workspace" className="sh-form" onSubmit={submit} noValidate>
        <Input label="Name" name="name" autoFocus value={name} error={error} maxLength={200} onChange={(e) => setName(e.target.value)} />
        {targets.length > 1 && <Select label="Organization" value={orgId} onValueChange={setOrgId} options={targets.map((t) => ({ value: t.org.id, label: t.org.name }))} />}
      </form>
    </Dialog>
  );
}
