// Team and roles > Roles: the organization's roles, with how many people hold each here, and a new role made as a copy.
import { ChevronRight, LockKeyhole, Plus, ShieldCheck } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate } from "react-router";
import { ApiError } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { whatWentWrong } from "../lib/errors";
import { Badge, Button, Dialog, EmptyState, Input, Select, Textarea, useToast } from "../ui";
import { createRole, listMembers, listRoles, type Role } from "./api";
import { LoadError, Loading, useLoad } from "./common";

/** Whether the caller may change roles: `roles.manage` and an organization owner or admin (a role reaches every workspace). */
export function useRoleEditing() {
  const { can, data, ready } = useCan();
  return { allowed: can("roles.manage") && (!ready || data?.role?.source === "organization"), ready };
}

export function NewRoleDialog({ open, onOpenChange, roles, from }: { open: boolean; onOpenChange: (o: boolean) => void; roles: Role[]; from?: Role }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [name, setName] = useState(from ? `${from.name} copy` : "");
  const [description, setDescription] = useState(from?.description ?? "");
  const [copy, setCopy] = useState(from?.key ?? "member");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!name.trim()) return setErrors({ name: "Give the role a name." });
    setBusy(true);
    setErrors({});
    try {
      const role = await createRole({ name: name.trim(), description: description.trim(), copy_from: copy });
      toast({ title: "Role created", description: `${role.name} starts as a copy of ${roles.find((r) => r.key === copy)?.name ?? copy}. Adjust it here.`, tone: "success" });
      onOpenChange(false);
      navigate(`/settings/team/roles/${role.id}`);
    } catch (err) {
      const taken = err instanceof ApiError ? err.fields?.name : undefined;
      setErrors(taken ? { name: `This name ${taken}.` } : { form: whatWentWrong(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={from ? `Duplicate ${from.name}` : "New role"}
      description="A role starts as a copy of another, with its capabilities and record access. You can change all of it next."
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" type="submit" form="new-role" loading={busy}>
            Create role
          </Button>
        </>
      }
    >
      <form id="new-role" className="adm-form" onSubmit={submit} noValidate>
        <Input label="Name" value={name} onChange={(e) => setName(e.target.value)} maxLength={100} error={errors.name || undefined} autoFocus required />
        <Textarea label="Description" value={description} onChange={(e) => setDescription(e.target.value)} maxLength={500} rows={2} hint="Optional. Who this role is for." />
        {!from && <Select label="Start from" value={copy} onValueChange={setCopy} options={roles.map((r) => ({ value: r.key, label: r.name }))} />}
        {errors.form && (
          <p className="ui-hint" data-tone="danger" role="alert">
            {errors.form}
          </p>
        )}
      </form>
    </Dialog>
  );
}

export function Roles() {
  const { allowed, ready } = useRoleEditing();
  const roles = useLoad(listRoles, []);
  const members = useLoad(listMembers, []);
  const [creating, setCreating] = useState(false);

  if (roles.error && !roles.data) return <LoadError what="roles" error={roles.error} retry={roles.reload} />;
  if (!roles.data) return <Loading label="Loading roles" rows={5} height={60} />;

  const holders = (r: Role) => members.data?.filter((m) => m.role.id === r.id).length;
  const system = roles.data.filter((r) => r.is_system);
  const custom = roles.data.filter((r) => !r.is_system);

  const row = (r: Role) => {
    const n = holders(r);
    return (
      <li key={r.id}>
        <Link to={`/settings/team/roles/${r.id}`} className="adm-row-link">
          <span className="adm-row-main">
            <strong>
              {r.name} {r.locked && <LockKeyhole size={13} aria-label="Locked" className="adm-inline-icon" />}
            </strong>
            <span className="adm-muted">{r.description || `${r.capabilities.length} capabilities`}</span>
          </span>
          <span className="adm-row-meta">
            {n !== undefined && <span className="adm-muted">{n === 0 ? "Nobody here" : `${n} ${n === 1 ? "person" : "people"} here`}</span>}
            {r.is_system && <Badge>System</Badge>}
            <ChevronRight size={16} aria-hidden />
          </span>
        </Link>
      </li>
    );
  };

  return (
    <div className="adm-stack">
      <div className="adm-toolbar">
        <p className="adm-muted">Roles belong to the organization, so a change applies in every workspace that uses the role.</p>
        {allowed && (
          <Button variant="primary" onClick={() => setCreating(true)}>
            <Plus size={16} aria-hidden /> New role
          </Button>
        )}
      </div>
      {ready && !allowed && <p className="adm-note">Only organization owners and admins with the capability roles.manage create and change roles. You can look at them here.</p>}
      <section aria-labelledby="system-roles">
        <h2 id="system-roles" className="adm-h2">
          System roles
        </h2>
        <ul className="adm-rows">{system.map(row)}</ul>
      </section>
      <section aria-labelledby="custom-roles">
        <h2 id="custom-roles" className="adm-h2">
          Custom roles
        </h2>
        {custom.length ? (
          <ul className="adm-rows">{custom.map(row)}</ul>
        ) : (
          <EmptyState
            icon={ShieldCheck}
            title="No custom roles yet"
            text="Make one for a job, like Account manager or Front desk: copy a system role, then limit what it sees down to single fields."
            action={allowed ? <Button onClick={() => setCreating(true)}>Create a role</Button> : undefined}
          />
        )}
      </section>
      {creating && <NewRoleDialog open onOpenChange={setCreating} roles={roles.data} />}
    </div>
  );
}
