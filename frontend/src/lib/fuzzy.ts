// Subsequence match with bonuses for consecutive runs and word starts. null = no match.
export function fuzzy(query: string, text: string): number | null {
  const q = query.trim().toLowerCase();
  if (!q) return 0;
  const t = text.toLowerCase();
  let score = 0;
  let ti = 0;
  let run = 0;
  for (const ch of q) {
    if (ch === " ") continue;
    const at = t.indexOf(ch, ti);
    if (at < 0) return null;
    const wordStart = at === 0 || t[at - 1] === " ";
    if (at - ti > 4 && !wordStart) return null; // too scattered to be a real match
    run = at === ti ? run + 1 : 0;
    score += 1 + run * 2 + (wordStart ? 4 : 0) - (at - ti) * 0.1;
    ti = at + 1;
  }
  return score;
}
