// One webhook endpoint: its delivery log (filters, payload, replay), its settings and its signing secret.
import { Eye, EyeOff, FilterX, Inbox, KeyRound, LoaderCircle, Power, RefreshCw, RotateCcw, Send, Trash2, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate, useSearchParams } from "react-router";
import { ApiError } from "../lib/api";
import { whatWentWrong } from "../lib/errors";
import { Badge, Button, EmptyState, Input, Select, Sheet, Tabs, TabsContent, TabsList, TabsTrigger, useToast, type Tone } from "../ui";
import { Combobox } from "../ui/Combobox";
import { deleteEndpoint, getDelivery, getEndpoint, listDeliveries, patchEndpoint, replayDelivery, revealSecret, rotateSecret, sendTest, webhookEventTypes, type Delivery, type DeliveryDetail, type DeliveryStatus, type Endpoint, type EndpointInput, type EventType } from "./api";
import { AdminHeader, ConfirmDialog, CopyText, JsonBlock, LoadError, Loading, useLoad, when } from "./common";
import { families, familyLabel, rangeError, readFilters, withDayBounds, type DeliveryFilters } from "./logic.ts";
import { EndpointForm, endpointStatus, SecretShown } from "./Webhooks";

const STATUS: Record<DeliveryStatus, { label: string; tone: Tone }> = {
  pending: { label: "Pending", tone: "info" },
  retrying: { label: "Retrying", tone: "warning" },
  succeeded: { label: "Delivered", tone: "success" },
  failed: { label: "Failed", tone: "danger" },
};
const TABS = ["deliveries", "settings", "secret"] as const;
type Tab = (typeof TABS)[number];
const FILTER_KEYS = ["status", "type", "from", "to"] as const;

