// Team and roles > Access check: what a member can see and do, and for one record whether they see it and why. It asks
// GET /api/v1/permissions/explain, which runs the same functions enforcement runs, so it cannot disagree with the API.
import { CircleCheck, CircleX, Eye, LockKeyhole, ScanSearch, TriangleAlert } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router";
import { Badge, Button, EmptyState, Input, Select } from "../ui";
import { Combobox } from "../ui/Combobox";
import { explain, getCatalog, getRecord, listMembers, listObjects, searchRecords, type Explanation, type RecordHit } from "./api";
import { Denied, isDenied, LoadError, Loading, personName, useLoad, useGate } from "./common";
import { ACTIONS, groupCatalog, isUuid, scopeLabel } from "./logic.ts";

export function Simulator() {
  const gate = useGate("members.manage");
  if (gate === "wait") return <Loading label="Loading" rows={2} height={64} />;
  if (gate === "no") return <Denied what="check what other people can see" capability="members.manage" />;
  return <Check />;
}

function Check() {
  const [params, setParams] = useSearchParams();
  const user = params.get("user");
  const object = params.get("object") ?? "contact";
  const record = params.get("record");
  const set = (next: Record<string, string | null>) => {
    const p = new URLSearchParams(params);
    for (const [k, v] of Object.entries(next)) (v ? p.set(k, v) : p.delete(k));
    setParams(p, { replace: true });
  };

  const members = useLoad(listMembers, []);
  const objects = useLoad(() => listObjects(), []);
  const catalog = useLoad(getCatalog, []);
  const result = useLoad(() => explain(user!, record && isUuid(record) ? record : null), [user, record], !!user);

  if (members.error && !members.data) return <LoadError what="members" error={members.error} retry={members.reload} />;
  if (!members.data) return <Loading label="Loading" rows={2} height={64} />;

  const person = members.data.find((m) => m.user_id === user);
  return (
    <div className="adm-stack">
      <p className="adm-muted">Pick a member to see their role, teams and what they may do with each kind of record. Add a record to see whether they can open it, and why.</p>
      <div className="adm-sim-form">
        <div className="ui-field">
          <span className="ui-label" id="sim-user">
            Member
          </span>
          <Combobox label="Member" placeholder="Pick a member" items={members.data.map((m) => ({ value: m.user_id, label: personName(m), hint: m.role.name }))} value={user} onChange={(v) => set({ user: v })} valueLabel={person ? personName(person) : undefined} />
        </div>
        <RecordPick objects={objects.data?.map((o) => ({ value: o.key, label: o.plural })) ?? []} object={object} record={record} onChange={set} />
      </div>
      {!user ? (
        <EmptyState icon={ScanSearch} title="Who do you want to check?" text="Pick a member above. Nothing changes for them: this only reads." />
      ) : result.error ? (
        isDenied(result.error) ? <Denied what="check what other people can see" capability="members.manage" /> : <LoadError what="the answer" error={result.error} retry={result.reload} />
      ) : !result.data || result.loading ? (
        <Loading label="Working it out" rows={3} height={72} />
      ) : (
        <Answer data={result.data} objectLabels={new Map((objects.data ?? []).map((o) => [o.key, o.plural]))} catalog={catalog.data?.capabilities ?? []} />
      )}
    </div>
  );
}

function RecordPick({ objects, object, record, onChange }: { objects: { value: string; label: string }[]; object: string; record: string | null; onChange: (n: Record<string, string | null>) => void }) {
  const [hits, setHits] = useState<RecordHit[]>([]);
  const [loading, setLoading] = useState(false);
  const [paste, setPaste] = useState("");
  const [label, setLabel] = useState<string | undefined>();
  const seq = useRef(0);
  const search = (q: string) => {
    const mine = ++seq.current;
    setLoading(true);
    searchRecords(object, q).then(
      (r) => mine === seq.current && (setHits(r), setLoading(false)),
      () => mine === seq.current && (setHits([]), setLoading(false)),
    );
  };
  useEffect(() => {
    setHits([]);
  }, [object]);
  useEffect(() => {
    if (!record || !isUuid(record)) return setLabel(undefined);
    const hit = hits.find((h) => h.id === record);
    if (hit) return setLabel(hit.display_name);
    getRecord(object, record).then(
      (r) => setLabel(r.display_name),
      () => setLabel(undefined), // out of the asker's own scope, or another object: the id still works
    );
    // only when the record changes
  }, [record]);
  const pasted = paste.trim();
  return (
    <>
      <Select label="Record of" value={object} onValueChange={(v) => onChange({ object: v, record: null })} options={objects.length ? objects : [{ value: object, label: object }]} />
      <div className="ui-field">
        <span className="ui-label">Record (optional)</span>
        <Combobox
          label="Record"
          placeholder="Search for a record"
          searchPlaceholder="Type a name, email or phone"
          items={hits.map((h) => ({ value: h.id, label: h.display_name }))}
          onSearch={search}
          loading={loading}
          emptyText={loading ? "Searching..." : "No records you can see match"}
          value={record}
          valueLabel={label ?? record ?? undefined}
          onChange={(v) => onChange({ record: v })}
          onClear={() => onChange({ record: null })}
          clearLabel="No record"
        />
      </div>
      <form
        className="adm-sim-paste"
        onSubmit={(e) => {
          e.preventDefault();
          if (isUuid(pasted)) {
            onChange({ record: pasted.toLowerCase() });
            setPaste("");
          }
        }}
      >
        <Input label="Or paste a record id" value={paste} onChange={(e) => setPaste(e.target.value)} placeholder="00000000-0000-0000-0000-000000000000" className="mono" error={pasted && !isUuid(pasted) ? "That is not a record id." : undefined} spellCheck={false} />
        <Button type="submit" disabled={!isUuid(pasted)}>
          Check
        </Button>
      </form>
    </>
  );
}

