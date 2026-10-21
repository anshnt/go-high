// The side panel: the settings of the trigger or of the selected step, with the server's errors under the setting they
// are about. Changes apply to the draft at once; Save makes them a version.
import { ArrowDown, ArrowUp, CircleAlert, Plus, Trash2 } from "lucide-react";
import { useMemo } from "react";
import { FilterBuilder } from "../records/FilterBuilder";
import { filterFields } from "../records/filter.ts";
import { useMeta } from "../records/meta.tsx";
import type { Filter } from "../records/types.ts";
import { Button, Input, Kbd, Select } from "../ui";
import type { ComboItem } from "../ui/Combobox";
import type { ActionSpec, Catalog, JsonSchema } from "./api";
import { iconOf } from "./Canvas";
import { ChoiceCombo, ConfigForm, errorFor, OffsetInput, useLookups } from "./ConfigForm";
import { ACTION_HELP, title, TYPE_HELP, TYPE_LABEL, type Names } from "./describe";
import { errorText } from "./schema";
import { eventGroup, eventHelp, eventLabel, objectsFor, type Scalar, type Trigger, type WfNode } from "./graph";

type Errors = Record<string, string>;
const LOOKUP_OF: Record<string, string> = { form_id: "forms", calendar_id: "calendars", to_stage_id: "stages", from_stage_id: "stages", channel_id: "channels" };
const MOD = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.userAgent) ? "⌥" : "Alt";

function Problems({ errors, known }: { errors: Errors; known: (key: string) => boolean }) {
  const loose = Object.entries(errors).filter(([k]) => !known(k));
  if (!loose.length) return null;
  return (
    <div className="wf-alert" role="alert">
      <CircleAlert size={16} aria-hidden />
      <ul>
        {loose.map(([k, m]) => (
          <li key={k}>{errorText(k, m)}</li>
        ))}
      </ul>
    </div>
  );
}

/** The data an event must hold, or an event wait must match: a key of the event and a value, picked where we know what
 * the value names (a form, a calendar, a stage). */
function DataRows({ label, schema, value, onChange, error, hint }: { label: string; schema: JsonSchema | undefined; value: Record<string, Scalar>; onChange: (v: Record<string, Scalar>) => void; error?: string; hint: string }) {
  const meta = useMeta();
  const lookups = useLookups();
  const properties = schema?.properties ?? {};
  const keys = Object.entries(properties)
    .filter(([k, s]) => !["id", "contact_id", "record_id", "object", "display_name"].includes(k) && s.type !== "array" && s.type !== "object" && !(Array.isArray(s.type) && s.type.includes("array")))
    .map(([k]) => k);
  const pickers: Record<string, ComboItem[] | null> = {
    form_id: lookups.forms && lookups.forms.map((f) => ({ value: f.id, label: f.name, hint: f.hint })),
    calendar_id: lookups.calendars && lookups.calendars.map((c) => ({ value: c.id, label: c.name })),
    to_stage_id: lookups.stages && lookups.stages.map((s) => ({ value: s.id, label: s.name, group: s.hint })),
    from_stage_id: lookups.stages && lookups.stages.map((s) => ({ value: s.id, label: s.name, group: s.hint })),
    channel_id: lookups.channels && lookups.channels.map((c) => ({ value: c.id, label: c.name, hint: c.hint })),
    tag_id: meta.tags.map((t) => ({ value: t.id, label: t.name })),
    host_user_id: meta.users.map((u) => ({ value: u.id, label: u.name })),
  };
  const set = (k: string, v: Scalar | undefined) => {
    const next = { ...value };
    if (v === undefined || v === "") delete next[k];
    else next[k] = v;
    onChange(next);
  };
  const free = keys.filter((k) => !(k in value));
  return (
    <fieldset className="wf-rows">
      <legend className="ui-label">{label}</legend>
      <p className="ui-hint">{hint}</p>
      {Object.entries(value).map(([k, v]) => {
        const s = properties[k];
        const items = pickers[k];
        const words = k.replace(/_id$/, "").replace(/_/g, " ");
        const name = words.charAt(0).toUpperCase() + words.slice(1);
        return (
          <div key={k} className="wf-row">
            {k in pickers ? (
              <ChoiceCombo label={name} items={items ?? []} loading={!items} failed={!!LOOKUP_OF[k] && lookups.failed.has(LOOKUP_OF[k])} onRetry={lookups.retry} what={`the ${name.toLowerCase()}s`} value={v === null ? null : String(v)} onChange={(x) => set(k, x ?? undefined)} />
            ) : s?.enum ? (
              <Select label={name} value={String(v ?? "")} onValueChange={(x) => set(k, x)} options={s.enum.filter((x) => x !== null).map((x) => ({ value: String(x), label: String(x).replace(/_/g, " ") }))} />
            ) : s?.type === "boolean" ? (
              <Select label={name} value={String(v)} onValueChange={(x) => set(k, x === "true")} options={[{ value: "true", label: "Yes" }, { value: "false", label: "No" }]} />
            ) : (
              <Input label={name} value={v === null ? "" : String(v)} onChange={(e) => set(k, s?.type === "integer" || s?.type === "number" ? Number(e.target.value) : e.target.value)} />
            )}
            <Button variant="ghost" size="icon" aria-label={`Stop matching on ${name}`} onClick={() => set(k, undefined)}>
              <Trash2 size={16} aria-hidden />
            </Button>
          </div>
        );
      })}
      {free.length > 0 && (
        <Select aria-label={`Add to: ${label}`} value="" placeholder="Add a detail to match" onValueChange={(k) => onChange({ ...value, [k]: properties[k]?.type === "boolean" ? true : "" })} options={free.map((k) => ({ value: k, label: k.replace(/_id$/, "").replace(/_/g, " ") }))} />
      )}
      {error && (
        <p className="ui-hint" data-tone="danger">
          {error}
        </p>
      )}
    </fieldset>
  );
}

