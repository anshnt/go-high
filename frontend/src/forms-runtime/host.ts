// Mounts the runtime into a shadow root of `el` with its styles, so the host page's CSS and the form's cannot meet.
import css from "./style.css?inline";
import { mount, type Handle, type Options } from "./runtime.ts";

const sheet = (() => {
  try {
    const s = new CSSStyleSheet();
    s.replaceSync(css);
    return s; // not subject to the host page's style-src, unlike a <style> element
  } catch {
    return null;
  }
})();

export function mountInto(el: HTMLElement, opts: Options): Handle {
  const shadow = el.shadowRoot ?? el.attachShadow({ mode: "open" });
  if (sheet && "adoptedStyleSheets" in shadow) shadow.adoptedStyleSheets = [sheet];
  else shadow.append(Object.assign(document.createElement("style"), { textContent: css }));
  return mount(shadow, opts);
}
