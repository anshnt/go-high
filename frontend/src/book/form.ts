// The details form without the DOM: which fields to ask, what is wrong with them, what to send, and where a server
// complaint belongs. Pure, so node can test it.
import type { LocationKind, NewBooking, Question } from "./types.ts";

export interface Values {
  name: string;
  email: string;
  phone: string;
  website: string; // the honeypot
  answers: Record<string, string>;
}

export const BUILT_IN = ["name", "email", "phone"];
const BASE: Record<string, Question> = {
  name: { key: "name", label: "Name", type: "text", required: true, options: [] },
  email: { key: "email", label: "Email", type: "email", required: true, options: [] },
  phone: { key: "phone", label: "Phone", type: "phone", required: true, options: [] },
};

export const isEmail = (s: string) => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(s.trim());

/** Name, email, phone in that order (the API always has them; a missing one is asked as the API would require it), then your own. */
export function askedFields(questions: Question[]): Question[] {
  const own = questions.filter((q) => !BUILT_IN.includes(q.key));
  return [...BUILT_IN.map((k) => questions.find((q) => q.key === k) ?? BASE[k]), ...own];
}

const REQUIRED: Record<string, string> = { name: "Enter your name", email: "Enter your email address", phone: "Enter your phone number" };

export const fieldId = (key: string) => (BUILT_IN.includes(key) ? key : `answers.${key}`);

function valueOf(v: Values, key: string): string {
  return (BUILT_IN.includes(key) ? (v as unknown as Record<string, string>)[key] : v.answers[key] ?? "").trim();
}

/** Messages by field id ("name", "email", "phone", "answers.<key>") for what is missing or wrong. Empty when all is well. */
export function validate(fields: Question[], v: Values): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const q of fields) {
    const value = valueOf(v, q.key);
    const id = fieldId(q.key);
    if (!value) {
      if (q.required) errors[id] = REQUIRED[q.key] ?? (q.type === "select" ? "Choose an option" : "This field is required");
    } else if (q.type === "email" && !isEmail(value)) errors[id] = "Enter a valid email address";
    else if (q.type === "select" && !q.options.includes(value)) errors[id] = "Choose one of the options";
  }
  return errors;
}

const NAMES: Record<string, string> = { time_zone: "Time zone", duration: "Length", start: "Time", location: "Location" };

/** The server says "is required", or "Email is not valid", or a bare reason: make each a sentence. */
export function sentence(label: string, message: string): string {
  const text = /^(is|are)\b/.test(message) ? `${label} ${message}` : message;
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** Splits the 422 `fields` into messages for fields on the form and the rest (time zone, length, time), to show once. */
export function serverErrors(
  fields: Question[],
  raw: Record<string, string>,
  onForm: string[] = [],
): { byField: Record<string, string>; other: string[] } {
  const label = (id: string) => (id.startsWith("answers.") || BUILT_IN.includes(id) ? (fields.find((q) => fieldId(q.key) === id)?.label ?? id) : (NAMES[id] ?? id));
  const known = new Set([...fields.map((q) => fieldId(q.key)), ...onForm]);
  const byField: Record<string, string> = {};
  const other: string[] = [];
  for (const [id, message] of Object.entries(raw)) {
    if (known.has(id)) byField[id] = sentence(label(id), message);
    else other.push(sentence(label(id), message));
  }
  return { byField, other };
}

/** The request for a new booking: only your own questions go in `answers`, empty ones left out. */
export function bookingBody(
  fields: Question[],
  v: Values,
  pick: { start: string; duration: number; zone: string },
  location?: LocationKind,
): NewBooking {
  const answers: Record<string, string> = {};
  for (const q of fields) {
    const value = BUILT_IN.includes(q.key) ? "" : valueOf(v, q.key);
    if (value) answers[q.key] = value;
  }
  const phone = v.phone.trim();
  return {
    start: pick.start,
    duration: pick.duration,
    time_zone: pick.zone,
    name: v.name.trim(),
    email: v.email.trim(),
    ...(phone ? { phone } : {}),
    answers,
    ...(location ? { location } : {}),
    website: v.website,
  };
}