function FilterField({ object, value, onChange, error, revision, label, help }: { object: string; value: unknown; onChange: (f: Record<string, unknown>) => void; error?: string; revision: string; label: string; help: string }) {
  const meta = useMeta();
  const refs = useMemo(() => filterFields(object, meta.objects, meta.fields, meta.links), [object, meta]);
  const noun = meta.objects.find((o) => o.key === object)?.plural ?? "records";
  const ast = value && typeof value === "object" && Object.keys(value).length ? (value as Filter) : null;
  return (
    <fieldset className="wf-filter">
      <legend className="ui-label">{label}</legend>
      <p className="ui-hint">{help}</p>
      <FilterBuilder key={revision} value={ast} refs={refs} noun={noun} onChange={(f) => onChange((f ?? {}) as Record<string, unknown>)} />
      {error && (
        <p className="ui-hint" data-tone="danger">
          {error}
        </p>
      )}
    </fieldset>
  );
}

export function TriggerPanel({ trigger, catalog, onChange, errors, revision, disabled }: { trigger: Trigger; catalog: Catalog; onChange: (t: Trigger) => void; errors: Errors; revision: string; disabled: boolean }) {
  const meta = useMeta();
  const spec = catalog.triggers.find((t) => t.event === trigger.event);
  const items = catalog.triggers.map((t) => ({ value: t.event, label: eventLabel(t.event), group: eventGroup(t.event) })).sort((a, b) => a.group.localeCompare(b.group));
  const objects = spec ? objectsFor(spec.record, spec.event, meta.objects.map((o) => o.key)) : ["contact"];
  const object = trigger.object ?? "contact";
  const known = (k: string) => k === "" || ["event", "object", "data", "filter"].some((x) => k === x || k.startsWith(`${x}.`));
  return (
    <fieldset className="wf-panel-body" disabled={disabled}>
      <Problems errors={errors} known={known} />
      <ChoiceCombo
        label="Starts when"
        items={items}
        value={trigger.event}
        error={errorFor(errors, "event")}
        hint={eventHelp(spec?.description)}
        onChange={(event) => {
          if (!event || event === trigger.event) return;
          const s = catalog.triggers.find((t) => t.event === event)!;
          const allowed = objectsFor(s.record, event, meta.objects.map((o) => o.key));
          const nextObject = allowed.includes(object) ? object : allowed[0]!;
          onChange({ event, object: nextObject, filter: nextObject === object ? trigger.filter : {}, data: {} });
        }}
      />
      {objects.length > 1 ? (
        <Select
          label="For which records"
          value={object}
          onValueChange={(o) => onChange({ ...trigger, object: o, filter: {} })}
          options={objects.map((o) => ({ value: o, label: meta.objects.find((x) => x.key === o)?.plural ?? o }))}
        />
      ) : (
        <p className="wf-muted">Runs on {meta.objects.find((o) => o.key === object)?.plural.toLowerCase() ?? object}.</p>
      )}
      {errorFor(errors, "object") && (
        <p className="ui-hint" data-tone="danger">
          {errorFor(errors, "object")}
        </p>
      )}
      <DataRows
        key={`${trigger.event}-${revision}`}
        label="Only when the event says"
        hint="Narrow it to one form, calendar or stage. Leave empty for any."
        schema={spec?.data_schema}
        value={trigger.data ?? {}}
        error={errorFor(errors, "data")}
        onChange={(data) => onChange({ ...trigger, data })}
      />
      <FilterField
        object={object}
        value={trigger.filter}
        revision={`${object}-${revision}`}
        label="And the record matches"
        help="Judged when the event is read. Leave empty for every record."
        error={errorFor(errors, "filter")}
        onChange={(filter) => onChange({ ...trigger, filter })}
      />
    </fieldset>
  );
}

