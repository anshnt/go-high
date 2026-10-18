// The form runtime: loads a published definition (or takes a preview), walks the steps with the same logic as the
// server, saves partial answers as they are typed, validates, completes, and shows the result. Plain DOM, no framework,
// so it can be embedded anywhere (see index.ts).
import { check } from "./check.ts";
import { h } from "./dom.ts";
import { empty, flow } from "./logic.ts";
import { score } from "./quiz.ts";
import type { Answers, Definition, Done, Field, Published } from "./types.ts";
import { fieldView, resultView } from "./view.ts";

export type Preview = { definition: Definition; name?: string; kind?: Published["kind"]; settings?: Partial<Published["settings"]> };
export type Options = {
  key?: string; // the form's public key (not needed for a preview)
  base?: string; // origin of the API; default: the page's own
  theme?: string; // light, dark or auto
  preview?: Preview; // render this definition and save nothing
};
export type Handle = { update: (definition: Definition) => void; destroy: () => void };

class Fail extends Error {
  constructor(public status: number, public code: string, message: string, public fields?: Record<string, string>) {
    super(message);
  }
}

const SAVE_DELAY = 1500;
const stored = (key: string) => `gh:response:${key}`;

export function resolveTheme(value: string | null | undefined): "light" | "dark" {
  return value === "dark" || (value === "auto" && matchMedia("(prefers-color-scheme: dark)").matches) ? "dark" : "light";
}

