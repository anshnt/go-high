import assert from "node:assert/strict";
import { test } from "node:test";
import { ApiFailure, failureOf } from "../src/book/api.ts";
import { askedFields, bookingBody, isEmail, sentence, serverErrors, validate } from "../src/book/form.ts";
import type { Values } from "../src/book/form.ts";
import { bookedHeading, durationLabel, failureText, isWebLink, locationText, lockedReason, retryText } from "../src/book/text.ts";
import type { BookingView, Question } from "../src/book/types.ts";

const q = (key: string, extra: Partial<Question> = {}): Question => ({ key, label: key, type: "text", required: false, options: [], ...extra });
const asked: Question[] = [
  q("name", { label: "Name", required: true }),
  q("email", { label: "Email", type: "email", required: true }),
  q("phone", { label: "Phone", type: "phone", required: false }),
  q("company", { label: "Company", required: true }),
  q("size", { label: "Team size", type: "select", options: ["1-10", "11-50"] }),
  q("notes", { label: "Anything to add?", type: "long_text" }),
];
const values = (over: Partial<Values> = {}, answers: Record<string, string> = {}): Values => ({
  name: "Ada Lovelace", email: "ada@example.com", phone: "", website: "", answers: { company: "Analytical Engines", ...answers }, ...over,
});

test("fields: name, email and phone come first, then your own, and a missing built-in is asked as required", () => {
  const jumbled = [q("company", { required: true }), q("phone", { type: "phone" }), q("email", { type: "email", required: true }), q("name", { required: true })];
  assert.deepEqual(askedFields(jumbled).map((f) => f.key), ["name", "email", "phone", "company"]);
  const bare = askedFields([]);
  assert.deepEqual(bare.map((f) => [f.key, f.required]), [["name", true], ["email", true], ["phone", true]]);
});

test("validation: required fields and the shape of an email", () => {
  assert.deepEqual(validate(asked, values()), {});
  assert.deepEqual(validate(asked, values({ name: "  ", email: "" }, { company: "" })), {
    name: "Enter your name",
    email: "Enter your email address",
    "answers.company": "This field is required",
  });
  assert.deepEqual(validate(asked, values({ email: "ada@" })), { email: "Enter a valid email address" });
  assert.deepEqual(validate(asked, values({ email: "ada lovelace@example.com" })), { email: "Enter a valid email address" });
  assert.ok(isEmail(" ada@example.com ") && isEmail("a.b+c@sub.example.co.uk") && !isEmail("a@b") && !isEmail("@b.co"));
});

test("validation: an optional phone may be empty, a required one may not, and a select needs a real option", () => {
  assert.deepEqual(validate(asked, values({ phone: "" })), {});
  const needsPhone = asked.map((f) => (f.key === "phone" ? { ...f, required: true } : f));
  assert.deepEqual(validate(needsPhone, values({ phone: "" })), { phone: "Enter your phone number" });
  assert.deepEqual(validate(asked, values({}, { size: "500" })), { "answers.size": "Choose one of the options" });
  assert.deepEqual(validate(asked, values({}, { size: "11-50" })), {});
  const needsSize = asked.map((f) => (f.key === "size" ? { ...f, required: true } : f));
  assert.deepEqual(validate(needsSize, values()), { "answers.size": "Choose an option" });
});

test("the request: trimmed, custom answers only, phone and location only when there are some, honeypot carried", () => {
  const pick = { start: "2026-11-03T14:00:00+00:00", duration: 30, zone: "Europe/London" };
  const body = bookingBody(asked, values({ name: " Ada ", phone: " +14155550123 ", website: "" }, { notes: "  hello ", size: "" }), pick, "video");
  assert.deepEqual(body, {
    start: "2026-11-03T14:00:00+00:00", duration: 30, time_zone: "Europe/London", name: "Ada", email: "ada@example.com",
    phone: "+14155550123", answers: { company: "Analytical Engines", notes: "hello" }, location: "video", website: "",
  });
  const lean = bookingBody(asked, values(), pick);
  assert.ok(!("phone" in lean) && !("location" in lean));
  assert.equal(bookingBody(asked, values({ website: "http://spam.example" }), pick).website, "http://spam.example");
});

