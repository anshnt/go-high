import { ChevronLeft, CircleAlert, LogOut } from "lucide-react";
import { useCallback, useEffect, useState, type FormEvent } from "react";
import { Link } from "react-router";
import { api, errorText } from "../lib/api";
import { describeDevice, timeAgo } from "../lib/device";
import { leave, refreshMe, useMe } from "../lib/session";
import { PageHeader } from "../shell/PageHeader";
import { Badge, Button, Dialog, EmptyState, Input, Table, useToast, type Column } from "../ui";

type Row = { id: string; created_at: string; last_seen_at: string; expires_at: string; ip: string | null; user_agent: string | null; current: boolean };
type Confirm = { kind: "one"; row: Row } | { kind: "others" } | null;

const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

/** Settings > Security: where you are signed in, with a way out of each place. */
export function SecuritySettings() {
  const toast = useToast();
  const [rows, setRows] = useState<Row[] | null>(null);
  const [error, setError] = useState<string>();
  const [confirm, setConfirm] = useState<Confirm>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setError(undefined);
    api
      .get<Row[]>("/api/auth/sessions")
      .then((list) => setRows([...list].sort((a, b) => Number(b.current) - Number(a.current))))
      .catch((e) => setError(errorText(e)));
  }, []);
  useEffect(load, [load]);

  const others = rows?.filter((r) => !r.current) ?? [];

  async function run(c: NonNullable<Confirm>) {
    setBusy(true);
    let signedOut = false;
    try {
      if (c.kind === "one") {
        await api.del(`/api/auth/sessions/${c.row.id}`);
        if (c.row.current) {
          signedOut = true;
          return leave(); // the server cleared our cookie too
        }
        toast({ title: "Session revoked", description: describeDevice(c.row.user_agent), tone: "success" });
      } else {
        const { revoked } = await api.post<{ revoked: number }>("/api/auth/sessions/revoke-others");
        toast({ title: `Signed out ${plural(revoked, "other device")}`, tone: "success" });
      }
    } catch (e) {
      toast({ title: "Could not revoke the session", description: errorText(e), tone: "danger" });
    } finally {
      setBusy(false);
      setConfirm(null);
      if (!signedOut) load();
    }
  }

  const columns: Column<Row>[] = [
    {
      key: "device",
      header: "Device",
      cell: (r) => (
        <div className="sh-sess-device">
          <span className="sh-sess-name">
            {describeDevice(r.user_agent)}
            {r.current && <Badge tone="accent">This device</Badge>}
          </span>
          <span className="sh-sess-meta mono">{r.ip ?? "Unknown address"}</span>
        </div>
      ),
    },
    {
      key: "last",
      header: "Last active",
      cell: (r) => (
        <time dateTime={r.last_seen_at} title={new Date(r.last_seen_at).toLocaleString()}>
          {timeAgo(r.last_seen_at)}
        </time>
      ),
    },
    {
      key: "actions",
      header: "Actions",
      align: "right",
      cell: (r) => (
        <Button size="sm" aria-label={`Revoke session on ${describeDevice(r.user_agent)}${r.current ? " (this device)" : ""}`} onClick={() => setConfirm({ kind: "one", row: r })}>
          Revoke
        </Button>
      ),
    },
  ];

  const text = !confirm
    ? null
    : confirm.kind === "others"
      ? { title: "Sign out everywhere else?", body: `${plural(others.length, "other device")} will be signed out. This device stays signed in.`, action: `Sign out ${plural(others.length, "device")}` }
      : confirm.row.current
        ? { title: "Sign out of this device?", body: "You will be signed out here and taken back to the sign-in screen.", action: "Sign out" }
        : { title: "Revoke this session?", body: `${describeDevice(confirm.row.user_agent)}${confirm.row.ip ? ` at ${confirm.row.ip}` : ""} will be signed out. It can sign in again at any time.`, action: "Revoke session" };

  return (
    <div className="sh-page">
      <Link to="/settings" className="sh-back">
        <ChevronLeft size={16} aria-hidden />
        Settings
      </Link>
      <PageHeader
        title="Security"
        description="Where you are signed in, and how to sign out of it."
        actions={
          <Button onClick={() => setConfirm({ kind: "others" })} disabled={others.length === 0}>
            <LogOut size={16} aria-hidden />
            Sign out everywhere else
          </Button>
        }
      />
      <section className="sh-section" aria-labelledby="sessions-title">
        <h2 id="sessions-title">Active sessions</h2>
        <p>Revoke any session you do not recognize. It is signed out on its next request.</p>
        {error ? (
          <EmptyState
            icon={CircleAlert}
            title="We could not load your sessions"
            text={error}
            action={
              <Button onClick={load}>Try again</Button>
            }
          />
        ) : (
          <Table caption="Active sessions" columns={columns} rows={rows ?? []} rowId={(r) => r.id} loading={rows === null} />
        )}
      </section>
      <PasswordSection onSaved={load} />

      <Dialog
        open={!!confirm}
        onOpenChange={(open) => !open && !busy && setConfirm(null)}
        title={text?.title ?? ""}
        description={text?.body}
        footer={
          <>
            <Button onClick={() => setConfirm(null)} disabled={busy}>
              Cancel
            </Button>
            <Button variant="danger" loading={busy} onClick={() => confirm && void run(confirm)}>
              {text?.action}
            </Button>
          </>
        }
      />
    </div>
  );
}

/** Change the password, or set a first one (magic-link users). The server signs out every other session. */
function PasswordSection({ onSaved }: { onSaved: () => void }) {
  const me = useMe();
  const toast = useToast();
  const has = me?.user.has_password ?? false;
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [error, setError] = useState<string>();
  const [busy, setBusy] = useState(false);

  async function submit(ev: FormEvent) {
    ev.preventDefault();
    if (next.length < 10) return setError("Use at least 10 characters.");
    setError(undefined);
    setBusy(true);
    try {
      await api.post("/api/auth/password", has ? { password: next, current_password: current } : { password: next });
      toast({ title: has ? "Password changed" : "Password set", description: "Other devices were signed out.", tone: "success" });
      setCurrent("");
      setNext("");
      await refreshMe();
      onSaved();
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="sh-section" aria-labelledby="password-title">
      <h2 id="password-title">Password</h2>
      <p>
        {has
          ? "Changing it signs you out everywhere else."
          : "You sign in with email links. Add a password to sign in without opening your inbox. For your safety this works within 15 minutes of signing in."}
      </p>
      <form className="sh-form sh-password" onSubmit={submit} noValidate>
        {has && <Input label="Current password" type="password" autoComplete="current-password" value={current} onChange={(e) => setCurrent(e.target.value)} />}
        <Input
          label={has ? "New password" : "Password"}
          type="password"
          autoComplete="new-password"
          hint="At least 10 characters."
          error={error}
          value={next}
          onChange={(e) => setNext(e.target.value)}
        />
        <div>
          <Button type="submit" variant="primary" loading={busy}>
            {has ? "Change password" : "Set password"}
          </Button>
        </div>
      </form>
    </section>
  );
}