export function WebhookDetail({ id }: { id: string }) {
  const toast = useToast();
  const navigate = useNavigate();
  const [params, setParams] = useSearchParams();
  const tab: Tab = (TABS as readonly string[]).includes(params.get("tab") ?? "") ? (params.get("tab") as Tab) : "deliveries";
  const endpoint = useLoad(() => getEndpoint(id), [id]);
  const types = useLoad(webhookEventTypes, []);
  const [testing, setTesting] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [busyDelete, setBusyDelete] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const back = { to: "/settings/api", label: "API and webhooks" };

  if (endpoint.error && !endpoint.data) {
    const missing = endpoint.error instanceof ApiError && endpoint.error.status === 404;
    return (
      <div className="sh-page adm-page">
        <AdminHeader title={missing ? "Webhook not found" : "Webhook"} back={back} />
        {missing ? <EmptyState icon={TriangleAlert} title="This webhook does not exist" text="It may have been deleted." /> : <LoadError what="the webhook" error={endpoint.error} retry={endpoint.reload} />}
      </div>
    );
  }
  if (!endpoint.data) {
    return (
      <div className="sh-page adm-page">
        <AdminHeader title="Webhook" back={back} />
        <Loading label="Loading the webhook" rows={3} height={64} />
      </div>
    );
  }
  const ep = endpoint.data;
  const st = endpointStatus(ep);

  const test = async () => {
    setTesting(true);
    try {
      await sendTest(ep.id);
      toast({ title: "Test event sent", description: "It shows in the deliveries below in a moment.", tone: "success" });
      setParams((p) => (p.delete("tab"), p), { replace: true });
      setTimeout(() => setRefresh((n) => n + 1), 1500);
    } catch (e) {
      toast({ title: "Could not send a test", description: whatWentWrong(e), tone: "danger" });
    } finally {
      setTesting(false);
    }
  };
  const toggle = async () => {
    try {
      endpoint.setData(await patchEndpoint(ep.id, { active: !ep.active }));
      toast({ title: ep.active ? "Webhook disabled" : "Webhook enabled", description: ep.active ? "Nothing is sent until you enable it again." : "New events are sent again.", tone: "success" });
    } catch (e) {
      toast({ title: "Could not change the webhook", description: whatWentWrong(e), tone: "danger" });
    }
  };
  const destroy = async () => {
    setBusyDelete(true);
    try {
      await deleteEndpoint(ep.id);
      toast({ title: "Webhook deleted", description: ep.url, tone: "success" });
      navigate("/settings/api");
    } catch (e) {
      toast({ title: "Could not delete the webhook", description: whatWentWrong(e), tone: "danger" });
      setBusyDelete(false);
      setDeleting(false);
    }
  };

  return (
    <Tabs value={tab} onValueChange={(v) => setParams(v === "deliveries" ? {} : { tab: v }, { replace: true })} activationMode="manual" className="sh-page adm-page">
      <AdminHeader
        title="Webhook"
        back={back}
        actions={
          <>
            <Button onClick={() => void test()} loading={testing} disabled={!ep.active} title={ep.active ? undefined : "Enable the webhook first"}>
              <Send size={16} aria-hidden /> Send test
            </Button>
            <Button onClick={() => void toggle()}>
              <Power size={16} aria-hidden /> {ep.active ? "Disable" : "Enable"}
            </Button>
            <Button variant="danger" onClick={() => setDeleting(true)}>
              <Trash2 size={16} aria-hidden /> Delete
            </Button>
          </>
        }
        views={
          <TabsList aria-label="Webhook">
            <TabsTrigger value="deliveries">Deliveries</TabsTrigger>
            <TabsTrigger value="settings">Settings</TabsTrigger>
            <TabsTrigger value="secret">Signing secret</TabsTrigger>
          </TabsList>
        }
      />
      <div className="adm-endpoint-head">
        <code className="mono adm-break">{ep.url}</code>
        <Badge tone={st.tone}>{st.label}</Badge>
      </div>
      {ep.disabled_reason && (
        <p className="adm-note" data-tone="warning">
          {ep.disabled_reason}. Fix the receiver, then enable the webhook and replay what failed.
        </p>
      )}
      {ep.active && ep.failing_since && (
        <p className="adm-note" data-tone="danger">
          Deliveries have failed since {when(ep.failing_since)}. After three days of only failures the webhook is disabled. The workspace admins are not emailed yet.
        </p>
      )}
      <TabsContent value="deliveries">
        <Deliveries endpoint={ep} types={types.data?.map((t) => t.type) ?? []} refresh={refresh} />
      </TabsContent>
      <TabsContent value="settings">
        <SettingsTab endpoint={ep} types={types} onSaved={(e) => endpoint.setData(e)} />
      </TabsContent>
      <TabsContent value="secret">
        <SecretTab endpoint={ep} />
      </TabsContent>
      <ConfirmDialog
        open={deleting}
        onOpenChange={setDeleting}
        title="Delete this webhook?"
        description="Nothing more is sent to it, deliveries still waiting are dropped, and its delivery log goes with it. This cannot be undone."
        confirm="Delete webhook"
        busy={busyDelete}
        onConfirm={() => void destroy()}
      />
    </Tabs>
  );
}

function SettingsTab({ endpoint, types, onSaved }: { endpoint: Endpoint; types: { data: EventType[] | null; error: unknown; reload: () => void }; onSaved: (e: Endpoint) => void }) {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const save = async (body: EndpointInput) => {
    setBusy(true);
    try {
      onSaved(await patchEndpoint(endpoint.id, body));
      toast({ title: "Webhook saved", tone: "success" });
    } finally {
      setBusy(false);
    }
  };
  if (types.error) return <LoadError what="the event types" error={types.error} retry={types.reload} />;
  if (!types.data) return <Loading label="Loading" rows={2} height={56} />;
  return (
    <div className="adm-narrow adm-stack">
      <EndpointForm key={`${endpoint.url}|${endpoint.event_types.join()}|${JSON.stringify(endpoint.filter)}`} id="webhook-settings" initial={endpoint} types={types.data} onSubmit={save} />
      <div>
        <Button variant="primary" type="submit" form="webhook-settings" loading={busy}>
          Save changes
        </Button>
      </div>
      <p className="adm-muted">A new URL starts a clean record: the failure streak is cleared. Changing the events applies to events from now on.</p>
    </div>
  );
}

