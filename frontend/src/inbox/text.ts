// Message text for the screen: search hits marked, and web addresses made into links. Pure: no DOM, no Vite.

export type Part = { text: string; hit: boolean; href?: string };

/** The words of a search query, lower case, without repeats. The server matches each as the start of a word. */
export function queryTerms(q: string): string[] {
  return [...new Set((q.toLowerCase().match(/[\p{L}\p{N}]+/gu) ?? []).filter(Boolean))];
}

const URL_RE = /\bhttps?:\/\/[^\s<>"']+[^\s<>"'.,;:!?)\]}]/g;

/** `text` cut into parts: the start of every word that a query term begins is a hit, and each web address carries its link. */
export function textParts(text: string, q = ""): Part[] {
  const terms = queryTerms(q);
  const hits = terms.length ? new RegExp(`(?<![\\p{L}\\p{N}])(?:${terms.map((t) => t.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|")})`, "giu") : null;
  const out: Part[] = [];
  const plain = (s: string, href?: string) => {
    if (!s) return;
    if (!hits) return void out.push({ text: s, hit: false, href });
    let at = 0;
    for (const m of s.matchAll(hits)) {
      if (m.index > at) out.push({ text: s.slice(at, m.index), hit: false, href });
      out.push({ text: m[0], hit: true, href });
      at = m.index + m[0].length;
    }
    if (at < s.length) out.push({ text: s.slice(at), hit: false, href });
  };
  let at = 0;
  for (const m of text.matchAll(URL_RE)) {
    plain(text.slice(at, m.index));
    plain(m[0], m[0]);
    at = m.index + m[0].length;
  }
  plain(text.slice(at));
  return out;
}

/** Whether an email's HTML would fetch anything from the web when shown (an image, a background), so the toggle only appears when it matters. */
export function hasRemoteImages(html: string | null | undefined): boolean {
  if (!html) return false;
  return /<img\b[^>]*\bsrc\s*=\s*["']?\s*(?:https?:)?\/\//i.test(html) || /url\(\s*["']?\s*(?:https?:)?\/\//i.test(html) || /\bbackground\s*=\s*["']?\s*https?:/i.test(html);
}
