// The words of the page that depend on data: lengths, places, statuses, what to say when a change is closed.
import type { ApiFailure } from "./api.ts";
import type { BookingStatus, BookingView, Location } from "./types.ts";

export function durationLabel(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${m} min`;
  return m ? `${h} hr ${m} min` : h === 1 ? "1 hour" : `${h} hours`;
}

/** What a place is called and, where there is one, the detail (a web link, a number, an address). */
export function locationText(loc: Partial<Location> | undefined): { title: string; detail: string } | null {
  if (!loc?.kind) return null;
  const value = (loc.value ?? "").trim();
  switch (loc.kind) {
    case "video":
      return { title: "Video call", detail: value };
    case "phone":
      return { title: "Phone call", detail: value };
    case "in_person":
      return { title: "In person", detail: value };
    default:
      return { title: value || "To be agreed", detail: "" };
  }
}

export const isWebLink = (s: string) => /^https?:\/\/\S+$/.test(s);

export const STATUS: Record<BookingStatus, { text: string; tone: "success" | "warning" | "info" | "danger" | "neutral" }> = {
  confirmed: { text: "Confirmed", tone: "success" },
  booked: { text: "Awaiting confirmation", tone: "warning" },
  rescheduled: { text: "Rescheduled", tone: "info" },
  cancelled: { text: "Cancelled", tone: "danger" },
  showed: { text: "Attended", tone: "neutral" },
  no_show: { text: "Missed", tone: "neutral" },
};

/** The heading once a booking is made: a request when the host still has to confirm. */
export const bookedHeading = (status: BookingStatus) => (status === "booked" ? "Request received, we will confirm it" : "You are booked");

/** Why a booking cannot be changed online, or null when it can. */
export function lockedReason(b: BookingView, now: Date = new Date()): string | null {
  if (b.can_change) return null;
  if (b.status === "cancelled") return "This booking was cancelled.";
  if (b.status === "showed" || b.status === "no_show" || new Date(b.starts_at) <= now) return "This booking has already happened.";
  return "This booking can no longer be changed online, please get in touch.";
}

export function retryText(seconds: number | null): string {
  if (!seconds) return "Too many booking requests, please try again in a few minutes.";
  const minutes = Math.ceil(seconds / 60);
  return seconds < 90
    ? `Too many booking requests, please try again in ${seconds} seconds.`
    : `Too many booking requests, please try again in ${minutes} minutes (${seconds} seconds).`;
}

/** A calm sentence for a failure that has no screen of its own. */
export function failureText(e: ApiFailure): string {
  if (e.status === 0) return "Could not reach the server. Check your connection and try again.";
  if (e.status === 429) return retryText(e.retryAfter);
  if (e.code === "slot_unavailable") return "That time was just taken, please pick another.";
  if (e.code === "change_closed") return "This booking can no longer be changed online, please get in touch.";
  return "Something went wrong, please try again.";
}
