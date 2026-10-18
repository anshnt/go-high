import { ChevronLeft } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router";
import { whatWentWrong } from "../lib/errors";
import { getPrefs, savePrefs, type Pref } from "../lib/notifications";
import { zone } from "../lib/tasks";
import { PageHeader } from "../shell/PageHeader";
import { Button, EmptyState, Input, Select, Skeleton, Switch, useToast } from "../ui";
import "../tasks/tasks.css";

const WHO = [
  { value: "mine", label: "Only what is about me" },
  { value: "all", label: "Everything in this workspace" },
];
const DEFAULT_QUIET = { start: "22:00", end: "07:00" };

/** Settings > Notifications: for each kind of event, where it reaches you and for whom, and when it waits. */
export function NotificationSettings() {
  const toast = useToast();
  const [prefs, setPrefs] = useState<Pref[] | null>(null);
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);

  useEffect(() => {
    getPrefs()
      .then(setPrefs)
      .catch((e) => setError(whatWentWrong(e)));
  }, []);

  const change = (kind: string, patch: Partial<Pref>) => {
    setPrefs((list) => list && list.map((p) => (p.kind === kind ? { ...p, ...patch } : p)));
    setDirty(true);
  };
  // Quiet hours are one setting for the person: every kind carries the same window.
  const quiet = prefs?.find((p) => p.quiet_start && p.quiet_end);
  const setQuiet = (patch: Partial<Pref>) => {
    setPrefs((list) => list && list.map((p) => ({ ...p, ...patch })));
    setDirty(true);
  };

  async function save() {
    if (!prefs) return;
    setBusy(true);
    try {
      setPrefs(await savePrefs(prefs));
      setDirty(false);
      toast({ title: "Notification settings saved", tone: "success" });
    } catch (e) {
      toast({ title: "Could not save", description: whatWentWrong(e), tone: "danger" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="sh-page tk-page">
      <Link to="/settings" className="sh-back">
        <ChevronLeft size={16} aria-hidden />
        Settings
      </Link>
      <PageHeader
        title="Notifications"
        description="Choose what reaches you, for whom, and when it waits."
        actions={
          <Button variant="primary" onClick={() => void save()} loading={busy} disabled={!dirty}>
            Save changes
          </Button>
        }
      />
      {error && !prefs ? (
        <EmptyState icon={ChevronLeft} title="Could not load your settings" text={error} />
      ) : !prefs ? (
        <div className="tk-skeleton" aria-busy aria-label="Loading settings">
          <Skeleton style={{ height: 84 }} />
          <Skeleton style={{ height: 84 }} />
        </div>
      ) : (
        <>
          <section className="sh-section" aria-labelledby="pref-events">
            <h2 id="pref-events">What to tell me about</h2>
            <p>Each kind of event, in the bell in the top bar. These settings are yours alone, in this workspace.</p>
            <ul className="tk-prefs">
              {prefs.map((p) => (
                <li key={p.kind} className="tk-pref">
                  <div className="tk-pref-name">
                    <strong>{p.label}</strong>
                  </div>
                  <div className="tk-pref-controls">
                    <Switch label="In the bell" checked={p.channels.includes("in_app")} onCheckedChange={(on) => change(p.kind, { channels: on ? [...p.channels, "in_app"] : p.channels.filter((c) => c !== "in_app") })} />
                    <Switch label="By email" checked={p.channels.includes("email")} disabled />
                    <Select aria-label={`Who ${p.label.toLowerCase()} is for`} value={p.scope} onValueChange={(scope) => change(p.kind, { scope: scope as Pref["scope"] })} options={WHO} />
                  </div>
                </li>
              ))}
            </ul>
            <p className="tk-muted">Email notifications and the daily digest arrive with the email module. Nothing is sent by email yet.</p>
          </section>
          <section className="sh-section" aria-labelledby="pref-quiet">
            <h2 id="pref-quiet">Quiet hours</h2>
            <p>While it is quiet, notifications are held and appear in the bell when quiet hours end.</p>
            <div className="tk-quiet">
              <Switch
                label="Hold notifications during quiet hours"
                checked={!!quiet}
                onCheckedChange={(on) => setQuiet(on ? { quiet_start: DEFAULT_QUIET.start, quiet_end: DEFAULT_QUIET.end, tz: zone() } : { quiet_start: null, quiet_end: null })}
              />
              {quiet && (
                <div className="tk-grid2">
                  <Input label="From" type="time" value={quiet.quiet_start ?? ""} onChange={(e) => e.target.value && setQuiet({ quiet_start: e.target.value })} />
                  <Input label="Until" type="time" value={quiet.quiet_end ?? ""} onChange={(e) => e.target.value && setQuiet({ quiet_end: e.target.value })} />
                  <p className="tk-muted">Times are in {quiet.tz ?? zone()}.</p>
                </div>
              )}
            </div>
          </section>
        </>
      )}
    </div>
  );
}
