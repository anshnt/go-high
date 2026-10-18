// Choosing a time: length, time zone, a month grid and the times of the chosen day. Used to book and to reschedule.
import { h, icon, uid } from "./dom.ts";
import type { Ctx } from "./dom.ts";
import { addDays, daysIn, keyOf, monthGrid, monthRange, monthsBetween, normaliseDays, sameMonth, stepMonth, weekday, ymOfKey } from "./month.ts";
import type { YM } from "./month.ts";
import { durationLabel } from "./text.ts";
import type { SlotsQuery, SlotsResponse } from "./types.ts";
import { clockLabel, detectZone, formatDay, formatTime, listZones, monthLabel, offsetLabel, splitZone, todayKey, weekdayLabels } from "./zones.ts";

export interface Pick {
  start: string;
  zone: string;
  duration: number;
}

export interface PickerOptions {
  ctx: Ctx;
  durations: number[];
  windowDays: number;
  load(q: SlotsQuery): Promise<SlotsResponse>;
  onPick(pick: Pick): void;
}

export interface Picker {
  el: HTMLElement;
  /** Forget what was loaded and ask again (a time was taken). */
  refresh(): void;
  /** Put focus back on a time (or its day) after going away and coming back. */
  focusTime(start: string): void;
}

type Phase = "loading" | "ready" | "error" | "searching" | "none";

const plural = (n: number) => `${n} ${n === 1 ? "time" : "times"}`;

