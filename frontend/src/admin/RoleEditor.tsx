// One role: its name, the capabilities it holds (the records matrix and the other modules), which records it sees per
// object, the per-field hidden and read-only matrix, and the people who hold it in this workspace.
import { ChevronDown, Copy, LockKeyhole, Trash2, TriangleAlert, UserPlus } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useNavigate } from "react-router";
import { ApiError } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { whatWentWrong } from "../lib/errors";
import { Badge, Button, Checkbox, EmptyState, Input, Select, Textarea, useToast } from "../ui";
import { Combobox } from "../ui/Combobox";
import { assignRole, deleteRole, getCatalog, getRole, listFields, listMembers, listObjects, listRoles, patchRole, type CatalogEntry, type FieldDef, type ObjectDef, type Role } from "./api";
import { AdminHeader, ConfirmDialog, isDenied, LoadError, Loading, personName, useLoad, useUnsavedGuard } from "./common";
import { accessOf, ACTIONS, ANY, capabilityWarnings, familyOf, FAMILIES, groupCatalog, roleChanges, ruleFor, sameRole, SCOPES, scopeLabel, withAccess, withScope, type Access, type RoleDraft, type Rule, type Scope } from "./logic.ts";
import { NewRoleDialog, useRoleEditing } from "./Roles";
import "./admin.css";

const draftOf = (r: Role): RoleDraft => ({ name: r.name, description: r.description, capabilities: [...r.capabilities], object_rules: r.object_rules.map((x) => ({ ...x })) });
const ACCESS: { value: Access; label: string }[] = [
  { value: "edit", label: "Can edit" },
  { value: "readonly", label: "Read-only" },
  { value: "hidden", label: "Hidden" },
];

export function RoleEditor({ id }: { id: string }) {
  const role = useLoad(() => getRole(id), [id]);
  const catalog = useLoad(getCatalog, []);
  const objects = useLoad(() => listObjects(), []);
  const back = { to: "/settings/team/roles", label: "Roles" };

  if (role.error && !role.data) {
    const missing = role.error instanceof ApiError && role.error.status === 404;
    return (
      <div className="sh-page adm-page">
        <AdminHeader title={missing ? "Role not found" : "Role"} back={back} />
        {missing ? <EmptyState icon={TriangleAlert} title="This role does not exist" text="It may have been deleted. Pick one from the list of roles." /> : <LoadError what="the role" error={role.error} retry={role.reload} />}
      </div>
    );
  }
  if (catalog.error || objects.error) {
    return (
      <div className="sh-page adm-page">
        <AdminHeader title={role.data?.name ?? "Role"} back={back} />
        <LoadError what="what roles are made of" error={catalog.error ?? objects.error} retry={() => (catalog.reload(), objects.reload())} />
      </div>
    );
  }
  if (!role.data || !catalog.data || !objects.data) {
    return (
      <div className="sh-page adm-page">
        <AdminHeader title="Role" back={back} />
        <Loading label="Loading the role" rows={4} height={120} />
      </div>
    );
  }
  return <Editor key={role.data.id} role={role.data} catalog={catalog.data.capabilities} objects={objects.data} onSaved={(r) => role.setData(r)} />;
}