type NodeProps = {
  id: string;
  node: WfNode;
  catalog: Catalog;
  object: string;
  names: Names;
  errors: Errors;
  revision: string;
  disabled: boolean;
  onChange: (patch: Partial<WfNode>) => void;
  onRemove: () => void;
  onMove: (dir: "up" | "down") => void;
  canMove: { up: boolean; down: boolean };
};

export function NodePanel(p: NodeProps) {
  const { node, catalog, errors } = p;
  const cfgErrors = Object.fromEntries(Object.entries(errors).filter(([k]) => k.startsWith("config.")).map(([k, v]) => [k.slice(7), v]));
  const action: ActionSpec | undefined = node.type === "action" ? catalog.actions.find((a) => a.key === node.action) : undefined;
  const nodeSpec = catalog.nodes.find((n) => n.type === node.type);
  const Icon = iconOf(node);
  const set = (config: Record<string, unknown>) => p.onChange({ config });
  const known = (k: string) => k === "label" || (k.startsWith("config.") && configKnown(node, k.slice(7)));
  return (
    <div className="wf-panel-node">
      <header className="wf-panel-head">
        <span className="wf-node-icon" aria-hidden>
          <Icon size={16} />
        </span>
        <div>
          <h2>{title(node, p.names)}</h2>
          <p className="wf-muted">
            {node.type === "action" ? (ACTION_HELP[node.action ?? ""] || action?.description || "") : (TYPE_HELP[node.type] ?? nodeSpec?.description ?? TYPE_LABEL[node.type])}
            {action?.outbound && " It leaves the system once per run, never twice, and a test run only shows what it would send."}
          </p>
        </div>
      </header>
      <fieldset className="wf-panel-body" disabled={p.disabled}>
        <Problems errors={errors} known={known} />
        <Input label="Name on the canvas (optional)" value={node.label ?? ""} maxLength={100} placeholder={title({ ...node, label: undefined }, p.names)} error={errors.label} onChange={(e) => p.onChange({ label: e.target.value })} />
        {node.type === "action" && action && node.action === "owner.assign" ? (
          <OwnerEditor config={node.config} onChange={set} errors={cfgErrors} schema={action.config_schema} object={p.object} />
        ) : node.type === "action" && action ? (
          <ConfigForm key={`${p.id}-${p.revision}`} schema={action.config_schema} value={node.config} onChange={set} errors={cfgErrors} object={p.object} />
        ) : node.type === "action" ? (
          <p className="wf-alert">This action is not in the catalog any more: remove the step or pick another action.</p>
        ) : null}
        {node.type === "wait" && <WaitEditor key={`${p.id}-${p.revision}`} config={node.config} onChange={set} errors={cfgErrors} object={p.object} catalog={catalog} />}
        {node.type === "condition" && (
          <FilterField object={p.object} value={node.config.filter} revision={`${p.id}-${p.revision}`} label="If the record matches" help="Records that match go down Yes, the rest down No." error={errorFor(cfgErrors, "filter")} onChange={(filter) => set({ ...node.config, filter })} />
        )}
        {node.type === "goal" && (
          <>
            <FilterField object={p.object} value={node.config.filter} revision={`${p.id}-${p.revision}`} label="The goal is met when" help="Checked on every change to the record: a run jumps here from wherever it is." error={errorFor(cfgErrors, "filter")} onChange={(filter) => set({ ...node.config, filter })} />
            <Select
              label="A run that reaches it by walking, before it is met"
              value={String(node.config.otherwise ?? "continue")}
              onValueChange={(otherwise) => set({ ...node.config, otherwise })}
              options={[
                { value: "continue", label: "Goes on from the goal" },
                { value: "end", label: "Ends" },
              ]}
            />
          </>
        )}
        {node.type === "split" && <SplitEditor key={`${p.id}-${p.revision}`} config={node.config} onChange={set} error={errorFor(cfgErrors, "paths")} />}
        {node.type === "subflow" && <p className="wf-alert">Sub-workflows are not built yet: this step can be saved, but the workflow cannot be published with it.</p>}
        {node.type === "end" && <p className="wf-muted">The run ends here. Steps after it are not possible.</p>}
      </fieldset>
      {!p.disabled && (
        <footer className="wf-panel-foot">
          <span className="mono wf-muted" title="The step's id: the API, the trace and the diff use it">
            {p.id}
          </span>
          <div className="wf-panel-actions">
            <Button variant="ghost" size="icon" aria-label="Move the step up" aria-keyshortcuts="Alt+ArrowUp" title={`Move up (${MOD}+Up)`} disabled={!p.canMove.up} onClick={() => p.onMove("up")}>
              <ArrowUp size={16} aria-hidden />
            </Button>
            <Button variant="ghost" size="icon" aria-label="Move the step down" aria-keyshortcuts="Alt+ArrowDown" title={`Move down (${MOD}+Down)`} disabled={!p.canMove.down} onClick={() => p.onMove("down")}>
              <ArrowDown size={16} aria-hidden />
            </Button>
            <Button variant="ghost" onClick={p.onRemove} aria-keyshortcuts="Delete">
              <Trash2 size={16} aria-hidden /> Remove <Kbd>Del</Kbd>
            </Button>
          </div>
        </footer>
      )}
    </div>
  );
}

