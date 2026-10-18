import { CalendarDays, ChevronLeft, ChevronRight, Copy, ExternalLink } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link } from "react-router";
import { ApiError } from "../lib/api";
import { bookingsVersion, cancelBooking, KIND, listBookings, listCalendars, markBooking, myHours, STATUS, type Booking, type CalendarItem } from "../lib/calendars";
import { whatWentWrong } from "../lib/errors";
import { useMe } from "../lib/session";
import { useStore } from "../lib/store";
import { PageHeader } from "../shell/PageHeader";
import { Badge, Button, EmptyState, Sheet, Skeleton, Tabs, TabsContent, TabsList, TabsTrigger, Textarea, useToast } from "../ui";
import { DAY_MINUTES, firstWorkMinute, layoutWeek, offWindows, workWindows, type Hours } from "./layout";
import { browserZone, dateKey, formatClock, formatDateLong, formatKey, rangeLabel, toIso, wallMinutes, weekRange, zoneNote, addDays } from "./time";
import "./calendar.css";

const HOUR_PX = 48;
const px = (minutes: number) => (minutes * HOUR_PX) / 60;
const HOURS = Array.from({ length: 24 }, (_, h) => h);
const hourLabel = (h: number) => (h === 0 ? "" : `${h % 12 || 12} ${h < 12 ? "AM" : "PM"}`);
const touch = () => bookingsVersion.set(bookingsVersion.get() + 1);

