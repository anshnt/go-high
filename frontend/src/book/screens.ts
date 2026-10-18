// The two flows of the page: booking a time on a calendar (/book/ws/cal) and seeing, moving or cancelling a booking from
// its link (/booking/token). Each screen replaces the last one and moves focus to its heading, so a screen reader hears
// where it is; what changes without a new screen is said through the live region (ctx.say).
import { ApiFailure } from "./api.ts";
import { h, icon, uid } from "./dom.ts";
import type { Ctx } from "./dom.ts";
import { askedFields, bookingBody, fieldId, serverErrors, validate } from "./form.ts";
import type { Values } from "./form.ts";
import { createPicker } from "./picker.ts";
import type { Pick } from "./picker.ts";
import { STATUS, bookedHeading, durationLabel, failureText, isWebLink, locationText, lockedReason } from "./text.ts";
import type { Booked, BookingView, CalendarInfo, Location, LocationKind, Question } from "./types.ts";
import { detectZone, formatDate, formatTime, zoneName } from "./zones.ts";

/** Shows a screen; focus goes to its heading unless this is the first one (a widget must not pull the host page around). */
function show(ctx: Ctx, view: HTMLElement, focus = true) {
  ctx.root.replaceChildren(view);
  if (focus) view.querySelector<HTMLElement>("h1, h2")?.focus();
}

const heading = (text: string, level: "h1" | "h2" = "h1") => h(level, { class: "gh-title", tabindex: -1 }, text);

function loading(ctx: Ctx) {
  ctx.root.replaceChildren(h("p", { class: "gh-hint", role: "status" }, icon("spin", 14), " Loading..."));
}

function problem(ctx: Ctx, title: string, text: string) {
  ctx.title(title);
  show(ctx, h("div", { class: "gh-stack", role: "alert" }, h("span", { class: "gh-done-icon" }, icon("alert", 22)), heading(title), h("p", { class: "gh-hint" }, text)), false);
}

const asFailure = (e: unknown) => (e instanceof ApiFailure ? e : new ApiFailure(0, "unknown", "Something went wrong"));

/** "Tuesday, 3 November 2026" and "2:00 PM to 2:30 PM (Europe/London)". */
function whenLines(start: string, end: string, zone: string): [string, string] {
  return [formatDate(start, zone), `${formatTime(start, zone)} to ${formatTime(end, zone)} (${zoneName(zone)})`];
}

const plusMinutes = (iso: string, minutes: number) => new Date(new Date(iso).getTime() + minutes * 60000).toISOString();

function placeNode(loc: Partial<Location> | undefined): HTMLElement | null {
  const text = locationText(loc);
  if (!text) return null;
  const detail = text.detail ? (isWebLink(text.detail) ? h("a", { href: text.detail, target: "_blank", rel: "noopener noreferrer" }, text.detail) : text.detail) : null;
  const kind = loc?.kind === "video" ? "video" : loc?.kind === "phone" ? "phone" : "pin";
  return h("div", null, icon(kind), h("div", null, h("div", null, text.title), detail && h("div", { class: "gh-hint" }, detail)));
}

function calendarHead(info: CalendarInfo): HTMLElement {
  const places = [...new Set(info.locations.map((l) => locationText(l)?.title).filter(Boolean))];
  return h(
    "header",
    { class: "gh-head" },
    h("p", { class: "gh-business" }, info.business),
    heading(info.name),
    h(
      "p",
      { class: "gh-meta" },
      h("span", null, icon("clock", 15), info.durations.map(durationLabel).join(" or ")),
      places.length > 0 && h("span", null, icon(info.locations[0].kind === "video" ? "video" : info.locations[0].kind === "phone" ? "phone" : "pin", 15), places.join(" or ")),
      info.hosts.length > 0 && h("span", null, icon(info.hosts.length > 1 ? "users" : "user", 15), info.hosts.join(", ")),
    ),
    info.description && h("p", { class: "gh-desc" }, info.description),
  );
}