function configKnown(node: WfNode, key: string): boolean {
  const top = key.split(".")[0]!;
  if (node.type === "wait") return ["duration", "until_field", "event"].includes(top);
  if (node.type === "condition" || node.type === "goal") return top === "filter" || top === "otherwise";
  if (node.type === "split") return top === "paths";
  return node.type === "action" && top !== "";
}

function OwnerEditor({ config, onChange, errors, schema, object }: { config: Record<string, unknown>; onChange: (c: Record<string, unknown>) => void; errors: Errors; schema: JsonSchema; object: string }) {
  const rr = Array.isArray(config.round_robin);
  return (
    <>
      <fieldset className="wf-radios">
        <legend className="ui-label">Who becomes the owner</legend>
        <label>
          <input type="radio" name="wf-owner" checked={!rr} onChange={() => onChange({ user_id: config.user_id ?? null })} /> One person
        </label>
        <label>
          <input type="radio" name="wf-owner" checked={rr} onChange={() => onChange({ round_robin: config.user_id ? [config.user_id] : [] })} /> Each of a list of people in turn
        </label>
      </fieldset>
      <ConfigForm schema={schema} value={config} onChange={(c) => onChange(rr ? { round_robin: c.round_robin ?? [] } : { user_id: c.user_id ?? null })} errors={errors} object={object} skip={[rr ? "user_id" : "round_robin"]} need={[rr ? "round_robin" : "user_id"]} />
    </>
  );
}

