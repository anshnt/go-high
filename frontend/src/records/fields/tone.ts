import type { Tone } from "../../ui";
import type { ColorName } from "../types.ts";

// Field and tag colors are names, not hex, so they follow the theme (and white label token sets).
const TONES: Record<ColorName, Tone> = {
  gray: "neutral",
  blue: "info",
  teal: "info",
  green: "success",
  amber: "warning",
  orange: "warning",
  red: "danger",
  pink: "danger",
  purple: "accent",
  indigo: "accent",
};

export const toneOf = (c?: ColorName): Tone => (c ? TONES[c] : "neutral") ?? "neutral";