function SecretTab({ endpoint }: { endpoint: Endpoint }) {
  const toast = useToast();
  const [secret, setSecret] = useState<string | null>(null);
  const [shown, setShown] = useState(false);
  const [busy, setBusy] = useState<"reveal" | "rotate" | null>(null);
  const [rotating, setRotating] = useState(false);
  const [fresh, setFresh] = useState(false);

  const reveal = async () => {
    if (secret) return setShown((s) => !s);
    setBusy("reveal");
    try {
      setSecret((await revealSecret(endpoint.id)).secret);
      setShown(true);
    } catch (e) {
      toast({ title: "Could not reveal the secret", description: whatWentWrong(e), tone: "danger", duration: 8000 });
    } finally {
      setBusy(null);
    }
  };
  const rotate = async () => {
    setBusy("rotate");
    try {
      const r = await rotateSecret(endpoint.id);
      setSecret(r.secret);
      setShown(true);
      setFresh(true);
      setRotating(false);
      toast({ title: "New secret made", description: "Deliveries are signed with it from now on. Update your server.", tone: "success" });
    } catch (e) {
      toast({ title: "Could not rotate the secret", description: whatWentWrong(e), tone: "danger", duration: 8000 });
    } finally {
      setBusy(null);
    }
  };

  return (
    <div className="adm-narrow adm-stack">
      <p className="adm-muted">Your server uses this secret to check that each delivery comes from go-high. Revealing it is recorded in the audit log.</p>
      {secret && shown && fresh ? (
        <SecretShown secret={secret} />
      ) : (
        <CopyText label="Signing secret" value={secret ?? "whsec_hidden_until_revealed"} masked={!secret || !shown} />
      )}
      <div className="adm-actions">
        <Button onClick={() => void reveal()} loading={busy === "reveal"}>
          {secret && shown ? <EyeOff size={16} aria-hidden /> : <Eye size={16} aria-hidden />} {secret && shown ? "Hide" : "Reveal"}
        </Button>
        <Button onClick={() => setRotating(true)}>
          <KeyRound size={16} aria-hidden /> Rotate secret
        </Button>
      </div>
      <ConfirmDialog
        open={rotating}
        onOpenChange={setRotating}
        tone="primary"
        title="Make a new signing secret?"
        description="The current secret stops working at once: deliveries from now on, retries included, are signed with the new one. Have your server ready to take the new secret."
        confirm="Rotate secret"
        busy={busy === "rotate"}
        onConfirm={() => void rotate()}
      />
    </div>
  );
}

