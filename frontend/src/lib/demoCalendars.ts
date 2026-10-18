import { addDays, browserZone, dateKey, weekdayOf, zonedToUtc } from "../calendar/time";
import { usualWeek } from "../calendar/hours";
import type { Booking, BookingStatus, CalendarItem } from "./calendars";
import { DemoMiss } from "./demoTasks";

// The public demo (VITE_DEMO=1): two booking pages and a week of fictional bookings around today, in memory. Cancelling
// and marking work until the page is reloaded.

const calendars: CalendarItem[] = [
  { id: "demo-cal-1", name: "Intro call", slug: "intro-call", kind: "personal", durations: [30], status: "active", color: "indigo",
    public_path: "/book/acme-demo/intro-call", public_url: "https://app.go-high.example/book/acme-demo/intro-call" },
  { id: "demo-cal-2", name: "Sales demo", slug: "sales-demo", kind: "round_robin", durations: [30, 60], status: "active", color: "green",
    public_path: "/book/acme-demo/sales-demo", public_url: "https://app.go-high.example/book/acme-demo/sales-demo" },
];

// [weekday from Monday, start, minutes, calendar, invitee, status]
const PLAN: [number, string, number, number, string, BookingStatus][] = [
  [0, "09:30", 30, 0, "Maya Chen", "showed"],
  [0, "11:00", 60, 1, "Jordan Blake", "confirmed"],
  [1, "10:00", 30, 0, "Priya Natarajan", "no_show"],
  [1, "10:00", 60, 1, "Sam Ortega", "confirmed"],
  [2, "14:00", 30, 0, "Lena Fischer", "confirmed"],
  [3, "09:00", 30, 0, "Omar Haddad", "booked"],
  [3, "13:30", 60, 1, "Chloe Martin", "rescheduled"],
  [4, "15:00", 30, 0, "Diego Alvarez", "cancelled"],
  [4, "16:00", 30, 0, "Hana Sato", "confirmed"],
];

let bookings: Booking[] | null = null;

function seed(): Booking[] {
  const zone = browserZone();
  const today = dateKey(Date.now(), zone);
  const monday = addDays(today, -weekdayOf(today));
  return PLAN.map(([day, time, minutes, cal, name, status], i): Booking => {
    const start = zonedToUtc(addDays(monday, day), time, zone);
    const c = calendars[cal]!;
    return {
      id: `demo-booking-${i + 1}`,
      status,
      starts_at: new Date(start).toISOString(),
      ends_at: new Date(start + minutes * 60_000).toISOString(),
      time_zone: zone,
      calendar: { id: c.id, name: c.name, kind: c.kind, color: c.color },
      host: { user_id: "demo-user", name: "Alex Rivera" },
      contact: null,
      invitee: { name, email: `${name.split(" ")[0]!.toLowerCase()}@example.com`, phone: null },
      location: { kind: "video", value: "https://meet.example.com/acme" },
      answers: cal === 1 ? { size: { label: "Team size", value: "11-50" } } : {},
      cancel_reason: status === "cancelled" ? "Something came up" : null,
    };
  });
}

/** The answer for a calendars call, or undefined when the path is not one of them. */
export function demoCalendars(method: string, path: string, body: unknown): unknown {
  const [route, search = ""] = path.split("?");
  const q = new URLSearchParams(search);
  bookings ??= seed();
  if (method === "GET" && route === "/api/v1/calendars") return { data: structuredClone(calendars), next_cursor: null };
  if (method === "GET" && route === "/api/v1/bookings") {
    const from = Date.parse(q.get("from") ?? "") || -Infinity;
    const to = Date.parse(q.get("to") ?? "") || Infinity;
    const data = bookings.filter((b) => Date.parse(b.ends_at) > from && Date.parse(b.starts_at) < to);
    return { data: structuredClone(data), next_cursor: null };
  }
  if (method === "GET" && route?.startsWith("/api/v1/availability/users/")) {
    return { owner: "users", id: route.split("/").pop(), saved: false, time_zone: browserZone(), weekly: usualWeek(), overrides: {} };
  }
  const m = /^\/api\/v1\/bookings\/([^/]+)\/(cancel|status)$/.exec(route ?? "");
  if (method === "POST" && m) {
    const b = bookings.find((x) => x.id === m[1]);
    if (!b) throw new DemoMiss(404, "Booking not found");
    const input = (body ?? {}) as { reason?: string; status?: BookingStatus };
    if (m[2] === "cancel") Object.assign(b, { status: "cancelled", cancel_reason: input.reason ?? null });
    else if (input.status) b.status = input.status;
    return structuredClone(b);
  }
  return undefined;
}