const yes = (on: boolean, label: string) => (
  <span className="adm-yesno" data-on={on || undefined}>
    {on ? <CircleCheck size={15} aria-hidden /> : <CircleX size={15} aria-hidden />}
    <span className="sr-only">{on ? `${label}: yes` : `${label}: no`}</span>
  </span>
);

function Answer({ data, objectLabels, catalog }: { data: Explanation; objectLabels: Map<string, string>; catalog: { module: string; capability: string; description: string }[] }) {
  const held = new Set(data.capabilities);
  const modules = useMemo(() => groupCatalog(catalog.filter((c) => held.has(c.capability))), [catalog, data]);
  const who = personName(data.user);
  const rec = data.record;
  const order = [...objectLabels.keys()];
  const rank = (k: string) => (order.includes(k) ? order.indexOf(k) : order.length);
  return (
    <div className="adm-stack" aria-live="polite">
      {rec && (
        <div className="adm-verdict" data-visible={rec.visible || undefined} role="status">
          {rec.visible ? <Eye size={20} aria-hidden /> : <LockKeyhole size={20} aria-hidden />}
          <div>
            <strong>
              {who} {rec.visible ? "can see" : "cannot see"} this {rec.object}
              {rec.in_trash ? " (it is in the trash)" : ""}
            </strong>
            <p>{rec.reason.charAt(0).toUpperCase() + rec.reason.slice(1)}.</p>
            {!rec.visible && <p className="adm-muted">For them it does not exist: it is a 404 in lists, search, links and the timeline.</p>}
          </div>
        </div>
      )}
      <div className="adm-sim-summary">
        <div>
          <span className="adm-label">Role</span>
          <strong>{data.role?.name ?? "No role"}</strong>
          {data.role?.source === "organization" && <Badge tone="accent">From the organization</Badge>}
        </div>
        <div>
          <span className="adm-label">Teams</span>
          {data.teams.length ? (
            <span className="adm-chips">
              {data.teams.map((t) => (
                <Badge key={t.id} tone={t.direct ? "neutral" : "info"}>
                  {t.name}
                  {t.direct ? "" : " (below theirs)"}
                </Badge>
              ))}
            </span>
          ) : (
            <span className="adm-muted">None</span>
          )}
        </div>
      </div>
      <div className="adm-matrix-wrap">
        <table className="adm-matrix adm-sim-table">
          <caption className="sr-only">What {who} may do with each kind of record</caption>
          <thead>
            <tr>
              <th scope="col">Object</th>
              <th scope="col">Records they see</th>
              {ACTIONS.map((a) => (
                <th scope="col" key={a.key}>
                  {a.label}
                </th>
              ))}
              <th scope="col">Hidden fields</th>
              <th scope="col">Read-only fields</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(data.objects)
              .sort(([a], [b]) => rank(a) - rank(b))
              .map(([key, a]) => (
              <tr key={key} data-highlight={rec?.object === key || undefined}>
                <th scope="row">{objectLabels.get(key) ?? key}</th>
                <td>
                  {scopeLabel(a.scope)}
                  {a.scope !== a.rule_scope && <span className="adm-muted"> (rule: {scopeLabel(a.rule_scope).toLowerCase()}, but no read capability)</span>}
                </td>
                {ACTIONS.map((x) => (
                  <td key={x.key}>{yes(a.can[x.key], x.label)}</td>
                ))}
                <td className="adm-wrap">{a.hidden_fields.length ? a.hidden_fields.join(", ") : <span className="adm-muted">None</span>}</td>
                <td className="adm-wrap">{a.readonly_fields.length ? a.readonly_fields.join(", ") : <span className="adm-muted">None</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <section aria-labelledby="sim-caps">
        <h3 id="sim-caps" className="adm-h3">
          Capabilities ({data.capabilities.length})
        </h3>
        {data.capabilities.length === 0 ? (
          <p className="adm-note" data-tone="warning">
            <TriangleAlert size={14} aria-hidden /> This role holds no capabilities: it can sign in but do nothing here.
          </p>
        ) : (
          <dl className="adm-caps">
            {modules.map((g) => (
              <div key={g.module}>
                <dt>{g.module}</dt>
                <dd>
                  {g.items.map((i) => (
                    <span key={i.capability} title={i.description} className="adm-cap-chip mono">
                      {i.capability}
                    </span>
                  ))}
                </dd>
              </div>
            ))}
          </dl>
        )}
      </section>
      <p className="adm-muted">This is what the API enforces right now. A change to their role or teams applies from their next request.</p>
    </div>
  );
}
