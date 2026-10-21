// Settings > Objects and fields: the objects of the workspace (contacts, companies, deals and custom ones), each with its
// fields in order and the association types that link it to other objects. /settings/fields/:object opens one.
import { Archive, ArchiveRestore, ArrowDown, ArrowUp, Box, ChevronRight, Link2, Pencil, Plus, Trash2, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { whatWentWrong } from "../lib/errors";
import { Badge, Button, Dialog, EmptyState, Input, Select, Switch, useToast } from "../ui";
import { createAssociationType, createObject, deleteAssociationType, listAssociationTypes, listFields, listObjects, patchField, patchObject, reorderFields, type AssociationType, type FieldDef, type ObjectDef } from "./api";
import { AdminHeader, ConfirmDialog, Denied, isDenied, LoadError, Loading, useLoad, useGate } from "./common";
import { FieldDialog } from "./FieldDialog";
import { CARDINALITIES, move, NAME_TYPES, objectKeyFrom, pluralOf, typeLabel } from "./logic.ts";
import "./admin.css";

const ICONS = [
  { value: "box", label: "Box" },
  { value: "user", label: "Person" },
  { value: "building", label: "Building" },
  { value: "handshake", label: "Handshake" },
  { value: "home", label: "Home" },
  { value: "briefcase", label: "Briefcase" },
  { value: "calendar", label: "Calendar" },
  { value: "file", label: "Document" },
  { value: "package", label: "Package" },
  { value: "star", label: "Star" },
];

export function DataModelPage() {
  const { object } = useParams();
  const gate = useGate("schema.read");
  if (gate === "wait")
    return (
      <div className="sh-page adm-page">
        <AdminHeader title="Objects and fields" />
        <Loading label="Loading" rows={3} height={56} />
      </div>
    );
  if (gate === "no")
    return (
      <div className="sh-page adm-page">
        <AdminHeader title="Objects and fields" />
        <Denied what="see the data model" capability="schema.read" />
      </div>
    );
  return object ? <ObjectPage objectKey={object} /> : <ObjectList />;
}

function NewObjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (o: boolean) => void }) {
  const navigate = useNavigate();
  const toast = useToast();
  const [singular, setSingular] = useState("");
  const [plural, setPlural] = useState("");
  const [key, setKey] = useState("");
  const [icon, setIcon] = useState("box");
  const [touched, setTouched] = useState({ plural: false, key: false });
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const found: Record<string, string> = {};
    if (!singular.trim()) found.singular = "Name one record, like Property.";
    if (!plural.trim()) found.plural = "Name several, like Properties.";
    if (!/^[a-z][a-z0-9_]{0,39}$/.test(key)) found.key = "Lower case letters, digits and _, starting with a letter (at most 40).";
    else if (key === "tags") found.key = "tags is reserved.";
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      const obj = await createObject({ key, singular: singular.trim(), plural: plural.trim(), icon });
      toast({ title: `${obj.plural} created`, description: "It starts with a required Name field. Add the fields it needs.", tone: "success" });
      onOpenChange(false);
      navigate(`/settings/fields/${obj.key}`);
    } catch (err) {
      const f = err instanceof ApiError ? err.fields : undefined;
      if (err instanceof ApiError && err.status === 409) setErrors({ key: `${err.message}.` });
      else if (f) setErrors(Object.fromEntries(Object.entries(f).map(([k, v]) => [k, v.charAt(0).toUpperCase() + v.slice(1) + "."])));
      else setErrors({ form: whatWentWrong(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="New object"
      description="A kind of record of your own, like Properties, Vehicles or Policies. It gets a list, filters, views, a timeline and the API, like contacts."
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" type="submit" form="new-object" loading={busy}>
            Create object
          </Button>
        </>
      }
    >
      <form id="new-object" className="adm-form" onSubmit={submit} noValidate>
        <Input
          label="Name of one record"
          placeholder="Property"
          value={singular}
          maxLength={100}
          autoFocus
          error={errors.singular}
          onChange={(e) => {
            const v = e.target.value;
            setSingular(v);
            if (!touched.plural) setPlural(pluralOf(v));
            if (!touched.key) setKey(objectKeyFrom(v));
          }}
        />
        <Input label="Name of several" placeholder="Properties" value={plural} maxLength={100} error={errors.plural} onChange={(e) => (setPlural(e.target.value), setTouched((t) => ({ ...t, plural: true })))} />
        <Input label="Key" className="mono" value={key} maxLength={40} error={errors.key} hint="Used in the API and in filters. It never changes." spellCheck={false} onChange={(e) => (setKey(e.target.value), setTouched((t) => ({ ...t, key: true })))} />
        <Select label="Icon" value={icon} onValueChange={setIcon} options={ICONS} />
        {errors.form && (
          <p className="ui-hint" data-tone="danger" role="alert">
            {errors.form}
          </p>
        )}
      </form>
    </Dialog>
  );
}

function ObjectList() {
  const { can } = useCan();
  const [archived, setArchived] = useState(false);
  const objects = useLoad(() => listObjects(archived), [archived]);
  const [creating, setCreating] = useState(false);
  const manage = can("objects.manage");

  return (
    <div className="sh-page adm-page">
      <AdminHeader
        title="Objects and fields"
        description="The kinds of records in this workspace, their fields and how they link to each other."
        actions={
          manage ? (
            <Button variant="primary" onClick={() => setCreating(true)}>
              <Plus size={16} aria-hidden /> New object
            </Button>
          ) : undefined
        }
      />
      <div className="adm-toolbar">
        <Switch label="Show archived objects" checked={archived} onCheckedChange={setArchived} />
      </div>
      {objects.error && !objects.data ? (
        isDenied(objects.error) ? <Denied what="see the data model" capability="schema.read" /> : <LoadError what="objects" error={objects.error} retry={objects.reload} />
      ) : !objects.data || objects.loading ? (
        <Loading label="Loading objects" rows={3} height={56} />
      ) : objects.data.length === 0 ? (
        <EmptyState icon={Box} title={archived ? "No archived objects" : "No objects"} text={archived ? "Objects you archive show here, with their records kept, until you bring them back." : "Every workspace has contacts, companies and deals."} />
      ) : (
        <ul className="adm-rows">
          {objects.data.map((o) => (
            <li key={o.key}>
              <Link to={`/settings/fields/${o.key}`} className="adm-row-link">
                <span className="adm-row-main">
                  <strong>{o.plural}</strong>
                  <span className="adm-muted mono">{o.key}</span>
                </span>
                <span className="adm-row-meta">
                  {o.is_system ? <Badge>Built in</Badge> : <Badge tone="accent">Custom</Badge>}
                  {o.archived_at && <Badge tone="warning">Archived</Badge>}
                  <ChevronRight size={16} aria-hidden />
                </span>
              </Link>
            </li>
          ))}
        </ul>
      )}
      {creating && <NewObjectDialog open onOpenChange={setCreating} />}
    </div>
  );
}

function ObjectPage({ objectKey }: { objectKey: string }) {
  const toast = useToast();
  const { can } = useCan();
  const manageObjects = can("objects.manage");
  const live = useLoad(() => listObjects(false), [objectKey]);
  const gone = useLoad(() => listObjects(true), [objectKey]);
  const back = { to: "/settings/fields", label: "Objects and fields" };
  const [editing, setEditing] = useState(false);
  const [archiving, setArchiving] = useState(false);
  const [busy, setBusy] = useState(false);

  const all = [...(live.data ?? []), ...(gone.data ?? [])];
  const obj = all.find((o) => o.key === objectKey);
  const loading = !live.data || !gone.data;
  if ((live.error || gone.error) && loading)
    return (
      <div className="sh-page adm-page">
        <AdminHeader title="Object" back={back} />
        {isDenied(live.error) ? <Denied what="see the data model" capability="schema.read" /> : <LoadError what="the object" error={live.error ?? gone.error} retry={() => (live.reload(), gone.reload())} />}
      </div>
    );
  if (loading)
    return (
      <div className="sh-page adm-page">
        <AdminHeader title="Object" back={back} />
        <Loading label="Loading the object" rows={4} height={48} />
      </div>
    );
  if (!obj)
    return (
      <div className="sh-page adm-page">
        <AdminHeader title="Object not found" back={back} />
        <EmptyState icon={TriangleAlert} title="This object does not exist" text="Check the address, or pick it from the list." />
      </div>
    );

  const setArchived = async (archived: boolean) => {
    setBusy(true);
    try {
      await patchObject(obj.key, { archived });
      toast({ title: archived ? `${obj.plural} archived` : `${obj.plural} restored`, description: archived ? "Its records are kept; restore it to bring them back." : undefined, tone: "success" });
      live.reload();
      gone.reload();
      setArchiving(false);
    } catch (e) {
      toast({ title: "Could not change the object", description: whatWentWrong(e), tone: "danger" });
    } finally {
      setBusy(false);
    }
  };

  const archived = !!obj.archived_at;
  return (
    <div className="sh-page adm-page">
      <AdminHeader
        title={obj.plural}
        description={obj.is_system ? "Built in. Its key and built-in fields cannot change, but you can add fields and rename it." : "A custom object."}
        back={back}
        actions={
          manageObjects ? (
            <>
              {!archived && (
                <Button onClick={() => setEditing(true)}>
                  <Pencil size={16} aria-hidden /> Edit object
                </Button>
              )}
              {!obj.is_system &&
                (archived ? (
                  <Button onClick={() => void setArchived(false)} loading={busy}>
                    <ArchiveRestore size={16} aria-hidden /> Restore
                  </Button>
                ) : (
                  <Button variant="danger" onClick={() => setArchiving(true)}>
                    <Archive size={16} aria-hidden /> Archive
                  </Button>
                ))}
            </>
          ) : undefined
        }
      />
      {archived ? (
        <p className="adm-note" data-tone="warning">
          This object is archived: it is hidden everywhere and its records are kept. Restore it to see and change its fields.
        </p>
      ) : (
        <>
          <dl className="adm-facts">
            <div>
              <dt>Key</dt>
              <dd className="mono">{obj.key}</dd>
            </div>
            <div>
              <dt>One record</dt>
              <dd>{obj.singular}</dd>
            </div>
            <div>
              <dt>Named by</dt>
              <dd className="mono">{obj.primary_fields.join(" + ")}</dd>
            </div>
          </dl>
          <Fields object={obj} />
          <Associations object={obj} objects={live.data ?? []} />
        </>
      )}
      {editing && <EditObjectDialog object={obj} onClose={() => setEditing(false)} onSaved={() => (setEditing(false), live.reload())} />}
      <ConfirmDialog
        open={archiving}
        onOpenChange={setArchiving}
        title={`Archive ${obj.plural}?`}
        description="It disappears from the app and the API with its records, views and links, which are all kept. You can restore it from the archived objects."
        confirm="Archive"
        busy={busy}
        onConfirm={() => void setArchived(true)}
      />
    </div>
  );
}

function EditObjectDialog({ object, onClose, onSaved }: { object: ObjectDef; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const fields = useLoad(() => listFields(object.key), [object.key]);
  const [singular, setSingular] = useState(object.singular);
  const [plural, setPlural] = useState(object.plural);
  const [icon, setIcon] = useState(object.icon);
  const [primary, setPrimary] = useState<string[]>(object.primary_fields);
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const namers = (fields.data ?? []).filter((f) => NAME_TYPES.includes(f.type));

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const found: Record<string, string> = {};
    if (!singular.trim()) found.singular = "Required.";
    if (!plural.trim()) found.plural = "Required.";
    if (primary.length === 0) found.primary = "Pick at least one field.";
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      const body: Parameters<typeof patchObject>[1] = { singular: singular.trim(), plural: plural.trim(), icon };
      if (primary.join() !== object.primary_fields.join()) body.primary_fields = primary;
      await patchObject(object.key, body);
      toast({ title: "Object saved", description: body.primary_fields ? "Every record was renamed from the new name fields." : undefined, tone: "success" });
      onSaved();
    } catch (err) {
      const f = err instanceof ApiError ? err.fields : undefined;
      if (f) setErrors({ ...Object.fromEntries(Object.entries(f).map(([k, v]) => [k === "primary_fields" ? "primary" : k, v.charAt(0).toUpperCase() + v.slice(1) + "."])) });
      else setErrors({ form: whatWentWrong(err) });
    } finally {
      setBusy(false);
    }
  };

  const slot = (i: number) => (
    <Select
      key={i}
      label={i === 0 ? "Named by" : `then (optional)`}
      value={primary[i] ?? "none"}
      onValueChange={(v) => setPrimary((p) => (v === "none" ? p.filter((_, j) => j !== i) : [...p.slice(0, i), v, ...p.slice(i + 1)].filter((k, j, a) => a.indexOf(k) === j)))}
      options={[...(i === 0 ? [] : [{ value: "none", label: "Nothing" }]), ...namers.filter((f) => f.key === primary[i] || !primary.includes(f.key)).map((f) => ({ value: f.key, label: f.label }))]}
    />
  );

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title={`Edit ${object.plural}`}
      description="The key never changes. Changing what names a record renames every record at once."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="edit-object" loading={busy}>
            Save
          </Button>
        </>
      }
    >
      <form id="edit-object" className="adm-form" onSubmit={submit} noValidate>
        <Input label="Name of one record" value={singular} maxLength={100} onChange={(e) => setSingular(e.target.value)} error={errors.singular} />
        <Input label="Name of several" value={plural} maxLength={100} onChange={(e) => setPlural(e.target.value)} error={errors.plural} />
        <Select label="Icon" value={icon} onValueChange={setIcon} options={ICONS.some((i) => i.value === icon) ? ICONS : [{ value: icon, label: icon }, ...ICONS]} />
        <fieldset className="adm-fieldset">
          <legend className="ui-label">What names a record</legend>
          {fields.error ? <LoadError what="fields" error={fields.error} retry={fields.reload} /> : !fields.data ? <Loading label="Loading fields" rows={1} height={36} /> : [0, 1, 2].filter((i) => i <= primary.length && i < 3).map(slot)}
          {errors.primary && (
            <p className="ui-hint" data-tone="danger" role="alert">
              {errors.primary}
            </p>
          )}
          <p className="ui-hint">Text, email, phone or URL fields, up to three, joined with spaces.</p>
        </fieldset>
        {errors.form && (
          <p className="ui-hint" data-tone="danger" role="alert">
            {errors.form}
          </p>
        )}
      </form>
    </Dialog>
  );
}

