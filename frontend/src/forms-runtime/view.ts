// What a question and a result look like. Pure rendering: values come in, a callback reports changes.
import { h } from "./dom.ts";
import type { Definition, Done, Field } from "./types.ts";

export type FieldCtx = { value: unknown; error?: string; set: (v: unknown) => void };

const AUTOCOMPLETE: Partial<Record<Field["type"], string>> = { email: "email", phone: "tel" };

export function fieldView(f: Field, ctx: FieldCtx): HTMLElement | null {
  if (f.type === "hidden") return null;
  const id = `gh-${f.key}`;
  if (f.type === "heading") return h("h3", { class: "gh-heading", "data-key": f.key }, f.label);
  if (f.type === "paragraph") return h("p", { class: "gh-par", "data-key": f.key }, f.label);
  const describedBy = [f.help && `${id}-help`, ctx.error && `${id}-err`].filter(Boolean).join(" ") || null;
  const star = f.required ? h("span", { class: "gh-req", "aria-hidden": "true" }, " *") : null;
  const common = { id, "data-key": f.key, name: f.key, "aria-describedby": describedBy, "aria-invalid": ctx.error ? "true" : null, "aria-required": f.required ? "true" : null };
  const v = ctx.value;
  let control: HTMLElement;
  let grouped = false;

  if (f.type === "long_text") {
    control = h("textarea", { ...common, class: "gh-input", rows: 4, placeholder: f.placeholder, maxlength: f.validation?.max_length, oninput: (e) => ctx.set((e.target as HTMLTextAreaElement).value) });
    (control as HTMLTextAreaElement).value = typeof v === "string" ? v : "";
  } else if (f.type === "select") {
    control = h("select", { ...common, class: "gh-input", onchange: (e) => ctx.set((e.target as HTMLSelectElement).value || undefined) },
      h("option", { value: "" }, f.placeholder || "Choose one"),
      ...(f.options ?? []).map((o) => h("option", { value: o.id, selected: v === o.id }, o.label)));
  } else if (f.type === "multi_select" || f.type === "yes_no" || f.type === "rating") {
    grouped = true;
    const radio = f.type !== "multi_select";
    const choices = f.type === "rating" ? [1, 2, 3, 4, 5].map((n) => ({ id: String(n), label: String(n), val: n })) : f.type === "yes_no" ? [{ id: "yes", label: "Yes", val: true }, { id: "no", label: "No", val: false }] : (f.options ?? []).map((o) => ({ ...o, val: o.id }));
    const on = (val: unknown) => (radio ? v === val : Array.isArray(v) && v.includes(val));
    control = h("div", { class: f.type === "rating" ? "gh-choices gh-rating" : "gh-choices", role: radio ? "radiogroup" : "group", "aria-labelledby": `${id}-label`, "aria-describedby": describedBy, "aria-required": f.required ? "true" : null },
      ...choices.map((c, i) => h("label", { class: "gh-choice", "aria-label": f.type === "rating" ? `${c.label} out of 5` : null },
        h("input", { type: radio ? "radio" : "checkbox", name: f.key, value: c.id, "data-key": f.key, id: i === 0 ? id : null, checked: on(c.val), "aria-invalid": ctx.error ? "true" : null,
          onchange: (e) => {
            if (radio) return ctx.set(c.val);
            const group = (e.target as HTMLElement).closest(".gh-choices")!;
            ctx.set([...group.querySelectorAll("input")].filter((i) => i.checked).map((i) => i.value));
          } }),
        h("span", null, c.label))));
  } else if (f.type === "checkbox" || f.type === "consent") {
    return h("div", { class: "gh-field", "data-field": f.key },
      h("label", { class: "gh-check" },
        h("input", { ...common, type: "checkbox", checked: v === true, onchange: (e) => ctx.set((e.target as HTMLInputElement).checked) }),
        h("span", { id: `${id}-label` }, f.label, star)),
      f.help && h("p", { class: "gh-help", id: `${id}-help` }, f.help),
      ctx.error && h("p", { class: "gh-error", id: `${id}-err`, role: "alert" }, ctx.error));
  } else {
    const type = f.type === "short_text" ? "text" : f.type === "phone" ? "tel" : f.type;
    control = h("input", { ...common, class: "gh-input", type, placeholder: f.placeholder, autocomplete: AUTOCOMPLETE[f.type] ?? "off", inputmode: f.type === "number" ? "decimal" : null,
      maxlength: f.validation?.max_length, step: f.type === "number" ? "any" : null,
      oninput: (e) => {
        const t = (e.target as HTMLInputElement).value;
        ctx.set(f.type === "number" ? (t === "" || Number.isNaN(Number(t)) ? undefined : Number(t)) : t);
      } });
    (control as HTMLInputElement).value = v == null ? "" : String(v);
  }
  return h("div", { class: "gh-field", "data-field": f.key },
    grouped ? h("div", { class: "gh-label", id: `${id}-label` }, f.label, star) : h("label", { class: "gh-label", for: id, id: `${id}-label` }, f.label, star),
    f.help && h("p", { class: "gh-help", id: `${id}-help` }, f.help),
    control,
    ctx.error && h("p", { class: "gh-error", id: `${id}-err`, role: "alert" }, ctx.error));
}

export function resultView(defn: Definition, done: Done, onContinue: (() => void) | null): HTMLElement {
  const r = done.result;
  const labels = new Map(defn.steps.flatMap((s) => s.fields).map((f) => [f.key, f.label]));
  return h("div", { class: "gh-done", role: "status", tabindex: "-1", "data-focus": "" },
    r ? h("h3", { class: "gh-result-title" }, r.band?.title || (r.passed === true ? "You passed" : r.passed === false ? "Not this time" : "Your result")) : h("h3", { class: "gh-result-title" }, "Thank you"),
    r && h("p", { class: "gh-score" }, `${r.score} out of ${r.max_score} points (${r.percent}%)`),
    r && r.passed != null && h("p", { class: r.passed ? "gh-pill gh-pass" : "gh-pill gh-fail" }, r.passed ? "Passed" : "Not passed"),
    r?.band?.message && h("p", null, r.band.message),
    done.message && h("p", { class: "gh-message" }, done.message),
    r && h("ul", { class: "gh-review" }, ...Object.entries(r.review).map(([k, ok]) => h("li", { class: ok ? "gh-right" : "gh-wrong" }, h("span", { "aria-hidden": "true" }, ok ? "✓ " : "✗ "), h("span", { class: "gh-sr" }, ok ? "Right: " : "Wrong: "), labels.get(k) ?? k))),
    onContinue && h("button", { type: "button", class: "gh-btn gh-primary", onclick: onContinue }, "Continue"));
}
