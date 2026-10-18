// What the public booking API sends and takes (backend/app/calendars/public.py).

export type LocationKind = "phone" | "video" | "in_person" | "custom";
export type QuestionType = "text" | "long_text" | "select" | "email" | "phone";

export interface Location {
  kind: LocationKind;
  value: string;
}

export interface Question {
  key: string;
  label: string;
  type: QuestionType;
  required: boolean;
  options: string[];
}

export interface CalendarInfo {
  name: string;
  description: string;
  kind: string;
  durations: number[];
  time_zone: string;
  locations: Location[];
  questions: Question[];
  confirmation: "auto" | "manual";
  color: string;
  business: string;
  window_days: number;
  paused: boolean;
  hosts: string[];
}

export interface SlotsResponse {
  time_zone: string;
  duration: number;
  from: string;
  to: string;
  days: Record<string, string[]>;
}

export interface SlotsQuery {
  from: string;
  to: string;
  tz: string;
  duration: number;
}

export type BookingStatus = "booked" | "confirmed" | "rescheduled" | "cancelled" | "showed" | "no_show";

export interface BookingView {
  status: BookingStatus;
  starts_at: string;
  ends_at: string;
  time_zone: string;
  calendar: { name: string; description: string; time_zone: string; color: string; business: string; durations: number[]; window_days: number };
  location: Partial<Location>;
  invitee: { name: string };
  can_change: boolean;
  change_until: string | null;
  ics_path: string;
  confirmation: "auto" | "manual";
}

export interface Booked extends BookingView {
  token: string;
  manage_path: string;
  manage_url: string;
}

export interface NewBooking {
  start: string;
  duration: number;
  time_zone: string;
  name: string;
  email: string;
  phone?: string;
  answers: Record<string, string>;
  location?: LocationKind;
  website: string;
}