function Deliveries({ endpoint, types, refresh }: { endpoint: Endpoint; types: string[]; refresh: number }) {
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const filters = useMemo(() => readFilters(params, FILTER_KEYS) as DeliveryFilters, [params]);
  const api = useMemo(() => withDayBounds(filters), [filters]);
  const badRange = rangeError(filters.from, filters.to);
  const [rows, setRows] = useState<Delivery[] | null>(null);
  const [cursor, setCursor] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [more, setMore] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const seq = useRef(0);
  const sentinel = useRef<HTMLDivElement>(null);
  const set = (k: keyof DeliveryFilters, v: string | null) =>
    setParams(
      (p) => {
        if (v) p.set(k, v);
        else p.delete(k);
        return p;
      },
      { replace: true },
    );

  const first = useCallback(() => {
    const mine = ++seq.current;
    setError(null);
    if (badRange) return (setRows([]), setCursor(null));
    listDeliveries(endpoint.id, api).then(
      (page) => mine === seq.current && (setRows(page.data), setCursor(page.next_cursor)),
      (e) => mine === seq.current && setError(e),
    );
  }, [endpoint.id, api, badRange]);
  useEffect(() => {
    setRows(null);
    first();
  }, [first]);
  useEffect(() => {
    if (refresh) first();
  }, [refresh]);

  const loadMore = useCallback(() => {
    if (!cursor || more) return;
    const mine = seq.current;
    setMore(true);
    listDeliveries(endpoint.id, api, cursor).then(
      (page) => {
        if (mine !== seq.current) return;
        setRows((r) => [...(r ?? []), ...page.data]);
        setCursor(page.next_cursor);
        setMore(false);
      },
      (e) => {
        if (mine !== seq.current) return;
        setMore(false);
        toast({ title: "Could not load more deliveries", description: whatWentWrong(e), tone: "danger" });
      },
    );
  }, [endpoint.id, api, cursor, more, toast]);
  useEffect(() => {
    const el = sentinel.current;
    if (!el || !cursor) return;
    const io = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && loadMore(), { rootMargin: "300px" });
    io.observe(el);
    return () => io.disconnect();
  }, [cursor, loadMore]);

  const typeItems = useMemo(
    () => families(types).flatMap((f) => [{ value: `${f.family}.*`, label: `${f.family}.*`, hint: "every type", group: familyLabel(f.family) }, ...f.types.map((t) => ({ value: t, label: t, group: familyLabel(f.family) }))]),
    [types],
  );
  const any = FILTER_KEYS.some((k) => filters[k]);
  const clear = () =>
    setParams(
      (p) => {
        for (const k of FILTER_KEYS) p.delete(k);
        return p;
      },
      { replace: true },
    );

  return (
    <div className="adm-stack">
      <div className="adm-filters adm-filters-4" role="group" aria-label="Filter deliveries">
        <Select
          label="Status"
          value={filters.status ?? "any"}
          onValueChange={(v) => set("status", v === "any" ? null : v)}
          options={[{ value: "any", label: "Any status" }, ...Object.entries(STATUS).map(([value, s]) => ({ value, label: s.label }))]}
        />
        <div className="ui-field">
          <span className="ui-label">Event type</span>
          <Combobox label="Event type" placeholder="Any type" items={typeItems} value={filters.type ?? null} onChange={(v) => set("type", v)} onClear={() => set("type", null)} clearLabel="Any type" />
        </div>
        <Input label="From" type="date" value={filters.from ?? ""} max={filters.to} onChange={(e) => set("from", e.target.value || null)} />
        <Input label="To" type="date" value={filters.to ?? ""} min={filters.from} onChange={(e) => set("to", e.target.value || null)} error={badRange} />
        <div className="adm-filter-actions">
          {any && (
            <Button variant="ghost" onClick={clear}>
              <FilterX size={16} aria-hidden /> Clear filters
            </Button>
          )}
          <Button variant="ghost" onClick={first} aria-label="Refresh deliveries">
            <RefreshCw size={16} aria-hidden /> Refresh
          </Button>
        </div>
      </div>
      {error ? (
        <LoadError what="deliveries" error={error} retry={first} />
      ) : !rows ? (
        <Loading label="Loading deliveries" rows={4} height={44} />
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Inbox}
          title={any ? "No deliveries match" : "No deliveries yet"}
          text={any ? "Try another status, type or date range." : "A delivery is made for each event this webhook subscribes to, from when it was added. Send a test to see one now."}
          action={any ? <Button onClick={clear}>Clear filters</Button> : undefined}
        />
      ) : (
        <>
          <div className="adm-matrix-wrap">
            <table className="adm-matrix adm-deliveries">
              <caption className="sr-only">Deliveries, newest first</caption>
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">Event</th>
                  <th scope="col">Status</th>
                  <th scope="col">Response</th>
                  <th scope="col">Attempts</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((d) => (
                  <tr key={d.id} data-status={d.status}>
                    <td>
                      <button type="button" className="adm-linkbtn" onClick={() => setOpen(d.id)} aria-haspopup="dialog" aria-label={`Delivery of ${d.event_type ?? "an event"} at ${when(d.created_at, true)}, ${STATUS[d.status].label}. Open it`}>
                        {when(d.created_at, true)}
                      </button>
                    </td>
                    <td>
                      <code className="mono">{d.event_type ?? "deleted event"}</code>
                      {d.replay_of && <Badge>Replay</Badge>}
                    </td>
                    <td>
                      <Badge tone={STATUS[d.status].tone}>{STATUS[d.status].label}</Badge>
                    </td>
                    <td className="mono">{d.response_status ? `${d.response_status}${d.response_ms !== null ? ` · ${d.response_ms} ms` : ""}` : d.error ? <span className="adm-error-text">{d.error.slice(0, 40)}</span> : "-"}</td>
                    <td className="mono">{d.attempts}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div ref={sentinel} className="adm-more">
            {cursor ? (
              <Button onClick={loadMore} loading={more}>
                {more ? "Loading more" : "Load more"}
              </Button>
            ) : (
              <p className="adm-muted">{rows.length === 1 ? "That is the only delivery." : `That is all: ${rows.length} deliveries.`}</p>
            )}
            {more && <LoaderCircle className="ui-spin sr-only" aria-label="Loading more deliveries" />}
          </div>
        </>
      )}
      <DeliverySheet id={open} endpoint={endpoint} onClose={() => setOpen(null)} onReplayed={(d) => (setRows((r) => [d, ...(r ?? [])]), setOpen(null))} />
    </div>
  );
}

