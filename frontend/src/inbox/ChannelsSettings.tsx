import { ChevronLeft, Copy, LockKeyhole, Plug, Plus, Power, Settings2, TriangleAlert, Zap } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { ApiError } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { whatWentWrong } from "../lib/errors";
import { PageHeader } from "../shell/PageHeader";
import { Badge, Button, Dialog, EmptyState, Input, Select, Skeleton, useToast, type Tone } from "../ui";
import { createChannel, listChannels, patchChannel, testChannel } from "./api";
import { buildCreate, buildPatch, emptyValues, errorsByField, hasRules, missing, specOf, SPECS, valuesOf, type FieldSpec, type Spec, type Values } from "./channelSpecs.ts";
import { ChannelIcon } from "./ChannelIcon";
import type { Channel, ChannelStatus } from "./types.ts";
import { CHANNEL_LABEL } from "./views.ts";
import "./channels.css";

const STATUS: Record<ChannelStatus, { label: string; tone: Tone }> = {
  active: { label: "Connected", tone: "success" },
  pending: { label: "Not verified yet", tone: "info" },
  failing: { label: "Failing", tone: "danger" },
  disabled: { label: "Disabled", tone: "neutral" },
};

function Copyable({ label, value, multiline }: { label: string; value: string; multiline?: boolean }) {
  const toast = useToast();
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      toast({ title: "Copied", description: label, tone: "success", duration: 2500 });
    } catch {
      toast({ title: "Could not copy", description: "Select the text and copy it yourself.", tone: "danger" });
    }
  };
  return (
    <div className="chs-copy">
      <span className="chs-copy-label">{label}</span>
      <div className="chs-copy-row">
        {multiline ? <pre tabIndex={0}>{value}</pre> : <code tabIndex={0}>{value}</code>}
        <Button size="sm" variant="secondary" onClick={() => void copy()} aria-label={`Copy ${label.toLowerCase()}`}>
          <Copy size={14} aria-hidden /> Copy
        </Button>
      </div>
    </div>
  );
}

/** What to do next with a channel: paste a URL into the provider's console, or the snippet into the website. */
function Connection({ channel, spec }: { channel: Channel; spec: Spec }) {
  if (channel.kind === "webchat" && channel.embed) {
    return (
      <div className="chs-conn">
        <p>Paste this on every page of your website, just before the closing body tag. The widget loads when a visitor clicks the bubble.</p>
        <Copyable label="Embed snippet" value={channel.embed} multiline />
      </div>
    );
  }
  if (spec.hook && channel.webhook_url) {
    return (
      <div className="chs-conn">
        <p>
          Paste this address into the {specOf(channel).provider === "meta" ? "webhook settings of your WhatsApp app" : `${spec.title.split(" with ")[1] ?? "provider"} console`} so incoming messages and delivery reports reach the inbox. Calls that are not signed by the provider are refused.
        </p>
        <Copyable label="Webhook URL" value={channel.webhook_url} />
      </div>
    );
  }
  if (spec.provider === "smtp") return <p className="chs-note">Outgoing mail goes through your server. Delivery reports and replies arrive when a mailbox is connected (coming soon).</p>;
  return null;
}

function FieldInput({ f, value, error, onChange, saved }: { f: FieldSpec; value: string; error?: string; onChange: (v: string) => void; saved: boolean }) {
  const hint = f.where === "secret" && saved ? "Saved and hidden. Leave empty to keep it, or type a new one to replace it." : f.hint;
  if (f.type === "select") {
    return <Select label={f.label} value={value} onValueChange={onChange} options={f.options ?? []} />;
  }
  return (
    <Input
      label={f.label + (f.required && !(f.where === "secret" && saved) ? " *" : "")}
      type={f.type === "password" ? "password" : f.type === "number" ? "number" : f.type === "color" ? "color" : "text"}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      placeholder={f.where === "secret" && saved ? "Saved" : f.placeholder}
      hint={hint}
      error={error}
      autoComplete={f.type === "password" ? "new-password" : "off"}
      spellCheck={false}
      className={f.type === "color" ? "chs-color" : undefined}
    />
  );
}

