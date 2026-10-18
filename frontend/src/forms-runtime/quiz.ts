// Quiz scoring, as backend/app/forms/answers.py does it (shared cases: backend/tests/fixtures/form_logic.json). The public
// definition has no correct answers, so a visitor's result always comes from the server; this copy scores the builder's
// preview, which has the full definition. Integer arithmetic only, so the numbers are the same on both sides.
import { same } from "./logic.ts";
import type { Answers, Definition, Field, Flow, QuizResult } from "./types.ts";

export function correct(f: Field, a: unknown): boolean {
  const expected = f.quiz!.correct;
  if (f.type === "multi_select") return Array.isArray(a) && same(a, expected);
  if (f.type === "short_text") return typeof a === "string" && (Array.isArray(expected) ? expected : [expected]).some((e) => same(a, e));
  return same(a, expected);
}

export function score(defn: Definition, fl: Flow, answers: Answers): QuizResult | null {
  const fields = new Map(defn.steps.flatMap((s) => s.fields).map((f) => [f.key, f]));
  const scored = fl.steps.flatMap((s) => s.fields).map((k) => fields.get(k)!).filter((f) => f.quiz);
  if (scored.length === 0) return null;
  const review = Object.fromEntries(scored.map((f) => [f.key, correct(f, answers[f.key])]));
  const got = scored.filter((f) => review[f.key]).reduce((n, f) => n + f.quiz!.points, 0);
  const top = scored.reduce((n, f) => n + f.quiz!.points, 0);
  const mark = defn.quiz?.pass_mark;
  const band = [...(defn.quiz?.bands ?? [])].reverse().find((b) => got * 100 >= b.min * top);
  return {
    score: got,
    max_score: top,
    percent: Math.floor((got * 100) / top),
    review,
    passed: mark == null ? null : got * 100 >= mark * top,
    band: band ? { title: band.title, message: band.message } : null,
  };
}