export function createPicker(o: PickerOptions): Picker {
  const { ctx } = o;
  let zone = detectZone();
  let duration = o.durations[0];
  let ym: YM = ymOfKey(todayKey(zone));
  let days: Record<string, string[]> = {};
  let phase: Phase = "loading";
  let selected: string | null = null;
  let tabKey: string | null = null;
  let seq = 0;
  const cache = new Map<string, Record<string, string[]>>();
  const buttons = new Map<string, HTMLButtonElement>();
  const cells = new Map<string, HTMLElement>();

  const first = () => ymOfKey(todayKey(zone));
  const last = () => ymOfKey(addDays(todayKey(zone), o.windowDays));
  const open = (key: string) => (days[key]?.length ?? 0) > 0;

  // ---- controls: length and time zone
  const ids = { month: uid("gh-month"), zone: uid("gh-zone"), times: uid("gh-times") };
  const lengths = o.durations.length > 1 ? lengthChooser() : null;
  const select = zoneSelect();
  const clock = h("p", { class: "gh-hint" });
  const prev = h("button", { type: "button", class: "gh-btn gh-icon-btn", "aria-label": "Previous month", onclick: () => step(-1) }, icon("left"));
  const next = h("button", { type: "button", class: "gh-btn gh-icon-btn", "aria-label": "Next month", onclick: () => step(1) }, icon("right"));
  const title = h("h2", { class: "gh-month", id: ids.month });
  const grid = h("table", { class: "gh-grid", role: "grid", "aria-labelledby": ids.month, onkeydown: (e: Event) => onKey(e as KeyboardEvent) });
  const message = h("div", { class: "gh-cal-msg" });
  const heading = h("h3", { class: "gh-times-title", id: ids.times });
  const list = h("ul", { class: "gh-slots", "aria-labelledby": ids.times });
  const times = h("div", { class: "gh-times" }, heading, list);

  const el = h(
    "div",
    { class: "gh-picker" },
    h(
      "div",
      { class: "gh-controls" },
      lengths,
      h("div", { class: "gh-field gh-zone" }, h("label", { class: "gh-label", for: ids.zone }, icon("globe", 14), " Time zone"), select, clock),
    ),
    h(
      "div",
      { class: "gh-cal" },
      h("div", { class: "gh-cal-head" }, title, h("div", { class: "gh-cal-nav" }, prev, next)),
      grid,
      message,
    ),
    times,
  );

  function lengthChooser(): HTMLElement {
    const name = uid("gh-len");
    return h(
      "fieldset",
      { class: "gh-field gh-seg" },
      h("legend", { class: "gh-label" }, "Length"),
      h(
        "div",
        { class: "gh-seg-row" },
        ...o.durations.map((d, i) =>
          h(
            "label",
            { class: "gh-seg-item" },
            h("input", {
              type: "radio", name, value: d, checked: i === 0,
              onchange: () => {
                duration = d;
                reset();
              },
            }),
            h("span", null, durationLabel(d)),
          ),
        ),
      ),
    );
  }

  function zoneSelect(): HTMLSelectElement {
    const sel = h("select", { class: "gh-input", id: ids.zone, onchange: () => changeZone(sel.value) });
    const groups = new Map<string, HTMLOptGroupElement>();
    for (const z of ["UTC", ...listZones([zone]).filter((z) => z !== "UTC")]) {
      const { region, city } = splitZone(z);
      let parent: HTMLElement = sel;
      if (region) {
        let g = groups.get(region);
        if (!g) groups.set(region, (g = sel.appendChild(h("optgroup", { label: region }))));
        parent = g;
      }
      parent.append(h("option", { value: z, selected: z === zone }, city));
    }
    return sel;
  }

  function tick() {
    const now = new Date();
    clock.textContent = `Local time there: ${clockLabel(zone, now)} (${offsetLabel(zone, now)})`;
  }
  tick();
  const timer = setInterval(() => (el.isConnected ? tick() : clearInterval(timer)), 20000);

  function changeZone(name: string) {
    zone = name;
    tick();
    const lo = first();
    const hi = last();
    if (monthsBetween(lo, ym) < 0) ym = lo;
    else if (monthsBetween(ym, hi) < 0) ym = hi;
    reset();
  }

  function reset() {
    selected = null;
    tabKey = null;
    void show(ym);
  }

  // ---- loading a month
  async function fetchMonth(target: YM): Promise<Record<string, string[]>> {
    const id = `${zone}|${duration}|${target.year}-${target.month}`;
    const hit = cache.get(id);
    if (hit) return hit;
    const res = await o.load({ ...monthRange(target), tz: zone, duration });
    const grouped = normaliseDays(res.days, zone);
    cache.set(id, grouped);
    return grouped;
  }

  async function show(target: YM, focus?: string) {
    const mine = ++seq;
    ym = target;
    days = {};
    phase = "loading";
    if (focus) tabKey = focus;
    build();
    paint();
    if (focus) buttons.get(focus)?.focus();
    try {
      const got = await fetchMonth(target);
      if (mine !== seq) return;
      days = got;
      phase = Object.keys(got).length ? "ready" : "none";
      if (phase === "none") phase = monthsBetween(target, last()) > 0 ? "ready" : "none";
    } catch {
      if (mine !== seq) return;
      phase = "error";
    }
    if (selected && !open(selected)) selected = null;
    paint();
    const count = Object.keys(days).length;
    if (phase !== "error") ctx.say(`${monthLabel(ym.year, ym.month)}: ${count ? `${count} ${count === 1 ? "day" : "days"} with times` : "no times"}`);
  }

  function step(by: number) {
    const target = stepMonth(ym, by);
    if (monthsBetween(first(), target) < 0 || monthsBetween(target, last()) < 0) return;
    selected = null;
    tabKey = null;
    void show(target);
  }

  async function findNext() {
    const mine = ++seq;
    phase = "searching";
    paint();
    try {
      let at = ym;
      while (monthsBetween(at, last()) > 0) {
        at = stepMonth(at, 1);
        const got = await fetchMonth(at);
        if (mine !== seq) return;
        const keys = Object.keys(got);
        if (keys.length) {
          selected = null;
          void show(at, keys[0]);
          return;
        }
      }
      phase = "none";
      days = {};
    } catch {
      if (mine !== seq) return;
      phase = "error";
    }
    paint();
  }

  // ---- drawing
  /** The grid for the visible month: built once per month, then painted as the data and choices change. */
  function build() {
    buttons.clear();
    cells.clear();
    title.textContent = monthLabel(ym.year, ym.month);
    const head = h("tr", { role: "row" }, ...weekdayLabels("short").map((d, i) => h("th", { scope: "col", role: "columnheader", abbr: weekdayLabels("long")[i] }, d)));
    const body = monthGrid(ym).map((week) =>
      h(
        "tr",
        { role: "row" },
        ...week.map((c) => {
          if (!c) return h("td", { role: "gridcell", "aria-hidden": "true" });
          const b = h("button", { type: "button", class: "gh-day", tabindex: -1, "data-key": c.key, onclick: () => choose(c.key) }, c.day);
          buttons.set(c.key, b);
          const td = h("td", { role: "gridcell" }, b);
          cells.set(c.key, td);
          return td;
        }),
      ),
    );
    grid.replaceChildren(h("thead", null, head), h("tbody", null, ...body));
  }

  function paint() {
    const today = todayKey(zone);
    const stop = tabKey && buttons.has(tabKey) ? tabKey : (Object.keys(days)[0] ?? (sameMonth(ymOfKey(today), ym) ? today : keyOf(ym, 1)));
    for (const [key, b] of buttons) {
      const n = days[key]?.length ?? 0;
      const label = formatDay(key);
      b.setAttribute("aria-label", phase === "ready" || phase === "none" ? `${label}, ${n ? plural(n) : "no times"}` : label);
      b.setAttribute("tabindex", key === stop ? "0" : "-1");
      b.toggleAttribute("data-open", n > 0);
      b.toggleAttribute("data-today", key === today);
      b.toggleAttribute("data-selected", key === selected);
      if (n > 0) b.removeAttribute("aria-disabled");
      else b.setAttribute("aria-disabled", "true");
      if (key === today) b.setAttribute("aria-current", "date");
      else b.removeAttribute("aria-current");
      cells.get(key)?.setAttribute("aria-selected", String(key === selected));
    }
    grid.setAttribute("aria-busy", String(phase === "loading" || phase === "searching"));
    prev.setAttribute("aria-disabled", String(monthsBetween(first(), ym) <= 0));
    next.setAttribute("aria-disabled", String(monthsBetween(ym, last()) <= 0));
    paintMessage();
    paintTimes();
  }

  function paintMessage() {
    const label = monthLabel(ym.year, ym.month);
    const retry = (text: string, run: () => void) => h("button", { type: "button", class: "gh-btn gh-btn-secondary", onclick: run }, text);
    message.replaceChildren();
    message.removeAttribute("role");
    if (phase === "loading") message.append(h("p", { class: "gh-hint" }, "Loading times..."));
    else if (phase === "searching") message.append(h("p", { class: "gh-hint" }, icon("spin", 14), " Looking for the next opening..."));
    else if (phase === "error") {
      message.setAttribute("role", "alert");
      message.append(h("p", null, "Could not load times."), retry("Try again", () => void show(ym)));
    } else if (!Object.keys(days).length) {
      const more = monthsBetween(ym, last()) > 0;
      message.append(
        h("p", null, `No times in ${label}.`),
        more ? retry("Next available", () => void findNext()) : h("p", { class: "gh-hint" }, `No open times in the next ${o.windowDays} days.`),
      );
    }
  }

  function paintTimes() {
    list.replaceChildren();
    if (!selected) {
      heading.textContent = "Times";
      list.append(h("li", { class: "gh-hint gh-slots-empty" }, phase === "ready" ? "Choose a day to see its times." : ""));
      return;
    }
    heading.textContent = formatDay(selected);
    for (const start of days[selected] ?? []) {
      list.append(h("li", null, h("button", { type: "button", class: "gh-slot", "data-start": start, onclick: () => o.onPick({ start, zone, duration }) }, formatTime(start, zone))));
    }
  }

  function choose(key: string) {
    tabKey = key;
    if (!open(key)) {
      ctx.say(`No times on ${formatDay(key)}`);
      return;
    }
    selected = key;
    paint();
    ctx.say(`${plural(days[key].length)} on ${formatDay(key)}`);
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    heading.scrollIntoView({ block: "nearest", behavior: reduced ? "auto" : "smooth" });
  }

  // ---- keyboard: arrows move over days (also into the next month), page keys change month
  function onKey(e: KeyboardEvent) {
    const key = (e.target as HTMLElement).closest<HTMLElement>("[data-key]")?.dataset.key;
    if (!key) return;
    const wd = weekday(key);
    const move: Record<string, string | undefined> = {
      ArrowLeft: addDays(key, -1), ArrowRight: addDays(key, 1), ArrowUp: addDays(key, -7), ArrowDown: addDays(key, 7),
      Home: addDays(key, -wd), End: addDays(key, 6 - wd),
      PageUp: monthJump(key, -1), PageDown: monthJump(key, 1),
    };
    const to = move[e.key];
    if (!to) return;
    e.preventDefault();
    const target = ymOfKey(to);
    if (sameMonth(target, ym)) {
      tabKey = to;
      paint();
      buttons.get(to)?.focus();
    } else if (monthsBetween(first(), target) >= 0 && monthsBetween(target, last()) >= 0) {
      selected = null;
      void show(target, to);
    }
  }

  function monthJump(key: string, by: number): string {
    const target = stepMonth(ymOfKey(key), by);
    return keyOf(target, Math.min(Number(key.slice(8)), daysIn(target)));
  }

  void show(ym);

  return {
    el,
    refresh() {
      cache.clear();
      void show(ym);
    },
    focusTime(start) {
      const slot = list.querySelector<HTMLElement>(`[data-start="${start}"]`);
      (slot ?? (selected ? buttons.get(selected) : null) ?? (tabKey ? buttons.get(tabKey) : null))?.focus();
    },
  };
}