function backButton(text: string, run: () => void) {
  return h("button", { type: "button", class: "gh-back", onclick: run }, icon("left", 16), text);
}

/** A labelled control for one question, with its error line wired up for screen readers. */
function control(q: Question, errorId: string): HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement {
  const common = { id: uid("gh-f"), name: fieldId(q.key), class: "gh-input", required: q.required, "aria-describedby": errorId };
  if (q.type === "long_text") return h("textarea", { ...common, maxlength: 5000, rows: 4 });
  if (q.type === "select") {
    return h("select", common, h("option", { value: "" }, q.required ? "Choose..." : "None"), ...q.options.map((o) => h("option", { value: o }, o)));
  }
  const auto: Record<string, string> = { name: "name", email: "email", phone: "tel" };
  const type = q.type === "email" ? "email" : q.type === "phone" ? "tel" : "text";
  return h("input", { ...common, type, autocomplete: auto[q.key] ?? "off", maxlength: q.key === "phone" ? 40 : q.key === "email" ? 254 : 1000 });
}

// --- booking a time ---------------------------------------------------------------------------------------------

export async function bookFlow(ctx: Ctx, ws: string, cal: string) {
  loading(ctx);
  let info: CalendarInfo;
  try {
    info = await ctx.api.calendar(ws, cal);
  } catch (e) {
    const f = asFailure(e);
    if (f.status === 404) return problem(ctx, "Page not found", "This booking page does not exist. Check the link you were given.");
    return problem(ctx, "Could not load", failureText(f));
  }
  ctx.title(`${info.name} | ${info.business}`);
  if (info.paused) {
    return show(ctx, h("div", null, calendarHead(info), h("p", { class: "gh-note", role: "status" }, "This calendar is not taking bookings right now.")), false);
  }

  const notice = h("div", { class: "gh-alert", role: "alert" });
  const picker = createPicker({ ctx, durations: info.durations, windowDays: info.window_days, load: (q) => ctx.api.slots(ws, cal, q), onPick: details });
  const pickScreen = h("div", { class: "gh-stack" }, calendarHead(info), notice, picker.el);
  show(ctx, pickScreen, false);

  function backToPicker(pick: Pick, message = "") {
    notice.textContent = message;
    show(ctx, pickScreen, false);
    if (message) picker.refresh();
    else picker.focusTime(pick.start);
  }

  function details(pick: Pick) {
    notice.textContent = "";
    const fields = askedFields(info.questions);
    const end = plusMinutes(pick.start, pick.duration);
    const [day, time] = whenLines(pick.start, end, pick.zone);
    const inputs = new Map<string, HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>();
    const errors = new Map<string, HTMLElement>();
    const alert = h("div", { class: "gh-alert", role: "alert" });
    const honeypot = h("input", { name: "website", tabindex: -1, autocomplete: "off" });

    const rows = fields.map((q) => {
      const errorId = uid("gh-err");
      const input = control(q, errorId);
      const error = h("p", { class: "gh-error", id: errorId });
      inputs.set(fieldId(q.key), input);
      errors.set(fieldId(q.key), error);
      const label = h("label", { class: "gh-label", for: input.id }, q.label, q.required && h("span", { class: "gh-req", "aria-hidden": "true" }, " *"));
      return h("div", { class: "gh-field" }, label, input, error);
    });

    // a choice of place only when there is more than one; the first is the default
    let place: LocationKind | undefined = info.locations[0]?.kind;
    const kinds = [...new Set(info.locations.map((l) => l.kind))];
    const locationError = h("p", { class: "gh-error", id: uid("gh-err") });
    errors.set("location", locationError);
    const placeRow =
      kinds.length > 1 &&
      h(
        "fieldset",
        { class: "gh-field", "aria-describedby": locationError.id },
        h("legend", { class: "gh-label" }, "Where"),
        h(
          "div",
          { class: "gh-choices" },
          ...kinds.map((kind, i) => {
            const loc = info.locations.find((l) => l.kind === kind);
            return h("label", { class: "gh-choice" }, h("input", { type: "radio", name: "location", value: kind, checked: i === 0, onchange: () => (place = kind) }), locationText(loc)?.title ?? kind);
          }),
        ),
        locationError,
      );

    const manual = info.confirmation === "manual";
    const submit = h("button", { type: "submit", class: "gh-btn gh-primary" }, manual ? "Request booking" : "Confirm booking");
    const form = h(
      "form",
      { class: "gh-form", novalidate: true, onsubmit: (e: Event) => void send(e) },
      ...rows,
      placeRow,
      h("div", { class: "gh-hp", "aria-hidden": "true" }, h("label", null, "Website", honeypot)),
      alert,
      h("div", { class: "gh-actions" }, submit),
    );

    const screen = h(
      "div",
      { class: "gh-stack" },
      backButton("Pick another time", () => backToPicker(pick)),
      heading("Your details", "h2"),
      h("div", { class: "gh-when" }, h("strong", null, info.name), h("span", null, day), h("span", null, `${time}, ${durationLabel(pick.duration)}`)),
      form,
    );
    show(ctx, screen);

    function showErrors(byField: Record<string, string>, other: string[] = []) {
      for (const [id, el] of errors) {
        el.textContent = byField[id] ?? "";
        inputs.get(id)?.setAttribute("aria-invalid", String(Boolean(byField[id])));
      }
      const count = Object.keys(byField).length;
      alert.replaceChildren(...[...other, count ? `Check the ${count === 1 ? "highlighted field" : `${count} highlighted fields`}.` : ""].filter(Boolean).map((t) => h("p", null, t)));
      const first = [...inputs.keys()].find((id) => byField[id]);
      if (first) inputs.get(first)?.focus();
    }

    async function send(e: Event) {
      e.preventDefault();
      if (submit.disabled) return;
      const value = (id: string) => inputs.get(id)?.value ?? "";
      const answers: Record<string, string> = {};
      for (const q of fields) if (!["name", "email", "phone"].includes(q.key)) answers[q.key] = value(fieldId(q.key));
      const values: Values = { name: value("name"), email: value("email"), phone: value("phone"), website: honeypot.value, answers };
      const wrong = validate(fields, values);
      if (Object.keys(wrong).length) return showErrors(wrong);
      showErrors({});
      submit.disabled = true;
      submit.replaceChildren(icon("spin", 16), manual ? "Requesting..." : "Booking...");
      try {
        const done = await ctx.api.book(ws, cal, bookingBody(fields, values, pick, kinds.length > 1 ? place : undefined));
        confirmation(done);
      } catch (err) {
        const f = asFailure(err);
        submit.disabled = false;
        submit.replaceChildren(manual ? "Request booking" : "Confirm booking");
        if (f.code === "slot_unavailable") return backToPicker(pick, failureText(f));
        if (f.status === 422 && Object.keys(f.fields).length) {
          const { byField, other } = serverErrors(fields, f.fields, ["location"]);
          return showErrors(byField, other);
        }
        showErrors({}, [f.status === 422 ? f.message : failureText(f)]);
      }
    }
  }

  function confirmation(b: Booked) {
    const zone = b.time_zone || detectZone();
    const [day, time] = whenLines(b.starts_at, b.ends_at, zone);
    const manage = ctx.embed ? ctx.api.url(b.manage_path) : new URL(b.manage_path, location.href).href;
    const linkBox = h("input", { class: "gh-input", readonly: true, value: manage, "aria-label": "Your booking link" });
    const copy = h("button", { type: "button", class: "gh-btn gh-icon-btn", "aria-label": "Copy the booking link", onclick: () => void copyLink() }, icon("copy", 16));
    async function copyLink() {
      try {
        await navigator.clipboard.writeText(manage);
        ctx.say("Link copied");
        copy.replaceChildren(icon("tick", 16));
      } catch {
        linkBox.select();
        ctx.say("Select the link and copy it");
      }
    }
    ctx.title(`${bookedHeading(b.status)} | ${info.business}`);
    show(
      ctx,
      h(
        "div",
        { class: "gh-stack gh-done" },
        h("span", { class: "gh-done-icon" }, icon("check", 26)),
        heading(bookedHeading(b.status)),
        h("p", { class: "gh-hint" }, b.status === "booked" ? `${info.business} will confirm your time.` : `We have booked you in with ${info.business}.`),
        h(
          "div",
          { class: "gh-facts gh-when" },
          h("div", null, icon("clock"), h("div", null, h("strong", null, info.name), h("div", null, day), h("div", { class: "gh-hint" }, time))),
          placeNode(b.location),
        ),
        h(
          "div",
          { class: "gh-actions" },
          h("a", { class: "gh-btn gh-primary", href: ctx.api.url(b.ics_path), download: "booking.ics" }, icon("plus", 16), "Add to calendar"),
          h("a", { class: "gh-btn", href: manage, target: ctx.embed ? "_blank" : null, rel: "noopener" }, "Manage booking"),
        ),
        h("div", { class: "gh-field", style: "text-align:left" }, h("p", { class: "gh-hint" }, "Keep this link to reschedule or cancel."), h("div", { class: "gh-copy" }, linkBox, copy)),
      ),
    );
  }
}