export function mount(host: HTMLElement | ShadowRoot, opts: Options): Handle {
  const root = h("div", { class: "gh", "data-theme": resolveTheme(opts.theme) });
  const live = h("div", { class: "gh-sr", "aria-live": "polite" });
  const body = h("div", { class: "gh-body" });
  root.append(body, live);
  host.append(root);

  const base = (opts.base ?? location.origin).replace(/\/$/, "");
  const preview = opts.preview;
  let pub: Published | null = preview
    ? { key: "preview", kind: preview.kind ?? "form", name: preview.name ?? "", version: 0, definition: preview.definition, settings: { success_message: "Thanks, we got your response.", redirect_url: null, ...preview.settings } }
    : null;
  let answers: Answers = {};
  let stepKey = "";
  let errors: Record<string, string> = {};
  let notice = "";
  let closed = "";
  let done: Done | null = null;
  let busy = false;
  let loading = !preview;
  let view = "";
  let resume: { id: string; token: string } | null = null;
  let showLink = false;
  let copied = false;
  let hp = "";
  let timer = 0;
  let chain: Promise<void> = Promise.resolve();
  let sig = "";
  let focus: "" | "step" | "error" = "";
  let gone = false;

  const def = () => pub!.definition;
  const fields = () => new Map(def().steps.flatMap((s) => s.fields).map((f) => [f.key, f]));
  const source = () => {
    const u = new URL(location.href);
    u.searchParams.delete("gh_resume");
    u.hash = "";
    const utm: Record<string, string> = {};
    for (const [k, v] of u.searchParams) if (k.startsWith("utm_")) utm[k] = v.slice(0, 200);
    return { url: u.href.slice(0, 2000), referrer: document.referrer.slice(0, 2000), utm };
  };

  async function call(path: string, payload?: unknown) {
    let res: Response;
    try {
      res = await fetch(`${base}/api/public/forms/${opts.key}${path}`, {
        method: payload === undefined ? "GET" : "POST",
        headers: payload === undefined ? undefined : { "Content-Type": "application/json" },
        body: payload === undefined ? undefined : JSON.stringify(payload),
        credentials: "omit",
      });
    } catch {
      throw new Fail(0, "network", "Could not reach the server. Check your connection and try again.");
    }
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Fail(res.status, data?.error?.code ?? "error", data?.error?.message ?? "Something went wrong. Try again.", data?.error?.fields);
    return data;
  }

  const position = () => {
    const path = flow(def(), answers).steps;
    const found = path.findIndex((s) => s.key === stepKey);
    return { path, idx: found < 0 ? 0 : found };
  };

  // ---- saving ----
  function doSave(): Promise<void> {
    chain = chain.then(async () => {
      if (preview || done || closed || gone) return;
      if (!resume && !Object.values(answers).some((v) => !empty(v))) return;
      try {
        const r = await call("/submissions", { answers, step: stepKey, view_token: view, resume_token: resume?.token, hp, ...(resume ? {} : source()) });
        if (!resume) {
          resume = { id: r.id, token: r.resume_token };
          try {
            sessionStorage.setItem(stored(opts.key!), resume.token);
          } catch {
            /* private window: the link still works */
          }
          render();
        }
      } catch (e) {
        if (e instanceof Fail && e.status === 410) {
          closed = e.message;
          render();
        }
      }
    });
    return chain;
  }
  const scheduleSave = () => {
    clearTimeout(timer);
    if (!preview) timer = window.setTimeout(() => void doSave(), SAVE_DELAY);
  };

  // ---- answering ----
  function set(f: Field, value: unknown) {
    if (empty(value)) delete answers[f.key];
    else answers[f.key] = value;
    let changed = false;
    if (errors[f.key]) {
      const m = check(f, answers[f.key]);
      if (m) errors[f.key] = m;
      else delete errors[f.key];
      changed = true;
    }
    if (JSON.stringify(flow(def(), answers).steps) !== sig || changed) render();
    scheduleSave();
  }

  async function next(e?: Event) {
    e?.preventDefault();
    if (busy) return;
    const { path, idx } = position();
    const f = fields();
    errors = {};
    for (const key of path[idx]!.fields) {
      const m = check(f.get(key)!, answers[key]);
      if (m) errors[key] = m;
    }
    if (Object.keys(errors).length) {
      focus = "error";
      return render();
    }
    if (idx < path.length - 1) {
      stepKey = path[idx + 1]!.key;
      focus = "step";
      render();
      return void doSave();
    }
    await submit(false);
  }

  async function submit(retried: boolean) {
    busy = true;
    notice = "";
    render();
    try {
      const fl = flow(def(), answers);
      if (preview) {
        done = { id: "preview", status: "complete", message: pub!.settings.success_message, redirect_url: null, result: pub!.kind === "quiz" ? score(def(), fl, fl.answers) : null };
      } else {
        await doSave();
        if (!resume) throw new Fail(0, "none", "Could not save your answers. Try again.");
        done = await call(`/submissions/${resume.id}/complete`, { answers, resume_token: resume.token, view_token: view, hp });
        try {
          sessionStorage.removeItem(stored(opts.key!));
        } catch {
          /* nothing stored */
        }
        const url = done!.redirect_url;
        if (url && /^https?:\/\//i.test(url) && !done!.result) setTimeout(() => location.assign(url), 1200);
      }
      focus = "step";
    } catch (e) {
      const fail = e instanceof Fail ? e : new Fail(0, "error", "Something went wrong. Try again.");
      if (fail.code === "invalid_view_token" && !retried) {
        view = (await call("/views", {}).catch(() => ({ view_token: "" }))).view_token;
        return submit(true);
      }
      if (fail.status === 410) closed = fail.message;
      else notice = fail.message;
      if (fail.status === 422 && fail.fields) {
        errors = fail.fields;
        const bad = def().steps.find((s) => s.fields.some((f) => errors[f.key]));
        if (bad) stepKey = bad.key;
        notice = "Some answers need fixing.";
        focus = "error";
      }
    }
    busy = false;
    render();
  }

  function back() {
    const { path, idx } = position();
    if (idx === 0) return;
    stepKey = path[idx - 1]!.key;
    errors = {};
    focus = "step";
    render();
  }

  // ---- drawing ----
  function render() {
    if (gone) return;
    const active = root.getRootNode() instanceof ShadowRoot ? (root.getRootNode() as ShadowRoot).activeElement : document.activeElement;
    const keep = active instanceof HTMLElement && root.contains(active) ? { key: active.dataset.key, start: (active as HTMLInputElement).selectionStart, end: (active as HTMLInputElement).selectionEnd, value: (active as HTMLInputElement).value } : null;
    body.replaceChildren(...build());
    for (const bar of body.querySelectorAll<HTMLElement>("[data-w]")) bar.style.width = `${bar.dataset.w}%`; // CSSOM, so a strict CSP is fine
    if (focus === "step") (body.querySelector("[data-focus]") as HTMLElement | null)?.focus({ preventScroll: false });
    else if (focus === "error") (body.querySelector('[aria-invalid="true"]') as HTMLElement | null)?.focus();
    else if (keep?.key) {
      const inputs = [...body.querySelectorAll<HTMLInputElement>(`[data-key="${CSS.escape(keep.key)}"]`)];
      const el = inputs.find((i) => i.value === keep.value && (i.type === "radio" || i.type === "checkbox")) ?? inputs[0];
      el?.focus();
      if (el && keep.start != null && !["radio", "checkbox", "select-one"].includes(el.type)) el.setSelectionRange?.(keep.start, keep.end);
    }
    focus = "";
  }

  function build(): Node[] {
    const out: Node[] = [];
    if (preview) out.push(h("p", { class: "gh-preview" }, "Preview. Nothing is saved."));
    if (loading) return [h("p", { class: "gh-muted" }, "Loading")];
    if (closed) return [h("p", { class: "gh-closed", role: "status" }, closed)];
    if (!pub) return [h("p", { class: "gh-error", role: "alert" }, notice || "This form is not available.")];
    const d = def();
    const title = d.title ?? pub.name;
    out.push(h("div", { class: "gh-head" }, title && h("h2", { class: "gh-title" }, title), d.description && h("p", { class: "gh-desc" }, d.description)));
    if (done) {
      const url = done.redirect_url && /^https?:\/\//i.test(done.redirect_url) ? done.redirect_url : null;
      out.push(resultView(d, done, done.result && url ? () => location.assign(url) : null));
      return out;
    }
    const { path, idx } = position();
    stepKey = path[idx]!.key;
    sig = JSON.stringify(path);
    const step = d.steps.find((s) => s.key === stepKey)!;
    const visible = new Set(path[idx]!.fields);
    const last = idx === path.length - 1;
    if (path.length > 1) {
      out.push(h("div", { class: "gh-progress" },
        h("div", { class: "gh-track", role: "progressbar", "aria-label": "Progress", "aria-valuemin": 1, "aria-valuemax": path.length, "aria-valuenow": idx + 1, "aria-valuetext": `Step ${idx + 1} of ${path.length}` }, h("div", { class: "gh-bar", "data-w": Math.round(((idx + 1) / path.length) * 100) })),
        h("span", { class: "gh-steps" }, `Step ${idx + 1} of ${path.length}`)));
    }
    live.textContent = path.length > 1 ? `Step ${idx + 1} of ${path.length}${step.title ? `: ${step.title}` : ""}` : "";
    if (notice) out.push(h("p", { class: "gh-error gh-notice", role: "alert" }, notice));
    out.push(h("form", { class: "gh-form", novalidate: true, onsubmit: (e) => void next(e) },
      h("div", { class: "gh-step" },
        step.title ? h("h3", { class: "gh-step-title", tabindex: "-1", "data-focus": "" }, step.title) : null,
        step.description && h("p", { class: "gh-desc" }, step.description),
        ...step.fields.filter((f) => visible.has(f.key)).map((f) => fieldView(f, { value: answers[f.key], error: errors[f.key], set: (v) => set(f, v) }))),
      h("div", { class: "gh-hp", "aria-hidden": "true" }, h("label", null, "Website", h("input", { type: "text", name: "website", tabindex: "-1", autocomplete: "off", oninput: (e) => (hp = (e.target as HTMLInputElement).value) }))),
      h("div", { class: "gh-nav" },
        idx > 0 && h("button", { type: "button", class: "gh-btn", onclick: back }, "Back"),
        h("button", { type: "submit", class: "gh-btn gh-primary", disabled: busy, "aria-busy": busy ? "true" : null }, busy ? "Sending" : last ? d.submit_label || "Send" : "Next"))));
    if (resume && !preview) out.push(resumeView());
    return out;
  }

  function resumeView(): HTMLElement {
    const u = new URL(location.href);
    u.hash = "";
    u.searchParams.set("gh_resume", resume!.token);
    return h("div", { class: "gh-resume" },
      h("button", { type: "button", class: "gh-link", "aria-expanded": showLink ? "true" : "false", onclick: () => { showLink = !showLink; render(); } }, "Save and finish later"),
      showLink && h("div", { class: "gh-resume-box" },
        h("p", { class: "gh-help" }, "Your answers are saved. Open this link on any device to carry on."),
        h("input", { class: "gh-input", readonly: true, "aria-label": "Link to continue", value: u.href, onfocus: (e) => (e.target as HTMLInputElement).select() }),
        h("button", { type: "button", class: "gh-btn", onclick: () => { void navigator.clipboard?.writeText(u.href); copied = true; render(); setTimeout(() => { copied = false; render(); }, 2000); } }, copied ? "Copied" : "Copy link")));
  }

  // ---- start ----
  async function init() {
    try {
      const token = new URLSearchParams(location.search).get("gh_resume") ?? (() => { try { return sessionStorage.getItem(stored(opts.key!)); } catch { return null; } })();
      if (token) {
        try {
          const r = await call("/resume", { resume_token: token });
          pub = r;
          answers = r.answers;
          stepKey = r.step ?? "";
          resume = { id: r.id, token };
        } catch (e) {
          if (e instanceof Fail && e.status === 410) throw e;
          try {
            sessionStorage.removeItem(stored(opts.key!));
          } catch {
            /* nothing stored */
          }
        }
      }
      pub ??= await call("");
      view = (await call("/views", {}).catch(() => ({ view_token: "" }))).view_token;
    } catch (e) {
      if (e instanceof Fail && e.status === 410) closed = e.message;
      else notice = e instanceof Fail && e.status === 404 ? "This form does not exist." : e instanceof Fail ? e.message : "";
      pub = null;
    }
    loading = false;
    if (pub) applyParams();
    render();
  }

  function applyParams() {
    const params = new URLSearchParams(location.search);
    for (const f of fields().values()) {
      const v = f.type === "hidden" ? params.get(f.param ?? f.key) : null;
      if (v && empty(answers[f.key])) answers[f.key] = v.slice(0, 500);
    }
  }

  render();
  if (!preview) void init();

  return {
    update(definition) {
      if (!pub) return;
      pub = { ...pub, definition };
      if (done) done = null;
      render();
    },
    destroy() {
      gone = true;
      clearTimeout(timer);
      root.remove();
    },
  };
}
