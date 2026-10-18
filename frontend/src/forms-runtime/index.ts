// The script behind `<script src=".../embed.js" data-form="KEY">` and the hosted page (/f/KEY). It mounts the form into
// a shadow root next to the script (no iframe), so the host page's CSS and analytics are untouched. Options on the tag:
//   data-form     the form's public key (required)
//   data-theme    light (default), dark or auto; otherwise the nearest ancestor's data-theme
//   data-target   a CSS selector to mount into, instead of right after the script
//   data-mode     "page" for the hosted page: a centred column, mounted in the body
import { mountInto } from "./host.ts";
import { resolveTheme } from "./runtime.ts";

function boot(script: HTMLScriptElement) {
  const key = script.dataset.form;
  if (!key || script.dataset.ghMounted) return;
  script.dataset.ghMounted = "1";
  let base: string;
  try {
    base = new URL(script.src).origin;
  } catch {
    base = location.origin;
  }
  const page = script.dataset.mode === "page";
  const target = script.dataset.target ? document.querySelector<HTMLElement>(script.dataset.target) : null;
  const host = target ?? document.createElement("div");
  host.dataset.ghForm = key;
  if (page) {
    Object.assign(host.style, { maxWidth: "640px", margin: "0 auto", padding: "24px 16px" });
    document.body.append(host);
  } else if (!target) script.after(host);
  const theme = script.dataset.theme ?? host.closest("[data-theme]")?.getAttribute("data-theme") ?? (page ? document.documentElement.dataset.theme : null);
  mountInto(host, { key, base, theme: resolveTheme(theme) });
}

const current = document.currentScript as HTMLScriptElement | null;
if (current) boot(current);
else document.querySelectorAll<HTMLScriptElement>("script[data-form]").forEach(boot);

// For a page that mounts forms itself: GoHighForms.mount(element, { key: "...", base: "https://app.example" }).
(window as unknown as { GoHighForms: unknown }).GoHighForms = { mount: mountInto };
