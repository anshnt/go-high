// Scores at or above STRONG are substring or word-prefix matches; below are loose subsequence
// matches, which callers drop whenever any strong match exists. null = no match.
export const STRONG = 500;

export function fuzzy(query: string, text: string): number | null {
  const q = query.trim().toLowerCase();
  if (!q) return 0;
  const t = text.toLowerCase();
  const at = t.indexOf(q);
  if (at >= 0) return STRONG * 2 - at + (at === 0 || t[at - 1] === " " ? 50 : 0);
  const words = t.split(/\s+/);
  if (q.split(/\s+/).every((w) => words.some((tw) => tw.startsWith(w)))) return STRONG;
  let score = 0;
  let ti = 0;
  let run = 0;
  for (const ch of q) {
    if (ch === " ") continue;
    const i = t.indexOf(ch, ti);
    if (i < 0) return null;
    const wordStart = i === 0 || t[i - 1] === " ";
    if (i - ti > 4 && !wordStart) return null; // too scattered to be a real match
    run = i === ti ? run + 1 : 0;
    score += 1 + run * 2 + (wordStart ? 4 : 0) - (i - ti) * 0.1;
    ti = i + 1;
  }
  return Math.min(score, STRONG - 1);
}

// Keeps matches, best first; loose matches only survive when nothing matched strongly.
export function rank<T>(items: T[], score: (item: T) => number | null): T[] {
  const scored = items.map((item) => ({ item, s: score(item) })).filter((r): r is { item: T; s: number } => r.s !== null);
  const strong = scored.some((r) => r.s >= STRONG);
  return scored.filter((r) => !strong || r.s >= STRONG).sort((a, b) => b.s - a.s).map((r) => r.item);
}