function Editor({ role, catalog, objects, onSaved }: { role: Role; catalog: CatalogEntry[]; objects: ObjectDef[]; onSaved: (r: Role) => void }) {
  const toast = useToast();
  const navigate = useNavigate();
  const { allowed, ready } = useRoleEditing();
  const editable = allowed && !role.locked;
  const [draft, setDraft] = useState<RoleDraft>(() => draftOf(role));
  const saved = useMemo(() => draftOf(role), [role]);
  const dirty = !sameRole(saved, draft);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [busyDelete, setBusyDelete] = useState(false);
  const [duplicating, setDuplicating] = useState(false);
  const roles = useLoad(listRoles, [], duplicating);
  const guard = useUnsavedGuard(dirty && !busyDelete);

  const held = new Set(draft.capabilities);
  const toggle = (caps: string[], on: boolean) =>
    setDraft((d) => ({ ...d, capabilities: on ? [...new Set([...d.capabilities, ...caps])] : d.capabilities.filter((c) => !caps.includes(c)) }));
  const setRules = (f: (r: Rule[]) => Rule[]) => setDraft((d) => ({ ...d, object_rules: f(d.object_rules) }));

  const save = async () => {
    if (!draft.name.trim()) return setError("Give the role a name.");
    setSaving(true);
    setError(null);
    try {
      const body: Parameters<typeof patchRole>[1] = {};
      if (draft.name.trim() !== saved.name || draft.description.trim() !== saved.description) Object.assign(body, { name: draft.name.trim(), description: draft.description.trim() });
      body.capabilities = [...new Set(draft.capabilities)].sort();
      body.object_rules = draft.object_rules;
      const next = await patchRole(role.id, body);
      onSaved(next);
      setDraft(draftOf(next));
      toast({ title: "Role saved", description: "It applies on the next request of everyone who holds it, in every workspace.", tone: "success" });
    } catch (e) {
      setError(whatWentWrong(e));
    } finally {
      setSaving(false);
    }
  };

  useEffect(() => {
    if (!editable) return;
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (dirty && !saving) void save();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const remove = async () => {
    setBusyDelete(true);
    try {
      await deleteRole(role.id);
      toast({ title: "Role deleted", description: role.name, tone: "success" });
      navigate("/settings/team/roles");
    } catch (e) {
      toast({ title: "Could not delete the role", description: whatWentWrong(e), tone: "danger", duration: 8000 });
      setBusyDelete(false);
      setDeleting(false);
    }
  };

  const modules = groupCatalog(catalog).filter((g) => g.module !== "Records");
  const warnings = capabilityWarnings(draft.capabilities);

  return (
    <div className="sh-page adm-page adm-editor" data-dirty={dirty || undefined}>
      <AdminHeader
        title={role.name}
        description={role.is_system ? "A system role. It exists in every organization and cannot be deleted." : "A custom role of this organization."}
        back={{ to: "/settings/team/roles", label: "Roles" }}
        actions={
          <>
            {allowed && (
              <Button onClick={() => setDuplicating(true)}>
                <Copy size={16} aria-hidden /> Duplicate
              </Button>
            )}
            {allowed && !role.is_system && (
              <Button variant="danger" onClick={() => setDeleting(true)}>
                <Trash2 size={16} aria-hidden /> Delete
              </Button>
            )}
          </>
        }
      />
      {role.locked ? (
        <p className="adm-note" data-tone="info" role="note">
          <LockKeyhole size={14} aria-hidden /> {role.name} always holds every capability{role.key === "admin" ? " but billing" : ""} and sees every record. To make a limited version, duplicate it.
        </p>
      ) : ready && !allowed ? (
        <p className="adm-note" data-tone="info" role="note">
          <LockKeyhole size={14} aria-hidden /> Only organization owners and admins with the capability roles.manage change roles, because a change reaches every workspace. You can look at this one.
        </p>
      ) : null}

      <Section title="Name" id="role-name">
        <div className="adm-grid-2">
          <Input label="Name" value={draft.name} maxLength={100} disabled={!editable} onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))} />
          <Textarea label="Description" value={draft.description} maxLength={500} rows={2} disabled={!editable} onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))} />
        </div>
      </Section>

      <Section title="What it may do" id="role-caps" text="Capabilities decide which actions the role may take. The records it may take them on are set below.">
        <RecordMatrix held={held} editable={editable} onToggle={toggle} />
        {warnings.length > 0 && (
          <ul className="adm-warnings" aria-label="Things to check">
            {warnings.map((w) => (
              <li key={w}>
                <TriangleAlert size={14} aria-hidden /> {w}
              </li>
            ))}
          </ul>
        )}
        <div className="adm-modules">
          {modules.map((g) => {
            const caps = g.items.map((i) => i.capability);
            const count = caps.filter((c) => held.has(c)).length;
            return (
              <fieldset key={g.module} className="adm-module">
                <legend>
                  <Checkbox
                    label={g.module}
                    checked={count === caps.length ? true : count ? "indeterminate" : false}
                    disabled={!editable}
                    onCheckedChange={(on) => toggle(caps, on)}
                    aria-label={`All of ${g.module}`}
                  />
                  <span className="adm-muted">
                    {count} of {caps.length}
                  </span>
                </legend>
                <ul>
                  {g.items.map((i) => (
                    <li key={i.capability}>
                      <Checkbox label={i.description} checked={held.has(i.capability)} disabled={!editable} onCheckedChange={(on) => toggle([i.capability], on)} />
                      <code className="adm-cap mono">{i.capability}</code>
                    </li>
                  ))}
                </ul>
              </fieldset>
            );
          })}
        </div>
      </Section>

      <Section title="Which records" id="role-scope" text="Per object, which records the role sees. Records outside its scope do not exist for it: not in lists, search, counts, links or the timeline.">
        <ScopeTable rules={draft.object_rules} objects={objects} held={held} editable={editable} onChange={setRules} />
      </Section>

      <Section title="Fields" id="role-fields" text="Hide a field, or make it read-only, for this role. A hidden field is not a field at all for it: not shown, not searchable, not filterable. Do not hide or lock a field that is required, or the role cannot create that kind of record.">
        <div className="adm-stack">
          {objects.map((o) => (
            <FieldMatrix key={o.key} object={o} rules={draft.object_rules} editable={editable} onChange={setRules} />
          ))}
        </div>
      </Section>

      <Holders role={role} />

      {(dirty || error) && (
        <div className="adm-savebar" role="region" aria-label="Unsaved changes">
          <div className="adm-savebar-text">
            {error ? (
              <span role="alert" className="adm-error">
                <TriangleAlert size={14} aria-hidden /> {error}
              </span>
            ) : (
              <span>Unsaved: {roleChanges(saved, draft).join(", ")}</span>
            )}
          </div>
          <div className="adm-savebar-actions">
            <Button variant="ghost" onClick={() => (setDraft(draftOf(role)), setError(null))} disabled={saving}>
              Discard
            </Button>
            <Button variant="primary" onClick={() => void save()} loading={saving} disabled={!dirty}>
              Save role
            </Button>
          </div>
        </div>
      )}

      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title={`Delete ${role.name}?`}
        description="The role disappears from every workspace of the organization. A role that someone still holds cannot be deleted: give them another one first."
        confirm="Delete role"
        busy={busyDelete}
        onConfirm={() => void remove()}
      />
      {duplicating && roles.data && <NewRoleDialog open onOpenChange={setDuplicating} roles={roles.data} from={role} />}
      {guard}
    </div>
  );
}

