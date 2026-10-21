// What the workflow screens' single-key shortcuts must leave alone.
import { TYPING } from "../shell/useShortcuts";

let gAt = 0;
const chords = new WeakSet<KeyboardEvent>();

// The shell's "g then a letter" goes somewhere (g t is Tasks): the letter is not a shortcut of this screen. Seen in the
// capture phase, before any screen's listener, whatever order those were added in.
if (typeof window !== "undefined")
  window.addEventListener(
    "keydown",
    (e) => {
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const typing = e.target instanceof Element && !!e.target.closest(TYPING);
      if (gAt && Date.now() - gAt < 1000 && e.key !== "g") {
        chords.add(e);
        gAt = 0;
      } else gAt = e.key === "g" && !typing ? Date.now() : 0;
    },
    true,
  );

/** The key is the second half of a "g" chord (or the g itself). */
export const inChord = (e: KeyboardEvent) => chords.has(e) || e.key === "g";

/** Where a key that acts on the screen (Enter, Delete) may act: nothing focused, or the given surfaces. Anywhere else
 * (a button, a link, a field) the key belongs to that control. */
export function onSurface(e: KeyboardEvent, surfaces: string): boolean {
  const t = e.target;
  return !(t instanceof Element) || t === document.body || t.matches(surfaces);
}
