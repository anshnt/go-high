// Settings > API and webhooks: the workspace's webhook endpoints. Each one opens on its own page (/settings/api/:id)
// with its settings, signing secret and delivery log.
import { ChevronRight, Plus, Webhook } from "lucide-react";
import { useState, type FormEvent } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError } from "../lib/api";
import { whatWentWrong } from "../lib/errors";
import { Badge, Button, Dialog, EmptyState, Input, Textarea, useToast, type Tone } from "../ui";
import { createEndpoint, listEndpoints, patchEndpoint, webhookEventTypes, type Endpoint, type EndpointInput, type EventType } from "./api";
import { AdminHeader, CopyText, Denied, isDenied, LoadError, Loading, useLoad, when, useGate } from "./common";
import { EventPicker } from "./EventPicker";
import { subscriptionText } from "./logic.ts";
import { WebhookDetail } from "./WebhookDetail";
import "./admin.css";

export function endpointStatus(e: Endpoint): { label: string; tone: Tone } {
  if (!e.active) return { label: "Disabled", tone: "neutral" };
  if (e.failing_since) return { label: "Failing", tone: "danger" };
  return { label: "Active", tone: "success" };
}

export function WebhooksPage() {
  const { id } = useParams();
  const gate = useGate("webhooks.manage");
  if (gate === "wait")
    return (
      <div className="sh-page adm-page">
        <AdminHeader title="API and webhooks" />
        <Loading label="Loading" rows={2} height={72} />
      </div>
    );
  if (gate === "no")
    return (
      <div className="sh-page adm-page">
        <AdminHeader title="API and webhooks" />
        <Denied what="manage webhooks" capability="webhooks.manage" />
      </div>
    );
  return id ? <WebhookDetail id={id} /> : <WebhookList />;
}

const VERIFY = `import hashlib, hmac, time

def verify(secret, signature_header, body: bytes, tolerance=300):
    parts = dict(p.split("=", 1) for p in signature_header.split(","))
    expected = hmac.new(secret.encode(), parts["t"].encode() + b"." + body, hashlib.sha256).hexdigest()
    return abs(time.time() - int(parts["t"])) <= tolerance and hmac.compare_digest(parts["v1"], expected)`;

/** Shown once a secret is new (created or rotated): how to check the signature with it. */
export function SecretShown({ secret }: { secret: string }) {
  return (
    <div className="adm-stack">
      <CopyText label="Signing secret" value={secret} />
      <p className="adm-muted">
        Every delivery carries <code className="mono">GoHigh-Signature: t=&lt;unix&gt;,v1=&lt;hex&gt;</code>, an HMAC-SHA256 of <code className="mono">t.body</code> with this secret. Check it on the raw body before parsing, and refuse timestamps older than five minutes:
      </p>
      <pre className="adm-json mono" tabIndex={0} aria-label="Signature check in Python">
        {VERIFY}
      </pre>
    </div>
  );
}

/** The URL, events and filter of an endpoint; used to create one and to edit it. */
export function EndpointForm({ id, initial, types, onSubmit }: { id: string; initial?: Endpoint; types: EventType[]; onSubmit: (body: EndpointInput) => Promise<void> }) {
  const [url, setUrl] = useState(initial?.url ?? "https://");
  const [events, setEvents] = useState<string[]>(initial?.event_types ?? ["*"]);
  const [filter, setFilter] = useState(initial && Object.keys(initial.filter).length ? JSON.stringify(initial.filter, null, 2) : "");
  const [errors, setErrors] = useState<Record<string, string>>({});

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const found: Record<string, string> = {};
    const u = url.trim();
    if (!/^https?:\/\/[^\s/]+/.test(u)) found.url = "Enter the full address, starting with https://.";
    if (events.length === 0) found.events = "Pick at least one event, or send every event.";
    let parsed: Record<string, unknown> = {};
    if (filter.trim()) {
      try {
        const v = JSON.parse(filter);
        if (!v || typeof v !== "object" || Array.isArray(v)) found.filter = 'The filter must be a JSON object, like {"object": "contact"}.';
        else parsed = v;
      } catch {
        found.filter = "This is not valid JSON.";
      }
    }
    setErrors(found);
    if (Object.keys(found).length) return;
    try {
      await onSubmit({ url: u, event_types: events, filter: parsed });
    } catch (err) {
      if (err instanceof ApiError && err.code === "email_unverified") return setErrors({ form: `${err.message}. Sign out and back in with "Email me a link" to confirm it.` });
      const f = err instanceof ApiError ? err.fields : undefined;
      if (f) {
        const out: Record<string, string> = {};
        for (const [k, v] of Object.entries(f)) out[k.startsWith("event_types") ? "events" : k] = v.charAt(0).toUpperCase() + v.slice(1) + ".";
        setErrors(out);
      } else setErrors({ form: whatWentWrong(err) });
    }
  };

  return (
    <form id={id} className="adm-form" onSubmit={submit} noValidate>
      <Input label="Endpoint URL" type="url" value={url} onChange={(e) => setUrl(e.target.value)} error={errors.url} hint="Must be https and reachable on the public internet. Redirects are not followed." spellCheck={false} autoFocus={!initial} />
      <EventPicker types={types} value={events} onChange={setEvents} error={errors.events} />
      <Textarea
        label="Filter (optional)"
        className="mono"
        rows={3}
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        error={errors.filter}
        hint={'Only events whose data contains this JSON are sent. For example {"object": "deal"} sends only events about deals.'}
        spellCheck={false}
      />
      {errors.form && (
        <p className="ui-hint" data-tone="danger" role="alert">
          {errors.form}
        </p>
      )}
    </form>
  );
}

