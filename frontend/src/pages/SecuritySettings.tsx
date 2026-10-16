import { ChevronLeft, CircleAlert, LogOut } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router";
import { api, errorText } from "../lib/api";
import { describeDevice, timeAgo } from "../lib/device";
import { leave } from "../lib/session";
import { PageHeader } from "../shell/PageHeader";
import { Badge, Button, Dialog, EmptyState, Table, useToast, type Column } from "../ui";

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
        // ponytail: one request per session, there is no bulk endpoint. Add one if people have dozens.
        const results = await Promise.allSettled(others.map((r) => api.del(`/api/auth/sessions/${r.id}`)));
        const failed = results.filter((r) => r.status === "rejected").length;
        toast(
          failed
            ? { title: `Signed out ${others.length - failed} of ${others.length}`, description: "Some sessions could not be revoked. Try again.", tone: "danger" }
            : { title: `Signed out ${plural(others.length, "other device")}`, tone: "success" },
        );
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