function Fields({ object }: { object: ObjectDef }) {
  const toast = useToast();
  const { can } = useCan();
  const manage = can("fields.manage");
  const fields = useLoad(() => listFields(object.key), [object.key]);
  const [showArchived, setShowArchived] = useState(false);
  const archived = useLoad(() => listFields(object.key, true), [object.key, showArchived], showArchived);
  const [dialog, setDialog] = useState<{ field?: FieldDef } | null>(null);
  const [archiving, setArchiving] = useState<FieldDef | null>(null);
  const [busy, setBusy] = useState(false);
  const [moving, setMoving] = useState(false);
  const [announce, setAnnounce] = useState("");
  const list = useRef<HTMLOListElement>(null);
  const refocus = useRef<{ key: string; dir: "up" | "down" } | null>(null);
  // Keep the keyboard on the field that moved: its arrow in the same direction, or the other one at the end of the list.
  useEffect(() => {
    const want = refocus.current;
    if (moving || !want) return;
    refocus.current = null;
    const q = (dir: string) => list.current?.querySelector<HTMLButtonElement>(`[data-move="${want.key}"][data-dir="${dir}"]:not(:disabled)`);
    (q(want.dir) ?? q(want.dir === "up" ? "down" : "up"))?.focus();
  }, [moving, fields.data]);
  const taken = useMemo(() => [...(fields.data ?? []), ...(archived.data ?? [])].map((f) => f.key), [fields.data, archived.data]);

  const reorder = async (from: number, to: number) => {
    const current = fields.data;
    if (!current || moving) return;
    const next = move(current, from, to);
    if (next === current) return;
    fields.setData(next); // at once; put back if the server says no
    setMoving(true);
    const f = current[from]!;
    try {
      fields.setData(await reorderFields(object.key, next.map((x) => x.key)));
      setAnnounce(`${f.label} moved to position ${Math.max(0, Math.min(next.length - 1, to)) + 1} of ${next.length}.`);
      refocus.current = { key: f.key, dir: to < from ? "up" : "down" };
    } catch (e) {
      fields.setData(current);
      toast({ title: "Could not move the field", description: whatWentWrong(e), tone: "danger" });
    } finally {
      setMoving(false);
    }
  };
  const onRowKey = (e: KeyboardEvent, i: number) => {
    if (!manage || !e.altKey || (e.key !== "ArrowUp" && e.key !== "ArrowDown")) return;
    e.preventDefault();
    void reorder(i, i + (e.key === "ArrowUp" ? -1 : 1));
  };
  const setFieldArchived = async (f: FieldDef, value: boolean) => {
    setBusy(true);
    try {
      await patchField(object.key, f.key, { archived: value });
      toast({
        title: value ? `${f.label} archived` : `${f.label} restored`,
        description: value ? "Its values are kept." : undefined,
        tone: "success",
        action: value ? { label: "Undo", onClick: () => void patchField(object.key, f.key, { archived: false }).then(() => (fields.reload(), archived.reload())) } : undefined,
      });
      setArchiving(null);
      fields.reload();
      archived.reload();
    } catch (e) {
      toast({ title: "Could not change the field", description: whatWentWrong(e), tone: "danger" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="adm-section" aria-labelledby="fields-title">
      <div className="adm-section-head">
        <div>
          <h2 id="fields-title" className="adm-h2">
            Fields
          </h2>
          <p className="adm-muted">{manage ? "In the order they show on a record. Move one with its arrows, or Alt and the arrow keys." : "In the order they show on a record."}</p>
        </div>
        {manage && (
          <Button variant="primary" onClick={() => setDialog({})}>
            <Plus size={16} aria-hidden /> Add field
          </Button>
        )}
      </div>
      <p className="sr-only" aria-live="polite">
        {announce}
      </p>
      {fields.error && !fields.data ? (
        <LoadError what="fields" error={fields.error} retry={fields.reload} />
      ) : !fields.data ? (
        <Loading label="Loading fields" rows={4} height={48} />
      ) : fields.data.length === 0 ? (
        <EmptyState icon={Box} title="No fields" text="Add the first field." />
      ) : (
        <ol className="adm-field-list" ref={list} aria-label={`Fields of ${object.plural}`}>
          {fields.data.map((f, i) => (
            <li key={f.key} className="adm-field-row" onKeyDown={(e) => onRowKey(e, i)}>
              {manage && (
                <span className="adm-move">
                  <Button size="icon" variant="ghost" data-move={f.key} data-dir="up" aria-label={`Move ${f.label} up`} disabled={i === 0 || moving} onClick={() => void reorder(i, i - 1)}>
                    <ArrowUp size={14} aria-hidden />
                  </Button>
                  <Button size="icon" variant="ghost" data-move={f.key} data-dir="down" aria-label={`Move ${f.label} down`} disabled={i === fields.data!.length - 1 || moving} onClick={() => void reorder(i, i + 1)}>
                    <ArrowDown size={14} aria-hidden />
                  </Button>
                </span>
              )}
              <span className="adm-field-main">
                <strong>{f.label}</strong>
                <code className="mono adm-muted">{f.key}</code>
              </span>
              <span className="adm-field-meta">
                <Badge tone="info">{typeLabel(f.type)}</Badge>
                {f.rules.required === true && <Badge tone="warning">Required</Badge>}
                {object.primary_fields.includes(f.key) && <Badge tone="accent">Names records</Badge>}
                {f.is_system && <Badge>Built in</Badge>}
              </span>
              {manage && (
                <span className="adm-actions">
                  <Button size="sm" variant="ghost" onClick={() => setDialog({ field: f })} aria-label={`Edit ${f.label}`}>
                    <Pencil size={14} aria-hidden /> Edit
                  </Button>
                  {!f.is_system && !object.primary_fields.includes(f.key) && (
                    <Button size="sm" variant="ghost" onClick={() => setArchiving(f)} aria-label={`Archive ${f.label}`}>
                      <Archive size={14} aria-hidden /> Archive
                    </Button>
                  )}
                </span>
              )}
            </li>
          ))}
        </ol>
      )}
      <div className="adm-toolbar">
        <Switch label="Show archived fields" checked={showArchived} onCheckedChange={setShowArchived} />
      </div>
      {showArchived &&
        (archived.error ? (
          <LoadError what="archived fields" error={archived.error} retry={archived.reload} />
        ) : !archived.data ? (
          <Loading label="Loading archived fields" rows={2} height={40} />
        ) : archived.data.length === 0 ? (
          <p className="adm-muted">No archived fields.</p>
        ) : (
          <ul className="adm-field-list" aria-label="Archived fields">
            {archived.data.map((f) => (
              <li key={f.key} className="adm-field-row" data-archived>
                <span className="adm-field-main">
                  <strong>{f.label}</strong>
                  <code className="mono adm-muted">{f.key}</code>
                </span>
                <span className="adm-field-meta">
                  <Badge>{typeLabel(f.type)}</Badge>
                </span>
                {manage && (
                  <Button size="sm" onClick={() => void setFieldArchived(f, false)} disabled={busy} aria-label={`Restore ${f.label}`}>
                    <ArchiveRestore size={14} aria-hidden /> Restore
                  </Button>
                )}
              </li>
            ))}
          </ul>
        ))}
      {dialog && (
        <FieldDialog
          object={object}
          field={dialog.field}
          taken={taken}
          onClose={() => setDialog(null)}
          onSaved={(f, created) => {
            setDialog(null);
            fields.reload();
            toast({ title: created ? "Field added" : "Field saved", description: f.label, tone: "success" });
          }}
        />
      )}
      <ConfirmDialog
        open={!!archiving}
        onOpenChange={(o) => !o && setArchiving(null)}
        title={`Archive ${archiving?.label ?? "field"}?`}
        description="It disappears from records, lists, filters and the API. Its values are kept, and restoring it brings them back. Saved views and workflows that use it may stop working."
        confirm="Archive field"
        busy={busy}
        onConfirm={() => archiving && void setFieldArchived(archiving, true)}
      />
    </section>
  );
}

function Associations({ object, objects }: { object: ObjectDef; objects: ObjectDef[] }) {
  const toast = useToast();
  const { can } = useCan();
  const manage = can("objects.manage");
  const types = useLoad(() => listAssociationTypes(object.key), [object.key]);
  const [adding, setAdding] = useState(false);
  const [removing, setRemoving] = useState<AssociationType | null>(null);
  const [busy, setBusy] = useState(false);
  const label = (key: string) => objects.find((o) => o.key === key)?.plural ?? key;

  const remove = async () => {
    if (!removing) return;
    setBusy(true);
    try {
      await deleteAssociationType(removing.id);
      toast({ title: "Association type deleted", tone: "success" });
      setRemoving(null);
      types.reload();
    } catch (e) {
      toast({ title: "Could not delete it", description: whatWentWrong(e), tone: "danger", duration: 8000 });
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="adm-section" aria-labelledby="links-title">
      <div className="adm-section-head">
        <div>
          <h2 id="links-title" className="adm-h2">
            Associations
          </h2>
          <p className="adm-muted">How {object.plural.toLowerCase()} link to other records, with a label for each direction.</p>
        </div>
        {manage && (
          <Button onClick={() => setAdding(true)}>
            <Link2 size={16} aria-hidden /> Add association
          </Button>
        )}
      </div>
      {types.error && !types.data ? (
        <LoadError what="associations" error={types.error} retry={types.reload} />
      ) : !types.data ? (
        <Loading label="Loading associations" rows={2} height={44} />
      ) : types.data.length === 0 ? (
        <EmptyState icon={Link2} title="No associations" text={`Link ${object.plural.toLowerCase()} to contacts, deals or any other object: a property has owners, a policy belongs to a company.`} action={manage ? <Button onClick={() => setAdding(true)}>Add an association</Button> : undefined} />
      ) : (
        <ul className="adm-field-list">
          {types.data.map((t) => (
            <li key={t.id} className="adm-field-row">
              <span className="adm-field-main">
                <strong>
                  {label(t.from_object)} <span className="adm-muted">{t.label}</span> {label(t.to_object)}
                </strong>
                <span className="adm-muted">
                  {label(t.to_object)} {t.inverse_label} {label(t.from_object)}
                </span>
              </span>
              <span className="adm-field-meta">
                <Badge tone="info">{CARDINALITIES.find((c) => c.value === t.cardinality)?.label ?? t.cardinality}</Badge>
                {t.is_system && <Badge>Built in</Badge>}
              </span>
              {manage && !t.is_system && (
                <Button size="sm" variant="ghost" onClick={() => setRemoving(t)} aria-label={`Delete ${label(t.from_object)} ${t.label} ${label(t.to_object)}`}>
                  <Trash2 size={14} aria-hidden /> Delete
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
      {adding && <NewAssociationDialog object={object} objects={objects} onClose={() => setAdding(false)} onSaved={() => (setAdding(false), types.reload())} />}
      <ConfirmDialog
        open={!!removing}
        onOpenChange={(o) => !o && setRemoving(null)}
        title="Delete this association type?"
        description="Only a type without links can be deleted; remove its links from the records first."
        confirm="Delete"
        busy={busy}
        onConfirm={() => void remove()}
      />
    </section>
  );
}

function NewAssociationDialog({ object, objects, onClose, onSaved }: { object: ObjectDef; objects: ObjectDef[]; onClose: () => void; onSaved: () => void }) {
  const toast = useToast();
  const [other, setOther] = useState(objects.find((o) => o.key !== object.key)?.key ?? object.key);
  const [labelText, setLabel] = useState("");
  const [inverse, setInverse] = useState("");
  const [cardinality, setCardinality] = useState<AssociationType["cardinality"]>("many_to_many");
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const otherDef = objects.find((o) => o.key === other);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const found: Record<string, string> = {};
    if (!labelText.trim()) found.label = "How one reads to the other, like owns.";
    if (!inverse.trim()) found.inverse = "And back, like is owned by.";
    setErrors(found);
    if (Object.keys(found).length) return;
    setBusy(true);
    try {
      await createAssociationType({ from_object: object.key, to_object: other, label: labelText.trim(), inverse_label: inverse.trim(), cardinality });
      toast({ title: "Association added", tone: "success" });
      onSaved();
    } catch (err) {
      setErrors({ form: whatWentWrong(err) });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog
      open
      onOpenChange={(o) => !o && onClose()}
      title="Add an association"
      description="A kind of link between two objects. Each link reads both ways."
      footer={
        <>
          <Button onClick={onClose}>Cancel</Button>
          <Button variant="primary" type="submit" form="new-association" loading={busy}>
            Add association
          </Button>
        </>
      }
    >
      <form id="new-association" className="adm-form" onSubmit={submit} noValidate>
        <Select label={`${object.plural} link to`} value={other} onValueChange={setOther} options={objects.map((o) => ({ value: o.key, label: o.plural }))} />
        <Input label={`Label from a ${object.singular.toLowerCase()}`} placeholder="owns" value={labelText} maxLength={100} onChange={(e) => setLabel(e.target.value)} error={errors.label} hint={labelText.trim() ? `${object.singular} ${labelText.trim()} ${otherDef?.singular ?? ""}` : undefined} />
        <Input label={`Label from a ${otherDef?.singular.toLowerCase() ?? "record"}`} placeholder="is owned by" value={inverse} maxLength={100} onChange={(e) => setInverse(e.target.value)} error={errors.inverse} hint={inverse.trim() ? `${otherDef?.singular ?? ""} ${inverse.trim()} ${object.singular}` : undefined} />
        <Select label="How many" value={cardinality} onValueChange={(v) => setCardinality(v as AssociationType["cardinality"])} options={CARDINALITIES.map((c) => ({ value: c.value, label: c.label }))} />
        {errors.form && (
          <p className="ui-hint" data-tone="danger" role="alert">
            {errors.form}
          </p>
        )}
      </form>
    </Dialog>
  );
}