function WebhookList() {
  const toast = useToast();
  const navigate = useNavigate();
  const endpoints = useLoad(listEndpoints, []);
  const types = useLoad(webhookEventTypes, []);
  const [adding, setAdding] = useState(false);
  const [busy, setBusy] = useState(false);
  const [created, setCreated] = useState<(Endpoint & { secret: string }) | null>(null);

  const create = async (body: EndpointInput) => {
    setBusy(true);
    try {
      const ep = await createEndpoint(body);
      setAdding(false);
      setCreated(ep);
      endpoints.reload();
      toast({ title: "Webhook added", tone: "success" });
    } finally {
      setBusy(false);
    }
  };
  const toggle = async (e: Endpoint) => {
    try {
      const next = await patchEndpoint(e.id, { active: !e.active });
      endpoints.setData((list) => list?.map((x) => (x.id === e.id ? next : x)) ?? null);
      toast({ title: next.active ? "Webhook enabled" : "Webhook disabled", description: next.url, tone: "success" });
    } catch (err) {
      toast({ title: "Could not change the webhook", description: whatWentWrong(err), tone: "danger" });
    }
  };

  const header = (
    <AdminHeader
      title="API and webhooks"
      description="Webhooks send a signed POST to your server when something happens in this workspace. API keys are coming; until then the API works with a signed-in session."
      actions={
        endpoints.data?.length ? (
          <Button variant="primary" onClick={() => setAdding(true)}>
            <Plus size={16} aria-hidden /> Add webhook
          </Button>
        ) : undefined
      }
    />
  );

  return (
    <div className="sh-page adm-page">
      {header}
      {endpoints.error && !endpoints.data ? (
        isDenied(endpoints.error) ? <Denied what="manage webhooks" capability="webhooks.manage" /> : <LoadError what="webhooks" error={endpoints.error} retry={endpoints.reload} />
      ) : !endpoints.data ? (
        <Loading label="Loading webhooks" rows={2} height={72} />
      ) : endpoints.data.length === 0 ? (
        <EmptyState
          icon={Webhook}
          title="No webhooks yet"
          text="Add the address of your server and pick the events it should get: a new contact, a deal that moves, a form response. Each delivery is signed, retried for about a day and logged."
          action={
            <Button variant="primary" onClick={() => setAdding(true)}>
              Add your first webhook
            </Button>
          }
        />
      ) : (
        <ul className="adm-cards">
          {endpoints.data.map((e) => {
            const st = endpointStatus(e);
            return (
              <li key={e.id} className="adm-card" data-status={st.label.toLowerCase()}>
                <div className="adm-card-main">
                  <Link to={`/settings/api/${e.id}`} className="adm-card-title mono" aria-label={`${e.url}, ${st.label}. Open its settings and deliveries`}>
                    {e.url}
                  </Link>
                  <Badge tone={st.tone}>{st.label}</Badge>
                </div>
                <p className="adm-muted">
                  {subscriptionText(e.event_types)}
                  {Object.keys(e.filter).length ? " · filtered" : ""} · added {when(e.created_at)}
                </p>
                {(e.disabled_reason || e.failing_since) && (
                  <p className="adm-note" data-tone={e.active ? "danger" : "warning"}>
                    {e.disabled_reason ?? `Deliveries have failed since ${when(e.failing_since!)}. After three days of only failures it is disabled.`}
                  </p>
                )}
                <div className="adm-actions">
                  <Button size="sm" onClick={() => navigate(`/settings/api/${e.id}`)}>
                    Deliveries and settings <ChevronRight size={14} aria-hidden />
                  </Button>
                  <Button size="sm" variant="ghost" onClick={() => void toggle(e)}>
                    {e.active ? "Disable" : "Enable"}
                  </Button>
                </div>
              </li>
            );
          })}
        </ul>
      )}

      <Dialog
        open={adding}
        onOpenChange={setAdding}
        title="Add a webhook"
        description="Deliveries start with the next event; nothing from before is sent."
        footer={
          <>
            <Button onClick={() => setAdding(false)}>Cancel</Button>
            <Button variant="primary" type="submit" form="new-webhook" loading={busy} disabled={!types.data}>
              Add webhook
            </Button>
          </>
        }
      >
        {types.error ? <LoadError what="the event types" error={types.error} retry={types.reload} /> : !types.data ? <Loading label="Loading event types" rows={2} height={40} /> : <EndpointForm id="new-webhook" types={types.data} onSubmit={create} />}
      </Dialog>
      <Dialog
        open={!!created}
        onOpenChange={(o) => !o && setCreated(null)}
        title="Save the signing secret"
        description="Your server needs it to check that a delivery comes from go-high. You can reveal it again later on the webhook's page."
        footer={
          <>
            <Button onClick={() => setCreated(null)}>Done</Button>
            {created && (
              <Button variant="primary" onClick={() => (navigate(`/settings/api/${created.id}`), setCreated(null))}>
                Open the webhook
              </Button>
            )}
          </>
        }
      >
        {created && <SecretShown secret={created.secret} />}
      </Dialog>
    </div>
  );
}
