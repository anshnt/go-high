import { api, queryString } from "./api";
import type { Hours } from "../calendar/layout";
import { memory } from "./store";

// The calendars API for signed-in people (backend/app/calendars/routes.py and bookings.py).

export type BookingStatus = "booked" | "confirmed" | "rescheduled" | "cancelled" | "showed" | "no_show";
export type CalendarItem = {
  id: string;
  name: string;
  slug: string;
  kind: "personal" | "round_robin" | "collective" | "class" | "service";
  durations: number[];
  status: "active" | "paused" | "archived";
  color: string;
  public_path: string | null;
  public_url: string | null;
};
export type Booking = {
  id: string;
  status: BookingStatus;
  starts_at: string;
  ends_at: string;
  time_zone: string;
  calendar: { id: string; name: string; kind: string; color: string };
  host: { user_id: string | null; name: string | null };
  contact: { id: string; display_name: string } | null;
  // null when the role may not read that field of contacts
  invitee: { name: string | null; email: string | null; phone: string | null };
  location: { kind?: string; value?: string };
  answers: Record<string, { label: string; value: string }>;
  cancel_reason: string | null;
};

const PAGE = 500;
const MAX_PAGES = 4; // ponytail: a week holds at most 2000 bookings on screen; page on scroll past that

/** Every booking that overlaps [from, to), by start. */
export async function listBookings(from: string, to: string): Promise<Booking[]> {
  const all: Booking[] = [];
  let cursor: string | undefined;
  for (let page = 0; page < MAX_PAGES; page++) {
    const res = await api.get<{ data: Booking[]; next_cursor: string | null }>(`/api/v1/bookings${queryString({ from, to, limit: PAGE, cursor })}`);
    all.push(...res.data);
    if (!res.next_cursor) break;
    cursor = res.next_cursor;
  }
  return all;
}

export const listCalendars = () => api.get<{ data: CalendarItem[] }>("/api/v1/calendars").then((r) => r.data);
export const cancelBooking = (id: string, reason: string) => api.post<Booking>(`/api/v1/bookings/${id}/cancel`, reason ? { reason } : {});
export const markBooking = (id: string, status: "confirmed" | "showed" | "no_show") => api.post<Booking>(`/api/v1/bookings/${id}/status`, { status });
export const myHours = (userId: string) => api.get<Hours>(`/api/v1/availability/users/${userId}`);

/** Bumped after a change to a booking, so the open week loads again. */
export const bookingsVersion = memory(0);

export const STATUS: Record<BookingStatus, { label: string; tone: "neutral" | "accent" | "success" | "warning" | "danger" | "info" }> = {
  booked: { label: "Awaiting confirmation", tone: "warning" },
  confirmed: { label: "Confirmed", tone: "success" },
  rescheduled: { label: "Rescheduled", tone: "info" },
  cancelled: { label: "Cancelled", tone: "danger" },
  showed: { label: "Showed", tone: "neutral" },
  no_show: { label: "No-show", tone: "neutral" },
};

export const KIND: Record<CalendarItem["kind"], string> = {
  personal: "One person",
  round_robin: "Round robin",
  collective: "Collective",
  class: "Class",
  service: "Service",
};
