// One campaign: while it is a draft, who it is from, who it goes to (with the exact count), the content in the block
// builder, an optional A/B test and the review with the deliverability check and the send or schedule; afterwards,
// its progress, controls (pause, resume, cancel) and report.
import { ChevronLeft, CircleAlert, Copy, Pause, Play, Send, Square, Undo2 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { ApiError, errorText } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { whatWentWrong } from "../lib/errors";
import { Badge, Button, Dialog, EmptyState, Input, Select, Skeleton, Switch, useToast } from "../ui";
import { Segmented } from "../ui/Segmented";
import { email, type AB, type Campaign, type Channel, type Check, type Doc, type Domain, type Preview, type Template, type Topic, type View } from "./api";
import { byLevel, issuesByBlock, scheduleBody, STATUS_LABEL, STATUS_TONE, withIds } from "./blocks";
import { Builder } from "./Builder";
import { IssueList } from "./Issues";
import { Report } from "./Report";
import "./email.css";

type Draft = Pick<Campaign, "name" | "from_name" | "from_email" | "reply_to" | "channel_id" | "topic_id" | "subject" | "preheader" | "audience" | "ab"> & { document: Doc };

const draftOf = (c: Campaign): Draft => ({
  name: c.name,
  from_name: c.from_name,
  from_email: c.from_email,
  reply_to: c.reply_to,
  channel_id: c.channel_id,
  topic_id: c.topic_id,
  subject: c.subject,
  preheader: c.preheader,
  audience: c.audience ?? {},
  ab: c.ab,
  document: withIds(c.document),
});

const zones = (() => {
  try {
    return Intl.supportedValuesOf("timeZone");
  } catch {
    return ["UTC"];
  }
})();
const here = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";

export function CampaignPage() {
  const { id = "" } = useParams();
  const [campaign, setCampaign] = useState<Campaign | null>(null);
  const [error, setError] = useState<string>();
  const load = useCallback(() => {
    email
      .campaign(id)
      .then((c) => (setCampaign(c), setError(undefined)))
      .catch((e) => setError(e instanceof ApiError && e.status === 404 ? "This campaign does not exist." : errorText(e)));
  }, [id]);
  useEffect(load, [load]);
  useEffect(() => {
    if (!campaign || !["sending", "testing", "scheduled"].includes(campaign.status)) return;
    const t = setInterval(load, 10000); // progress while it sends
    return () => clearInterval(t);
  }, [campaign, load]);

  if (error)
    return (
      <div className="sh-page em-page">
        <EmptyState icon={CircleAlert} title="We could not open this campaign" text={error} action={<Link to="/email">Back to campaigns</Link>} />
      </div>
    );
  if (!campaign)
    return (
      <div className="sh-page em-page" aria-busy>
        <Skeleton className="em-skel-title" />
        <Skeleton className="em-skel-block" />
      </div>
    );
  return campaign.status === "draft" ? <DraftEditor campaign={campaign} onSaved={setCampaign} /> : <Sent campaign={campaign} onChange={setCampaign} />;
}

function Header({ campaign, saving, actions }: { campaign: Campaign; saving?: string; actions?: React.ReactNode }) {
  useEffect(() => {
    document.title = `${campaign.name} | Email | go-high`;
  }, [campaign.name]);
  return (
    <header className="em-head">
      <Link to="/email" className="em-back">
        <ChevronLeft size={16} aria-hidden />
        Campaigns
      </Link>
      <div className="em-head-row">
        <div className="em-head-title">
          <h1>{campaign.name}</h1>
          <Badge tone={STATUS_TONE[campaign.status]}>{STATUS_LABEL[campaign.status]}</Badge>
          {saving && (
            <span className="em-muted" role="status" aria-live="polite">
              {saving}
            </span>
          )}
        </div>
        <div className="em-row">{actions}</div>
      </div>
    </header>
  );
}

function DraftEditor({ campaign, onSaved }: { campaign: Campaign; onSaved: (c: Campaign) => void }) {
  const navigate = useNavigate();
  const toast = useToast();
  const { can } = useCan();
  const readOnly = !can("marketing.write");
  const [draft, setDraft] = useState<Draft>(() => draftOf(campaign));
  const saved = useRef(JSON.stringify(draftOf(campaign)));
  const [saving, setSaving] = useState<string>();
  const [fields, setFields] = useState<Record<string, string>>({});
  const [domains, setDomains] = useState<Domain[]>([]);
  const [channels, setChannels] = useState<Channel[]>([]);
  const [topics, setTopics] = useState<Topic[]>([]);
  const [views, setViews] = useState<View[]>([]);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [check, setCheck] = useState<Check | null>(null);
  const [checking, setChecking] = useState(false);

  useEffect(() => {
    void Promise.all([
      email.domains().then(setDomains),
      email.channels().then(setChannels),
      email.topics().then(setTopics),
      email.views().then(setViews),
      email.templates({}).then((p) => setTemplates(p.data)),
    ]).catch(() => {});
  }, []);

  const set = <K extends keyof Draft>(key: K, value: Draft[K]) => setDraft((d) => ({ ...d, [key]: value }));
  const dirty = JSON.stringify(draft) !== saved.current;

  // Saves a moment after the last change; a refusal stays on screen next to what it is about.
  useEffect(() => {
    if (!dirty || readOnly) return;
    setSaving("Saving...");
    const t = setTimeout(async () => {
      const body = { ...draft, reply_to: draft.reply_to || null };
      try {
        const c = await email.patchCampaign(campaign.id, body);
        saved.current = JSON.stringify(draft);
        setFields({});
        setSaving("Saved");
        setCheck(null);
        onSaved({ ...c });
      } catch (e) {
        setFields(e instanceof ApiError && e.fields ? e.fields : {});
        setSaving(`Not saved: ${whatWentWrong(e)}`);
      }
    }, 700);
    return () => clearTimeout(t);
  }, [draft, dirty, readOnly, campaign.id, onSaved]);

  const audienceKey = JSON.stringify([draft.audience, draft.topic_id, saving === "Saved"]);
  useEffect(() => {
    if (dirty) return;
    email.audience(campaign.id).then(setPreview).catch(() => setPreview(null));
  }, [audienceKey, campaign.id, dirty]);

  const runCheck = useCallback(async () => {
    setChecking(true);
    try {
      setCheck(await email.check(campaign.id));
    } catch (e) {
      toast({ title: "The check did not run", description: errorText(e), tone: "danger" });
    } finally {
      setChecking(false);
    }
  }, [campaign.id, toast]);

  const [local, domainName] = useMemo(() => {
    const [l = "", d = ""] = draft.from_email.split("@");
    return [l, d];
  }, [draft.from_email]);
  const blockIssues = issuesByBlock(draft.document, fields);

  return (
    <div className="sh-page em-page em-campaign">
      <Header campaign={campaign} saving={saving} />
      <div className="em-steps">
        <section className="em-card" aria-labelledby="from-h">
          <h2 id="from-h" className="em-h2">
            From
          </h2>
          <div className="em-grid">
            <Input label="Campaign name (only you see it)" value={draft.name} maxLength={200} disabled={readOnly} error={fields.name} onChange={(e) => set("name", e.target.value)} />
            <Input label="Sender name" value={draft.from_name} maxLength={200} disabled={readOnly} error={fields.from_name} onChange={(e) => set("from_name", e.target.value)} />
            <div className="em-address">
              <Input label="From address" value={local} disabled={readOnly || !domains.length} error={fields.from_email} onChange={(e) => set("from_email", `${e.target.value.replace(/@.*/, "")}@${domainName}`)} />
              <span className="em-at" aria-hidden>
                @
              </span>
              <Select
                label="Sending domain"
                value={domainName || undefined}
                placeholder="Choose a domain"
                disabled={readOnly || !domains.length}
                options={domains.map((d) => ({ value: d.domain, label: `${d.domain}${d.status === "verified" ? "" : " (not verified)"}` }))}
                onValueChange={(v) => set("from_email", `${local || "hello"}@${v}`)}
              />
            </div>
            <Input label="Reply-to (optional)" type="email" value={draft.reply_to ?? ""} disabled={readOnly} error={fields.reply_to} onChange={(e) => set("reply_to", e.target.value)} hint="Where replies go, if not to the From address." />
            <Select
              label="Send through"
              value={draft.channel_id ?? undefined}
              placeholder="Choose an email channel"
              disabled={readOnly}
              options={channels.map((c) => ({ value: c.id, label: `${c.name} (${c.address})` }))}
              onValueChange={(v) => set("channel_id", v)}
            />
            <Select
              label="Topic"
              value={draft.topic_id ?? "none"}
              disabled={readOnly}
              options={[{ value: "none", label: "No topic" }, ...topics.map((t) => ({ value: t.id, label: t.name }))]}
              onValueChange={(v) => set("topic_id", v === "none" ? null : v)}
            />
          </div>
          {!domains.length && (
            <p className="em-note">
              No sending domain yet. <Link to="/email/domains">Set one up</Link> first: mail from your own verified domain is what reaches the inbox.
            </p>
          )}
          {!channels.length && (
            <p className="em-note">
              No email channel yet. <Link to="/settings/channels">Connect Mailgun, SES or SMTP</Link> under Channels.
            </p>
          )}
          <p className="ui-hint">With a topic, the unsubscribe link leaves that topic only; without one, it stops all marketing email.</p>
        </section>

        <section className="em-card" aria-labelledby="to-h">
          <h2 id="to-h" className="em-h2">
            To
          </h2>
          <Segmented
            label="Audience"
            value={draft.audience.view_id ? "view" : draft.audience.all ? "all" : "view"}
            onChange={(v) => set("audience", v === "all" ? { all: true } : { view_id: views[0]?.id })}
            options={[
              { value: "view", label: "A saved view" },
              { value: "all", label: "Every contact" },
            ]}
          />
          {!draft.audience.all && (
            <Select
              label="Saved view of contacts"
              value={draft.audience.view_id}
              placeholder={views.length ? "Choose a view" : "No saved views yet"}
              disabled={readOnly || !views.length}
              options={views.map((v) => ({ value: v.id, label: `${v.name}${v.count !== undefined ? ` (${v.count.toLocaleString()})` : ""}` }))}
              onValueChange={(v) => set("audience", { view_id: v })}
            />
          )}
          {fields["audience.view_id"] && <p className="em-field-error">{fields["audience.view_id"]}</p>}
          <AudiencePreview preview={preview} />
        </section>

        <section className="em-card em-card-wide" aria-labelledby="content-h">
          <div className="em-card-head">
            <h2 id="content-h" className="em-h2">
              Content
            </h2>
            {!readOnly && templates.length > 0 && (
              <Select
                aria-label="Replace the content with a template"
                placeholder="Use a template"
                options={templates.map((t) => ({ value: t.id, label: t.name }))}
                onValueChange={async (v) => {
                  try {
                    const c = await email.patchCampaign(campaign.id, { template_id: v } as never);
                    const next = draftOf(c);
                    saved.current = JSON.stringify(next);
                    setDraft(next);
                    onSaved(c);
                    toast({ title: "Template applied", tone: "success" });
                  } catch (e) {
                    toast({ title: "Could not apply it", description: errorText(e), tone: "danger" });
                  }
                }}
              />
            )}
          </div>
          <div className="em-grid">
            <Input label="Subject" value={draft.subject} maxLength={500} disabled={readOnly} error={fields.subject} onChange={(e) => set("subject", e.target.value)} hint={`${draft.subject.length} characters; inboxes show about 78.`} />
            <Input label="Preview text" value={draft.preheader} maxLength={300} disabled={readOnly} error={fields.preheader} onChange={(e) => set("preheader", e.target.value)} hint="Shown after the subject in most inboxes." />
          </div>
          {blockIssues.other.length > 0 && <IssueList issues={blockIssues.other.map((m) => ({ level: "error", code: "field", message: m }))} />}
          <Builder doc={draft.document} onChange={(d) => set("document", d)} subject={draft.subject} preheader={draft.preheader} issues={blockIssues.blocks} readOnly={readOnly} />
        </section>

        <ABSection ab={draft.ab} base={draft} readOnly={readOnly} errors={fields} onChange={(ab) => set("ab", ab)} />

        <section className="em-card" aria-labelledby="review-h">
          <h2 id="review-h" className="em-h2">
            Review and send
          </h2>
          <Review campaign={campaign} check={check} checking={checking} dirty={dirty} onCheck={runCheck} onSent={(c) => (onSaved(c), navigate(`/email/campaigns/${c.id}`))} />
        </section>
      </div>
    </div>
  );
}

function AudiencePreview({ preview }: { preview: Preview | null }) {
  if (!preview) return <Skeleton className="em-skel-line" />;
  const excluded = Object.entries(preview.excluded);
  const words = { suppressed: "on the suppression list", unsubscribed: "unsubscribed or on do not disturb", topic_unsubscribed: "unsubscribed from this topic" };
  return (
    <div className="em-audience" aria-live="polite">
      <p className="em-big">
        <strong>{preview.recipients.toLocaleString()}</strong> {preview.recipients === 1 ? "person" : "people"} will get it
      </p>
      <ul className="em-small-list">
        <li>{preview.matched.toLocaleString()} contacts match</li>
        {preview.matched > preview.with_email && <li>{(preview.matched - preview.with_email).toLocaleString()} have no email address</li>}
        {preview.duplicates > 0 && <li>{preview.duplicates.toLocaleString()} share an address with another contact (they get one email)</li>}
        {excluded.map(([k, n]) => (
          <li key={k}>
            {n!.toLocaleString()} {words[k as keyof typeof words]}
          </li>
        ))}
      </ul>
      {preview.sample.length > 0 && (
        <details>
          <summary>Some of them</summary>
          <ul className="em-small-list">
            {preview.sample.map((s) => (
              <li key={s.id}>
                <Link to={`/contacts/${s.id}`}>{s.display_name || s.email}</Link> <span className="em-muted">{s.email}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="ui-hint">The audience is read again when the campaign starts, so people who join the view by then get it too.</p>
    </div>
  );
}

function ABSection({ ab, base, readOnly, errors, onChange }: { ab: AB; base: Draft; readOnly: boolean; errors: Record<string, string>; onChange: (ab: AB) => void }) {
  const b = ab.variants[0] ?? { key: "B" as const };
  const setB = (patch: Partial<typeof b>) => onChange({ ...ab, variants: [{ ...b, ...patch }] });
  const variantErrors = Object.entries(errors).filter(([k]) => k.startsWith("ab."));
  const bDoc = b.document ? withIds(b.document) : null;
  return (
    <section className="em-card" aria-labelledby="ab-h">
      <div className="em-card-head">
        <h2 id="ab-h" className="em-h2">
          A/B test
        </h2>
        <Switch label="Test two versions" checked={ab.enabled} disabled={readOnly} onCheckedChange={(on) => onChange({ ...ab, enabled: on, variants: on && !ab.variants.length ? [{ key: "B", subject: "" }] : ab.variants })} />
      </div>
      {ab.enabled ? (
        <div className="em-grid">
          <Input label="Variant B subject" value={b.subject ?? ""} maxLength={500} disabled={readOnly} onChange={(e) => setB({ subject: e.target.value || null })} hint="Variant A is the subject above." />
          <Input label="Variant B preview text (optional)" value={b.preheader ?? ""} maxLength={300} disabled={readOnly} onChange={(e) => setB({ preheader: e.target.value || null })} />
          <Select
            label="The winner is the one with more"
            value={ab.metric}
            disabled={readOnly}
            options={[
              { value: "opens", label: "Opens (by people, not privacy proxies)" },
              { value: "clicks", label: "Clicks (by people, not scanners)" },
            ]}
            onValueChange={(v) => onChange({ ...ab, metric: v as "opens" })}
          />
          <Input label="Test group, % of the audience" type="number" min={10} max={100} value={ab.test_percent} disabled={readOnly} onChange={(e) => onChange({ ...ab, test_percent: Number(e.target.value) || 20 })} hint="Split evenly between A and B; the rest get the winner." />
          <Input label="Hours before the winner is chosen" type="number" min={1} max={72} value={ab.wait_hours} disabled={readOnly} onChange={(e) => onChange({ ...ab, wait_hours: Number(e.target.value) || 4 })} />
          <div className="em-span">
            <Switch
              label="Variant B has different content"
              checked={!!b.document}
              disabled={readOnly}
              onCheckedChange={(on) => setB({ document: on ? withIds(JSON.parse(JSON.stringify(base.document))) : null })}
            />
          </div>
          {bDoc && (
            <div className="em-span">
              <Builder doc={bDoc} onChange={(d) => setB({ document: d })} subject={b.subject || base.subject} preheader={b.preheader ?? base.preheader} readOnly={readOnly} />
            </div>
          )}
          {variantErrors.map(([k, m]) => (
            <p key={k} className="em-field-error">
              {m}
            </p>
          ))}
        </div>
      ) : (
        <p className="em-muted">Send two versions (subject, preview text or content) to part of the audience, then the better one to everyone else, automatically. Ties go to A.</p>
      )}
    </section>
  );
}

function Review({ campaign, check, checking, dirty, onCheck, onSent }: { campaign: Campaign; check: Check | null; checking: boolean; dirty: boolean; onCheck: () => void; onSent: (c: Campaign) => void }) {
  const toast = useToast();
  const { can } = useCan();
  const [when, setWhen] = useState<"now" | "later">("now");
  const [date, setDate] = useState(() => new Date(Date.now() + 864e5).toISOString().slice(0, 10));
  const [time, setTime] = useState("09:00");
  const [zone, setZone] = useState(here);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!dirty && !check && !checking) onCheck();
  }, [dirty, check, checking, onCheck]);
  const schedule = when === "later" ? scheduleBody(date, time, zone) : { timezone: zone };
  const errors = check?.issues.filter((i) => i.level === "error") ?? [];
  async function send() {
    setBusy(true);
    try {
      const c = await email.schedule(campaign.id, schedule!);
      setConfirm(false);
      toast({ title: when === "now" ? "Sending" : "Scheduled", description: when === "now" ? "The campaign is on its way." : `It goes ${new Date(c.scheduled_at!).toLocaleString()}.`, tone: "success" });
      onSent(c);
    } catch (e) {
      setConfirm(false);
      toast({ title: "Not sent", description: errorText(e), tone: "danger" });
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="em-review">
      <div className="em-row">
        <Button onClick={onCheck} loading={checking} disabled={dirty}>
          Run the check again
        </Button>
        {dirty && <span className="em-muted">Saving your changes first...</span>}
      </div>
      {check ? (
        <>
          <IssueList issues={byLevel(check.issues)} empty="Ready: nothing stands between this campaign and the inbox." />
          <p className="em-muted">
            {check.audience.recipients.toLocaleString()} recipients
            {Number(check.estimate.estimated_cost) > 0 && ` · estimated cost ${check.estimate.estimated_cost}`}
          </p>
        </>
      ) : (
        <Skeleton className="em-skel-line" />
      )}
      {can("marketing.send") && (
        <>
          <Segmented
            label="When"
            value={when}
            onChange={setWhen}
            options={[
              { value: "now", label: "Send now" },
              { value: "later", label: "Schedule" },
            ]}
          />
          {when === "later" && (
            <div className="em-grid em-grid-3">
              <Input label="Date" type="date" value={date} onChange={(e) => setDate(e.target.value)} />
              <Input label="Time" type="time" value={time} onChange={(e) => setTime(e.target.value)} />
              <Select label="Time zone" value={zone} options={zones.map((z) => ({ value: z, label: z.replace(/_/g, " ") }))} onValueChange={setZone} />
            </div>
          )}
          <div className="em-row">
            <Button variant="primary" disabled={!check || !check.ok || dirty || !schedule || busy} onClick={() => setConfirm(true)}>
              <Send size={16} aria-hidden />
              {when === "now" ? "Send now" : "Schedule"}
            </Button>
            {check && !check.ok && <span className="em-muted">{errors.length === 1 ? "Fix the one error above to send." : `Fix the ${errors.length} errors above to send.`}</span>}
          </div>
          <Dialog
            open={confirm}
            onOpenChange={(o) => !o && !busy && setConfirm(false)}
            title={when === "now" ? `Send to ${check?.audience.recipients.toLocaleString() ?? ""} people now?` : "Schedule this campaign?"}
            description={
              when === "now"
                ? "It starts at once, at the pace your sending domain allows. You can pause or cancel what has not gone yet."
                : `It starts ${date} at ${time} (${zone.replace(/_/g, " ")}). Until then you can unschedule it and edit it.`
            }
            footer={
              <>
                <Button onClick={() => setConfirm(false)} disabled={busy}>
                  Cancel
                </Button>
                <Button variant="primary" loading={busy} onClick={() => void send()}>
                  {when === "now" ? "Send now" : "Schedule"}
                </Button>
              </>
            }
          />
        </>
      )}
    </div>
  );
}

function Sent({ campaign, onChange }: { campaign: Campaign; onChange: (c: Campaign) => void }) {
  const navigate = useNavigate();
  const toast = useToast();
  const { can } = useCan();
  const [cancelling, setCancelling] = useState(false);
  const act = async (action: "unschedule" | "pause" | "resume" | "cancel") => {
    try {
      const c = await email.act(campaign.id, action);
      onChange(c);
      toast({ title: { unschedule: "Back to a draft", pause: "Paused", resume: "Resumed", cancel: "Cancelled" }[action], tone: "success" });
    } catch (e) {
      toast({ title: "That did not work", description: errorText(e), tone: "danger" });
    }
  };
  const running = ["scheduled", "sending", "testing"].includes(campaign.status);
  const send = can("marketing.send");
  return (
    <div className="sh-page em-page em-campaign">
      <Header
        campaign={campaign}
        actions={
          <>
            {send && (campaign.status === "scheduled" || (campaign.status === "paused" && campaign.paused_from === "scheduled")) && (
              <Button onClick={() => void act("unschedule")}>
                <Undo2 size={16} aria-hidden />
                Unschedule
              </Button>
            )}
            {send && running && (
              <Button onClick={() => void act("pause")}>
                <Pause size={16} aria-hidden />
                Pause
              </Button>
            )}
            {send && campaign.status === "paused" && (
              <Button variant="primary" onClick={() => void act("resume")}>
                <Play size={16} aria-hidden />
                Resume
              </Button>
            )}
            {send && (running || campaign.status === "paused") && (
              <Button variant="danger" onClick={() => setCancelling(true)}>
                <Square size={16} aria-hidden />
                Cancel
              </Button>
            )}
            {can("marketing.write") && (
              <Button
                onClick={async () => {
                  try {
                    navigate(`/email/campaigns/${(await email.duplicateCampaign(campaign.id)).id}`);
                  } catch (e) {
                    toast({ title: "Could not duplicate", description: errorText(e), tone: "danger" });
                  }
                }}
              >
                <Copy size={16} aria-hidden />
                Duplicate
              </Button>
            )}
          </>
        }
      />
      <StatusNote campaign={campaign} />
      <Report campaign={campaign} />
      <Dialog
        open={cancelling}
        onOpenChange={setCancelling}
        title="Cancel this campaign?"
        description="Emails that have not gone yet never go. What went stays in the report. This cannot be undone; duplicate it to send again."
        footer={
          <>
            <Button onClick={() => setCancelling(false)}>Keep it</Button>
            <Button
              variant="danger"
              onClick={() => {
                setCancelling(false);
                void act("cancel");
              }}
            >
              Cancel campaign
            </Button>
          </>
        }
      />
    </div>
  );
}

function StatusNote({ campaign: c }: { campaign: Campaign }) {
  const at = (s: string | null) => (s ? new Date(s).toLocaleString() : "");
  const note =
    c.status === "scheduled"
      ? `Goes out ${at(c.scheduled_at)} (${c.timezone.replace(/_/g, " ")}). The audience is read then.`
      : c.status === "sending"
        ? `Sending at the pace your domain allows: ${c.stats.sent.toLocaleString()} of ${(c.audience_count ?? c.stats.recipients).toLocaleString()} sent so far.`
        : c.status === "testing"
          ? `The A/B test is running. The winner is chosen ${at(c.test_ends_at)} and goes to everyone else.`
          : c.status === "paused"
            ? `Paused${c.error ? `: ${c.error}` : ""}. Nothing more goes until you resume.`
            : c.status === "failed"
              ? `Failed: ${c.error}`
              : c.status === "cancelled"
                ? `Cancelled ${at(c.finished_at)}.`
                : `Sent ${at(c.finished_at)}${c.winner && c.ab?.enabled ? `; variant ${c.winner} won the A/B test` : ""}.${c.error ? ` ${c.error}` : ""}`;
  return (
    <p className="em-status-note" data-tone={STATUS_TONE[c.status]} role="status">
      {note}
    </p>
  );
}