function DeliverySheet({ id, endpoint, onClose, onReplayed }: { id: string | null; endpoint: Endpoint; onClose: () => void; onReplayed: (d: Delivery) => void }) {
  const toast = useToast();
  const detail = useLoad<DeliveryDetail | null>(() => (id ? getDelivery(id) : Promise.resolve(null)), [id], !!id);
  const [busy, setBusy] = useState(false);
  const d = detail.data && detail.data.id === id ? detail.data : null;

  const replay = async () => {
    if (!d) return;
    setBusy(true);
    try {
      const next = await replayDelivery(d.id);
      toast({ title: "Replay queued", description: "The same event goes out again now, with the same GoHigh-Event-Id.", tone: "success" });
      onReplayed(next);
    } catch (e) {
      toast({ title: "Could not replay", description: whatWentWrong(e), tone: "danger" });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet open={!!id} onOpenChange={(o) => !o && onClose()} title={d?.event_type ?? "Delivery"} description={d ? `${STATUS[d.status].label} · ${when(d.created_at, true)}` : undefined}>
      {detail.error ? (
        <LoadError what="the delivery" error={detail.error} retry={detail.reload} />
      ) : !d ? (
        <Loading label="Loading the delivery" rows={3} height={48} />
      ) : (
        <div className="adm-stack">
          <div className="adm-actions">
            <Button onClick={() => void replay()} loading={busy} disabled={!endpoint.active || !d.payload} title={endpoint.active ? undefined : "Enable the webhook first"}>
              <RotateCcw size={16} aria-hidden /> Replay
            </Button>
            {!endpoint.active && <span className="adm-muted">Enable the webhook to replay.</span>}
          </div>
          <dl className="adm-dl">
            <dt>Status</dt>
            <dd>
              <Badge tone={STATUS[d.status].tone}>{STATUS[d.status].label}</Badge>
              {d.next_attempt_at && <span className="adm-muted"> next try {when(d.next_attempt_at, true)}</span>}
            </dd>
            <dt>Attempts</dt>
            <dd>{d.attempts} of 12</dd>
            <dt>Response</dt>
            <dd className="mono">{d.response_status ? `HTTP ${d.response_status}${d.response_ms !== null ? ` in ${d.response_ms} ms` : ""}` : "None"}</dd>
            {d.error && (
              <>
                <dt>Error</dt>
                <dd className="adm-error-text">{d.error}</dd>
              </>
            )}
            <dt>Delivery id</dt>
            <dd className="mono adm-break">{d.id}</dd>
            {d.replay_of && (
              <>
                <dt>Replay of</dt>
                <dd className="mono adm-break">{d.replay_of}</dd>
              </>
            )}
          </dl>
          {d.response_body_excerpt && (
            <div>
              <h3 className="adm-h3">Response body (first 2 KB)</h3>
              <pre className="adm-json mono" tabIndex={0} aria-label="Response body">
                {d.response_body_excerpt}
              </pre>
            </div>
          )}
          <div>
            <h3 className="adm-h3">Payload</h3>
            {d.payload ? <JsonBlock label="Payload" value={d.payload} /> : <p className="adm-muted">The event no longer exists.</p>}
          </div>
          {d.request_headers && (
            <div>
              <h3 className="adm-h3">Headers</h3>
              <JsonBlock label="Request headers" value={d.request_headers} />
            </div>
          )}
        </div>
      )}
    </Sheet>
  );
}