type WaitMode = "duration" | "until_field" | "event";
function WaitEditor({ config, onChange, errors, object, catalog }: { config: Record<string, unknown>; onChange: (c: Record<string, unknown>) => void; errors: Errors; object: string; catalog: Catalog }) {
  const meta = useMeta();
  const mode: WaitMode = config.until_field ? "until_field" : config.event ? "event" : "duration";
  const until = (config.until_field ?? {}) as { field?: string; offset?: unknown; at?: string };
  const ev = (config.event ?? {}) as { event?: string; match?: Record<string, Scalar>; timeout?: unknown };
  const dateFields = (meta.fields[object] ?? []).filter((f) => !f.archived && (f.type === "date" || f.type === "datetime"));
  const switchTo = (m: WaitMode) =>
    onChange(m === "duration" ? { duration: { days: 1 } } : m === "until_field" ? { until_field: { field: dateFields[0]?.key ?? "", at: "09:00" } } : { event: { event: catalog.triggers[0]?.event ?? "", match: {}, timeout: { days: 3 } } });
  return (
    <>
      <fieldset className="wf-radios">
        <legend className="ui-label">Wait</legend>
        {(
          [
            ["duration", "For a length of time"],
            ["until_field", "Until a date on the record"],
            ["event", "Until something happens, with a time limit"],
          ] as const
        ).map(([m, text]) => (
          <label key={m}>
            <input type="radio" name="wf-wait" checked={mode === m} onChange={() => switchTo(m)} /> {text}
          </label>
        ))}
      </fieldset>
      {mode === "duration" && <OffsetInput key="d" label="How long" value={config.duration} required onChange={(duration) => onChange({ duration })} error={errorFor(errors, "duration")} hint="A test run skips it on its virtual clock and says how long it skipped." />}
      {mode === "until_field" && (
        <>
          <ChoiceCombo
            label="Date field"
            items={dateFields.map((f) => ({ value: f.key, label: f.label, hint: f.type }))}
            value={until.field || null}
            onChange={(field) => onChange({ until_field: { ...until, field } })}
            error={errorFor(errors, "until_field.field")}
            hint={dateFields.length ? undefined : "This object has no date fields yet: add one in Settings, Custom fields."}
          />
          <OffsetInput key="o" label="Offset" signed value={until.offset} onChange={(offset) => onChange({ until_field: { ...until, offset } })} error={errorFor(errors, "until_field.offset")} hint="For example 1 day before a renewal date." />
          <Input label="At (for a date without a time)" type="time" value={until.at ?? "09:00"} onChange={(e) => onChange({ until_field: { ...until, at: e.target.value || "09:00" } })} error={errorFor(errors, "until_field.at")} hint="In the contact's time zone field, else UTC." />
        </>
      )}
      {mode === "event" && (
        <>
          <ChoiceCombo
            label="Until"
            items={catalog.triggers.map((t) => ({ value: t.event, label: eventLabel(t.event), group: eventGroup(t.event) })).sort((a, b) => a.group.localeCompare(b.group))}
            value={ev.event || null}
            onChange={(event) => onChange({ event: { ...ev, event, match: {} } })}
            error={errorFor(errors, "event.event")}
            hint="When it happens the run goes down When it happens; at the time limit, down If it times out."
          />
          <DataRows key={ev.event} label="Only when the event says" hint="Leave empty for any." schema={catalog.triggers.find((t) => t.event === ev.event)?.data_schema} value={ev.match ?? {}} onChange={(match) => onChange({ event: { ...ev, match } })} error={errorFor(errors, "event.match")} />
          <OffsetInput key="t" label="Time limit" required value={ev.timeout} onChange={(timeout) => onChange({ event: { ...ev, timeout } })} error={errorFor(errors, "event.timeout")} />
        </>
      )}
      {errors[""] && (
        <p className="ui-hint" data-tone="danger">
          {errors[""]}
        </p>
      )}
    </>
  );
}

function SplitEditor({ config, onChange, error }: { config: Record<string, unknown>; onChange: (c: Record<string, unknown>) => void; error?: string }) {
  const paths = (Array.isArray(config.paths) ? config.paths : []) as { name: string; percent: number }[];
  const total = paths.reduce((s, p) => s + (Number(p.percent) || 0), 0);
  const nameError = (name: string, i: number) =>
    !name ? "Give the path a name" : !/^[a-z]/.test(name) ? "Start with a letter" : paths.some((p, j) => j !== i && p.name === name) ? "Another path has this name" : undefined;
  const set = (next: { name: string; percent: number }[]) => onChange({ ...config, paths: next });
  const fresh = () => {
    for (let c = 97; c < 123; c++) if (!paths.some((p) => p.name === String.fromCharCode(c))) return String.fromCharCode(c);
    return `path_${paths.length + 1}`;
  };
  return (
    <fieldset className="wf-rows">
      <legend className="ui-label">Paths</legend>
      <p className="ui-hint">Each run takes one path, picked by its id, so a run always takes the same one. Names are lower case letters, digits and _.</p>
      {paths.map((p, i) => (
        <div key={i} className="wf-row wf-row-top">
          <Input aria-label={`Name of path ${i + 1}`} value={p.name} maxLength={40} error={nameError(p.name, i)} onChange={(e) => set(paths.map((x, j) => (j === i ? { ...x, name: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "") } : x)))} />
          <Input aria-label={`Percent of path ${i + 1}`} inputMode="numeric" value={String(p.percent)} onChange={(e) => set(paths.map((x, j) => (j === i ? { ...x, percent: Number(e.target.value.replace(/[^0-9]/g, "").slice(0, 3)) || 0 } : x)))} />
          <span className="wf-muted" aria-hidden>
            %
          </span>
          <Button variant="ghost" size="icon" aria-label={`Remove path ${p.name}`} disabled={paths.length <= 2} onClick={() => set(paths.filter((_, j) => j !== i))}>
            <Trash2 size={16} aria-hidden />
          </Button>
        </div>
      ))}
      <div className="wf-split-foot">
        <Button variant="ghost" size="sm" disabled={paths.length >= 10} onClick={() => set([...paths, { name: fresh(), percent: 0 }])}>
          <Plus size={14} aria-hidden /> Add a path
        </Button>
        <span className={total === 100 ? "wf-muted" : "wf-failed"} aria-live="polite">
          {total}% of 100%
        </span>
      </div>
      {error && (
        <p className="ui-hint" data-tone="danger">
          {error}
        </p>
      )}
    </fieldset>
  );
}