// --- a booking, from its link -----------------------------------------------------------------------------------

export async function manageFlow(ctx: Ctx, token: string) {
  loading(ctx);
  const zone = detectZone();
  let b: BookingView;
  try {
    b = await ctx.api.booking(token);
  } catch (e) {
    const f = asFailure(e);
    if (f.status === 404) return problem(ctx, "Link not valid", "This booking link is not valid. Check the link in your confirmation.");
    return problem(ctx, "Could not load", failureText(f));
  }
  view(b, "", false);

  function view(current: BookingView, message: string, focus = true) {
    b = current;
    ctx.title(`${b.calendar.name} | ${b.calendar.business}`);
    const status = STATUS[b.status];
    const [day, time] = whenLines(b.starts_at, b.ends_at, zone);
    const locked = lockedReason(b);
    const open = !locked;
    show(
      ctx,
      h(
        "div",
        { class: "gh-stack" },
        h(
          "header",
          { class: "gh-head" },
          h("p", { class: "gh-business" }, b.calendar.business),
          heading(b.calendar.name),
          h("p", { class: "gh-meta" }, h("span", { class: "gh-pill", "data-tone": status.tone }, status.text), h("span", null, icon("user", 15), b.invitee.name)),
        ),
        message && h("p", { class: "gh-note", role: "status" }, message),
        h(
          "div",
          { class: "gh-facts gh-when" },
          h("div", null, icon("clock"), h("div", null, h("strong", { class: b.status === "cancelled" ? "gh-old" : null }, day), h("div", { class: "gh-hint" }, time))),
          placeNode(b.location),
        ),
        locked && b.status !== "cancelled" && locked !== message && h("p", { class: "gh-note" }, locked),
        open && b.change_until && h("p", { class: "gh-hint" }, `You can change this booking online until ${formatDate(b.change_until, zone)}, ${formatTime(b.change_until, zone)}.`),
        h(
          "div",
          { class: "gh-actions" },
          open && h("button", { type: "button", class: "gh-btn gh-primary", onclick: reschedule }, "Reschedule"),
          open && h("button", { type: "button", class: "gh-btn gh-danger", onclick: cancel }, "Cancel booking"),
          b.status !== "cancelled" && h("a", { class: "gh-btn", href: ctx.api.url(b.ics_path), download: "booking.ics" }, icon("plus", 16), "Add to calendar"),
        ),
      ),
      focus,
    );
  }

  /** A change failed: closed (the cutoff passed while the page was open) shows the booking as it now is. */
  async function failed(e: unknown, alert: HTMLElement, retry: () => void) {
    const f = asFailure(e);
    if (f.code === "change_closed" || (f.status === 409 && f.code !== "slot_unavailable")) {
      try {
        return view(await ctx.api.booking(token), f.code === "change_closed" ? failureText(f) : f.message);
      } catch {
        /* fall through to the message */
      }
    }
    if (f.code === "slot_unavailable") return retry();
    alert.textContent = failureText(f);
  }

  function reschedule() {
    const length = Math.round((new Date(b.ends_at).getTime() - new Date(b.starts_at).getTime()) / 60000);
    const notice = h("div", { class: "gh-alert", role: "alert" });
    const picker = createPicker({ ctx, durations: [length], windowDays: b.calendar.window_days, load: (q) => ctx.api.bookingSlots(token, q), onPick: confirmMove });
    const [oldDay, oldTime] = whenLines(b.starts_at, b.ends_at, zone);
    const pickScreen = h(
      "div",
      { class: "gh-stack" },
      backButton("Keep my time", () => view(b, "")),
      heading("Pick a new time", "h2"),
      h("p", { class: "gh-hint" }, `Now: ${oldDay}, ${oldTime}`),
      notice,
      picker.el,
    );
    show(ctx, pickScreen);

    function confirmMove(pick: Pick) {
      const [day, time] = whenLines(pick.start, plusMinutes(pick.start, length), pick.zone);
      const alert = h("div", { class: "gh-alert", role: "alert" });
      const go = h("button", { type: "button", class: "gh-btn gh-primary", onclick: () => void move() }, "Move my booking");
      show(
        ctx,
        h(
          "div",
          { class: "gh-stack" },
          backButton("Pick another time", () => {
            show(ctx, pickScreen, false);
            picker.focusTime(pick.start);
          }),
          heading("Move your booking?", "h2"),
          h("div", { class: "gh-when" }, h("span", { class: "gh-old" }, `${oldDay}, ${oldTime}`), h("strong", null, day), h("span", null, time)),
          alert,
          h("div", { class: "gh-actions" }, go),
        ),
      );
      async function move() {
        go.disabled = true;
        go.replaceChildren(icon("spin", 16), "Moving...");
        try {
          view(await ctx.api.reschedule(token, pick.start, pick.zone), "Your booking was moved.");
        } catch (e) {
          go.disabled = false;
          go.replaceChildren("Move my booking");
          await failed(e, alert, () => {
            notice.textContent = failureText(asFailure(e));
            show(ctx, pickScreen, false);
            picker.refresh();
          });
        }
      }
    }
  }

  function cancel() {
    const alert = h("div", { class: "gh-alert", role: "alert" });
    const reasonId = uid("gh-reason");
    const reason = h("textarea", { id: reasonId, class: "gh-input", maxlength: 500, rows: 3 });
    const go = h("button", { type: "submit", class: "gh-btn gh-danger" }, "Cancel booking");
    const [day, time] = whenLines(b.starts_at, b.ends_at, zone);
    show(
      ctx,
      h(
        "form",
        { class: "gh-stack", onsubmit: (e: Event) => void send(e) },
        backButton("Keep my booking", () => view(b, "")),
        heading("Cancel this booking?", "h2"),
        h("div", { class: "gh-when" }, h("strong", null, b.calendar.name), h("span", null, day), h("span", null, time)),
        h("div", { class: "gh-field" }, h("label", { class: "gh-label", for: reasonId }, "Reason (optional)"), reason),
        alert,
        h("div", { class: "gh-actions" }, go),
      ),
    );
    async function send(e: Event) {
      e.preventDefault();
      if (go.disabled) return;
      go.disabled = true;
      go.replaceChildren(icon("spin", 16), "Cancelling...");
      try {
        view(await ctx.api.cancel(token, reason.value.trim()), "Your booking was cancelled.");
      } catch (err) {
        go.disabled = false;
        go.replaceChildren("Cancel booking");
        await failed(err, alert, () => (alert.textContent = failureText(asFailure(err))));
      }
    }
  }
}
