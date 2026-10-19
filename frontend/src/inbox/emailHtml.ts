// An email's HTML is whatever the sender mailed. It is cleaned here and then shown in a sandboxed frame (no scripts, no
// forms, no plugins) under a Content-Security-Policy that blocks every request: images only when the person asks.
// Two layers, so a hole in one is not enough. Needs a browser (DOMParser parses without running or loading anything).

const DROP = "script,iframe,frame,frameset,object,embed,applet,form,input,button,textarea,select,option,meta,link,base,noscript,audio,video,source,track,svg,math,template,dialog";
const URL_ATTRS = ["href", "src", "action", "formaction", "xlink:href", "background", "poster", "data"];
const BAD_SCHEME = /^\s*(?:javascript|vbscript|data:(?!image\/(?:png|gif|jpe?g|webp|avif)[;,]))/i;
const REMOTE = /^\s*(?:https?:)?\/\//i;

export type CleanEmail = { srcdoc: string; blocked: number };

/** The frame's whole document, and how many remote images were held back. */
export function emailDocument(html: string, opts: { images: boolean }): CleanEmail {
  const doc = new DOMParser().parseFromString(html, "text/html");
  const styles = [...doc.querySelectorAll("style")].map((s) => (s.textContent ?? "").replace(/@import[^;]*;?/gi, ""));
  doc.querySelectorAll(DROP).forEach((el) => el.remove());
  let blocked = 0;
  for (const el of doc.body.querySelectorAll("*")) {
    for (const attr of [...el.attributes]) {
      const name = attr.name.toLowerCase();
      if (name.startsWith("on") || name === "srcdoc" || name === "ping") el.removeAttribute(attr.name);
      else if (URL_ATTRS.includes(name) && BAD_SCHEME.test(attr.value)) el.removeAttribute(attr.name);
    }
    if (el.tagName === "A") {
      el.setAttribute("target", "_blank");
      el.setAttribute("rel", "noopener noreferrer nofollow");
    }
    if (el.tagName === "IMG") {
      el.removeAttribute("srcset");
      el.removeAttribute("loading");
      const src = el.getAttribute("src") ?? "";
      if (src && !/^\s*data:/i.test(src) && (!opts.images || !REMOTE.test(src))) {
        el.removeAttribute("src");
        el.setAttribute("data-blocked", "");
        if (!el.getAttribute("alt")) el.setAttribute("alt", "Image not loaded");
        blocked += 1;
      }
    }
    const style = el.getAttribute("style");
    if (style && /url\(/i.test(style)) {
      const kept = opts.images ? style : style.replace(/url\([^)]*\)/gi, "none");
      el.setAttribute("style", kept.replace(/expression\([^)]*\)/gi, ""));
      if (!opts.images && kept !== style) blocked += 1;
    }
    if (el.hasAttribute("background") && !opts.images) {
      el.removeAttribute("background");
      blocked += 1;
    }
  }
  const css = (opts.images ? styles : styles.map((s) => s.replace(/url\([^)]*\)/gi, "none"))).join("\n");
  // default-src none: nothing loads unless allowed below. Images only when asked for; styles may be inline (an email's own).
  const csp = `default-src 'none'; style-src 'unsafe-inline'; img-src data:${opts.images ? " https: http:" : ""}`;
  const srcdoc = `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${csp}"><base target="_blank"><meta name="viewport" content="width=device-width, initial-scale=1"><style>html{color-scheme:light}body{margin:0;padding:12px 14px;background:#fff;color:#1b1b1f;font:14px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif;overflow-wrap:anywhere}img{max-width:100%;height:auto}img[data-blocked]{display:inline-block;min-width:24px;min-height:16px;background:#eee;color:#666;font-size:12px}table{max-width:100%}a{color:#4338ca}pre{white-space:pre-wrap}blockquote{margin:8px 0;padding-left:10px;border-left:3px solid #ddd;color:#555}</style>${css ? `<style>${css}</style>` : ""}</head><body>${doc.body.innerHTML}</body></html>`;
  return { srcdoc, blocked };
}
