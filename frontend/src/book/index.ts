// The script behind the booking page and widget, dist/book/book.js. Two ways in:
//   the page   /book/{ws}/{cal} and /booking/{token} serve page.html, whose script tag says data-mode="page"; the route
//              comes from the address and ?theme=dark picks the dark theme
//   a widget   <div data-go-high-booking="ws/cal"></div><script async src="https://host/book/book.js"></script> on any
//              site; each such div gets the page in a shadow root (no iframe), talking to the host the script came from.
//              data-theme="dark" on the div (or an ancestor) picks the dark theme.
import { createApi } from "./api.ts";
import { h } from "./dom.ts";
import type { Ctx } from "./dom.ts";
import { bookFlow, manageFlow } from "./screens.ts";
import css from "./style.css?inline";

type Route = { kind: "book"; ws: string; cal: string } | { kind: "manage"; token: string };

const sheet = (() => {
  try {
    const s = new CSSStyleSheet();
    s.replaceSync(css);
    return s; // not subject to the host page's style-src, unlike a <style> element
  } catch {
    return null;
  }
})();

function mount(host: HTMLElement, route: Route, base: string, theme: string, embed: boolean) {
  const shadow = host.shadowRoot ?? host.attachShadow({ mode: "open" });
  const live = h("div", { class: "gh-sr", role: "status", "aria-live": "polite" });
  const root = h("div", { class: "gh-view" });
  shadow.replaceChildren(h("div", { class: "gh", "data-theme": theme === "dark" ? "dark" : "light" }, root, live));
  if (sheet && "adoptedStyleSheets" in shadow) shadow.adoptedStyleSheets = [sheet];
  else shadow.prepend(h("style", null, css));
  const ctx: Ctx = {
    root,
    api: createApi(base),
    embed,
    say(message) {
      live.textContent = "";
      setTimeout(() => (live.textContent = message), 50); // cleared first, so the same words are read again
    },
    title(text) {
      if (!embed) document.title = text;
    },
  };
  if (route.kind === "book") void bookFlow(ctx, route.ws, route.cal);
  else void manageFlow(ctx, route.token);
}

/** The route of a page address, or null for any other path. */
export function routeOf(path: string): Route | null {
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  if (parts[0] === "book" && parts.length === 3) return { kind: "book", ws: parts[1], cal: parts[2] };
  if (parts[0] === "booking" && parts.length === 2) return { kind: "manage", token: parts[1] };
  return null;
}

function boot(script: HTMLScriptElement | null) {
  let base = location.origin;
  try {
    if (script?.src) base = new URL(script.src).origin;
  } catch {
    /* the page's own origin */
  }
  if (script?.dataset.mode === "page") {
    const route = routeOf(location.pathname);
    const theme = new URLSearchParams(location.search).get("theme") === "dark" ? "dark" : "light";
    document.documentElement.dataset.theme = theme;
    const host = document.getElementById("gh-book") ?? document.body.appendChild(document.createElement("main"));
    if (route) mount(host, route, base, theme, false);
    return;
  }
  for (const el of document.querySelectorAll<HTMLElement>("[data-go-high-booking]")) {
    if (el.dataset.ghMounted) continue;
    const [ws, cal] = (el.dataset.goHighBooking ?? "").split("/");
    if (!ws || !cal) continue;
    el.dataset.ghMounted = "1";
    const theme = el.closest("[data-theme]")?.getAttribute("data-theme") ?? "light";
    mount(el, { kind: "book", ws, cal }, base, theme, true);
  }
}

const current = document.currentScript as HTMLScriptElement | null;
if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", () => boot(current));
else boot(current);