test("server complaints land on the right field and the rest are listed once", () => {
  const raw = {
    email: "Email is not a valid email address",
    phone: "is required",
    "answers.company": "is required",
    "answers.size": "is not one of the options",
    time_zone: "is not a time zone",
    duration: "is not offered",
    location: "is not offered",
    start: "Input should be a valid datetime",
  };
  const { byField, other } = serverErrors(asked, raw, ["location"]);
  assert.deepEqual(byField, {
    email: "Email is not a valid email address",
    phone: "Phone is required",
    "answers.company": "Company is required",
    "answers.size": "Team size is not one of the options",
    location: "Location is not offered",
  });
  assert.deepEqual(other, ["Time zone is not a time zone", "Length is not offered", "Input should be a valid datetime"]);
  assert.equal(sentence("Phone", "is required"), "Phone is required");
  assert.equal(sentence("Phone", "must be a number"), "Must be a number");
});

test("api failures read the error envelope, and fall back on anything else", () => {
  const e = failureOf(422, { error: { code: "validation_failed", message: "Some details are missing or wrong", fields: { phone: "is required" } } });
  assert.deepEqual([e.status, e.code, e.fields, e.retryAfter], [422, "validation_failed", { phone: "is required" }, null]);
  const limited = failureOf(429, { error: { code: "rate_limited", message: "Too many" } }, "600");
  assert.equal(limited.retryAfter, 600);
  const odd = failureOf(502, "<html>bad gateway</html>");
  assert.deepEqual([odd.code, odd.message, odd.fields], ["http_502", "Something went wrong", {}]);
  assert.equal(failureOf(500, null, "soon").retryAfter, null);
});

test("words: lengths, places, headings and the rate limit text", () => {
  assert.deepEqual([30, 45, 60, 90, 120].map(durationLabel), ["30 min", "45 min", "1 hour", "1 hr 30 min", "2 hours"]);
  assert.deepEqual(locationText({ kind: "video", value: "https://meet.example.com/x" }), { title: "Video call", detail: "https://meet.example.com/x" });
  assert.deepEqual(locationText({ kind: "phone", value: "" }), { title: "Phone call", detail: "" });
  assert.deepEqual(locationText({ kind: "in_person", value: "1 Main St" }), { title: "In person", detail: "1 Main St" });
  assert.deepEqual(locationText({ kind: "custom", value: "At the park" }), { title: "At the park", detail: "" });
  assert.deepEqual(locationText({ kind: "custom", value: "" }), { title: "To be agreed", detail: "" });
  assert.equal(locationText({}), null);
  assert.equal(locationText(undefined), null);
  assert.ok(isWebLink("https://meet.example.com/x") && !isWebLink("javascript:alert(1)") && !isWebLink("meet.example.com"));
  assert.equal(bookedHeading("confirmed"), "You are booked");
  assert.equal(bookedHeading("booked"), "Request received, we will confirm it");
  assert.equal(retryText(45), "Too many booking requests, please try again in 45 seconds.");
  assert.equal(retryText(600), "Too many booking requests, please try again in 10 minutes (600 seconds).");
  assert.match(retryText(null), /few minutes/);
  assert.match(failureText(new ApiFailure(429, "rate_limited", "x", {}, 600)), /600 seconds/);
  assert.match(failureText(new ApiFailure(409, "slot_unavailable", "x")), /just taken/);
  assert.match(failureText(new ApiFailure(0, "network", "x")), /Could not reach/);
  assert.match(failureText(new ApiFailure(500, "http_500", "x")), /try again/);
});

test("a booking that cannot be changed says why", () => {
  const view = (over: Partial<BookingView>): BookingView => ({
    status: "confirmed", starts_at: "2026-11-03T14:00:00+00:00", ends_at: "2026-11-03T14:30:00+00:00", time_zone: "UTC",
    calendar: { name: "Call", description: "", time_zone: "UTC", color: "indigo", business: "Acme", durations: [30] },
    location: {}, invitee: { name: "Ada" }, can_change: true, change_until: null, ics_path: "/x", confirmation: "auto", ...over,
  });
  const before = new Date("2026-11-01T00:00:00Z");
  assert.equal(lockedReason(view({}), before), null);
  assert.match(lockedReason(view({ can_change: false, status: "cancelled" }), before)!, /cancelled/);
  assert.match(lockedReason(view({ can_change: false }), new Date("2026-11-04T00:00:00Z"))!, /already happened/);
  assert.match(lockedReason(view({ can_change: false, status: "showed" }), before)!, /already happened/);
  assert.match(lockedReason(view({ can_change: false, change_until: "2026-11-02T14:00:00+00:00" }), before)!, /can no longer be changed online, please get in touch/);
});