function Section({ title, id, text, children }: { title: string; id: string; text?: string; children: ReactNode }) {
  return (
    <section className="adm-section" aria-labelledby={id}>
      <h2 id={id} className="adm-h2">
        {title}
      </h2>
      {text && <p className="adm-muted adm-section-text">{text}</p>}
      {children}
    </section>
  );
}

/** Contacts, companies, deals and custom objects against see, create and edit, delete and export. */
function RecordMatrix({ held, editable, onToggle }: { held: Set<string>; editable: boolean; onToggle: (caps: string[], on: boolean) => void }) {
  return (
    <div className="adm-matrix-wrap">
      <table className="adm-matrix">
        <caption className="sr-only">Record capabilities</caption>
        <thead>
          <tr>
            <th scope="col">Records</th>
            {ACTIONS.map((a) => (
              <th scope="col" key={a.key}>
                {a.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {FAMILIES.map((f) => (
            <tr key={f.key}>
              <th scope="row">{f.label}</th>
              {ACTIONS.map((a) => {
                const cap = `${f.key}.${a.key}`;
                return (
                  <td key={a.key}>
                    <Checkbox aria-label={`${f.label}: ${a.label}`} checked={held.has(cap)} disabled={!editable} onCheckedChange={(on) => onToggle([cap], on)} />
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const INHERIT = "inherit";

function ScopeTable({ rules, objects, held, editable, onChange }: { rules: Rule[]; objects: ObjectDef[]; held: Set<string>; editable: boolean; onChange: (f: (r: Rule[]) => Rule[]) => void }) {
  const any = rules.find((r) => r.object_key === ANY);
  const rows = [...objects.map((o) => ({ key: o.key, label: o.plural })), { key: ANY, label: "Any other object" }];
  return (
    <ul className="adm-scopes">
      {rows.map((row) => {
        const own = rules.find((r) => r.object_key === row.key);
        const applied = row.key === ANY ? any : ruleFor(rules, row.key);
        const family = familyOf(row.key);
        const reads = row.key === ANY || held.has(`${family}.read`);
        const options =
          row.key === ANY
            ? [{ value: INHERIT, label: "No records" }, ...SCOPES.filter((s) => s.value !== "none").map((s) => ({ value: s.value, label: s.label }))]
            : [{ value: INHERIT, label: `Same as any other object (${any ? scopeLabel(any.scope) : "no records"})` }, ...SCOPES.map((s) => ({ value: s.value, label: s.label }))];
        const value = row.key === ANY ? (any && any.scope !== "none" ? any.scope : INHERIT) : (own?.scope ?? INHERIT);
        const help = SCOPES.find((s) => s.value === (applied?.scope ?? "none"))?.help;
        return (
          <li key={row.key} className="adm-scope">
            <div className="adm-scope-name">
              <strong>{row.label}</strong>
              <span className="adm-muted">{row.key === ANY ? "Objects without a rule of their own, custom objects added later included." : help}</span>
              {!reads && (
                <span className="adm-warn-inline">
                  <TriangleAlert size={13} aria-hidden /> Without {family}.read it sees none of them, whatever the scope.
                </span>
              )}
            </div>
            <div className="adm-scope-pick">
              <Select
                aria-label={`Records of ${row.label} the role sees`}
                value={value}
                options={options}
                disabled={!editable}
                onValueChange={(v) => onChange((r) => (v === INHERIT ? (row.key === ANY ? withScope(r, ANY, null) : withScope(r, row.key, null)) : withScope(r, row.key, v as Scope)))}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

/** The hidden and read-only matrix of one object: one row per field, three choices each. Fields load when it opens. */
function FieldMatrix({ object, rules, editable, onChange }: { object: ObjectDef; rules: Rule[]; editable: boolean; onChange: (f: (r: Rule[]) => Rule[]) => void }) {
  const [open, setOpen] = useState(false);
  const fields = useLoad(() => listFields(object.key), [object.key], open);
  const own = rules.find((r) => r.object_key === object.key);
  const rule = ruleFor(rules, object.key);
  const hidden = own?.hidden_fields.length ?? 0;
  const readonly = own?.readonly_fields.length ?? 0;
  const known = new Set((fields.data ?? []).map((f) => f.key));
  const stale = own ? [...own.hidden_fields, ...own.readonly_fields].filter((k) => fields.data && !known.has(k)) : [];
  const summary = hidden || readonly ? [hidden && `${hidden} hidden`, readonly && `${readonly} read-only`].filter(Boolean).join(", ") : "Every field visible and editable";

  return (
    <details className="adm-fields" open={open} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>
        <ChevronDown size={16} aria-hidden className="adm-chevron" />
        <strong>{object.plural}</strong>
        <span className="adm-muted">{summary}</span>
      </summary>
      <div className="adm-fields-body">
        {!own && rule && <p className="adm-muted">This object follows the rule for any other object. Changing a field gives it a rule of its own with the same scope.</p>}
        {rule?.scope === "none" && <p className="adm-note" data-tone="warning">The role sees no {object.plural.toLowerCase()}, so field rules change nothing until it does.</p>}
        {fields.error ? (
          isDenied(fields.error) ? <p className="adm-note">Your role cannot read the fields of {object.plural.toLowerCase()}.</p> : <LoadError what="the fields" error={fields.error} retry={fields.reload} />
        ) : !fields.data ? (
          <Loading label={`Loading fields of ${object.plural}`} rows={3} height={36} />
        ) : (
          <div className="adm-matrix-wrap">
            <table className="adm-matrix adm-access">
              <caption className="sr-only">Field access of {object.plural} for this role</caption>
              <thead>
                <tr>
                  <th scope="col">Field</th>
                  {ACCESS.map((a) => (
                    <th scope="col" key={a.value}>
                      {a.label}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {fields.data.map((f) => (
                  <AccessRow key={f.key} object={object.key} field={f} access={accessOf(own, f.key)} editable={editable} onChange={(a) => onChange((r) => withAccess(r, object.key, f.key, a))} />
                ))}
              </tbody>
            </table>
          </div>
        )}
        {stale.length > 0 && <p className="adm-muted">Also listed for fields that are archived or that your role cannot see: {stale.join(", ")}.</p>}
      </div>
    </details>
  );
}

function AccessRow({ object, field, access, editable, onChange }: { object: string; field: FieldDef; access: Access; editable: boolean; onChange: (a: Access) => void }) {
  const name = `access-${object}-${field.key}`;
  const required = field.rules.required === true;
  return (
    <tr data-access={access}>
      <th scope="row">
        <span className="adm-field-name">
          {field.label}
          <code className="mono adm-muted">{field.key}</code>
          {required && access !== "edit" && (
            <Badge tone="warning">
              <TriangleAlert size={12} aria-hidden /> Required
            </Badge>
          )}
        </span>
      </th>
      {ACCESS.map((a) => (
        <td key={a.value}>
          <input type="radio" className="adm-radio" name={name} value={a.value} checked={access === a.value} disabled={!editable} onChange={() => onChange(a.value)} aria-label={`${field.label}: ${a.label}`} />
        </td>
      ))}
    </tr>
  );
}

/** Who holds the role in this workspace, and giving it to someone else. */
function Holders({ role }: { role: Role }) {
  const toast = useToast();
  const { can } = useCan();
  const members = useLoad(listMembers, []);
  const [busy, setBusy] = useState(false);
  const have = (members.data ?? []).filter((m) => m.role.id === role.id);
  const others = (members.data ?? []).filter((m) => m.role.id !== role.id && !m.implicit);

  const give = async (userId: string) => {
    const m = members.data?.find((x) => x.user_id === userId);
    if (!m) return;
    setBusy(true);
    try {
      await assignRole(userId, role.id);
      members.setData((list) => list?.map((x) => (x.user_id === userId ? { ...x, role: { id: role.id, key: role.key, name: role.name } } : x)) ?? null);
      toast({ title: "Role given", description: `${personName(m)} is now ${role.name} in this workspace.`, tone: "success" });
    } catch (e) {
      toast({ title: "Could not give the role", description: whatWentWrong(e), tone: "danger", duration: 8000 });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Section title="People with this role here" id="role-people" text="The role is set per workspace. These people hold it in this one.">
      {members.error ? (
        <LoadError what="members" error={members.error} retry={members.reload} />
      ) : !members.data ? (
        <Loading label="Loading members" rows={2} height={40} />
      ) : (
        <div className="adm-stack">
          {have.length ? (
            <ul className="adm-people">
              {have.map((m) => (
                <li key={m.user_id}>
                  <strong>{personName(m)}</strong> <span className="adm-muted">{m.email}</span>
                  {m.implicit && <Badge tone="accent">Organization {m.role.key}</Badge>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="adm-muted">Nobody holds this role in this workspace.</p>
          )}
          {can("members.manage") && !role.locked && others.length > 0 && (
            <div className="adm-inline">
              <Combobox
                label="Give this role to"
                placeholder="Give this role to..."
                items={others.map((m) => ({ value: m.user_id, label: personName(m), hint: m.role.name }))}
                value={null}
                onChange={(v) => void give(v)}
                disabled={busy}
                trigger={
                  <Button loading={busy}>
                    <UserPlus size={16} aria-hidden /> Give this role to...
                  </Button>
                }
              />
            </div>
          )}
        </div>
      )}
    </Section>
  );
}
