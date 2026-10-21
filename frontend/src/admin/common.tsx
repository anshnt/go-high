// Pieces every admin screen shares: the header with its way back, the loading, error and permission-denied states,
// a confirm dialog, copyable text, a JSON block and the guard against leaving with unsaved changes.
import { Check, ChevronLeft, Copy, LockKeyhole, TriangleAlert } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { Link, useBlocker } from "react-router";
import { ApiError } from "../lib/api";
import { useCan } from "../lib/capabilities";
import { whatWentWrong } from "../lib/errors";
import { PageHeader } from "../shell/PageHeader";
import { Button, Dialog, EmptyState, Skeleton, useToast } from "../ui";

/** The way back to the settings list (or to `to`), then the page title. */
export function AdminHeader({ title, description, actions, back = { to: "/settings", label: "Settings" }, views }: { title: string; description?: string; actions?: ReactNode; back?: { to: string; label: string }; views?: ReactNode }) {
  return (
    <>
      <Link to={back.to} className="sh-back">
        <ChevronLeft size={16} aria-hidden />
        {back.label}
      </Link>
      <PageHeader title={title} description={description} actions={actions} views={views} />
    </>
  );
}

export const Denied = ({ what, capability }: { what: string; capability: string }) => (
  <EmptyState icon={LockKeyhole} title={`Your role cannot ${what}`} text={`Ask a workspace admin. They can give your role the capability ${capability}.`} />
);

export const LoadError = ({ what, error, retry }: { what: string; error: unknown; retry: () => void }) => (
  <EmptyState icon={TriangleAlert} title={`Could not load ${what}`} text={whatWentWrong(error)} action={<Button onClick={retry}>Try again</Button>} />
);

/** Whether the caller may use a screen that needs `capability`: "wait" until the capabilities arrive (so a role that
 * may not is not sent requests it will be refused), then "yes" or "no". If they never arrive (the call failed) the
 * screen goes ahead after a few seconds and the server decides, which shows its own permission-denied state. */
export function useGate(capability: string): "wait" | "yes" | "no" {
  const { can, ready } = useCan();
  const [late, setLate] = useState(false);
  useEffect(() => {
    if (ready) return;
    const t = setTimeout(() => setLate(true), 4000);
    return () => clearTimeout(t);
  }, [ready]);
  if (!ready) return late ? "yes" : "wait";
  return can(capability) ? "yes" : "no";
}

export const isDenied = (e: unknown) => e instanceof ApiError && e.status === 403;

export function Loading({ label, rows = 3, height = 56 }: { label: string; rows?: number; height?: number }) {
  return (
    <div className="adm-stack" aria-busy="true" aria-label={label} role="status">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} style={{ height }} />
      ))}
    </div>
  );
}

/** Loads with `fn` when `enabled` and again on `reload`; keeps the last good answer while reloading. */
export function useLoad<T>(fn: () => Promise<T>, deps: unknown[], enabled = true) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(enabled);
  const [tick, setTick] = useState(0);
  const seq = useRef(0);
  useEffect(() => {
    if (!enabled) return;
    const mine = ++seq.current;
    setLoading(true);
    fn().then(
      (d) => {
        if (mine !== seq.current) return;
        setData(d);
        setError(null);
        setLoading(false);
      },
      (e) => {
        if (mine !== seq.current) return;
        setError(e);
        setLoading(false);
      },
    );
    // the caller lists what the call depends on
  }, [enabled, tick, ...deps]);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  return { data, setData, error, loading, reload };
}

export function ConfirmDialog({ open, onOpenChange, title, description, confirm, onConfirm, busy, tone = "danger", children }: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  title: string;
  description: string;
  confirm: string;
  onConfirm: () => void;
  busy?: boolean;
  tone?: "danger" | "primary";
  children?: ReactNode;
}) {
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      description={description}
      footer={
        <>
          <Button onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant={tone} onClick={onConfirm} loading={busy} autoFocus>
            {confirm}
          </Button>
        </>
      }
    >
      {children}
    </Dialog>
  );
}

/** A value with a Copy button; `masked` shows dots until it is revealed by the caller. */
export function CopyText({ label, value, masked, mono = true }: { label: string; value: string; masked?: boolean; mono?: boolean }) {
  const toast = useToast();
  const [done, setDone] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(value);
      setDone(true);
      setTimeout(() => setDone(false), 1500);
      toast({ title: "Copied", description: label, tone: "success", duration: 2500 });
    } catch {
      toast({ title: "Could not copy", description: "Select the text and copy it yourself.", tone: "danger" });
    }
  };
  return (
    <div className="adm-copy">
      <code className={mono ? "mono" : undefined} tabIndex={0} aria-label={masked ? `${label}, hidden` : label}>
        {masked ? "•".repeat(Math.min(40, Math.max(12, value.length))) : value}
      </code>
      <Button size="sm" onClick={() => void copy()} aria-label={`Copy ${label.toLowerCase()}`} disabled={masked}>
        {done ? <Check size={14} aria-hidden /> : <Copy size={14} aria-hidden />} Copy
      </Button>
    </div>
  );
}

export function JsonBlock({ label, value }: { label: string; value: unknown }) {
  return (
    <pre className="adm-json mono" tabIndex={0} aria-label={label}>
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

/** Asks before leaving a page with unsaved changes (another route, a reload or closing the tab). */
export function useUnsavedGuard(dirty: boolean) {
  const blocker = useBlocker(({ currentLocation, nextLocation }) => dirty && currentLocation.pathname !== nextLocation.pathname);
  useEffect(() => {
    if (!dirty) return;
    const stop = (e: BeforeUnloadEvent) => e.preventDefault();
    window.addEventListener("beforeunload", stop);
    return () => window.removeEventListener("beforeunload", stop);
  }, [dirty]);
  return (
    <Dialog
      open={blocker.state === "blocked"}
      onOpenChange={(o) => !o && blocker.state === "blocked" && blocker.reset()}
      title="Leave without saving?"
      description="You have changes that are not saved yet."
      footer={
        <>
          <Button onClick={() => blocker.state === "blocked" && blocker.reset()}>Keep editing</Button>
          <Button variant="danger" onClick={() => blocker.state === "blocked" && blocker.proceed()}>
            Leave without saving
          </Button>
        </>
      }
    />
  );
}

const DATE_TIME = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit" });
const DATE_TIME_S = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" });
const DATE = new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric", year: "numeric" });
export const when = (iso: string, seconds = false) => (seconds ? DATE_TIME_S : DATE_TIME).format(new Date(iso));
export const day = (iso: string) => DATE.format(new Date(iso));

/** A person as a short label. */
export const personName = (p: { name: string | null; email: string | null }) => p.name?.trim() || p.email || "Unknown person";