/** One form for adding and editing: the provider's own fields, secrets that can only be written, and the sending rules. */
function ChannelForm({ spec, channel, onDone, onClose }: { spec: Spec; channel?: Channel; onDone: (c: Channel) => void; onClose: () => void }) {
  const editing = !!channel;
  const [v, setV] = useState<Values>(() => (channel ? valuesOf(spec, channel) : emptyValues(spec)));
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const set = (key: string, value: string) => setV((x) => ({ ...x, fields: { ...x.fields, [key]: value } }));
  const rule = (key: keyof Values["rules"], value: string) => setV((x) => ({ ...x, rules: { ...x.rules, [key]: value } }));

  const submit = async () => {
    const gaps = missing(spec, v, editing);
    if (gaps.length) {
      setErrors(Object.fromEntries(gaps.map((k) => [k, "Required"])));
      return setMessage("Fill in the fields marked as required.");
    }
    setBusy(true);
    setErrors({});
    setMessage(null);
    try {
      onDone(channel ? await patchChannel(channel.id, buildPatch(spec, v)) : await createChannel(buildCreate(spec, v)));
    } catch (e) {
      if (e instanceof ApiError && e.fields) {
        setErrors(errorsByField(spec, e.fields));
        setMessage("Some settings need another look.");
      } else setMessage(whatWentWrong(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form
      className="chs-form"
      onSubmit={(e) => {
        e.preventDefault();
        void submit();
      }}
    >
      {spec.fields.map((f) => (
        <FieldInput key={f.key} f={f} value={v.fields[f.key] ?? ""} error={errors[f.key]} onChange={(x) => set(f.key, x)} saved={editing && !!channel?.secrets_set} />
      ))}
      {hasRules(spec.kind) && (
        <fieldset className="chs-rules">
          <legend>Sending rules</legend>
          {spec.kind === "sms" && <Input label="Price of one segment" inputMode="decimal" placeholder="0.0079" value={v.rules.segment_cost} onChange={(e) => rule("segment_cost", e.target.value)} hint="Shown as a cost estimate under the message box." />}
          <div className="chs-pair">
            <Input label="Quiet hours start" type="time" value={v.rules.quiet_start} onChange={(e) => rule("quiet_start", e.target.value)} />
            <Input label="Quiet hours end" type="time" value={v.rules.quiet_end} onChange={(e) => rule("quiet_end", e.target.value)} />
          </div>
          <p className="chs-note">Outside these hours, in the contact's own time zone, new messages wait (a contact who just wrote can always be answered). Empty uses 21:00 to 08:00.</p>
          <div className="chs-pair">
            <Input label="Most messages to one contact" type="number" min={0} placeholder="10" value={v.rules.cap_max} onChange={(e) => rule("cap_max", e.target.value)} />
            <Input label="in this many hours" type="number" min={1} max={720} placeholder="24" value={v.rules.cap_hours} onChange={(e) => rule("cap_hours", e.target.value)} />
          </div>
        </fieldset>
      )}
      {spec.kind === "email" && <Input label="Reply-to address" type="email" placeholder="support@example.com" value={v.rules.reply_to} onChange={(e) => rule("reply_to", e.target.value)} hint="Where replies go, if not the From address." />}
      {message && (
        <p className="ui-hint" data-tone="danger" role="alert">
          {message}
        </p>
      )}
      <div className="chs-form-foot">
        <Button type="button" variant="ghost" onClick={onClose}>
          Cancel
        </Button>
        <Button type="submit" variant="primary" loading={busy}>
          {editing ? "Save changes" : "Add channel"}
        </Button>
      </div>
    </form>
  );
}

function Picker({ onPick }: { onPick: (s: Spec) => void }) {
  return (
    <ul className="chs-pick" aria-label="Channel types">
      {SPECS.map((s) => (
        <li key={s.id}>
          <button type="button" className="chs-pick-item" onClick={() => onPick(s)} data-spec={s.id}>
            <ChannelIcon kind={s.kind} size={20} />
            <span>
              <strong>{s.title}</strong>
              <span>{s.blurb}</span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Settings > Channels: the messaging accounts of the workspace, added, tested and switched off here. Needs channels.manage. */
export function ChannelsSettings() {
  const toast = useToast();
  const { can, ready } = useCan();
  const [channels, setChannels] = useState<Channel[] | null>(null);
  const [error, setError] = useState<string>();
  const [adding, setAdding] = useState<{ spec?: Spec } | null>(null);
  const [editing, setEditing] = useState<Channel | null>(null);
  const [testing, setTesting] = useState<string | null>(null);
  const [fresh, setFresh] = useState<string | null>(null);
  const allowed = can("channels.manage");

  const load = useCallback(() => {
    listChannels().then(
      (c) => (setChannels(c), setError(undefined)),
      (e) => setError(whatWentWrong(e)),
    );
  }, []);
  useEffect(() => {
    if (ready && !allowed) return;
    load();
  }, [load, ready, allowed]);

  const replace = (c: Channel) => setChannels((list) => (list ? (list.some((x) => x.id === c.id) ? list.map((x) => (x.id === c.id ? c : x)) : [...list, c]) : [c]));

  const test = async (c: Channel) => {
    setTesting(c.id);
    try {
      const r = await testChannel(c.id);
      toast({ title: r.ok ? "Connection works" : "The test failed", description: r.detail, tone: r.ok ? "success" : "danger", duration: 7000 });
      load();
    } catch (e) {
      toast({ title: "Could not run the test", description: whatWentWrong(e), tone: "danger" });
    } finally {
      setTesting(null);
    }
  };
  const toggle = async (c: Channel) => {
    try {
      replace(await patchChannel(c.id, { status: c.status === "disabled" ? "active" : "disabled" }));
    } catch (e) {
      toast({ title: "Could not change the channel", description: whatWentWrong(e), tone: "danger" });
    }
  };

  const header = (
    <>
      <Link to="/settings" className="sh-back">
        <ChevronLeft size={16} aria-hidden />
        Settings
      </Link>
      <PageHeader
        title="Channels"
        description="The accounts you send and receive messages on. Each one appears in the inbox."
        actions={
          allowed ? (
            <Button variant="primary" onClick={() => setAdding({})}>
              <Plus size={16} aria-hidden /> Add channel
            </Button>
          ) : undefined
        }
      />
    </>
  );

  if (ready && !allowed) {
    return (
      <div className="sh-page chs-page">
        {header}
        <EmptyState icon={LockKeyhole} title="Your role cannot manage channels" text="Ask a workspace admin. They can also give you the capability channels.manage." />
      </div>
    );
  }

  return (
    <div className="sh-page chs-page">
      {header}
      {error && !channels ? (
        <EmptyState icon={TriangleAlert} title="Could not load channels" text={error} action={<Button onClick={load}>Try again</Button>} />
      ) : !channels ? (
        <div className="chs-skeleton" aria-busy aria-label="Loading channels">
          <Skeleton style={{ height: 76 }} />
          <Skeleton style={{ height: 76 }} />
        </div>
      ) : channels.length === 0 ? (
        <EmptyState icon={Plug} title="No channels yet" text="Add an SMS number, an email address, WhatsApp or the web chat widget. Messages on it land in the inbox, in one conversation per contact." action={<Button variant="primary" onClick={() => setAdding({})}>Add your first channel</Button>} />
      ) : (
        <ul className="chs-list">
          {channels.map((c) => {
            const spec = specOf(c);
            const st = STATUS[c.status];
            return (
              <li key={c.id} className="chs-card" data-status={c.status} data-channel-id={c.id}>
                <div className="chs-card-main">
                  <span className="chs-icon" data-kind={c.kind}>
                    <ChannelIcon kind={c.kind} size={20} />
                  </span>
                  <div className="chs-card-titles">
                    <h2>{c.name}</h2>
                    <p>
                      {spec.title.replace(/^SMS with |^Email with /, "")} {"·"} {CHANNEL_LABEL[c.kind]}
                      {c.kind !== "webchat" && c.address ? ` · ${c.address}` : ""}
                    </p>
                  </div>
                  <Badge tone={st.tone}>{st.label}</Badge>
                </div>
                {c.status_detail && <p className="chs-detail">{c.status_detail}</p>}
                {c.status === "pending" && <p className="chs-detail" data-tone="info">Not proven to work yet. Run a test, or it turns on when the first message arrives or is accepted.</p>}
                <div className="chs-card-actions">
                  <Button size="sm" variant="secondary" onClick={() => void test(c)} loading={testing === c.id} disabled={c.status === "disabled"}>
                    <Zap size={14} aria-hidden /> Test connection
                  </Button>
                  <Button size="sm" variant="secondary" onClick={() => setEditing(c)}>
                    <Settings2 size={14} aria-hidden /> Settings
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => void toggle(c)}>
                    <Power size={14} aria-hidden /> {c.status === "disabled" ? "Switch on" : "Switch off"}
                  </Button>
                </div>
                {(fresh === c.id || c.kind === "webchat" || spec.hook) && c.status !== "disabled" && <Connection channel={c} spec={spec} />}
              </li>
            );
          })}
        </ul>
      )}

      <Dialog open={!!adding} onOpenChange={(o) => !o && setAdding(null)} title={adding?.spec ? adding.spec.title : "Add a channel"} description={adding?.spec ? adding.spec.blurb : "Pick what you want to connect."}>
        {adding && !adding.spec && <Picker onPick={(spec) => setAdding({ spec })} />}
        {adding?.spec && (
          <ChannelForm
            spec={adding.spec}
            onClose={() => setAdding(null)}
            onDone={(c) => {
              replace(c);
              setFresh(c.id);
              setAdding(null);
              toast({ title: "Channel added", description: c.webhook_url || c.embed ? "Next, connect it with the details on its card." : undefined, tone: "success" });
            }}
          />
        )}
      </Dialog>
      <Dialog open={!!editing} onOpenChange={(o) => !o && setEditing(null)} title={editing ? `${editing.name} settings` : ""} description="Secrets are saved encrypted and can only be replaced, never read back.">
        {editing && (
          <ChannelForm
            key={editing.id}
            spec={specOf(editing)}
            channel={editing}
            onClose={() => setEditing(null)}
            onDone={(c) => {
              replace(c);
              setEditing(null);
              toast({ title: "Channel saved", tone: "success" });
            }}
          />
        )}
      </Dialog>
    </div>
  );
}