/** Calendar: your team's bookings in a week, and the booking pages people book from. */
export function CalendarPage() {
  return (
    <div className="sh-page cl-page">
      <Tabs defaultValue="week">
        <PageHeader
          title="Calendar"
          description="Bookings from your booking pages, on your clock."
          views={
            <TabsList aria-label="View" className="cl-views">
              <TabsTrigger value="week">Bookings</TabsTrigger>
              <TabsTrigger value="calendars">Booking pages</TabsTrigger>
            </TabsList>
          }
        />
        <TabsContent value="week">
          <Week />
        </TabsContent>
        <TabsContent value="calendars">
          <Calendars />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function Week() {
  const zone = useMemo(browserZone, []);
  const version = useStore(bookingsVersion);
  const me = useMe()?.user.id;
  const [day, setDay] = useState(() => dateKey(Date.now(), zone));
  const week = useMemo(() => weekRange(day, zone), [day, zone]);
  const [loaded, setLoaded] = useState<{ from: number; list: Booking[] } | null>(null);
  const [error, setError] = useState<string>();
  const [hours, setHours] = useState<Hours | null>(null);
  const [open, setOpen] = useState<Booking | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const bookings = loaded?.from === week.from ? loaded.list : null;
  const today = dateKey(Date.now(), zone);

  useEffect(() => {
    let alive = true;
    listBookings(toIso(week.from), toIso(week.to))
      .then((list) => {
        if (!alive) return;
        setLoaded({ from: week.from, list });
        setError(undefined);
      })
      .catch((e) => alive && setError(whatWentWrong(e)));
    return () => {
      alive = false;
    };
  }, [week.from, week.to, version]);

  useEffect(() => {
    if (me) myHours(me).then(setHours, () => setHours(null)); // shading only: without hours the grid is plain
  }, [me]);

  // Scroll to the start of the working day when the week changes.
  useEffect(() => {
    scroller.current?.scrollTo({ top: Math.max(0, px(firstWorkMinute(hours, week.days, zone)) - 8) });
  }, [hours, week, zone]);

  const placed = useMemo(
    () => layoutWeek((bookings ?? []).map((b) => ({ start: Date.parse(b.starts_at), end: Date.parse(b.ends_at), item: b })), week.days, zone),
    [bookings, week.days, zone],
  );
  const count = (bookings ?? []).filter((b) => b.status !== "cancelled").length;

  return (
    <section className="cl-week" aria-label="Bookings this week">
      <div className="cl-toolbar">
        <div className="cl-nav">
          <Button variant="ghost" size="icon" aria-label="Previous week" onClick={() => setDay(addDays(week.days[0]!, -7))}>
            <ChevronLeft size={18} aria-hidden />
          </Button>
          <Button size="sm" onClick={() => setDay(today)}>
            Today
          </Button>
          <Button variant="ghost" size="icon" aria-label="Next week" onClick={() => setDay(addDays(week.days[0]!, 7))}>
            <ChevronRight size={18} aria-hidden />
          </Button>
        </div>
        <h2 aria-live="polite">{rangeLabel(week.days[0]!, week.days[6]!)}</h2>
        <p className="cl-zone">
          {bookings ? `${count} ${count === 1 ? "booking" : "bookings"}, ` : ""}
          {zoneNote(zone, week.from)}
        </p>
      </div>

      {error && !bookings ? (
        <EmptyState icon={CalendarDays} title="Could not load bookings" text={error} action={<Button onClick={touch}>Try again</Button>} />
      ) : (
        <div className="cl-scroll" ref={scroller} aria-busy={!bookings}>
          <div className="cl-grid">
            <div className="cl-corner" />
            {week.days.map((d) => (
              <div key={d} className="cl-dayhead" data-today={d === today || undefined}>
                <span>{formatKey(d, { weekday: "short" })}</span>
                <strong>{formatKey(d, { day: "numeric" })}</strong>
              </div>
            ))}
            <div className="cl-gutter" aria-hidden>
              {HOURS.map((h) => (
                <span key={h} style={{ top: px(h * 60) }}>
                  {hourLabel(h)}
                </span>
              ))}
            </div>
            {week.days.map((d) => (
              <div key={d} className="cl-col" style={{ height: px(DAY_MINUTES) }} role="group" aria-label={formatKey(d, { weekday: "long", month: "long", day: "numeric" })}>
                {hours && offWindows(workWindows(hours, d, zone)).map(([a, b]) => <div key={a} className="cl-off" style={{ top: px(a), height: px(b - a) }} />)}
                {d === today && <div className="cl-now" style={{ top: px(wallMinutes(Date.now(), zone)) }} aria-hidden />}
                {!bookings && <Skeleton className="cl-loading" />}
                {(placed.get(d) ?? []).map(({ item: b, top, height, col, cols }) => (
                  <button
                    key={b.id}
                    type="button"
                    className="cl-event"
                    data-status={b.status}
                    data-short={height < 40 || undefined}
                    style={{ top: px(top), height: px(height), left: `${(col / cols) * 100}%`, width: `${100 / cols}%` }}
                    aria-label={`${formatClock(Date.parse(b.starts_at), zone)} to ${formatClock(Date.parse(b.ends_at), zone)}, ${b.invitee.name}, ${b.calendar.name}, ${STATUS[b.status].label}`}
                    onClick={() => setOpen(b)}
                  >
                    <strong>{b.invitee.name}</strong>
                    <span>
                      {formatClock(Date.parse(b.starts_at), zone)} {b.calendar.name}
                    </span>
                  </button>
                ))}
              </div>
            ))}
          </div>
        </div>
      )}
      {error && bookings && (
        <p role="alert" className="cl-error">
          {error}
        </p>
      )}
      {bookings && count === 0 && !error && <p className="cl-empty">No bookings this week. Share a booking page to get some.</p>}
      {open && <BookingSheet booking={open} zone={zone} onClose={() => setOpen(null)} />}
    </section>
  );
}

function BookingSheet({ booking, zone, onClose }: { booking: Booking; zone: string; onClose: () => void }) {
  const toast = useToast();
  const [b, setB] = useState(booking);
  const [busy, setBusy] = useState<string | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");
  const start = Date.parse(b.starts_at);
  const live = (b.status === "booked" || b.status === "confirmed" || b.status === "rescheduled") && start > Date.now();
  const run = async (what: string, call: () => Promise<Booking>, done: string) => {
    setBusy(what);
    try {
      setB(await call());
      setCancelling(false);
      touch();
      toast({ title: done, tone: "success" });
    } catch (e) {
      toast({ title: e instanceof ApiError ? e.message : whatWentWrong(e), tone: "danger" });
    } finally {
      setBusy(null);
    }
  };
  const facts: [string, ReactNode][] = [
    ["Status", <Badge tone={STATUS[b.status].tone}>{STATUS[b.status].label}</Badge>],
    ["Host", b.host.name ?? "Unassigned"],
    ["Email", <a href={`mailto:${b.invitee.email}`}>{b.invitee.email}</a>],
  ];
  if (b.invitee.phone) facts.push(["Phone", <a href={`tel:${b.invitee.phone}`}>{b.invitee.phone}</a>]);
  if (b.contact) facts.push(["Contact", <Link to={`/contacts/${b.contact.id}`}>{b.contact.display_name}</Link>]);
  const place = b.location?.kind ? [{ video: "Video call", phone: "Phone call", in_person: "In person" }[b.location.kind] ?? "", b.location.value].filter(Boolean).join(": ") : "";
  if (place) facts.push(["Where", place]);
  for (const a of Object.values(b.answers ?? {})) facts.push([a.label, a.value]);
  if (b.cancel_reason) facts.push(["Reason", b.cancel_reason]);

  return (
    <Sheet
      open
      onOpenChange={(o) => !o && onClose()}
      title={b.invitee.name}
      description={`${b.calendar.name}, ${formatDateLong(start, zone)}, ${formatClock(start, zone)} to ${formatClock(Date.parse(b.ends_at), zone)}`}
      footer={
        cancelling ? (
          <>
            <Button variant="ghost" onClick={() => setCancelling(false)}>
              Keep it
            </Button>
            <Button variant="danger" loading={busy === "cancel"} onClick={() => run("cancel", () => cancelBooking(b.id, reason.trim()), "Booking cancelled")}>
              Cancel booking
            </Button>
          </>
        ) : (
          <>
            {live && (
              <Button variant="danger" onClick={() => setCancelling(true)}>
                Cancel
              </Button>
            )}
            {b.status !== "cancelled" && b.status !== "no_show" && start <= Date.now() && (
              <Button loading={busy === "no_show"} onClick={() => run("no_show", () => markBooking(b.id, "no_show"), "Marked as no-show")}>
                No-show
              </Button>
            )}
            {b.status !== "cancelled" && b.status !== "showed" && start <= Date.now() && (
              <Button loading={busy === "showed"} onClick={() => run("showed", () => markBooking(b.id, "showed"), "Marked as showed")}>
                Showed
              </Button>
            )}
            {(b.status === "booked" || b.status === "rescheduled") && (
              <Button variant="primary" loading={busy === "confirmed"} onClick={() => run("confirmed", () => markBooking(b.id, "confirmed"), "Booking confirmed")}>
                Confirm
              </Button>
            )}
          </>
        )
      }
    >
      <dl className="cl-facts">
        {facts.map(([label, value], i) => (
          <div key={i} className="cl-fact">
            <dt>{label}</dt>
            <dd>{value}</dd>
          </div>
        ))}
      </dl>
      {cancelling && <Textarea label="Reason (optional)" value={reason} maxLength={500} onChange={(e) => setReason(e.target.value)} />}
    </Sheet>
  );
}

function Calendars() {
  const toast = useToast();
  const [list, setList] = useState<CalendarItem[] | null>(null);
  const [error, setError] = useState<string>();
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let alive = true;
    listCalendars().then(
      (l) => alive && setList(l),
      (e) => alive && setError(whatWentWrong(e)),
    );
    return () => {
      alive = false;
    };
  }, [attempt]);

  const copy = async (c: CalendarItem) => {
    try {
      await navigator.clipboard.writeText(c.public_url ?? "");
      toast({ title: "Link copied", description: c.public_url ?? undefined, tone: "success" });
    } catch {
      toast({ title: "Could not copy the link", description: c.public_url ?? undefined, tone: "danger" });
    }
  };

  if (error && !list) return <EmptyState icon={CalendarDays} title="Could not load booking pages" text={error} action={<Button onClick={() => setAttempt((n) => n + 1)}>Try again</Button>} />;
  if (!list) return <Skeleton style={{ height: 120 }} />;
  if (list.length === 0) return <EmptyState icon={CalendarDays} title="No booking pages yet" text="Make a calendar through the API (POST /api/v1/calendars) and its booking page shows here, ready to share." />;
  return (
    <ul className="cl-cards">
      {list.map((c) => (
        <li key={c.id} className="cl-card">
          <div>
            <h3>{c.name}</h3>
            <p>
              {KIND[c.kind]}, {c.durations.map((d) => `${d} min`).join(" or ")}
              {c.status !== "active" && <> &middot; {c.status === "paused" ? "Paused" : "Archived"}</>}
            </p>
            {c.public_url && <code>{c.public_url}</code>}
          </div>
          {c.public_url && (
            <div className="cl-card-actions">
              <Button size="sm" onClick={() => void copy(c)} aria-label={`Copy the link to ${c.name}`}>
                <Copy size={14} aria-hidden />
                Copy link
              </Button>
              <a className="ui-btn" data-variant="ghost" data-size="sm" href={c.public_url} target="_blank" rel="noopener noreferrer" aria-label={`Open ${c.name} in a new tab`}>
                <ExternalLink size={14} aria-hidden />
                Open
              </a>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}
