// A tiny element builder. Text goes in as text nodes, never as markup, so nothing a form owner or a visitor typed can
// become HTML.
type Attr = string | number | boolean | null | undefined | ((e: Event) => void);
type Kid = Node | string | null | false | undefined;

export function h(tag: string, attrs: Record<string, Attr> | null, ...kids: Kid[]): HTMLElement {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs ?? {})) {
    if (v == null || v === false) continue;
    if (typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "class") el.className = String(v);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids) if (kid != null && kid !== false) el.append(kid);
  return el;
}
