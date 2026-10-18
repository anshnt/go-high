// The public booking API (no sign in). Every failure is an ApiFailure, so the screens handle one kind of error.
import type { Booked, BookingView, CalendarInfo, NewBooking, SlotsQuery, SlotsResponse } from "./types.ts";

export class ApiFailure extends Error {
  status: number;
  code: string;
  fields: Record<string, string>;
  retryAfter: number | null;

  constructor(status: number, code: string, message: string, fields: Record<string, string> = {}, retryAfter: number | null = null) {
    super(message);
    this.status = status;
    this.code = code;
    this.fields = fields;
    this.retryAfter = retryAfter;
  }
}

/** Reads an error answer ({"error": {code, message, fields?}}) into an ApiFailure; anything else is a generic failure. */
export function failureOf(status: number, body: unknown, retryAfter: string | null = null): ApiFailure {
  const e = (body as { error?: { code?: string; message?: string; fields?: Record<string, string> } } | null)?.error;
  const seconds = retryAfter && Number.isFinite(Number(retryAfter)) ? Number(retryAfter) : null;
  return new ApiFailure(status, e?.code ?? `http_${status}`, e?.message ?? "Something went wrong", e?.fields ?? {}, seconds);
}

export interface Api {
  calendar(ws: string, cal: string): Promise<CalendarInfo>;
  slots(ws: string, cal: string, q: SlotsQuery): Promise<SlotsResponse>;
  book(ws: string, cal: string, body: NewBooking): Promise<Booked>;
  booking(token: string): Promise<BookingView>;
  bookingSlots(token: string, q: SlotsQuery): Promise<SlotsResponse>;
  cancel(token: string, reason: string): Promise<BookingView>;
  reschedule(token: string, start: string, zone: string): Promise<BookingView>;
  url(path: string): string;
}

const enc = encodeURIComponent;

/** `origin` is "" when the page is served by the API itself, and the API's origin when embedded in another site. */
export function createApi(origin: string): Api {
  async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
    let res: Response;
    try {
      res = await fetch(`${origin}/api/public${path}`, {
        method,
        headers: body === undefined ? undefined : { "Content-Type": "application/json" },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch {
      throw new ApiFailure(0, "network", "Could not reach the server");
    }
    const data: unknown = await res.json().catch(() => null);
    if (!res.ok) throw failureOf(res.status, data, res.headers.get("Retry-After"));
    return data as T;
  }
  const query = (q: SlotsQuery, withDuration: boolean) =>
    `?from=${q.from}&to=${q.to}&tz=${enc(q.tz)}${withDuration ? `&duration=${q.duration}` : ""}`;
  const cal = (ws: string, c: string) => `/calendars/${enc(ws)}/${enc(c)}`;
  return {
    calendar: (ws, c) => call("GET", cal(ws, c)),
    slots: (ws, c, q) => call("GET", `${cal(ws, c)}/slots${query(q, true)}`),
    book: (ws, c, body) => call("POST", `${cal(ws, c)}/bookings`, body),
    booking: (token) => call("GET", `/bookings/${enc(token)}`),
    // moving a booking keeps its length, so the duration is not sent
    bookingSlots: (token, q) => call("GET", `/bookings/${enc(token)}/slots${query(q, false)}`),
    cancel: (token, reason) => call("POST", `/bookings/${enc(token)}/cancel`, reason ? { reason } : {}),
    reschedule: (token, start, zone) => call("POST", `/bookings/${enc(token)}/reschedule`, { start, time_zone: zone }),
    url: (path) => `${origin}${path}`,
  };
}
